"""Compare ASR engines on your own recordings.

    uv run copilot bench recordings/standup.wav --engines parakeet nemotron whisper_turbo

Reports load time, real-time factor (RTF = processing time / audio duration,
lower is better), first-final latency, and WER if ``<wav>.ref.txt`` exists.
Transcripts are written next to the wav as ``<wav>.<engine>.txt``.
"""

from __future__ import annotations

import asyncio
import re
import time
import wave
from pathlib import Path

from ..audio.file import FileSource
from . import make_transcriber


def _wer(ref: str, hyp: str) -> float:
    norm = lambda s: re.sub(r"[^a-z0-9' ]+", " ", s.lower()).split()
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)] / max(len(r), 1)


async def _run_one(name: str, engines: dict, wav: Path) -> dict:
    with wave.open(str(wav)) as w:
        dur = w.getnframes() / w.getframerate()
    tr = make_transcriber(name, engines)

    t_load = time.perf_counter()
    await tr.load()
    load_s = time.perf_counter() - t_load

    t0 = time.perf_counter()
    finals = []
    async for u in tr.transcribe(FileSource(wav, realtime=False).frames()):
        if u.final:
            finals.append(u)
    proc_s = time.perf_counter() - t0

    text = "\n".join(f"[{u.t0:7.2f}] {u.channel}: {u.text}" for u in finals)
    wav.with_suffix(f".{name}.txt").write_text(text, encoding="utf-8")
    ref = wav.with_suffix(".ref.txt")
    wer = _wer(ref.read_text(encoding="utf-8"), " ".join(u.text for u in finals)) if ref.exists() else None
    return {"engine": name, "load_s": load_s, "rtf": proc_s / dur, "proc_s": proc_s, "dur_s": dur, "utts": len(finals), "wer": wer}


async def bench(wav: Path, names: list[str], engines: dict) -> None:
    rows = []
    for n in names:
        print(f"-- {n} ...", flush=True)
        try:
            rows.append(await _run_one(n, engines, wav))
        except Exception as e:  # keep benchmarking the rest
            print(f"   failed: {e}")
    print(f"\n{'engine':<18}{'load s':>8}{'RTF':>8}{'utts':>6}{'WER':>8}")
    for r in rows:
        wer = f"{r['wer']*100:6.1f}%" if r["wer"] is not None else "     -"
        print(f"{r['engine']:<18}{r['load_s']:>8.1f}{r['rtf']:>8.3f}{r['utts']:>6}{wer:>8}")
    print(f"\naudio: {rows[0]['dur_s']:.1f}s" if rows else "")
