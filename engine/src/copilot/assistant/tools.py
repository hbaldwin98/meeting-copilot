"""Tool plumbing for Claude calls: the in-process memory MCP server, the
user's external MCP servers, and the read-only guard."""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    create_sdk_mcp_server,
    tool,
)

MEMORY_TOOLS = ["mcp__memory__recall", "mcp__memory__topic"]


def memory_server(memory):
    @tool(
        "recall",
        "Full-text search of meeting transcripts and summaries. scope: meeting | past | all.",
        {"query": str, "scope": str},
    )
    async def recall(args: dict[str, Any]):
        scope = args.get("scope") if args.get("scope") in ("meeting", "past", "all") else "meeting"
        return {"content": [{"type": "text", "text": memory.recall(args["query"], scope)}]}

    @tool("topic", "One topic (by numeric id, e.g. 12 for T12) with related topics and its transcript.", {"id": int})
    async def topic(args: dict[str, Any]):
        return {"content": [{"type": "text", "text": memory.topic(int(args["id"]))}]}

    return create_sdk_mcp_server("memory", tools=[recall, topic])


def server_of(tool_name: str) -> str:
    """mcp__claude_ai_Atlassian__search -> claude_ai_Atlassian"""
    return tool_name.split("__")[1] if tool_name.startswith("mcp__") else ""


# First word of a tool's action name that implies a write.
_WRITE_VERBS = {
    "create", "update", "delete", "remove", "add", "edit", "write", "save", "send", "post", "put",
    "patch", "set", "move", "transition", "assign", "comment", "upload", "merge", "archive", "close",
    "publish", "share", "invite", "submit", "approve", "reply", "mark", "rename", "restore", "retire",
    "unshare", "resolve", "execute", "run", "import", "install", "uninstall", "start", "stop",
}
_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def is_write_tool(name: str) -> bool:
    action = name.split("__")[-1]
    words = [w.lower() for w in _SPLIT.findall(action)]
    return bool(words) and words[0] in _WRITE_VERBS


def read_only_guard(allow_servers: list[str]):
    """can_use_tool callback: allow read-style tools on allow-listed MCP servers
    (fnmatch patterns, e.g. "claude_ai_*"); deny everything else."""

    async def guard(name: str, _input: dict[str, Any], _ctx) -> Any:
        server = server_of(name)
        if server and any(fnmatch.fnmatch(server, p) for p in allow_servers) and not is_write_tool(name):
            return PermissionResultAllow()
        why = "writes are not allowed" if is_write_tool(name) else "this server is not allow-listed"
        return PermissionResultDeny(message=f"{name} denied: {why} (meeting copilot is read-only).")

    return guard