from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..types import Utterance

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings(id INTEGER PRIMARY KEY, started REAL, ended REAL, title TEXT, summary TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS meetings_fts USING fts5(title, summary, content='meetings', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS m_ai AFTER INSERT ON meetings BEGIN
  INSERT INTO meetings_fts(rowid, title, summary) VALUES(new.id, coalesce(new.title,''), coalesce(new.summary,''));
END;
CREATE TRIGGER IF NOT EXISTS m_au AFTER UPDATE ON meetings BEGIN
  INSERT INTO meetings_fts(meetings_fts, rowid, title, summary) VALUES('delete', old.id, coalesce(old.title,''), coalesce(old.summary,''));
  INSERT INTO meetings_fts(rowid, title, summary) VALUES(new.id, coalesce(new.title,''), coalesce(new.summary,''));
END;
CREATE TRIGGER IF NOT EXISTS m_ad AFTER DELETE ON meetings BEGIN
  INSERT INTO meetings_fts(meetings_fts, rowid, title, summary) VALUES('delete', old.id, coalesce(old.title,''), coalesce(old.summary,''));
END;

CREATE TABLE IF NOT EXISTS utterances(id INTEGER PRIMARY KEY, meeting INTEGER, channel TEXT, t0 REAL, t1 REAL, text TEXT);
CREATE INDEX IF NOT EXISTS utt_m ON utterances(meeting, t0);
CREATE VIRTUAL TABLE IF NOT EXISTS utterances_fts USING fts5(text, content='utterances', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS u_ai AFTER INSERT ON utterances BEGIN
  INSERT INTO utterances_fts(rowid, text) VALUES(new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS u_ad AFTER DELETE ON utterances BEGIN
  INSERT INTO utterances_fts(utterances_fts, rowid, text) VALUES('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS topics(id INTEGER PRIMARY KEY, meeting INTEGER, title TEXT, summary TEXT, t0 REAL, t1 REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS topics_fts USING fts5(title, summary, content='topics', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS t_ai AFTER INSERT ON topics BEGIN
  INSERT INTO topics_fts(rowid, title, summary) VALUES(new.id, new.title, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS t_au AFTER UPDATE ON topics BEGIN
  INSERT INTO topics_fts(topics_fts, rowid, title, summary) VALUES('delete', old.id, old.title, old.summary);
  INSERT INTO topics_fts(rowid, title, summary) VALUES(new.id, new.title, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS t_ad AFTER DELETE ON topics BEGIN
  INSERT INTO topics_fts(topics_fts, rowid, title, summary) VALUES('delete', old.id, old.title, old.summary);
END;
CREATE TABLE IF NOT EXISTS topic_spans(topic INTEGER, t0 REAL, t1 REAL);
CREATE TABLE IF NOT EXISTS edges(a INTEGER, b INTEGER, PRIMARY KEY(a, b));

CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY, meeting INTEGER, query TEXT, kind TEXT,
  headline TEXT, body_md TEXT, sources TEXT, created REAL);
"""

_STOP = set("a an the of to in on for and or is are was were be what how why who when where which does do did "
            "about with from at by it this that there their our we you i me my".split())
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if w not in _STOP and len(w) > 1}


def _fts(q: str) -> str:
    toks = _tokens(q)
    return " OR ".join(f'"{t}"' for t in toks) if toks else '""'


def _ts(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def _date(epoch: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(epoch))


class SqliteMemory:
    def __init__(self, path: str | Path, digest_chars: int = 6000, cache_days: float = 14):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.digest_chars = digest_chars
        self.cache_days = cache_days
        self.meeting: int | None = None

    # ------------------------------------------------------------ lifecycle
    def start_meeting(self, title: str | None = None) -> int:
        for row in self.db.execute("SELECT id FROM meetings WHERE ended IS NULL").fetchall():
            self.end_meeting(None, meeting=row["id"])  # crashed/killed sessions
        cur = self.db.execute("INSERT INTO meetings(started, title) VALUES(?, ?)", (time.time(), title))
        self.db.commit()
        self.meeting = cur.lastrowid
        return self.meeting

    def end_meeting(self, summary: str | None, title: str | None = None, meeting: int | None = None) -> None:
        m = meeting or self.meeting
        if m is None:
            return
        if not self.db.execute("SELECT 1 FROM utterances WHERE meeting=? LIMIT 1", (m,)).fetchone():
            self.forget(m)  # nothing was said; don't keep empty meetings
            return
        if summary is None:  # fallback: topic titles
            titles = [r["title"] for r in self.db.execute("SELECT title FROM topics WHERE meeting=? ORDER BY t0", (m,))]
            summary = "Topics: " + "; ".join(titles) if titles else "(no topics recorded)"
        self.db.execute(
            "UPDATE meetings SET ended=?, summary=?, title=coalesce(?, title) WHERE id=?",
            (time.time(), summary, title, m),
        )
        self.db.commit()

    def forget(self, meeting: int) -> None:
        tids = [r["id"] for r in self.db.execute("SELECT id FROM topics WHERE meeting=?", (meeting,))]
        q = ",".join("?" * len(tids))
        if tids:
            self.db.execute(f"DELETE FROM edges WHERE a IN ({q}) OR b IN ({q})", tids + tids)
            self.db.execute(f"DELETE FROM topic_spans WHERE topic IN ({q})", tids)
        for table in ("topics", "utterances", "results"):
            self.db.execute(f"DELETE FROM {table} WHERE meeting=?", (meeting,))
        self.db.execute("DELETE FROM meetings WHERE id=?", (meeting,))
        self.db.commit()
        if meeting == self.meeting:
            self.meeting = None

    # ------------------------------------------------------------ writes
    def add(self, u: Utterance) -> None:
        if not u.final or self.meeting is None:
            return
        self.db.execute(
            "INSERT INTO utterances(meeting, channel, t0, t1, text) VALUES(?,?,?,?,?)",
            (self.meeting, u.channel, u.t0, u.t1, u.text),
        )
        self.db.commit()

    def apply(self, topics: list[dict[str, Any]], t0: float, t1: float) -> None:
        """Each item: {id?: int, title, summary, related?: [int]}. Unknown ids become new topics."""
        for item in topics or []:
            tid = item.get("id")
            row = (
                self.db.execute("SELECT id FROM topics WHERE id=? AND meeting=?", (tid, self.meeting)).fetchone()
                if tid
                else None
            )
            if row:
                self.db.execute(
                    "UPDATE topics SET title=?, summary=?, t1=? WHERE id=?",
                    (item["title"], item["summary"], t1, tid),
                )
            else:
                tid = self.db.execute(
                    "INSERT INTO topics(meeting, title, summary, t0, t1) VALUES(?,?,?,?,?)",
                    (self.meeting, item["title"], item["summary"], t0, t1),
                ).lastrowid
            self.db.execute("INSERT INTO topic_spans VALUES(?,?,?)", (tid, t0, t1))
            for other in item.get("related") or []:
                if isinstance(other, int) and other != tid:
                    self.db.execute("INSERT OR IGNORE INTO edges VALUES(?,?)", (min(tid, other), max(tid, other)))
        self.db.commit()

    def remember(self, query: str, kind: str, card: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO results(meeting, query, kind, headline, body_md, sources, created) VALUES(?,?,?,?,?,?,?)",
            (self.meeting, query, kind, card["headline"], card["body_md"], json.dumps(card.get("sources", [])), time.time()),
        )
        self.db.commit()

    # ------------------------------------------------------------ reads
    def topics(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id, title, summary, t0, t1 FROM topics WHERE meeting=? ORDER BY t1 DESC", (self.meeting,)
        ).fetchall()
        out = []
        for r in rows:
            rel = [
                e[0]
                for e in self.db.execute(
                    "SELECT CASE WHEN a=? THEN b ELSE a END FROM edges WHERE a=? OR b=?", (r["id"],) * 3
                )
            ]
            out.append({**dict(r), "related": rel})
        return out

    def digest(self) -> str:
        """Current meeting's topic graph + what's already been surfaced. Bounded."""
        lines = []
        budget = self.digest_chars
        for t in self.topics():
            rel = f" (→ {', '.join(f'T{x}' for x in t['related'])})" if t["related"] else ""
            full = f"T{t['id']} [{_ts(t['t0'])}–{_ts(t['t1'])}] {t['title']}{rel}: {t['summary']}"
            line = full if budget > len(full) else f"T{t['id']} {t['title']}"  # older topics shrink to titles
            budget -= len(line)
            if budget < 0:
                lines.append("… older topics omitted; use recall()")
                break
            lines.append(line)
        surfaced = [
            r["headline"]
            for r in self.db.execute(
                "SELECT headline FROM results WHERE meeting=? ORDER BY created DESC LIMIT 20", (self.meeting,)
            )
        ]
        out = "<topics>\n" + ("\n".join(lines) or "(none yet)") + "\n</topics>"
        if surfaced:
            out += "\n<already_surfaced>\n" + "\n".join(f"- {h}" for h in surfaced) + "\n</already_surfaced>"
        return out

    def recent(self, seconds: float) -> list[Utterance]:
        last = self.db.execute("SELECT max(t1) FROM utterances WHERE meeting=?", (self.meeting,)).fetchone()[0]
        if last is None:
            return []
        rows = self.db.execute(
            "SELECT channel, t0, t1, text FROM utterances WHERE meeting=? AND t1>=? ORDER BY t0",
            (self.meeting, last - seconds),
        )
        return [Utterance(r["channel"], r["t0"], r["t1"], r["text"]) for r in rows]

    def recall(self, query: str, scope: str = "meeting", limit: int = 6) -> str:
        """Search transcript (and, for past/all, previous meetings' summaries + topics)."""
        q = _fts(query)
        out: list[str] = []
        if scope in ("past", "all"):
            for r in self.db.execute(
                "SELECT m.id, m.started, m.title, m.summary FROM meetings_fts f JOIN meetings m ON m.id=f.rowid "
                "WHERE meetings_fts MATCH ? AND m.id IS NOT ? ORDER BY bm25(meetings_fts) LIMIT ?",
                (q, self.meeting, limit),
            ):
                out.append(f"## Meeting {r['id']} on {_date(r['started'])}: {r['title'] or ''}\n{r['summary']}")
            for r in self.db.execute(
                "SELECT t.id, t.title, t.summary, m.started FROM topics_fts f JOIN topics t ON t.id=f.rowid "
                "JOIN meetings m ON m.id=t.meeting WHERE topics_fts MATCH ? AND t.meeting IS NOT ? "
                "ORDER BY bm25(topics_fts) LIMIT ?",
                (q, self.meeting, limit),
            ):
                out.append(f"- past topic T{r['id']} ({_date(r['started'])}) {r['title']}: {r['summary']}")
        meeting_filter = "" if scope == "all" else ("AND u.meeting = ?" if scope == "meeting" else "AND u.meeting IS NOT ?")
        params: tuple = (q,) if scope == "all" else (q, self.meeting)
        hits = self.db.execute(
            f"SELECT u.id, u.meeting FROM utterances_fts f JOIN utterances u ON u.id=f.rowid "
            f"WHERE utterances_fts MATCH ? {meeting_filter} ORDER BY bm25(utterances_fts) LIMIT ?",
            params + (limit,),
        ).fetchall()
        for h in hits:
            ctx = self.db.execute(
                "SELECT channel, t0, text FROM utterances WHERE meeting=? AND id BETWEEN ? AND ? ORDER BY id",
                (h["meeting"], h["id"] - 2, h["id"] + 2),
            )
            tag = "" if h["meeting"] == self.meeting else f" (meeting {h['meeting']})"
            out.append(f"--- excerpt{tag}\n" + "\n".join(f"[{_ts(c['t0'])} {c['channel']}] {c['text']}" for c in ctx))
        return "\n\n".join(out) or "No matches."

    def topic(self, tid: int) -> str:
        t = self.db.execute("SELECT * FROM topics WHERE id=?", (tid,)).fetchone()
        if not t:
            return f"No topic T{tid}."
        rel = self.db.execute(
            "SELECT t.id, t.title FROM edges e JOIN topics t ON t.id = CASE WHEN e.a=? THEN e.b ELSE e.a END "
            "WHERE e.a=? OR e.b=?",
            (tid,) * 3,
        ).fetchall()
        lines = []
        for s in self.db.execute("SELECT DISTINCT t0, t1 FROM topic_spans WHERE topic=? ORDER BY t0", (tid,)):
            lines += [
                f"[{_ts(r['t0'])} {r['channel']}] {r['text']}"
                for r in self.db.execute(
                    "SELECT channel, t0, text FROM utterances WHERE meeting=? AND t0>=? AND t0<=? ORDER BY t0",
                    (t["meeting"], s["t0"], s["t1"]),
                )
            ]
        seen, uniq = set(), []
        for l in lines:
            if l not in seen:
                seen.add(l)
                uniq.append(l)
        related = ", ".join(f"T{r['id']} {r['title']}" for r in rel) or "none"
        return f"T{tid} {t['title']}\n{t['summary']}\nRelated: {related}\n\nTranscript:\n" + "\n".join(uniq[-60:])

    def cached(self, query: str, threshold: float = 0.6) -> dict[str, Any] | None:
        """Most similar recent result (token Jaccard), or None."""
        want = _tokens(query)
        if not want:
            return None
        best, best_score = None, threshold
        for r in self.db.execute(
            "SELECT * FROM results WHERE created > ? ORDER BY created DESC LIMIT 500",
            (time.time() - self.cache_days * 86400,),
        ):
            have = _tokens(r["query"])
            score = len(want & have) / len(want | have) if have else 0
            if score >= best_score:
                best, best_score = r, score
        if not best:
            return None
        return {
            "headline": best["headline"],
            "body_md": best["body_md"],
            "sources": json.loads(best["sources"] or "[]"),
            "cached_at": best["created"],
        }
