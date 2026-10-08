"""
a2apay MCP server.

Exposes a2apay.io's two live, pay-per-call tools (AI query, persistent
memory write) to any MCP-aware agent/framework over stdio. No account, no
API key -- the free tier works immediately; paid calls need a funded
wallet via A2APAY_PRIVATE_KEY.

Honest about scope: there is currently no memory *read* tool here because
the live API has no read-back route yet (write-only memory today). Don't
add a fake one.

Run:
    python mcp_server.py

Add to an MCP client config (e.g. Claude Desktop, claude_desktop_config.json):
    {
      "mcpServers": {
        "a2apay": {
          "command": "python",
          "args": ["/absolute/path/to/mcp_server.py"],
          "env": {"A2APAY_PRIVATE_KEY": "0x..."}
        }
      }
    }
"""

from mcp.server.mcpserver import MCPServer

from a2apay import Agent, A2ApayError

mcp = MCPServer("a2apay")
_agent = Agent()


@mcp.tool()
def ask(prompt: str) -> str:
    """Submit a prompt and get a real AI-generated answer.

    Free for the first 5 calls/day per caller; falls back to a real
    x402 micropayment ($0.028 USDC on Base) after that if a wallet is
    configured via the A2APAY_PRIVATE_KEY environment variable.
    """
    try:
        return _agent.ask(prompt)
    except A2ApayError as e:
        return f"Error: {e}"


@mcp.tool()
def remember(key: str, value: str, tags: list[str] | None = None) -> str:
    """Store a flat key/value record (text) in persistent memory, with
    optional tags. Same free-tier-then-paid behavior as ask().

    Note: this is write-only -- use checkpoint()/resume() below for
    memory you'll need to read back later.
    """
    try:
        ok = _agent.remember(key, value, tags or [])
        return "stored" if ok else "store reported failure"
    except A2ApayError as e:
        return f"Error: {e}"


@mcp.tool()
def checkpoint(task_id: str, key: str, value: str, tags: list[str] | None = None) -> str:
    """Write versioned, task-scoped state you can read back later with
    resume() -- even from a different process. Writing the same key again
    under the same task_id adds a new version, it does not overwrite.
    """
    try:
        ok = _agent.checkpoint(task_id, key, value, tags or [])
        return "checkpointed" if ok else "checkpoint reported failure"
    except A2ApayError as e:
        return f"Error: {e}"


@mcp.tool()
def resume(task_id: str) -> str:
    """Read back the latest version of every key checkpointed under
    task_id that this wallet owns or was granted read access to. Always
    requires payment ($0.014/call) -- there's no free tier for reads yet,
    so this needs A2APAY_PRIVATE_KEY configured even on the first call.
    """
    try:
        records = _agent.resume(task_id)
        if not records:
            return "No records found for this task_id (none written yet, or not visible to this wallet)."
        return "\n".join(f"{r['key']} (v{r['version']}): {r['value']}" for r in records)
    except A2ApayError as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
