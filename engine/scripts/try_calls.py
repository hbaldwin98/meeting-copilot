"""Exercise the assistant's Claude call paths directly (costs a few cents)."""

import asyncio
import sys

from copilot.assistant import prompts
from copilot.assistant.claude import ClaudeAssistant
from copilot.memory import open_memory
from copilot.types import Utterance


async def main():
    mem = open_memory(":memory:")
    mem.start_meeting()
    batch = [
        Utterance("them", 0, 4, "So the main thing today is the migration from Postgres to CockroachDB."),
        Utterance("them", 5, 9, "Does anyone know the typical p99 write latency for a three region cluster?"),
    ]
    for u in batch:
        mem.add(u)
    a = ClaudeAssistant(memory=mem)

    print("== scribe (structured output)")
    out, _ = await a._call("scribe", "haiku", prompts.SCRIBE,
                           f"{mem.digest()}\n\n<transcript>\n{batch[0].text}\n{batch[1].text}\n</transcript>",
                           prompts.SCRIBE_SCHEMA)
    print(out)

    print("\n== docs agent: which connectors are visible?")
    seen = []
    _, text = await a._call(
        "agents", "haiku",
        "List the exact names of every tool you have whose name starts with mcp__. One per line, nothing else.",
        "List your MCP tools.", tools=["mcp__memory__recall", "mcp__memory__topic"], external=True, max_turns=2,
        on_tool=lambda b: seen.append(b.name),
    )
    names = sorted({l.split("__")[1] for l in text.splitlines() if l.strip().startswith("mcp__")})
    print("servers:", names)
    print("cost:", a._spend)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
