"""MeetingMemory module: everything the copilot remembers lives here, on disk,
instead of in Claude's context window.

  start_meeting() / end_meeting(summary)    lifecycle; unfinished meetings are
                                            closed with a fallback summary
  add(u)                                    store a final utterance
  apply(topics, t0, t1)                     merge topic-graph updates
  digest()                                  bounded text for prompts (~1.5k tokens)
  topics()                                  current meeting's graph, for the UI
  recall(query, scope)                      full-text search: "meeting" | "past" | "all"
  topic(id)                                 one node + neighbours + its transcript
  recent(seconds)                           tail of the transcript (for asks)
  cached(query) / remember(query, ...)      agent result cache
  forget(meeting_id)

Prompts only ever see digest(); anything deeper is pulled through tools that
wrap recall()/topic(). So prompt size stays flat however long a meeting runs.
"""

from __future__ import annotations

from pathlib import Path

from .sqlite import SqliteMemory

DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "memory.db"


def open_memory(path: str | Path | None = None) -> SqliteMemory:
    """``":memory:"`` gives a throwaway store (tests, scripted runs)."""
    return SqliteMemory(path or DEFAULT_DB)


__all__ = ["SqliteMemory", "open_memory"]
