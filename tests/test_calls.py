import json

from proxy_core import calls


def record(id, at="2026-11-06T20:00:00-05:00", **kw):
    return {"id": id, "started_at": at, "kind": "phone", "contact": None, "summary": "s", "outcome": "needs_you",
            "actions": [{"text": "call back", "done": False}], **kw}


def test_runtime_joins_seeds_newest_first_and_mark_done_survives(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOSE_DATA_DIR", str(tmp_path))
    seeds = len(calls.list_calls())
    calls.write_call(record("new"))
    (tmp_path / "calls" / "half.json").write_text('{"id": "ha')     # a bad file must not hide the rest
    rows = calls.list_calls()
    assert len(rows) == seeds + 1 and rows[0]["id"] == "new"
    assert calls.mark_done("seed-0002")["actions"][0]["done"] is True
    assert calls.get_call("seed-0002")["actions"][0]["done"] is True
    assert len(calls.list_calls()) == seeds + 1
    assert calls.mark_done("nope") is None and calls.get_call("../../.env") is None


def test_brief_comes_from_records():
    text = calls.brief(calls.list_calls(), "Pranav")
    assert "2 need you" in text and "Lena" in text and "Rohan" in text
    assert calls.brief([record("a", contact={"name": "Sam Okafor"})], "Pranav").startswith("Hi Pranav. 1 call so far.")


def test_seeds_have_the_web_shape():
    keys = {"id", "started_at", "ended_at", "kind", "number", "contact", "persona", "pack", "summary", "outcome", "actions", "transcript"}
    for path in calls.SEED.glob("*.json"):
        r = json.loads(path.read_text(encoding="utf-8"))
        assert set(r) == keys and r["outcome"] in calls.OUTCOMES
