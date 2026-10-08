"""
a2apay Python SDK.

Honest about what this actually does:
- Free-tier calls are plain HTTP, zero dependencies on crypto at all.
- Paid calls require a real funded wallet (Base mainnet USDC) and sign a
  real on-chain payment authorization (EIP-3009 transferWithAuthorization)
  using eth-account -- a well-established, Ethereum Foundation-maintained
  library. No private key is ever sent anywhere; it only signs locally.
- Memory storage here is flat key/value/tags (text), not a document store.
  This SDK doesn't pretend otherwise.
"""

import base64
import json
import os
import secrets
import time

import requests

try:
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    _HAS_ETH = True
except ImportError:
    _HAS_ETH = False


class A2ApayError(Exception):
    """Raised for any non-success response from the a2apay API."""


class Agent:
    """
    Minimal client for a2apay's pay-per-call AI query and memory endpoints.

    Tries the free tier first on every call (no payment attached). If the
    free tier is unavailable (exhausted today, or not eligible) and a
    private key is configured, falls back to a real paid request signed
    with that key. If no private key is configured, free-tier-only usage
    still works -- paid calls will raise a clear error instead of failing
    silently.
    """

    DEFAULT_BASE_URL = "https://a2apay.io"

    def __init__(self, base_url: str = None, private_key: str = None, timeout: int = 30):
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        key = private_key or os.environ.get("A2APAY_PRIVATE_KEY")
        self._account = None
        if key:
            if not _HAS_ETH:
                raise A2ApayError(
                    "A private key was provided but eth-account isn't installed. "
                    "Install it with: pip install a2apay[paid]"
                )
            self._account = Account.from_key(key)

    @property
    def address(self):
        """The wallet address paid calls will be signed from, or None if no key is configured."""
        return self._account.address if self._account else None

    def ask(self, prompt: str) -> str:
        """Submit a prompt, get a real AI-generated answer back."""
        result = self._call("/api/agent-service", {"prompt": prompt})
        return result["result"]

    def remember(self, key: str, value: str, tags=None) -> bool:
        """Store a key/value record (flat text, with optional tags) in persistent memory."""
        body = {"key": key, "val": value, "tags": tags or []}
        result = self._call("/api/agent-memory", body)
        return bool(result["result"])

    def checkpoint(self, task_id: str, key: str, value: str, tags=None, ttl_seconds: int = None, readers=None) -> bool:
        """
        Write a versioned, task-scoped memory record -- the same free-tier-
        then-paid record this SDK can later pull back with resume(), even
        from a different process. Writing the same key again under the same
        task_id adds a new version, it does not overwrite.

        On a free-tier call (no wallet, or free tier not yet exhausted),
        this SDK's own address is used as the self-declared owner so a
        later resume() from the same Agent instance can still find it --
        but note the free tier has no payment signature to verify that
        identity against, so it's a convenience, not a guarantee.
        """
        body = {
            "key": key,
            "val": value,
            "tags": tags or [],
            "taskId": task_id,
            "owner": self.address or f"anon-{id(self)}",
            "ttlSeconds": ttl_seconds,
            "readers": readers or [],
        }
        result = self._call("/api/agent-memory", body)
        return bool(result["result"])

    def resume(self, task_id: str) -> list:
        """
        Read back the latest version of every key checkpointed under
        task_id that this wallet owns or was explicitly granted read
        access to. Paid only -- there's no free tier for reads yet, so
        this requires a configured wallet even on the first call.
        """
        if not self._account:
            raise A2ApayError(
                "resume() requires payment on every call (no free tier for reads yet) "
                "and no wallet is configured. Pass private_key=... to Agent() or set "
                "the A2APAY_PRIVATE_KEY environment variable."
            )
        result = self._call("/api/agent-memory/resume", {"taskId": task_id})
        return result["result"]

    # ------------------------------------------------------------------

    def _call(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"

        free_resp = requests.post(url, json=body, timeout=self.timeout)
        if free_resp.status_code == 200:
            return free_resp.json()
        if free_resp.status_code != 402:
            raise A2ApayError(f"{path} returned {free_resp.status_code}: {free_resp.text}")

        if not self._account:
            raise A2ApayError(
                f"{path} requires payment (free tier used up today, or not eligible for "
                "this request) and no wallet is configured. Pass private_key=... to Agent() "
                "or set the A2APAY_PRIVATE_KEY environment variable."
            )

        raw_requirements = free_resp.headers.get("PAYMENT-REQUIRED") or free_resp.headers.get(
            "payment-required"
        )
        if not raw_requirements:
            raise A2ApayError(
                f"{path} returned 402 but no PAYMENT-REQUIRED header was present -- "
                f"can't determine payment terms. Body: {free_resp.text}"
            )
        requirements = json.loads(base64.b64decode(raw_requirements))
        payment_header = self._build_payment_header(requirements)

        paid_resp = requests.post(
            url, json=body, headers={"payment-signature": payment_header}, timeout=self.timeout
        )
        if paid_resp.status_code != 200:
            raise A2ApayError(f"{path} paid attempt returned {paid_resp.status_code}: {paid_resp.text}")
        return paid_resp.json()

    def _build_payment_header(self, requirements: dict) -> str:
        """
        Builds a real, signed x402 "exact" EVM scheme payment payload, per
        the x402 protocol spec (x402-foundation/x402,
        specs/schemes/exact/scheme_exact_evm.md). Signs an EIP-3009
        transferWithAuthorization locally -- the private key never leaves
        this process.
        """
        accept = requirements["accepts"][0]
        chain_id = int(accept["network"].split(":")[1])  # "eip155:8453" -> 8453
        now = int(time.time())
        nonce = "0x" + secrets.token_hex(32)

        message = {
            "from": self._account.address,
            "to": accept["payTo"],
            "value": int(accept["amount"]),
            "validAfter": 0,
            "validBefore": now + int(accept.get("maxTimeoutSeconds", 60)),
            "nonce": nonce,
        }

        domain = {
            "name": accept["extra"]["name"],
            "version": accept["extra"]["version"],
            "chainId": chain_id,
            "verifyingContract": accept["asset"],
        }
        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        }

        signable = encode_typed_data(
            full_message={
                "types": types,
                "domain": domain,
                "primaryType": "TransferWithAuthorization",
                "message": message,
            }
        )
        signed = self._account.sign_message(signable)
        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature

        payload = {
            "x402Version": requirements.get("x402Version", 2),
            "resource": requirements.get("resource"),
            "accepted": accept,
            "payload": {
                "signature": signature,
                "authorization": {
                    "from": message["from"],
                    "to": message["to"],
                    "value": str(message["value"]),
                    "validAfter": str(message["validAfter"]),
                    "validBefore": str(message["validBefore"]),
                    "nonce": nonce,
                },
            },
        }
        return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
