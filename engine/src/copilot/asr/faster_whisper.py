"""faster-whisper adapter. On AMD it runs on CPU (CTranslate2 has no ROCm/DirectML)."""

from __future__ import annotations

import numpy as np

from .batch import BatchTranscriber


class FasterWhisperTranscriber(BatchTranscriber):
    def __init__(
        self,
        name: str,
        model: str = "turbo",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "en",
        cpu_threads: int = 0,
        **vad_kw,
    ):
        super().__init__(name, **vad_kw)
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.cpu_threads = cpu_threads

    def _load(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise ImportError("faster-whisper not installed: `uv sync --extra whisper`") from e
        return WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
        )

    def _decode(self, pcm: np.ndarray) -> str:
        segments, _ = self._model.transcribe(
            pcm,
            language=self.language,
            beam_size=1,
            vad_filter=False,  # we already segmented with silero
            condition_on_previous_text=False,  # big hallucination reducer
            no_speech_threshold=0.6,
        )
        return " ".join(s.text for s in segments if s.no_speech_prob < 0.6)
