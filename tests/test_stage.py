"""The reset between test and demo, and Skyler's calls in the history. No network."""
import os
import subprocess
import sys
from datetime import datetime

from fastapi.testclient import TestClient

from app.agent import GooseAgent
from app.api import app
from app.worker import _save
from proxy_core import calls, vault
from proxy_core.config import ROOT


def stage(cmd, tmp_path):
    env = {**os.environ, "GOOSE_DATA_DIR": str(tmp_path), "PYTHONUTF8": "1"}
    out = subprocess.run([sys.executable, "scripts/stage.py", cmd], cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_reset_clear_and_the_web_see_one_world(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOSE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GOOSE_AGENT_TAG", raising=False)
    calls.write_call({"id": "leftover", "started_at": "2030-01-01T00:00:00-05:00", "kind": "phone", "contact": {"name": "Muhammad Rahman"},
                      "summary": "test", "outcome": "info", "actions": [], "transcript": []})
    overlay = tmp_path / "data" / "tasks.json"
    overlay.parent.mkdir()
    overlay.write_text("[]")
    print(stage("reset", tmp_path))
    rows = calls.list_calls()
    assert not overlay.exists() and len(rows) == 4 and "Muhammad Rahman" not in str(rows)
    assert all(datetime.fromisoformat(c["started_at"]).date() == datetime.now().date() for c in rows)
    assert datetime.fromisoformat(rows[0]["transcript"][0]["ts"]) >= datetime.fromisoformat(rows[0]["started_at"])
    assert [c["id"] for c in TestClient(app).get("/api/calls").json()] == [c["id"] for c in rows]
    assert "Rohan" in calls.brief(rows, "Pranav") and any(c["outcome"] == "needs_you" for c in rows)
    calls.mark_done("seed-0004")
    stage("reset", tmp_path)                # a reset undoes what the last run did
    assert calls.get_call("seed-0004")["actions"][0]["done"] is False
    stage("clear", tmp_path)
    assert calls.list_calls() == [] and TestClient(app).get("/api/calls").json() == []
    assert calls.brief(calls.list_calls("pranav"), "Pranav") == "Hi Pranav, no calls yet."
    stage("reset", tmp_path)
    assert len(calls.list_calls()) == 4


class Fake:
    def __init__(self):
        self.handlers = {}

    def on(self, event, fn):
        self.handlers[event] = fn

    def is_fake_job(self):
        return False

    def add_shutdown_callback(self, fn):
        pass

    job = type("Job", (), {"id": "AJ_jesse"})
    history = type("History", (), {"items": []})


def test_skyler_calls_save_with_a_hangup_reason_and_stay_out_of_pranavs_briefing(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOSE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GOOSE_AGENT_TAG", raising=False)
    agent, fake = GooseAgent("jesse", caller="+15559999999"), Fake()
    agent.log.append("end: hostile caller")
    _save(fake, fake, agent)
    fake.handlers["close"]()
    row = calls.get_call("AJ_jesse")
    assert row["owner"] == "skyler" and row["persona"] == "jesse" and row["hangup"] == "hostile caller"
    assert "AJ_jesse" in str(TestClient(app).get("/api/calls").json())
    assert "AJ_jesse" not in str(calls.list_calls("pranav")) and "AJ_jesse" in str(calls.list_calls("skyler"))
    assert vault.owner_dir("skyler")
