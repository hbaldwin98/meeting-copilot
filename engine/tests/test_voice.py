from copilot.voice import should_speak, spoken_text
from copilot.voice.text import normalize


def test_normalize():
    assert normalize("100-300ms at P99") == "100 to 300 milliseconds at P 99"
    assert normalize("spent $1.2M, about 40%") == "spent 1.2 million dollars, about 40 percent"
    assert normalize("CockroachDB vs. Spanner") == "Cockroach DB versus Spanner"


def test_spoken_text_is_headline_plus_first_sentence():
    card = {"headline": "Figma sharded Postgres", "body_md": "- **Approach:** app-level sharding. More detail.\n- Two\n\nSources:\n- https://x.y"}
    assert spoken_text(card) == "Figma sharded Postgres. Approach: app-level sharding."


def test_policy():
    ask = {"type": "card", "origin": "ask", "kind": "instant"}
    auto = {"type": "card", "origin": "auto", "kind": "instant", "task_id": None}
    task = {"type": "card", "origin": "auto", "kind": "lookup", "task_id": "t1"}
    cached = {"type": "card", "origin": "auto", "kind": "cached"}
    assert should_speak(ask, "asks") and not should_speak(auto, "asks") and not should_speak(task, "asks")
    assert should_speak(task, "asks+tasks") and not should_speak(auto, "asks+tasks")
    assert should_speak(auto, "all") and not should_speak(cached, "all")
    assert not should_speak({"type": "task.done"}, "all")
