"""User-editable settings: a schema the UI renders, live appliers, and an
overlay file (data/settings.json) so config.toml (with its comments) is never
rewritten.

  load_config(path)            config.toml + overlay, merged
  Settings(cfg, appliers)      .schema() for the UI, .update(patch) -> restart?
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, Callable

OVERLAY = Path(__file__).resolve().parents[2] / "data" / "settings.json"

MODELS = ["haiku", "sonnet", "opus"]


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    if OVERLAY.exists():
        cfg = _merge(cfg, json.loads(OVERLAY.read_text(encoding="utf-8")))
    return cfg


def _get(cfg: dict, key: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _set(d: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


class Settings:
    """``appliers`` maps a key to a function that applies it live. Keys without
    an applier are saved and take effect after an engine restart."""

    def __init__(self, cfg: dict, appliers: dict[str, Callable[[Any], None]], options: dict[str, list] | None = None):
        self.cfg = cfg
        self.appliers = appliers
        self.options = options or {}
        self.pending_restart = False

    def schema(self) -> list[dict[str, Any]]:
        o = self.options
        a = "assistant"
        fields = [
            # group, key, label, type, extra
            ("Voice", "voice.enabled", "Speak answers", "bool", {}),
            ("Voice", "voice.voice", "Voice", "select", {"options": o.get("voices", [])}),
            ("Voice", "voice.speed", "Speed", "range", {"min": 0.8, "max": 1.4, "step": 0.05}),
            ("Voice", "voice.speak", "Read aloud", "select", {"options": [
                ["asks", "Answers to my questions"], ["asks+tasks", "…and agent results"], ["all", "Everything"]]}),
            ("Voice", "voice.output_device", "Output device", "select", {"options": [["", "System default"], *o.get("outputs", [])]}),
            ("Assistant", f"{a}.listener_model", "Main model", "select", {"options": MODELS}),
            ("Assistant", f"{a}.scribe_model", "Note-taking model", "select", {"options": MODELS}),
            ("Assistant", f"{a}.worker_models.lookup", "Quick lookups", "select", {"options": MODELS}),
            ("Assistant", f"{a}.worker_models.research", "Research", "select", {"options": MODELS}),
            ("Assistant", f"{a}.flush_secs", "Check-in interval (s)", "number", {"min": 5, "max": 120, "step": 5}),
            ("Assistant", f"{a}.budget_usd", "Spending cap per meeting ($, 0 = none)", "number", {"min": 0, "step": 0.5}),
            ("Assistant", f"{a}.trigger_words", "Wake words", "list", {}),
            ("Listening", "run.engine", "Transcription", "select", {"options": o.get("engines", [])}),
            ("Listening", "audio.mic", "Capture my microphone", "bool", {}),
            ("Listening", "audio.loopback", "Capture system audio", "bool", {}),
            ("Listening", "audio.mic_device", "Microphone", "select", {"options": [["", "System default"], *o.get("inputs", [])]}),
        ]
        defaults = {"voice.enabled": False, "voice.voice": "bf_emma", "voice.speed": 1.05, "voice.speak": "asks",
                    "voice.output_device": "", "audio.mic_device": "", "audio.mic": True, "audio.loopback": True,
                    f"{a}.budget_usd": 0, f"{a}.flush_secs": 20, f"{a}.worker_models.lookup": "haiku",
                    f"{a}.worker_models.research": "sonnet"}
        return [
            {"group": g, "key": k, "label": label, "type": t, "value": _get(self.cfg, k, defaults.get(k)),
             "live": k in self.appliers, **extra}
            for g, k, label, t, extra in fields
        ]

    def update(self, patch: dict[str, Any]) -> bool:
        """Apply + persist. Returns True if a restart is needed for some change."""
        overlay = json.loads(OVERLAY.read_text(encoding="utf-8")) if OVERLAY.exists() else {}
        for key, value in patch.items():
            _set(self.cfg, key, value)
            _set(overlay, key, value)
            if key in self.appliers:
                self.appliers[key](value)
            else:
                self.pending_restart = True
        OVERLAY.parent.mkdir(parents=True, exist_ok=True)
        OVERLAY.write_text(json.dumps(overlay, indent=2), encoding="utf-8")
        return self.pending_restart
