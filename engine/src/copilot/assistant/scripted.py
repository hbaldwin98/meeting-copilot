"""Fake assistant for UI development and plumbing tests. No Claude calls.

Every 4th final utterance produces an instant card; every ask() runs a fake
task that streams progress for a few seconds and then finishes with a card.
"""

from __future__ import annotations

import asyncio
import itertools
from typing import AsyncIterator

from ..types import AgentEvent, Utterance


class ScriptedAssistant:
    def __init__(self):
        self._q: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._ids = itertools.count(1)
        self._n = 0
        self._tasks: dict[str, asyncio.Task] = {}

    async def __aenter__(self):
        self._emit("status", state="ready", detail="scripted")
        return self

    async def __aexit__(self, *exc):
        for t in self._tasks.values():
            t.cancel()

    async def hear(self, u: Utterance) -> None:
        if not u.final:
            return
        self._n += 1
        if self._n % 4 == 0:
            words = [w for w in u.text.split() if len(w) > 4][:3] or ["something"]
            self._emit(
                "card",
                id=f"c{next(self._ids)}",
                headline=f"About “{' '.join(words)}”",
                body_md=f"Scripted card for:\n\n> {u.text}\n\n- point one\n- point two",
                sources=[],
                task_id=None,
                kind="instant",
                origin="auto",
            )

    async def ask(self, prompt: str) -> None:
        tid = f"t{next(self._ids)}"
        self._emit("task.started", id=tid, title=prompt or "What's being discussed", kind="research")
        self._tasks[tid] = asyncio.create_task(self._fake(tid, prompt))

    async def cancel(self, task_id: str) -> None:
        if t := self._tasks.get(task_id):
            t.cancel()

    async def events(self) -> AsyncIterator[AgentEvent]:
        while True:
            yield await self._q.get()

    async def _fake(self, tid: str, prompt: str):
        try:
            for note in ["WebSearch: example query", "WebFetch: https://example.com", "summarizing"]:
                await asyncio.sleep(1.2)
                self._emit("task.progress", id=tid, note=note)
            cid = f"c{next(self._ids)}"
            self._emit(
                "card",
                id=cid,
                headline=f"Answer: {prompt or 'current topic'}",
                body_md="- A **finding**\n- Another finding\n\nSources:\n- https://example.com",
                sources=["https://example.com"],
                task_id=tid,
                kind="research",
                origin="ask",
            )
            self._emit("task.done", id=tid, card_id=cid)
        except asyncio.CancelledError:
            self._emit("task.cancelled", id=tid)

    def _emit(self, t: str, **data):
        self._q.put_nowait(AgentEvent(t, data))
