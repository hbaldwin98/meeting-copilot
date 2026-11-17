"""Wiring only: source -> transcriber -> assistant -> bus (+ speaker). Keep this
file small; if logic accumulates here it belongs inside one of the modules."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator, Callable

from .asr import Transcriber
from .assistant import Assistant
from .audio import AudioSource
from .bus import EventBus
from .memory import SqliteMemory
from .settings import Settings
from .types import AudioFrame
from .voice import NullSpeaker, Speaker, should_speak, spoken_text


class Clock:
    """When did anyone last say something? Shared by the speaker's quiet() check."""

    def __init__(self, quiet_secs: float = 1.2):
        self.quiet_secs = quiet_secs
        self.last = 0.0

    def heard(self) -> None:
        self.last = time.monotonic()

    def quiet(self) -> bool:
        return time.monotonic() - self.last >= self.quiet_secs


async def run(
    source: AudioSource,
    transcriber: Transcriber,
    assistant: Assistant,
    bus: EventBus,
    memory: SqliteMemory,
    speaker: Speaker,
    clock: Clock,
    settings: Settings,
    voice_mode: str = "asks",
    restart: Callable[[], None] = lambda: None,
) -> None:
    paused = asyncio.Event()
    voice = {"mode": voice_mode, "on": not isinstance(speaker, NullSpeaker) and voice_mode != "off"}

    async def gated() -> AsyncIterator[AudioFrame]:
        async for f in source.frames():
            # never transcribe our own voice coming back through loopback / the mic
            if not paused.is_set() and not speaker.speaking:
                yield f

    # live-applied settings (others are saved and need a restart)
    def _voice_on(v):
        voice["on"] = bool(v)
        if not v:
            speaker.stop()

    live = {"voice.speak": lambda v: voice.update(mode=v)}
    if not isinstance(speaker, NullSpeaker):
        live |= {
            "voice.enabled": _voice_on,
            "voice.voice": lambda v: setattr(speaker, "voice", v),
            "voice.speed": lambda v: setattr(speaker, "speed", float(v)),
            "voice.output_device": lambda v: setattr(speaker, "output_device", v or None),
        }
    live |= getattr(assistant, "live_settings", dict)()
    settings.appliers.update(live)

    async def publish_settings():
        await bus.publish({"type": "settings", "fields": settings.schema(), "restart": settings.pending_restart})

    async def publish_voice():
        await bus.publish({"type": "voice", "on": voice["on"], "mode": voice["mode"]})

    async def on_command(cmd: dict) -> None:
        match cmd.get("cmd"):
            case "ask":
                await assistant.ask(cmd.get("prompt", ""))
            case "cancel":
                await assistant.cancel(cmd["id"])
            case "pause":
                paused.set()
                await bus.publish({"type": "status", "state": "paused", "detail": ""})
            case "resume":
                paused.clear()
                await bus.publish({"type": "status", "state": "listening", "detail": ""})
            case "topic":
                await bus.publish({"type": "topic.detail", "id": cmd["id"], "text": memory.topic(int(cmd["id"]))})
            case "speak":
                await speaker.speak(cmd.get("text", ""))
            case "preview_voice":
                speaker.stop()
                await speaker.speak("Hi, I'm your copilot. This is how I'll sound when I read answers to you.",
                                    voice=cmd.get("voice"), wait=False)
            case "stop_speaking":
                speaker.stop()
            case "settings":
                await publish_settings()
            case "set":
                settings.update(cmd.get("patch", {}))
                await publish_settings()
                await publish_voice()
            case "restart":
                restart()
            case "voice":
                settings.update({"voice.enabled": bool(cmd.get("on", not voice["on"]))})
                await publish_settings()
                await publish_voice()

    async def listen():
        async for u in transcriber.transcribe(gated()):
            clock.heard()
            await bus.publish(u.to_event())
            await assistant.hear(u)

    async def forward():
        async for e in assistant.events():
            event = e.to_event()
            await bus.publish(event)
            if voice["on"] and should_speak(event, voice["mode"]):
                await speaker.speak(spoken_text(event))

    bus.on_command(on_command)
    await asyncio.gather(transcriber.load(), speaker.load())
    await publish_voice()
    async with assistant:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(bus.serve_forever())
            tg.create_task(forward())
            tg.create_task(listen())
