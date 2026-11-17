"""sherpa-onnx adapters: Parakeet (offline transducer) and Nemotron (streaming).

``provider`` is passed straight to ONNX Runtime: "cpu" works everywhere;
"directml" needs a sherpa-onnx build with DirectML enabled (AMD on Windows).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import numpy as np
import sherpa_onnx

from ..types import SAMPLE_RATE, AudioFrame, Utterance
from .batch import BatchTranscriber
from .filters import clean

MODELS = Path(__file__).resolve().parents[3] / "models"


def _model_files(model_dir: str | Path) -> dict[str, str]:
    d = Path(model_dir)
    if not d.is_absolute():
        d = MODELS / d
    if not d.exists():
        raise FileNotFoundError(f"{d} missing -- see `uv run copilot models --help`")

    def pick(prefix: str) -> str:
        cands = sorted(d.glob(f"{prefix}*.onnx"))
        # prefer int8 when both exist
        cands.sort(key=lambda p: "int8" not in p.name)
        if not cands:
            raise FileNotFoundError(f"no {prefix}*.onnx in {d}")
        return str(cands[0])

    return {
        "encoder": pick("encoder"),
        "decoder": pick("decoder"),
        "joiner": pick("joiner"),
        "tokens": str(d / "tokens.txt"),
    }


class SherpaOfflineTranscriber(BatchTranscriber):
    """Parakeet TDT and other NeMo offline transducers."""

    def __init__(self, name: str, model_dir: str, provider: str = "cpu", num_threads: int = 4, **vad_kw):
        super().__init__(name, **vad_kw)
        self.model_dir = model_dir
        self.provider = provider
        self.num_threads = num_threads

    def _load(self):
        return sherpa_onnx.OfflineRecognizer.from_transducer(
            **_model_files(self.model_dir),
            num_threads=self.num_threads,
            provider=self.provider,
            model_type="nemo_transducer",
        )

    def _decode(self, pcm: np.ndarray) -> str:
        s = self._model.create_stream()
        s.accept_waveform(SAMPLE_RATE, pcm)
        self._model.decode_stream(s)
        return s.result.text


class SherpaStreamingTranscriber:
    """Cache-aware streaming transducer (Nemotron streaming). Emits partials."""

    def __init__(
        self,
        name: str,
        model_dir: str,
        provider: str = "cpu",
        num_threads: int = 4,
        endpoint_silence: float = 0.8,
        max_utterance: float = 20.0,
    ):
        self.name = name
        self.model_dir = model_dir
        self.provider = provider
        self.num_threads = num_threads
        self.endpoint_silence = endpoint_silence
        self.max_utterance = max_utterance
        self._rec = None

    def _load(self):
        return sherpa_onnx.OnlineRecognizer.from_transducer(
            **_model_files(self.model_dir),
            num_threads=self.num_threads,
            sample_rate=SAMPLE_RATE,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=self.endpoint_silence,
            rule3_min_utterance_length=self.max_utterance,
            provider=self.provider,
        )

    def _step(self, stream, pcm: np.ndarray):
        rec = self._rec
        stream.accept_waveform(SAMPLE_RATE, pcm)
        while rec.is_ready(stream):
            rec.decode_stream(stream)
        text = rec.get_result(stream)
        endpoint = rec.is_endpoint(stream)
        if endpoint:
            rec.reset(stream)
        return text, endpoint

    async def load(self) -> None:
        if self._rec is None:
            self._rec = await asyncio.to_thread(self._load)

    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[Utterance]:
        await self.load()
        streams: dict[str, object] = {}
        last: dict[str, str] = {}
        start: dict[str, float] = {}

        async for f in frames:
            s = streams.get(f.channel) or streams.setdefault(f.channel, self._rec.create_stream())
            text, endpoint = await asyncio.to_thread(self._step, s, f.pcm)
            text = text.strip()
            now = f.t + len(f.pcm) / SAMPLE_RATE
            if text and f.channel not in start:
                start[f.channel] = f.t
            if endpoint:
                final = clean(text)
                if final:
                    yield Utterance(f.channel, round(start.get(f.channel, f.t), 2), round(now, 2), final, True)
                start.pop(f.channel, None)
                last[f.channel] = ""
            elif text and text != last.get(f.channel):
                last[f.channel] = text
                yield Utterance(f.channel, round(start[f.channel], 2), round(now, 2), text, False)

        for ch, s in streams.items():  # end of input: pad, finish, flush tails
            text = await asyncio.to_thread(self._finish, s)
            final = clean(text)
            if final and ch in start:
                yield Utterance(ch, round(start[ch], 2), round(now, 2), final, True)

    def _finish(self, stream) -> str:
        stream.accept_waveform(SAMPLE_RATE, np.zeros(SAMPLE_RATE, np.float32))
        stream.input_finished()
        while self._rec.is_ready(stream):
            self._rec.decode_stream(stream)
        return self._rec.get_result(stream).strip()
