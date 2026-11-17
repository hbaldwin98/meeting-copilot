"""Check synthesis speed and write voice samples to recordings/."""

import sys
import time
import wave
from pathlib import Path

import numpy as np

from copilot.voice.kokoro import KokoroSpeaker
from copilot.voice.text import normalize

OUT = Path(__file__).resolve().parents[2] / "recordings"
TEXT = ("CockroachDB multi-region writes land around 100-300ms at P99. Figma spent $1.2M "
        "moving off Kubernetes autoscaling, about 40% of their infra budget.")

sys.stdout.reconfigure(encoding="utf-8")
print("normalized:", normalize(TEXT))
for voice in ("af_heart", "am_michael", "bf_emma"):
    sp = KokoroSpeaker(quiet=lambda: True, voice=voice)
    t = time.perf_counter(); sp._tts = sp._build(); load = time.perf_counter() - t
    first = sp._chunks(TEXT)[0]
    t = time.perf_counter(); sp.synth(first); t_first = time.perf_counter() - t
    t = time.perf_counter(); pcm, sr = sp.synth(TEXT); dt = time.perf_counter() - t
    with wave.open(str(OUT / f"voice-{voice}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"{voice}: load {load:.1f}s · first chunk {t_first:.2f}s · {len(pcm)/sr:.1f}s audio in {dt:.2f}s (RTF {dt/(len(pcm)/sr):.2f})")
