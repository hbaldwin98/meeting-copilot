"""WebSocket seam between the engine and any UI.

Engine -> UI: JSON events (see types.AgentEvent / Utterance.to_event).
UI -> engine: JSON commands {"cmd": "ask"|"cancel"|"pause"|"resume", ...}.

New clients get a replay of cards/tasks so a restarted panel is not empty.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from websockets.asyncio.server import ServerConnection, serve

log = logging.getLogger(__name__)
Handler = Callable[[dict[str, Any]], Awaitable[None]]

_REPLAY_TYPES = ("card", "task.started", "task.progress", "task.done", "task.failed", "task.cancelled", "status", "topics", "cost", "voice", "settings")


class EventBus:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, echo: bool = False):
        self.host, self.port, self.echo = host, port, echo
        self._clients: set[ServerConnection] = set()
        self._history: list[str] = []
        self._handler: Handler | None = None

    def on_command(self, handler: Handler) -> None:
        self._handler = handler

    async def publish(self, event: dict[str, Any]) -> None:
        msg = json.dumps(event)
        if event["type"] in _REPLAY_TYPES:
            self._history.append(msg)
            del self._history[:-500]
        if self.echo:
            _print(event)
        for ws in list(self._clients):
            try:
                await ws.send(msg)
            except Exception:
                self._clients.discard(ws)

    async def serve_forever(self) -> None:
        for attempt in range(20):  # after a restart the old process may still hold the port
            try:
                server = await serve(self._conn, self.host, self.port)
                break
            except OSError:
                await asyncio.sleep(0.5)
        else:
            raise OSError(f"port {self.port} busy")
        async with server:
            log.info("event bus on ws://%s:%d", self.host, self.port)
            await asyncio.Future()

    async def _conn(self, ws: ServerConnection):
        for msg in self._history:
            await ws.send(msg)
        self._clients.add(ws)
        try:
            async for raw in ws:
                try:
                    cmd = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if self._handler:
                    await self._handler(cmd)
        finally:
            self._clients.discard(ws)


def _print(e: dict[str, Any]) -> None:
    t = e["type"]
    if t == "transcript":
        if e["final"]:
            print(f"  {e['channel']:>4} │ {e['text']}", flush=True)
    elif t == "card":
        print(f"\n  ■ {e['headline']}\n" + "\n".join(f"    {l}" for l in e["body_md"].splitlines()) + "\n", flush=True)
    elif t.startswith("task."):
        detail = e.get("title") or e.get("note") or e.get("error") or ""
        print(f"  ⟳ [{e['id']}] {t[5:]} {detail}", flush=True)
    elif t == "status":
        print(f"  · {e['state']} {e.get('detail', '')}", flush=True)
