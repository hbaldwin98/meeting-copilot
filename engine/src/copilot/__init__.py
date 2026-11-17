"""Copilot engine CLI.

  uv run copilot run [--source file --file x.wav] [--engine nemotron] [--assistant scripted]
  uv run copilot bench recordings/x.wav --engines parakeet nemotron whisper_turbo
  uv run copilot models silero parakeet nemotron
  uv run copilot devices
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "config.toml"


def _load_config(path: Path) -> dict:
    from .settings import load_config

    return load_config(path)


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="copilot")
    p.add_argument("--config", type=Path, default=CONFIG)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="start the engine")
    r.add_argument("--source", choices=["wasapi", "file"])
    r.add_argument("--file", type=Path, help="wav for --source file")
    r.add_argument("--engine")
    r.add_argument("--assistant", choices=["claude", "scripted"])
    r.add_argument("--port", type=int)
    r.add_argument("--quiet", action="store_true", help="don't echo events to the console")

    b = sub.add_parser("bench", help="compare ASR engines on a wav")
    b.add_argument("wav", type=Path)
    b.add_argument("--engines", nargs="+")

    m = sub.add_parser("models", help="download sherpa-onnx models")
    m.add_argument("names", nargs="*", default=["silero", "parakeet", "nemotron", "kokoro"])

    s = sub.add_parser("say", help="speak text with the configured voice")
    s.add_argument("text")
    s.add_argument("--voice")

    sub.add_parser("devices", help="list capture devices")

    a = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper", "phonemizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = _load_config(a.config)
    engines = cfg["asr"]["engines"]

    if a.command == "models":
        from .models import download

        download(a.names)
    elif a.command == "devices":
        from .audio.wasapi import list_devices

        list_devices()
    elif a.command == "bench":
        from .asr.bench import bench

        asyncio.run(bench(a.wav, a.engines or list(engines), engines))
    elif a.command == "say":
        _say(a, cfg)
    elif a.command == "run":
        _run(a, cfg, engines)


def _run(a, cfg: dict, engines: dict) -> None:
    from . import session
    from .asr import make_transcriber
    from .assistant import make_assistant
    from .audio import make_source
    from .bus import EventBus
    from .memory import open_memory
    from .settings import Settings
    from .voice import make_speaker
    from .voice.kokoro import VOICES

    run_cfg = cfg.get("run", {})
    src_kind = a.source or run_cfg.get("source", "wasapi")
    if src_kind == "file":
        if not a.file:
            sys.exit("--source file needs --file path.wav")
        source = make_source("file", path=a.file)
    else:
        source = make_source("wasapi", **cfg.get("audio", {}))

    transcriber = make_transcriber(a.engine or run_cfg.get("engine", "parakeet"), engines)
    kind = a.assistant or run_cfg.get("assistant", "claude")
    acfg = dict(cfg.get("assistant", {}))
    for k in ("trigger_words", "context_dirs"):
        if k in acfg:
            acfg[k] = tuple(acfg[k])
    acfg["mcp"] = cfg.get("mcp", {})
    memory = open_memory(":memory:" if kind == "scripted" else cfg.get("memory", {}).get("path"))
    assistant = make_assistant(kind, memory, **(acfg if kind == "claude" else {}))
    bus = EventBus(port=a.port or run_cfg.get("port", 8765), echo=not a.quiet)
    vcfg = cfg.get("voice", {})
    clock = session.Clock()
    speaker = make_speaker(vcfg, clock.quiet)
    try:
        from .audio.wasapi import device_names

        inputs, outputs = device_names()
    except Exception:
        inputs, outputs = [], []
    settings = Settings(cfg, {}, {"voices": VOICES, "engines": list(engines), "inputs": inputs, "outputs": outputs})

    def restart():
        # relaunch this same command, then exit so the new process can take the port
        import os
        import subprocess

        subprocess.Popen([sys.executable, "-c", "import copilot; copilot.main()", *sys.argv[1:]])
        os._exit(0)

    try:
        asyncio.run(session.run(source, transcriber, assistant, bus, memory, speaker, clock, settings,
                                vcfg.get("speak", "asks") if vcfg.get("enabled", False) else "off", restart))
    except KeyboardInterrupt:
        pass


def _say(a, cfg: dict) -> None:
    from .voice import make_speaker

    vcfg = {**cfg.get("voice", {}), "enabled": True}
    if a.voice:
        vcfg["voice"] = a.voice

    async def go():
        sp = make_speaker(vcfg, lambda: True)
        await sp.speak(a.text)
        await asyncio.sleep(0.5)
        while sp.speaking or not sp._queue.empty():
            await asyncio.sleep(0.1)

    asyncio.run(go())