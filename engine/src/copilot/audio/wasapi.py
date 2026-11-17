"""Live capture on Windows: microphone ("me") + WASAPI loopback ("them").

Loopback captures whatever the default output device plays, so Zoom/Teams/Meet
audio is picked up without a virtual cable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

import numpy as np
import pyaudiowpatch as pyaudio
import soxr

from ..types import SAMPLE_RATE, AudioFrame, Channel

log = logging.getLogger(__name__)


class _Stream:
    """One device -> resampled mono frames pushed onto an asyncio queue."""

    def __init__(self, pa, device: dict, channel: Channel, out: asyncio.Queue, loop, t0: float):
        self.channel = channel
        self.out = out
        self.loop = loop
        self.t0 = t0
        self.nch = int(device["maxInputChannels"]) or 1
        self.sr = int(device["defaultSampleRate"])
        self.resampler = soxr.ResampleStream(self.sr, SAMPLE_RATE, 1, dtype="float32")
        self.stream = pa.open(
            format=pyaudio.paInt16,
            channels=self.nch,
            rate=self.sr,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=self.sr // 20,  # 50 ms
            stream_callback=self._callback,
        )
        log.info("capturing %s from %r (%d Hz, %d ch)", channel, device["name"], self.sr, self.nch)

    def _callback(self, in_data, frame_count, _time_info, _status):
        x = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
        x = x.reshape(-1, self.nch).mean(axis=1)
        y = self.resampler.resample_chunk(x)
        t = time.monotonic() - self.t0 - frame_count / self.sr
        if len(y):
            self.loop.call_soon_threadsafe(self.out.put_nowait, AudioFrame(self.channel, t, y))
        return (None, pyaudio.paContinue)

    def close(self):
        self.stream.stop_stream()
        self.stream.close()


class WasapiSource:
    def __init__(self, mic: bool = True, loopback: bool = True, mic_device: str | None = None):
        self.mic = mic
        self.loopback = loopback
        self.mic_device = mic_device

    def _find_mic(self, pa) -> dict:
        if self.mic_device:
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if self.mic_device.lower() in d["name"].lower() and d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
                    return d
            raise RuntimeError(f"no input device matching {self.mic_device!r}")
        return pa.get_default_input_device_info()

    async def frames(self) -> AsyncIterator[AudioFrame]:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[AudioFrame] = asyncio.Queue()
        t0 = time.monotonic()
        pa = pyaudio.PyAudio()
        streams: list[_Stream] = []
        try:
            if self.mic:
                streams.append(_Stream(pa, self._find_mic(pa), "me", q, loop, t0))
            if self.loopback:
                streams.append(_Stream(pa, pa.get_default_wasapi_loopback(), "them", q, loop, t0))
            while True:
                yield await q.get()
        finally:
            for s in streams:
                s.close()
            pa.terminate()


def list_devices() -> None:
    pa = pyaudio.PyAudio()
    try:
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d["maxInputChannels"] > 0:
                tag = "loopback" if d.get("isLoopbackDevice") else "input"
                print(f"[{i:>2}] {tag:8} {d['name']}  ({int(d['defaultSampleRate'])} Hz)")
    finally:
        pa.terminate()


def device_names() -> tuple[list[str], list[str]]:
    """(inputs, outputs) on the WASAPI host API, for settings dropdowns."""
    pa = pyaudio.PyAudio()
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
        ins, outs = [], []
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d["hostApi"] != wasapi or d.get("isLoopbackDevice"):
                continue
            if d["maxInputChannels"] > 0:
                ins.append(d["name"])
            if d["maxOutputChannels"] > 0:
                outs.append(d["name"])
        return sorted(set(ins)), sorted(set(outs))
    finally:
        pa.terminate()
