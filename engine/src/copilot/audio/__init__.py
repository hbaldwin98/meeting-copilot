"""AudioSource module.

Interface: ``source.frames()`` yields AudioFrame forever (or until the source
ends). Every frame is already 16 kHz mono float32 and tagged with a channel,
so nothing downstream knows about devices, sample rates or WASAPI.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from ..types import AudioFrame


class AudioSource(Protocol):
    def frames(self) -> AsyncIterator[AudioFrame]: ...


def make_source(kind: str, **kw) -> AudioSource:
    if kind == "wasapi":
        from .wasapi import WasapiSource

        return WasapiSource(**kw)
    if kind == "file":
        from .file import FileSource

        return FileSource(**kw)
    raise ValueError(f"unknown audio source {kind!r}")
