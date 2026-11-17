"""Shared machinery for non-streaming engines: per-channel VAD -> decode -> filter.

Subclasses only implement ``_load()`` and ``_decode(pcm) -> str``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import numpy as np
import sherpa_onnx

from ..types import SAMPLE_RATE, AudioFrame, Utterance
from .filters import clean

DEFAULT_VAD = Path(__file__).resolve().parents[3] / "models" / "silero_vad.onnx"


class _ChannelVad:
    WINDOW = 512  # silero requirement at 16 kHz

    def __init__(self, model: Path, min_silence: float, max_speech: float):
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(model)
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.min_silence_duration = min_silence
        cfg.silero_vad.min_speech_duration = 0.25
        cfg.silero_vad.max_speech_duration = max_speech
        cfg.sample_rate = SAMPLE_RATE
        self.vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)
        self.buf = np.zeros(0, dtype=np.float32)
        self.t_origin: float | None = None  # session time of sample 0 fed to this VAD
        self.fed = 0

    def feed(self, frame: AudioFrame) -> list[tuple[float, float, np.ndarray]]:
        if self.t_origin is None:
            self.t_origin = frame.t
        self.buf = np.concatenate([self.buf, frame.pcm])
        while len(self.buf) >= self.WINDOW:
            self.vad.accept_waveform(self.buf[: self.WINDOW])
            self.buf = self.buf[self.WINDOW :]
            self.fed += self.WINDOW
        return self._drain()

    def flush(self) -> list[tuple[float, float, np.ndarray]]:
        self.vad.flush()
        return self._drain()

    def _drain(self):
        out = []
        while not self.vad.empty():
            seg = self.vad.front
            pcm = np.array(seg.samples, dtype=np.float32)
            t0 = (self.t_origin or 0.0) + seg.start / SAMPLE_RATE
            out.append((t0, t0 + len(pcm) / SAMPLE_RATE, pcm))
            self.vad.pop()
        return out


class BatchTranscriber:
    name: str

    def __init__(
        self,
        name: str,
        vad_model: str | None = None,
        min_silence: float = 0.5,
        max_speech: float = 15.0,
    ):
        self.name = name
        self.vad_model = Path(vad_model) if vad_model else DEFAULT_VAD
        self.min_silence = min_silence
        self.max_speech = max_speech
        self._model = None

    # -- subclass hooks -------------------------------------------------
    def _load(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def _decode(self, pcm: np.ndarray) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- interface ------------------------------------------------------
    async def load(self) -> None:
        if self._model is None:
            self._model = await asyncio.to_thread(self._load)

    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[Utterance]:
        if not self.vad_model.exists():
            raise FileNotFoundError(f"{self.vad_model} missing -- run `uv run copilot models silero`")
        await self.load()
        vads: dict[str, _ChannelVad] = {}

        async def emit(ch, segs):
            for t0, t1, pcm in segs:
                text = clean(await asyncio.to_thread(self._decode, pcm))
                if text:
                    yield Utterance(ch, round(t0, 2), round(t1, 2), text, True)

        async for f in frames:
            vad = vads.get(f.channel) or vads.setdefault(
                f.channel, _ChannelVad(self.vad_model, self.min_silence, self.max_speech)
            )
            async for u in emit(f.channel, vad.feed(f)):
                yield u
        for ch, vad in vads.items():
            async for u in emit(ch, vad.flush()):
                yield u
