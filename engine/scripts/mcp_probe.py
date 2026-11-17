"""Show which MCP servers the SDK's CLI connects, with and without env flags."""

import asyncio
import sys

from claude_agent_sdk import ClaudeAgentOptions, SystemMessage, query


async def probe(env: dict[str, str], **kw):
    async def msg():
        yield {"type": "user", "message": {"role": "user", "content": "Reply OK."}}

    opts = ClaudeAgentOptions(model="haiku", tools=[], max_turns=1, env=env, **{"setting_sources": [], **kw})
    async for m in query(prompt=msg(), options=opts):
        if isinstance(m, SystemMessage) and m.subtype == "init":
            print(kw or env or "(default)", "->", [(s.get("name"), s.get("status")) for s in m.data.get("mcp_servers", [])])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(probe({}))
    asyncio.run(probe({}, setting_sources=["user"]))
    asyncio.run(probe({}, setting_sources=["user"], cli_path=r"C:\Users\hunte\.local\bin\claude.exe"))
