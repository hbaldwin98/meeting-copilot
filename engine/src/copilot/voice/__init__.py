"""Speaker module: reads short answers aloud.

Interface:
  load()          load the voice model now (idempotent)
  speak(text, voice=None, wait=True)
                  queue text (optionally in another voice); returns immediately. Waits for a pause in the
                  conversation (``quiet()``) before talking, up to max_wait.
  stop()          stop talking now and drop anything queued
  speaking        True while audio is playing (+ a short tail) -- the session
                  uses this to drop capture so the copilot never hears itself

``spoken_text(card)`` and ``should_speak(event, mode)`` are the policy: what
gets said, and when.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Protocol


class Speaker(Protocol):
    speaking: bool

    async def load(self) -> None: ...
    async def speak(self, text: str, voice: str | None = None, wait: bool = True) -> None: ...
    def stop(self) -> None: ...


class NullSpeaker:
    speaking = False

    async def load(self) -> None: ...
    async def speak(self, text: str, voice: str | None = None, wait: bool = True) -> None: ...
    def stop(self) -> None: ...


def make_speaker(cfg: dict[str, Any], quiet: Callable[[], bool]) -> Speaker:
    if not cfg.get("enabled", False):
        return NullSpeaker()
    kind = cfg.get("engine", "kokoro")
    if kind == "kokoro":
        from .kokoro import KokoroSpeaker

        opts = {k: v for k, v in cfg.items() if k not in ("enabled", "engine", "speak")}
        return KokoroSpeaker(quiet=quiet, **opts)
    raise ValueError(f"unknown voice engine {kind!r}")


# ---------------------------------------------------------------- policy
_MD = re.compile(r"[*_`#>\[\]]|\(https?://[^)]*\)|https?://\S+")
_SENT = re.compile(r"(?<=[.!?])\s+")


def _plain(md: str) -> str:
    return re.sub(r"\s+", " ", _MD.sub("", md)).strip()


def spoken_text(card: dict[str, Any], sentences: int = 1) -> str:
    """Headline plus the first sentence of the body -- the panel has the rest."""
    head = _plain(card.get("headline", "")).rstrip(".") + "."
    body = card.get("body_md", "").split("Sources:")[0]
    lines = [re.sub(r"^\s*(?:[-*•]|\d+\.)\s+", "", l).strip() for l in body.splitlines()]
    text = " ".join(l if l.endswith((".", "!", "?", ":")) else l + "." for l in lines if l)
    first = [s for s in _SENT.split(_plain(text)) if len(s) > 3]
    return " ".join([head, *first[:sentences]]).strip()


def should_speak(event: dict[str, Any], mode: str) -> bool:
    """mode: "asks" (answers to your asks) | "asks+tasks" (+ any agent result) | "all"."""
    if event.get("type") != "card" or event.get("kind") == "cached" and event.get("origin") != "ask":
        return False
    if mode == "all":
        return True
    if event.get("origin") == "ask":
        return True
    return mode == "asks+tasks" and bool(event.get("task_id"))
