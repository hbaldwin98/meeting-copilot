# Meeting Copilot

Listens to your meetings (mic + system audio), transcribes locally, and keeps a
persistent Claude session that surfaces context and spawns background agents.

```
AudioSource ─frames─▶ Transcriber ─utterances─▶ Assistant ─events─▶ EventBus ⇄ Panel
 wasapi | file        parakeet | nemotron |      claude | scripted   ws://127.0.0.1:8765  Tauri + Svelte
                      whisper_*
```

| Module | Interface | Adapters |
|---|---|---|
| `engine/src/copilot/audio` | `frames()` → 16 kHz mono `AudioFrame`s tagged `me`/`them` | `WasapiSource`, `FileSource` |
| `engine/src/copilot/asr` | `load()`, `transcribe(frames)` → `Utterance`s (partials + finals) | Parakeet, Nemotron (streaming), faster-whisper |
| `engine/src/copilot/assistant` | `hear`, `ask`, `cancel`, `events()` | `ClaudeAssistant`, `ScriptedAssistant` |
| `engine/src/copilot/bus.py` | JSON events out, `{cmd: ask/cancel/pause/resume}` in | WebSocket |

`session.py` is only wiring.

## How Claude is used (and kept cheap)

Nothing accumulates in a context window. Memory lives in SQLite
(`engine/data/memory.db`): every utterance (full-text indexed), a topic graph
per meeting, short summaries of past meetings, and a cache of agent results.

| Call | Model | When | Sees |
|---|---|---|---|
| scribe | Haiku | every ~20 s batch | topic digest + new batch -> topic updates, "escalate?" |
| listener | Sonnet | escalation, trigger word, or your ask | digest + batch; can `recall()` transcript / past meetings |
| agents | Haiku (lookup, context) / Sonnet (research, docs) | spawned by listener | brief; can `recall()`; results cached |

System prompts are static so every call's prefix is prompt-cached. A
per-meeting `budget_usd` stops automatic work once reached (asks still run).

`docs` agents can use your claude.ai connectors (Linear, Atlassian, Drive…)
and any servers in `[mcp.servers]`, filtered by `[mcp].allow`. They are
read-only: tool names starting with create/update/delete/send/… are denied.

## Voice

Answers can be read aloud locally with Kokoro-82M (`kokoro-onnx`, espeak-ng
pronunciation, ~0.8 s to first audio on CPU). Configure under `[voice]`:
`speak = "asks"` reads only answers to your asks (headline + first sentence);
`asks+tasks` adds agent results; `all` reads everything. While it speaks,
capture is muted so the copilot never transcribes itself. It waits for a
pause in the conversation (up to 6 s) before talking.

Try voices: `uv run copilot say "Hello there" --voice am_michael`.
Panel: 🔊 toggles voice, "Read aloud" on any card, `Ctrl+Shift+.` stops speech.

## Quick start (Windows 10/11)

```powershell
git clone https://github.com/hbaldwin98/meeting-copilot
cd meeting-copilot
.\run.ps1 -Install   # first time only: winget-installs uv, Node, pnpm, Rust, Claude Code
claude               # first time only: log in to Claude, then exit
.\run.ps1            # sets up packages + models (~1 GB) on first run, then starts
```

`run.ps1` is idempotent: it only installs/downloads/builds what is missing,
then opens the engine in its own window and the panel (tray icon, bottom-right).
Rust also needs the MSVC C++ build tools (Visual Studio Build Tools, "Desktop
development with C++").

Options: `-Engine nemotron` · `-File recordings\x.wav -Assistant scripted`
(demo without a meeting or Claude calls) · `-Dev` (panel hot reload) · `-Setup`.

Hotkeys: `Ctrl+Shift+Space` ask about the last ~90 s · `Ctrl+Shift+K` type a
question · `Ctrl+Shift+L` show/hide · `Ctrl+Shift+P` pause capture ·
`Ctrl+Shift+.` stop speech. Saying "Claude" or "copilot" in the meeting
forces a check-in. Settings (sliders icon or tray menu) change voice, models,
budget, devices and window opacity.
## Compare ASR engines on your own audio

```powershell
cd engine
uv run copilot bench ..\recordings\standup.wav --engines parakeet nemotron whisper_turbo
```

Put a reference transcript at `standup.ref.txt` to get WER. Engines are
defined in `engine/config.toml`; set `provider = "directml"` to try the GPU
once a DirectML-enabled sherpa-onnx build is installed.
