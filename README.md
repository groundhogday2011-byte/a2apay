# a2apay

Python client for [a2apay.io](https://a2apay.io) — pay-per-call AI answers
and persistent memory for autonomous agents. No account, no API key.

<!-- mcp-name: io.github.groundhogday2011-byte/a2apay -->
<!-- Required by the official MCP Registry (modelcontextprotocol.io) to
     verify PyPI package ownership against this GitHub account. Do not
     remove or edit this line without also updating the registry entry. -->

```bash
pip install a2apay-io          # free-tier only
pip install "a2apay-io[paid]"  # adds real payment support (eth-account)
```

(The PyPI distribution is named `a2apay-io` — an unrelated package already
holds the bare `a2apay` name. The importable module is still `a2apay`.)

## Quick start (free tier, zero setup)

Every call tries the free tier first automatically — 5 requests/day per
caller, no wallet needed:

```python
from a2apay import Agent

agent = Agent()
answer = agent.ask("What's 7 times 8?")
print(answer)

agent.remember("last_task", "processed invoice #4471", tags=["billing"])
```

## With real payment (once the free tier is used up)

```python
from a2apay import Agent

agent = Agent(private_key="0x...")  # or set A2APAY_PRIVATE_KEY
answer = agent.ask("What's 7 times 8?")
```

The wallet needs a small USDC balance on Base mainnet ($0.028/call). The
private key is used only to sign a payment authorization locally — it is
never sent anywhere.

## Checkpoint / resume (task memory)

Write versioned, task-scoped state and read it back later — even from a
different process. Each `checkpoint()` to the same key adds a new version
rather than overwriting, and `resume()` always returns the latest.

```python
from a2apay import Agent

agent = Agent(private_key="0x...")
agent.checkpoint("invoice-batch-7", key="status", value="processed rows 1-400")

# ...process dies, or a second process picks up later...

agent2 = Agent(private_key="0x...")  # same wallet
records = agent2.resume("invoice-batch-7")
print(records[0]["value"])  # "processed rows 1-400"
```

`resume()` always requires payment ($0.014/call) — there's no free tier
for reads yet, so it needs a configured wallet even for your first call.
`checkpoint()` follows the same free-tier-then-paid behavior as
`remember()`.

## What this honestly does and doesn't do

- `ask()` returns a real AI-generated answer.
- `remember()` stores a flat key/value record with optional tags — this is
  simple text storage, not a document database. Values are stored as text.
- Falls back to a real payment only when the free tier returns a `402`;
  if no `private_key` is configured at that point, it raises a clear
  `A2ApayError` rather than failing silently.
- Payment signing uses `eth-account` (maintained by the Ethereum
  Foundation ecosystem), implementing the real x402 "exact" EVM scheme
  per the [x402 protocol spec](https://github.com/x402-foundation/x402).

## MCP server

An MCP server (`mcp_server.py`) exposes `ask` and `remember` as MCP tools
for any MCP-aware agent or framework (Claude Desktop, etc.):

```bash
pip install "a2apay-io[mcp]"
python mcp_server.py
```

Add to an MCP client config:

```json
{
  "mcpServers": {
    "a2apay": {
      "command": "python",
      "args": ["/absolute/path/to/mcp_server.py"],
      "env": {"A2APAY_PRIVATE_KEY": "0x..."}
    }
  }
}
```

Honest scope note: `remember` is write-only — there's no memory read-back
tool because the live API doesn't have a read-back route yet.

## Full API reference

See [a2apay.io/openapi.yaml](https://a2apay.io/openapi.yaml) for the
underlying HTTP API this wraps.
