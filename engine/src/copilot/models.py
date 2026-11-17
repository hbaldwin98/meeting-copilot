"""Download sherpa-onnx models into engine/models/. faster-whisper downloads its own."""

from __future__ import annotations

import tarfile
import urllib.request
from pathlib import Path

MODELS = Path(__file__).resolve().parents[2] / "models"
_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"

CATALOG = {
    "silero": "asr-models/silero_vad.onnx",
    "parakeet": "asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
    "parakeet_v3": "asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2",
    "nemotron": "asr-models/sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25.tar.bz2",
}


# kokoro-onnx model files (fp32 is ~5x faster than int8 on CPU)
_KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def download(names: list[str]) -> None:
    MODELS.mkdir(exist_ok=True)
    for n in names:
        if n == "kokoro":
            d = MODELS / "kokoro-v1.0"
            d.mkdir(exist_ok=True)
            for f in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
                if not (d / f).exists():
                    print(f"kokoro: downloading {f} ...", flush=True)
                    urllib.request.urlretrieve(_KOKORO + f, d / f)
            print(f"kokoro: ok -> {d}")
            continue
        rel = CATALOG[n]
        fname = rel.split("/")[-1]
        target = MODELS / fname.removesuffix(".tar.bz2")
        if target.exists():
            print(f"{n}: already present")
            continue
        tmp = MODELS / (fname + ".part")
        print(f"{n}: downloading {fname} ...", flush=True)
        urllib.request.urlretrieve(_BASE + rel, tmp)
        if fname.endswith(".tar.bz2"):
            with tarfile.open(tmp, "r:bz2") as tf:
                tf.extractall(MODELS, filter="data")
            tmp.unlink()
        else:
            tmp.rename(target)
        print(f"{n}: ok -> {target}")
