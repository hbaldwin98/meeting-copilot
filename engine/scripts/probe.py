"""Connect to a running engine like the panel would, optionally send an ask,
and print every event for N seconds.  uv run python scripts/probe.py 40 "what is raft?" """

import asyncio
import json
import sys

from websockets.asyncio.client import connect


async def main(secs: float, ask: str | None):
    async with connect("ws://127.0.0.1:8765") as ws:
        if ask is not None:
            await ws.send(json.dumps({"cmd": "ask", "prompt": ask}))
        try:
            async with asyncio.timeout(secs):
                async for m in ws:
                    e = json.loads(m)
                    if e["type"] == "transcript" and not e["final"]:
                        continue
                    print(json.dumps(e)[:300], flush=True)
        except TimeoutError:
            pass


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 30, sys.argv[2] if len(sys.argv) > 2 else None))
