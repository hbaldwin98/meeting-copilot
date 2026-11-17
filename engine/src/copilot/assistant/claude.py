"""Claude-backed assistant on the Claude Agent SDK.

Every call is stateless and bounded -- nothing accumulates in a context window:

  scribe    (cheap model, every batch)  digest + new transcript -> topic-graph
            updates + "escalate?"; the topic graph lives in MeetingMemory
  listener  (strong model, only on escalate / trigger / ask) digest + batch ->
            instant cards + background tasks; can recall() the transcript
  workers   one query() each, parallel, cancellable, model chosen per kind;
            results cached in memory so repeats are free

System prompts are static, so each call's prefix is prompt-cached.
Auth comes from the Claude Code login (the SDK drives the bundled CLI).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import warnings

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolUseBlock,
    query,
)

from ..memory import SqliteMemory
from ..types import AgentEvent, Utterance
from . import prompts
from .tools import MEMORY_TOOLS, memory_server, read_only_guard

log = logging.getLogger(__name__)
# memory tools are intentionally auto-approved via allowed_tools
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")
_URL = re.compile(r"https?://[^\s)>\]]+")


def _lines(us: list[Utterance]) -> str:
    return "\n".join(f"[{int(u.t0 // 60):02d}:{int(u.t0 % 60):02d} {u.channel}] {u.text}" for u in us)


async def _one_message(text: str):
    # Streaming-input form: required for can_use_tool and in-process MCP servers.
    yield {"type": "user", "message": {"role": "user", "content": text}}


class ClaudeAssistant:
    def __init__(
        self,
        memory: SqliteMemory,
        scribe_model: str = "haiku",
        listener_model: str = "sonnet",
        worker_models: dict[str, str] | None = None,
        flush_secs: float = 20.0,
        idle_secs: float = 1.5,
        max_tasks: int = 3,
        trigger_words: tuple[str, ...] = ("claude", "copilot"),
        context_dirs: tuple[str, ...] = (),
        ask_window_secs: float = 90.0,
        budget_usd: float = 0.0,  # 0 = no cap
        task_budget_usd: float = 0.5,
        mcp: dict[str, Any] | None = None,
    ):
        self.memory = memory
        self.scribe_model = scribe_model
        self.listener_model = listener_model
        self.worker_models = {"lookup": "haiku", "research": "sonnet", "docs": "sonnet", "context": "haiku"} | (
            worker_models or {}
        )
        self.flush_secs = flush_secs
        self.idle_secs = idle_secs
        self.trigger_words = tuple(w.lower() for w in trigger_words)
        self.context_dirs = [str(Path(d).expanduser()) for d in context_dirs]
        self.ask_window_secs = ask_window_secs
        self.budget_usd = budget_usd
        self.task_budget_usd = task_budget_usd

        mcp = mcp or {}
        self.use_connectors = mcp.get("claude_ai_connectors", True)
        self.mcp_servers = mcp.get("servers", {})
        self.mcp_allow = list(mcp.get("allow", ["claude_ai_*"])) + list(self.mcp_servers)
        self.kinds = {"lookup", "research"}
        if self.mcp_allow:
            self.kinds.add("docs")
        if self.context_dirs:
            self.kinds.add("context")
        kinds_text = "\n".join(
            f"  - {k}: {prompts.TASK_KINDS[k].format(servers=', '.join(self.mcp_allow))}" for k in sorted(self.kinds)
        )
        self.listener_prompt = prompts.LISTENER.replace("{task_kinds}", kinds_text)

        self._events: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._kick = asyncio.Event()
        self._sem = asyncio.Semaphore(max_tasks)
        self._ids = itertools.count(1)
        self._pending: list[Utterance] = []
        self._first_pending_at = 0.0
        self._last_heard_at = 0.0
        self._asks: list[str] = []
        self._triggered = False
        self._tasks: dict[str, asyncio.Task] = {}
        self._spend = {"scribe": 0.0, "listener": 0.0, "agents": 0.0}
        self._loop_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ interface
    async def __aenter__(self):
        self.memory.start_meeting()
        self._loop_task = asyncio.create_task(self._flush_loop(), name="assistant")
        extra = f" · MCP: {', '.join(self.mcp_allow)}" if self.mcp_allow else ""
        self._emit("status", state="ready", detail=f"{self.scribe_model}/{self.listener_model}{extra}")
        self._emit_topics()
        return self

    async def __aexit__(self, *exc):
        if self._loop_task:
            self._loop_task.cancel()
        for t in list(self._tasks.values()):
            t.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        try:
            out, _ = await asyncio.wait_for(
                self._call("scribe", self.scribe_model, prompts.SUMMARY, self.memory.digest(), prompts.SUMMARY_SCHEMA),
                timeout=60,
            )
            self.memory.end_meeting(out.get("summary") if out else None, out.get("title") if out else None)
        except Exception:
            self.memory.end_meeting(None)  # fallback summary from topic titles

    def live_settings(self) -> dict:
        """Settings keys this assistant applies without a restart."""
        a = "assistant."
        return {
            a + "listener_model": lambda v: setattr(self, "listener_model", v),
            a + "scribe_model": lambda v: setattr(self, "scribe_model", v),
            a + "worker_models.lookup": lambda v: self.worker_models.__setitem__("lookup", v),
            a + "worker_models.research": lambda v: self.worker_models.__setitem__("research", v),
            a + "flush_secs": lambda v: setattr(self, "flush_secs", float(v)),
            a + "budget_usd": lambda v: setattr(self, "budget_usd", float(v)),
            a + "trigger_words": lambda v: setattr(self, "trigger_words", tuple(w.strip().lower() for w in v if w.strip())),
        }

    async def hear(self, u: Utterance) -> None:

        if not u.final:
            return
        self.memory.add(u)
        now = time.monotonic()
        if not self._pending:
            self._first_pending_at = now
        self._pending.append(u)
        self._last_heard_at = now
        if any(w in u.text.lower() for w in self.trigger_words):
            self._triggered = True
        self._kick.set()

    async def ask(self, prompt: str) -> None:
        self._asks.append(prompt.strip() or "Help me with what is being discussed right now.")
        self._kick.set()

    async def cancel(self, task_id: str) -> None:
        if (t := self._tasks.get(task_id)) and not t.done():
            t.cancel()

    async def events(self) -> AsyncIterator[AgentEvent]:
        while True:
            yield await self._events.get()

    # ------------------------------------------------------------------ batching
    async def _flush_loop(self):
        while True:
            try:
                await asyncio.wait_for(self._kick.wait(), timeout=0.5)
            except TimeoutError:
                pass
            self._kick.clear()
            if not self._should_flush():
                continue
            try:
                await self._flush()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("flush failed")
                self._emit("status", state="error", detail=str(e)[:200])

    def _should_flush(self) -> bool:
        if self._asks:
            return True
        if not self._pending:
            return False
        now = time.monotonic()
        quiet = now - self._last_heard_at >= self.idle_secs
        if self._triggered and quiet:
            return True
        age = now - self._first_pending_at
        return (age >= self.flush_secs and quiet) or age >= self.flush_secs * 2

    @property
    def _over_budget(self) -> bool:
        return self.budget_usd > 0 and sum(self._spend.values()) >= self.budget_usd

    async def _flush(self):
        batch, self._pending = self._pending, []
        asks, self._asks = self._asks, []
        triggered, self._triggered = self._triggered, False

        escalate = False
        if batch:
            self._emit("status", state="thinking", detail="scribe")
            msg = f"{self.memory.digest()}\n\n<transcript>\n{_lines(batch)}\n</transcript>"
            out, _ = await self._call("scribe", self.scribe_model, prompts.SCRIBE, msg, prompts.SCRIBE_SCHEMA)
            if out:
                self.memory.apply(out.get("topics", []), batch[0].t0, batch[-1].t1)
                self._emit_topics()
                escalate = bool(out.get("escalate"))
                if escalate:
                    log.info("escalate: %s", out.get("reason", ""))

        if asks or ((escalate or triggered) and not self._over_budget):
            self._emit("status", state="thinking", detail="listener")
            await self._listen(batch, asks)
        self._emit_status()

    async def _listen(self, batch: list[Utterance], asks: list[str]):
        parts = [self.memory.digest()]
        if asks and not batch:
            batch = self.memory.recent(self.ask_window_secs)
        if batch:
            parts.append(f"<transcript>\n{_lines(batch)}\n</transcript>")
        parts += [f"<ask>{a}</ask>" for a in asks]
        out, _ = await self._call(
            "listener", self.listener_model, self.listener_prompt, "\n\n".join(parts), prompts.LISTENER_SCHEMA,
            tools=MEMORY_TOOLS, max_turns=6,
        )
        if not out:
            return
        origin = "ask" if asks else "auto"
        for c in out.get("cards", []):
            card = {"headline": c["headline"], "body_md": c["body_md"], "sources": _URL.findall(c["body_md"])}
            self.memory.remember(c["headline"], "instant", card)
            self._emit("card", id=f"c{next(self._ids)}", task_id=None, kind="instant", origin=origin, **card)
        for t in out.get("tasks", []):
            kind = t["kind"] if t["kind"] in self.kinds else "lookup"
            if hit := self.memory.cached(t["query"]):
                self._emit("card", id=f"c{next(self._ids)}", task_id=None, kind="cached", origin=origin,
                           headline=hit["headline"], body_md=hit["body_md"], sources=hit["sources"])
                continue
            if self._over_budget:
                continue
            self._spawn(t["title"], kind, t["query"], t["brief"], origin)

    # ------------------------------------------------------------------ workers
    def _spawn(self, title: str, kind: str, query_: str, brief: str, origin: str = "auto") -> str:
        tid = f"t{next(self._ids)}"
        self._emit("task.started", id=tid, title=title, kind=kind)
        task = asyncio.create_task(self._run_task(tid, title, kind, query_, brief, origin), name=tid)
        self._tasks[tid] = task
        task.add_done_callback(lambda _t: self._tasks.pop(tid, None))
        return tid

    async def _run_task(self, tid: str, title: str, kind: str, query_: str, brief: str, origin: str):
        try:
            async with self._sem:
                self._emit("task.progress", id=tid, note="working")
                tools = list(MEMORY_TOOLS)
                builtin: list[str] = []
                if kind in ("lookup", "research"):
                    builtin = ["WebSearch", "WebFetch"]
                elif kind == "context":
                    builtin = ["Read", "Grep", "Glob"]
                _, text = await self._call(
                    "agents", self.worker_models.get(kind, "sonnet"), prompts.WORKERS[kind], brief,
                    builtin=builtin, tools=tools + builtin, external=(kind == "docs"),
                    max_turns=6 if kind == "lookup" else 12, budget=self.task_budget_usd,
                    cwd=self.context_dirs[0] if kind == "context" and self.context_dirs else None,
                    on_tool=lambda b: self._emit("task.progress", id=tid, note=_describe(b)),
                )
            headline, body = _split_card(text, title)
            card = {"headline": headline, "body_md": body, "sources": _URL.findall(body)}
            self.memory.remember(query_, kind, card)
            cid = f"c{next(self._ids)}"
            self._emit("card", id=cid, task_id=tid, kind=kind, origin=origin, **card)
            self._emit("task.done", id=tid, card_id=cid)
        except asyncio.CancelledError:
            self._emit("task.cancelled", id=tid)
            raise
        except Exception as e:
            log.exception("task %s failed", tid)
            self._emit("task.failed", id=tid, error=str(e)[:200])
        finally:
            self._emit_status()

    # ------------------------------------------------------------------ one Claude call
    async def _call(
        self,
        bucket: str,
        model: str,
        system: str,
        message: str,
        schema: dict | None = None,
        *,
        tools: list[str] = (),
        builtin: list[str] = (),
        external: bool = False,
        max_turns: int = 1,
        budget: float | None = None,
        cwd: str | None = None,
        on_tool: Callable[[ToolUseBlock], None] | None = None,
    ) -> tuple[dict | None, str]:
        servers: dict[str, Any] = {}
        if any(t.startswith("mcp__memory__") for t in tools):
            servers["memory"] = memory_server(self.memory)
        if external:
            servers.update(self.mcp_servers)
        opts = ClaudeAgentOptions(
            system_prompt=system,
            model=model,
            tools=list(builtin),
            allowed_tools=list(tools),
            mcp_servers=servers,
            # docs agents also see the account's claude.ai connectors; the guard limits them
            strict_mcp_config=not (external and self.use_connectors),
            # claude.ai connectors only load with user settings; the guard still limits them
            setting_sources=["user"] if (external and self.use_connectors) else [],
            max_turns=max_turns + (1 if schema else 0),
            max_budget_usd=budget,
            output_format={"type": "json_schema", "schema": schema} if schema else None,
            can_use_tool=read_only_guard(self.mcp_allow if external else []),
            cwd=cwd,
            add_dirs=self.context_dirs[1:] if cwd else [],
        )
        structured, text = None, ""
        async for m in query(prompt=_one_message(message), options=opts):
            if isinstance(m, AssistantMessage) and on_tool:
                for b in m.content:
                    if isinstance(b, ToolUseBlock):
                        on_tool(b)
            elif isinstance(m, ResultMessage):
                self._spend[bucket] += m.total_cost_usd or 0.0  # one-shot: this is the call's own cost
                if m.is_error and not m.structured_output:
                    raise RuntimeError(m.result or m.subtype)
                structured, text = m.structured_output, m.result or ""
        return structured, text

    # ------------------------------------------------------------------ events
    def _emit(self, type_: str, **data):
        self._events.put_nowait(AgentEvent(type_, data))

    def _emit_topics(self):
        self._emit("topics", items=self.memory.topics())

    def _emit_status(self):
        s = self._spend
        total = sum(s.values())
        state = "budget" if self._over_budget else "listening"
        self._emit("status", state=state, detail=f"${total:.3f}")
        self._emit("cost", total=round(total, 4), **{k: round(v, 4) for k, v in s.items()}, budget=self.budget_usd)


def _describe(b: ToolUseBlock) -> str:
    i = b.input or {}
    detail = i.get("query") or i.get("url") or i.get("pattern") or i.get("file_path") or i.get("cql") or i.get("jql") or ""
    name = b.name.split("__")[-1] if b.name.startswith("mcp__") else b.name
    return f"{name}: {detail}"[:120]


def _split_card(md: str, fallback: str) -> tuple[str, str]:
    lines = md.strip().splitlines()
    if lines and lines[0].startswith("#"):
        return lines[0].lstrip("# ").strip(), "\n".join(lines[1:]).strip()
    return fallback, md.strip()
