"""
Real checkpoint -> die -> resume demo using the a2apay Python SDK.

"Die" is simulated by discarding the first Agent and creating a brand new
one for resume() -- same wallet, no shared in-memory state, which is the
actual point: the state survives the process, not just the variable.

Requires A2APAY_PRIVATE_KEY set in the environment (a funded Base mainnet
wallet). Run: python checkpoint_resume_demo.py

Honest provenance note: this exact flow (same gateway endpoints, same
request shapes) was verified for real on 2026-10-08 via an equivalent
Node script using the same funded wallet -- real free-tier write, real
$0.014 paid resume, correct value recovered. This Python version shares
100% of its payment-signing code with Agent.ask(), which was separately
verified earlier (local EIP-712 self-check + live network round-trip).
It has not itself been re-run end-to-end against a funded wallet.
"""

import time

from a2apay import Agent

TASK_ID = f"demo-{int(time.time() * 1000)}"


def main():
    print(f"=== Checkpoint -> die -> resume demo (taskId={TASK_ID}) ===\n")

    # --- Process A: checkpoint some task state ---
    agent_a = Agent()
    print(f"[Process A, wallet {agent_a.address}] writing checkpoint...")
    ok = agent_a.checkpoint(
        TASK_ID,
        key="status",
        value="processed rows 1-400 of invoice-batch-7",
        tags=["demo", "invoice-batch"],
    )
    print(f"  -> checkpoint ok: {ok}")
    assert ok, "checkpoint write failed"

    print("\n[Process A exits -- simulating a real crash/restart]\n")
    del agent_a

    # --- Process B: a *different* Agent instance, resumes the task ---
    agent_b = Agent()
    print(f"[Process B, wallet {agent_b.address}] resuming task \"{TASK_ID}\"...")
    records = agent_b.resume(TASK_ID)
    print(f"  -> {records}")
    assert records, "resume returned no records"

    recovered = records[0]
    print(f"\n=== Recovered state: \"{recovered['value']}\" (version {recovered['version']}) ===")
    assert "processed rows 1-400" in recovered["value"], "value mismatch"
    print("PASS: resumed value matches what Process A wrote.")


if __name__ == "__main__":
    main()
