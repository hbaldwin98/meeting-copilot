"""Local Kokoro-82M voice (kokoro-onnx: ONNX Runtime + bundled espeak-ng G2P).

espeak-ng phonemizes every word, so names like "Kubernetes" are pronounced
rather than skipped. Text is cut into short chunks; chunk n+1 is synthesized
while chunk n plays, so speech starts after the first short chunk is ready.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np
import pyaudiowpatch as pyaudio

from .text import normalize

log = logging.getLogger(__name__)
MODELS = Path(__file__).resolve().parents[3] / "models"

# a/b = American/British, f/m = female/male.
VOICES = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore", "af_nicole", "af_nova",
    "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]
_SPLIT = re.compile(r"(?<=[.!?;:,])\s+")


class KokoroSpeaker:
    def __init__(
        self,
        quiet: Callable[[], bool],
        model_dir: str = "kokoro-v1.0",
        voice: str = "bf_emma",
        speed: float = 1.05,
        volume: float = 0.9,
        output_device: str | None = None,
        max_wait: float = 6.0,
        tail_secs: float = 0.4,
    ):
        self.quiet = quiet
        self.model_dir = Path(model_dir) if Path(model_dir).is_absolute() else MODELS / model_dir
        self.voice = voice
        self.speed = speed
        self.volume = volume
        self.output_device = output_device
        self.max_wait = max_wait
        self.tail_secs = tail_secs

        self._tts = None
        self._queue: asyncio.Queue[tuple[str, str | None, bool]] = asyncio.Queue()
        self._stop = threading.Event()
        self._worker: asyncio.Task | None = None
        self._playing = False
        self._until = 0.0

    @property
    def speaking(self) -> bool:
        return self._playing or time.monotonic() < self._until

    # ------------------------------------------------------------ interface
    async def load(self) -> None:
        if self._tts is None:
            self._tts = await asyncio.to_thread(self._build)
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="speaker")

    async def speak(self, text: str, voice: str | None = None, wait: bool = True) -> None:
        if text.strip():
            await self.load()
            self._queue.put_nowait((text.strip(), voice, wait))

    def stop(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
        self._stop.set()

    # ------------------------------------------------------------ internals
    def _build(self):
        from kokoro_onnx import Kokoro

        model, voices = self.model_dir / "kokoro-v1.0.onnx", self.model_dir / "voices-v1.0.bin"
        if not model.exists():
            raise FileNotFoundError(f"{model} missing -- run `uv run copilot models kokoro`")
        tts = Kokoro(str(model), str(voices))
        tts.create("Ready.", voice=self.voice)  # warm up ONNX Runtime
        return tts

    def synth(self, text: str, voice: str | None = None) -> tuple[np.ndarray, int]:
        pcm, sr = self._tts.create(normalize(text), voice=voice or self.voice, speed=self.speed, lang="en-us")
        return np.asarray(pcm, dtype=np.float32), sr

    def _chunks(self, text: str, max_words: int = 14) -> list[str]:
        out = []
        for part in (p.strip() for p in _SPLIT.split(text) if p.strip()):
            words = part.split()
            out += [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]
        return out

    def _device_index(self, pa) -> int | None:
        if not self.output_device:
            return None
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d["maxOutputChannels"] > 0 and self.output_device.lower() in d["name"].lower():
                return i
        log.warning("output device %r not found; using default", self.output_device)
        return None

    async def _run(self):
        while True:
            text, voice, wait = await self._queue.get()
            self._stop.clear()
            waited = 0.0
            while wait and not self.quiet() and waited < self.max_wait and not self._stop.is_set():
                await asyncio.sleep(0.2)
                waited += 0.2
            try:
                await asyncio.to_thread(self._say, text, voice or self.voice)
            except Exception:
                log.exception("speech failed")

    def _say(self, text: str, voice: str):
        log.info("speaking: %s", text[:120])
        chunks = self._chunks(text)
        pa = pyaudio.PyAudio()
        stream = None
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                nxt = ex.submit(self.synth, chunks[0], voice) if chunks else None
                for i in range(len(chunks)):
                    pcm, sr = nxt.result()
                    nxt = ex.submit(self.synth, chunks[i + 1], voice) if i + 1 < len(chunks) else None
                    if self._stop.is_set():
                        return
                    if not len(pcm):
                        continue
                    if stream is None:
                        stream = pa.open(format=pyaudio.paFloat32, channels=1, rate=sr, output=True,
                                         output_device_index=self._device_index(pa))
                        self._playing = True
                    pcm = pcm * self.volume
                    step = sr // 20
                    for j in range(0, len(pcm), step):
                        if self._stop.is_set():
                            return
                        stream.write(pcm[j : j + step].tobytes())
        finally:
            self._playing = False
            self._until = time.monotonic() + self.tail_secs
            if stream is not None:
                stream.stop_stream()
                stream.close()
            pa.terminate()
