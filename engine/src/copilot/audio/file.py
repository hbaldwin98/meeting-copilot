"""Replay a WAV file as if it were live audio. Used by tests and the bench."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from typing import AsyncIterator

import numpy as np
import soxr

from ..types import SAMPLE_RATE, AudioFrame, Channel


class FileSource:
    """Mono files go to ``channel``; stereo files map left->me, right->them."""

    def __init__(
        self,
        path: str | Path,
        channel: Channel = "them",
        realtime: bool = True,
        chunk_ms: int = 100,
    ):
        self.path = Path(path)
        self.channel = channel
        self.realtime = realtime
        self.chunk_ms = chunk_ms

    def _load(self) -> list[tuple[Channel, np.ndarray]]:
        with wave.open(str(self.path), "rb") as w:
            sr, nch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if width != 2:
            raise ValueError(f"{self.path}: only 16-bit PCM WAV is supported")
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        data = data.reshape(-1, nch)
        if nch == 1:
            tracks: list[tuple[Channel, np.ndarray]] = [(self.channel, data[:, 0])]
        else:
            tracks = [("me", data[:, 0]), ("them", data[:, 1])]
        if sr != SAMPLE_RATE:
            tracks = [(c, soxr.resample(x, sr, SAMPLE_RATE).astype(np.float32)) for c, x in tracks]
        return tracks

    async def frames(self) -> AsyncIterator[AudioFrame]:
        tracks = await asyncio.to_thread(self._load)
        step = SAMPLE_RATE * self.chunk_ms // 1000
        n = max(len(x) for _, x in tracks)
        loop = asyncio.get_running_loop()
        start = loop.time()
        for i in range(0, n, step):
            t = i / SAMPLE_RATE
            if self.realtime:
                delay = start + t - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
            for ch, x in tracks:
                chunk = x[i : i + step]
                if len(chunk):
                    yield AudioFrame(ch, t, np.ascontiguousarray(chunk))
            if not self.realtime:
                await asyncio.sleep(0)
