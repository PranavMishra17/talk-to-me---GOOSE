"""The real owner agent and its writes against a scripted model: no network, no credits."""
import asyncio

import pytest
from livekit.agents import AgentSession
from test_gate_flow import Script

from app.agent import GooseAgent
from app.owner import OwnerAgent
from proxy_core import vault
from proxy_core.config import load_config


def play(steps, line, tier="private"):
    async def run():
        async with AgentSession(llm=Script(steps)) as session:
            await session.start(OwnerAgent("goose", "pranav", "goose", tier=tier))
            r = await session.run(user_input=line)
            return [e.item.output for e in r.events if getattr(e, "type", "") == "function_call_output"]
    return asyncio.run(run())


@pytest.fixture(autouse=True)
def overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOSE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GOOSE_AGENT_TAG", raising=False)
    monkeypatch.setattr(OwnerAgent, "_brief", lambda self: asyncio.sleep(0))   # a text session has no TTS to say it with


def test_moving_dinner_shows_in_later_reads_and_leaves_data_alone():
    before = (vault.DATA / "calendar.json").read_text(encoding="utf-8")
    out = play([("update_calendar_event", '{"event": "dinner sam", "where": "Bungalow"}'), "Moved it."], "Move dinner to Bungalow.")
    assert out == ["Updated Dinner with Sam, Lena and Rohan."]
    assert [e["where"] for e in vault.get_calendar("friends") if "Dinner" in e.get("title", "")] == ["Bungalow"]
    assert (vault.DATA / "calendar.json").read_text(encoding="utf-8") == before


def test_two_matches_ask_which_one():
    out = play([("update_calendar_event", '{"event": "dinner", "where": "Bungalow"}'), "Which?"], "Move dinner.")
    assert out[0].startswith("Which one:") and "Dinner with Sam" in out[0]


def test_new_entry_is_private_and_a_task_lands():
    out = play([("add_calendar_event", '{"title": "Dentist", "start": "2026-11-09T09:00:00"}'), ("add_task", '{"text": "Buy wine"}'), "Done."], "Add both.")
    assert out[0] == "Added Dentist." and out[1] == "Added Buy wine."
    assert any(e.get("title") == "Dentist" for e in vault.get_calendar("private"))
    assert not any(e.get("title") == "Dentist" for e in vault.get_calendar("family"))
    assert vault._load("tasks")[-1]["text"] == "Buy wine"


def test_bad_input_changes_nothing():
    assert play([("add_calendar_event", '{"title": "X", "start": "saturday"}'), "Which day?"], "Add it.") == ["That needs a full date and time."]
    assert len(vault._load("calendar")) == len(vault._read(vault.DATA / "calendar.json"))
    assert vault.update_event("meetup nothing", "private", where="x") == []


def test_the_phone_owner_cannot_touch_what_the_cap_hides():
    out = play([("update_calendar_event", '{"event": "cardiology", "where": "x"}'), "No."], "Move it.", tier="family")
    assert out == ["No entry like that."]


def test_a_broken_overlay_never_stops_reads():
    vault._edits("calendar").parent.mkdir(parents=True)
    vault._edits("calendar").write_text("[{broken")
    assert len(vault._load("calendar")) == len(vault._read(vault.DATA / "calendar.json"))


def test_writes_stay_off_the_phone_agent():
    names = {t.id for t in GooseAgent("goose", caller="+15550100222", cfg=load_config()).tools}
    assert not names & {"add_calendar_event", "update_calendar_event", "add_task", "mark_done", "list_calls", "get_call"}
