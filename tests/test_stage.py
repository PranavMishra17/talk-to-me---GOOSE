"""The reset between test and demo, and Skyler's calls in the history. No network."""
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import stage as stage_cli
from app.agent import GooseAgent
from app.api import STATIC, _first_persona, app
from app.worker import _save
from proxy_core import calls, vault
from proxy_core.config import ROOT, agent_name, load_config


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
    now = datetime.now().astimezone()      # hours back, not "today": this must pass just after midnight too
    assert all(timedelta(0) <= now - datetime.fromisoformat(c["started_at"]) < timedelta(days=1) for c in rows)
    assert datetime.fromisoformat(rows[0]["transcript"][0]["ts"]) >= datetime.fromisoformat(rows[0]["started_at"])
    assert [c["id"] for c in TestClient(app).get("/api/calls").json()] == [c["id"] for c in rows]
    assert "Rohan" in calls.brief(rows, "Pranav") and any(c["outcome"] == "needs_you" for c in rows)
    calls.mark_done("seed-0004")
    stage("reset", tmp_path)                # a reset undoes what the last run did
    assert calls.get_call("seed-0004")["actions"][0]["done"] is False
    stage("clear", tmp_path)
    assert calls.list_calls() == [] and TestClient(app).get("/api/calls").json() == []
    assert calls.brief(calls.list_calls("pranav"), "Pranav") == "No calls yet."
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





def test_up_restarts_a_crash_and_stops_everything(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(stage_cli, "OUT", tmp_path)
    flag, alive = tmp_path / "crashed", tmp_path / "alive"
    child = (f"import pathlib, sys, time\nf = pathlib.Path({str(flag)!r})\nprint('up now', flush=True)\n"
             f"if not f.exists():\n    f.touch()\n    sys.exit(3)\n"
             f"while True:\n    pathlib.Path({str(alive)!r}).write_text(str(time.time()))\n    time.sleep(0.1)\n")
    stop = threading.Event()
    item = {"name": "fake", "cmd": [sys.executable, "-c", child], "env": dict(os.environ), "ready": "up now"}
    t = threading.Thread(target=stage_cli.serve, args=([item], stop))
    t.start()
    end = time.time() + 20
    while not alive.exists() and time.time() < end:
        time.sleep(0.1)
    assert alive.exists()                       # the second start, after the crash
    stop.set()
    t.join(20)
    assert not t.is_alive()
    beat = alive.read_text()
    time.sleep(0.5)
    assert alive.read_text() == beat            # the child is really gone
    out = capsys.readouterr().out
    assert out.count("READY fake") == 2 and "fake exited with 3" in out and "stopped" in out
