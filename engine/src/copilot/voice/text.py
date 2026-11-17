"""Text clean-up before synthesis. espeak-ng handles pronunciation; this only
fixes things it reads badly: units glued to numbers, ranges, money suffixes,
camelCase names, and a few symbols."""

from __future__ import annotations

import re

_UNITS = {"ms": "milliseconds", "s": "seconds", "sec": "seconds", "min": "minutes", "h": "hours", "hr": "hours",
          "kb": "kilobytes", "mb": "megabytes", "gb": "gigabytes", "tb": "terabytes", "k": "thousand",
          "m": "million", "b": "billion", "bn": "billion", "x": "times", "hz": "hertz", "ghz": "gigahertz"}
_ABBR = {"e.g.": "for example", "i.e.": "that is", "vs.": "versus", " vs ": " versus ", "etc.": "et cetera",
         "&": " and ", "~": " about ", "≈": " about ", "→": " to ", "->": " to ", "±": " plus or minus "}
_NUM = r"\d[\d,]*(?:\.\d+)?"


def normalize(text: str) -> str:
    t = text
    for k, v in _ABBR.items():
        t = t.replace(k, v)
    # $1.2M -> 1.2 million dollars ; $40 -> 40 dollars
    t = re.sub(rf"\$({_NUM})\s*([kKmMbB]n?)?\b",
               lambda m: f"{m[1]} {_UNITS[m[2].lower()] + ' ' if m[2] else ''}dollars", t)
    t = re.sub(rf"({_NUM})\s*%", r"\1 percent", t)
    t = re.sub(rf"({_NUM})\s*[–—-]\s*({_NUM})", r"\1 to \2", t)  # 100-300 -> 100 to 300
    t = re.sub(rf"\b({_NUM})\s*([A-Za-z]{{1,3}})\b",
               lambda m: f"{m[1]} {_UNITS.get(m[2].lower(), m[2])}", t)  # 300ms, 3x, 10k
    t = re.sub(rf"\b([A-Za-z])({_NUM})\b", r"\1 \2", t)  # P99 -> P 99
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)  # CockroachDB -> Cockroach DB
    return re.sub(r"\s+", " ", t).strip()
