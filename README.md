# Copilot

An agent that hears what your computer hears.

Copilot taps your system audio through **WASAPI loopback**. That means whatever
is playing through your speakers: a call, a lecture, a video, a podcast, a
stream. Your microphone can be added too. Everything is transcribed **locally**,
and the transcript goes to a **Claude agent that decides for itself when to
act**. It stays quiet until something is worth acting on. Then it can:

- surface a definition or fact on the spot
- spin up **background agents** that search the web, cross-check sources, or
  dig through your docs and tickets over MCP
- recall what was said earlier, today or in a previous session
- read the answer back to you in a local voice

All of it lands in a small always-on-top panel. You can see each agent working,
cancel it, or open its result.

```
loopback + mic ─▶ local ASR ─▶ scribe (Haiku) ──escalate?──▶ agent (Sonnet) ─┬─▶ instant cards
 (WASAPI)         Parakeet /     topic graph,                 recall() memory  ├─▶ web research agents
                  Nemotron /     every ~20 s                                   ├─▶ MCP docs agents
                  Whisper                                                      └─▶ local voice (Kokoro)
```

## Quick start (Windows 10/11)

```powershell
git clone https://github.com/hbaldwin98/meeting-copilot
cd meeting-copilot
.\run.ps1 -Install   # first time only: winget-installs uv, Node, pnpm, Rust, Claude Code
claude               # first time only: log in to Claude, then exit
.\run.ps1            # sets up packages + models (~1 GB) on first run, then starts
```

`run.ps1` is idempotent. It only installs, downloads or builds what is missing,
then opens the engine in its own window and the panel (tray icon, bottom-right).
Rust also needs the MSVC C++ build tools (Visual Studio Build Tools, "Desktop
development with C++").

Options:
- `-Engine nemotron`: pick a speech-recognition engine
- `-File recordings\x.wav -Assistant scripted`: demo from a recording, with no Claude calls
- `-Dev`: panel with hot reload
- `-Setup`: set up only, don't start

Hotkeys:
- `Ctrl+Shift+Space`: ask about the last ~90 s
- `Ctrl+Shift+K`: type a question
- `Ctrl+Shift+L`: show or hide the panel
- `Ctrl+Shift+P`: pause capture
- `Ctrl+Shift+.`: stop speech

Saying "Claude" or "copilot" wakes the agent immediately. Settings (the sliders
icon, or the tray menu) change voice, models, spending cap, devices and window
opacity.

## The agent loop

Nothing piles up in a context window. Memory lives on disk in SQLite
(`engine/data/memory.db`):
- every utterance, full-text indexed
- a topic graph for each session
- short summaries of past sessions
- a cache of agent results

| Call | Model | When | Sees |
|---|---|---|---|
| scribe | Haiku | every ~20 s batch | topic digest + new transcript → topic updates, "escalate?" |
| agent | Sonnet | on escalation, wake word, or your ask | digest + batch; can `recall()` this or past sessions |
| workers | Haiku (lookup, context) / Sonnet (research, docs) | spawned by the agent, in parallel | a self-contained brief; can `recall()`; results cached |

Each call is stateless, and its static system prompt is prompt-cached, so cost
per call stays flat however long a session runs. An optional `budget_usd`
limits automatic work per session; your own questions always run.

`docs` workers can use your claude.ai connectors (Linear, Atlassian, Drive…)
and any servers listed in `[mcp.servers]`, filtered by `[mcp].allow`. They are
**read-only**: tools whose names start with create/update/delete/send/… are
always denied.

## Voice

Answers are read aloud locally with Kokoro-82M (`kokoro-onnx`; espeak-ng
handles pronunciation). The first audio arrives about 0.8 s after an answer on
CPU. `speak` in `[voice]` controls what gets read:
- `asks`: only answers to your questions (headline + first sentence)
- `asks+tasks`: adds background-agent results
- `all`: everything

While it speaks, capture is muted so it never transcribes itself. It waits for
a pause in the audio (up to 6 s) before talking. Preview voices in Settings
with ▶, or run `uv run copilot say "Hello" --voice bf_emma`.

## Architecture

```
AudioSource ─frames─▶ Transcriber ─utterances─▶ Assistant ─events─▶ EventBus ⇄ Panel
 wasapi | file        parakeet | nemotron |      claude | scripted   ws://127.0.0.1:8765  Tauri + Svelte
                      whisper_*
```

| Module | Interface | Adapters |
|---|---|---|
| `engine/src/copilot/audio` | `frames()` → 16 kHz mono `AudioFrame`s tagged `me`/`them` | `WasapiSource` (loopback + mic), `FileSource` |
| `engine/src/copilot/asr` | `load()`, `transcribe(frames)` → `Utterance`s (partials + finals) | Parakeet, Nemotron (streaming), faster-whisper |
| `engine/src/copilot/assistant` | `hear`, `ask`, `cancel`, `events()` | `ClaudeAssistant`, `ScriptedAssistant` |
| `engine/src/copilot/memory` | `add`, `apply`, `digest`, `recall`, `topic`, `cached` | SQLite (FTS5) |
| `engine/src/copilot/voice` | `speak`, `stop`, `speaking` | Kokoro |
| `engine/src/copilot/bus.py` | JSON events out, commands in | WebSocket |

`session.py` is only wiring.

## Compare ASR engines on your own audio

```powershell
cd engine
uv run copilot bench ..\recordings\sample.wav --engines parakeet nemotron whisper_turbo
```

Put a reference transcript at `sample.ref.txt` to get the word error rate.
Engines are defined in `engine/config.toml`. Set `provider = "directml"` to
try the GPU once a DirectML-enabled sherpa-onnx build is installed.
