"""Transcriber module.

Interface: ``transcriber.transcribe(frames)`` consumes AudioFrames and yields
Utterances. Channels are transcribed independently. Engines that stream
natively emit partials (``final=False``); batch engines emit finals only.
VAD, chunking, resampling, hallucination filtering and threading all live
behind this seam -- callers never see the difference between engines.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

from ..types import AudioFrame, Utterance


class Transcriber(Protocol):
    name: str

    async def load(self) -> None:
        """Load models now (idempotent). Otherwise the first transcribe() pays for it."""

    def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[Utterance]: ...


def make_transcriber(name: str, engines: dict[str, dict[str, Any]]) -> Transcriber:
    """Build the engine called ``name`` from the [asr.engines] config table."""
    if name not in engines:
        raise ValueError(f"unknown ASR engine {name!r}; configured: {', '.join(engines)}")
    cfg = dict(engines[name])
    kind = cfg.pop("kind")
    if kind == "faster_whisper":
        from .faster_whisper import FasterWhisperTranscriber

        return FasterWhisperTranscriber(name=name, **cfg)
    if kind == "sherpa_offline":
        from .sherpa import SherpaOfflineTranscriber

        return SherpaOfflineTranscriber(name=name, **cfg)
    if kind == "sherpa_streaming":
        from .sherpa import SherpaStreamingTranscriber

        return SherpaStreamingTranscriber(name=name, **cfg)
    raise ValueError(f"engine {name!r}: unknown kind {kind!r}")
