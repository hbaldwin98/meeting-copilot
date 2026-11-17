"""Text clean-up shared by all engines (mainly Whisper hallucination guards)."""

from __future__ import annotations

import re

# Phrases Whisper famously invents on silence / noise.
_HALLUCINATIONS = {
    "thank you.",
    "thanks for watching!",
    "thanks for watching.",
    "thank you for watching.",
    "please subscribe.",
    "you",
    ".",
    "bye.",
    "so",
}

_WS = re.compile(r"\s+")


def clean(text: str) -> str:
    """Return normalised text, or "" if it looks like noise/hallucination."""
    t = _WS.sub(" ", text).strip()
    if not t or t.lower() in _HALLUCINATIONS:
        return ""
    if not any(c.isalnum() for c in t):
        return ""
    if _is_looping(t):
        return ""
    return t


def _is_looping(t: str, n: int = 3, max_repeats: int = 4) -> bool:
    """Detect "the the the the ..." / repeated n-gram loops."""
    words = t.lower().split()
    if len(words) < n * max_repeats:
        return False
    grams = [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]
    most = max(grams.count(g) for g in set(grams))
    return most >= max_repeats and most * n >= len(words) * 0.6
