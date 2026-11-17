"""Assistant module.

Interface (use as ``async with assistant:``):
  hear(u)       feed transcript; cheap, never blocks on Claude
  ask(prompt)   explicit request (hotkey / typed); always produces output
  cancel(id)    cancel a running background task
  events()      async stream of AgentEvent (cards + task lifecycle)

Batching, the stay-quiet policy, subagent spawning, concurrency limits,
context compaction and cost tracking all live behind this seam.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from ..types import AgentEvent, Utterance


class Assistant(Protocol):
    async def __aenter__(self) -> "Assistant": ...
    async def __aexit__(self, *exc) -> None: ...
    async def hear(self, u: Utterance) -> None: ...
    async def ask(self, prompt: str) -> None: ...
    async def cancel(self, task_id: str) -> None: ...
    def events(self) -> AsyncIterator[AgentEvent]: ...


def make_assistant(kind: str, memory, **kw) -> Assistant:
    if kind == "claude":
        from .claude import ClaudeAssistant

        return ClaudeAssistant(memory=memory, **kw)
    if kind == "scripted":
        from .scripted import ScriptedAssistant

        return ScriptedAssistant()
    raise ValueError(f"unknown assistant {kind!r}")
