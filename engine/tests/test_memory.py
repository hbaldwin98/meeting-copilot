from copilot.assistant.tools import is_write_tool
from copilot.memory import open_memory
from copilot.types import Utterance


def _meeting(mem, lines):
    mem.start_meeting()
    for i, text in enumerate(lines):
        mem.add(Utterance("them", i * 5.0, i * 5.0 + 4, text))


def test_topics_digest_and_recall():
    mem = open_memory(":memory:")
    _meeting(mem, ["We are migrating Postgres to CockroachDB", "Raft overhead hurts write latency"])
    mem.apply([{"id": None, "title": "CockroachDB migration", "summary": "Moving off Postgres"}], 0, 9)
    tid = mem.topics()[0]["id"]
    mem.apply([{"id": tid, "title": "CockroachDB migration", "summary": "Raft latency concern", "related": []}], 5, 9)
    assert len(mem.topics()) == 1
    assert "Raft latency concern" in mem.digest()
    assert "Raft overhead" in mem.recall("raft latency")
    assert "Raft overhead" in mem.topic(tid)


def test_past_meetings_are_recallable_and_current_excluded():
    mem = open_memory(":memory:")
    _meeting(mem, ["We picked CockroachDB for the ledger service"])
    mem.end_meeting("Decided on CockroachDB for the ledger service.", title="DB choice")
    _meeting(mem, ["What did we decide about the ledger database?"])
    past = mem.recall("ledger database", scope="past")
    assert "DB choice" in past and "What did we decide" not in past


def test_empty_meetings_are_dropped_and_crashed_ones_closed():
    mem = open_memory(":memory:")
    mem.start_meeting()
    mem.end_meeting(None)  # nothing said
    assert mem.db.execute("SELECT count(*) FROM meetings").fetchone()[0] == 0
    _meeting(mem, ["hello there team"])
    mem.apply([{"id": None, "title": "Greetings", "summary": "hi"}], 0, 1)
    mem.start_meeting()  # previous never ended -> closed with fallback summary
    row = mem.db.execute("SELECT summary FROM meetings WHERE ended IS NOT NULL").fetchone()
    assert "Greetings" in row[0]


def test_result_cache():
    mem = open_memory(":memory:")
    mem.start_meeting()
    mem.remember("CockroachDB p99 write latency three regions", "lookup", {"headline": "~50ms", "body_md": "x"})
    assert mem.cached("p99 write latency of CockroachDB across three regions")["headline"] == "~50ms"
    assert mem.cached("Figma Postgres sharding blog") is None


def test_guard_allowlist():
    import asyncio

    from claude_agent_sdk import PermissionResultAllow
    from copilot.assistant.tools import read_only_guard

    g = read_only_guard(["claude_ai_*"])
    ok = lambda n: isinstance(asyncio.run(g(n, {}, None)), PermissionResultAllow)
    assert ok("mcp__claude_ai_Atlassian__searchConfluenceUsingCql")
    assert not ok("mcp__claude_ai_Atlassian__createJiraIssue")
    assert not ok("mcp__rea__open_binary")
    assert not ok("Bash")


def test_write_guard():
    for name in ["mcp__atlassian__createJiraIssue", "mcp__linear__save_issue", "mcp__x__addCommentToJiraIssue",
                 "mcp__gmail__send_message", "mcp__x__transitionJiraIssue"]:
        assert is_write_tool(name), name
    for name in ["mcp__atlassian__searchConfluenceUsingCql", "mcp__atlassian__getJiraIssue",
                 "mcp__linear__list_issues", "mcp__memory__recall", "mcp__drive__search"]:
        assert not is_write_tool(name), name
