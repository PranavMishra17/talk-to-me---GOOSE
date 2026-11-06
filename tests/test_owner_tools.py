"""The real owner agent and its writes against a scripted model: no network, no credits."""
import asyncio
import json

import pytest
from livekit.agents import AgentSession
from test_gate_flow import Script

from app import providers, recap, worker
from app.agent import GooseAgent
from app.owner import OwnerAgent
from proxy_core import vault
from proxy_core.config import load_config
from proxy_core.personality import load_pack, owner_hello


def play2(turns, tier="private"):
    """Each turn is what the model does; one session throughout, as on stage. Returns each turn's tool outputs."""
    async def run():
        out = []
        async with AgentSession(llm=Script([s for steps in turns for s in steps])) as session:
            await session.start(OwnerAgent("goose", "pranav", "goose", tier=tier))
            for _ in turns:
                r = await session.run(user_input="Go on.")
                out.append([e.item.output for e in r.events if getattr(e, "type", "") == "function_call_output"])
        return out
    return asyncio.run(run())


def play(steps, line, tier="private"):
    return play2([steps], tier)[0]


@pytest.fixture(autouse=True)
def overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOSE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GOOSE_AGENT_TAG", raising=False)
    monkeypatch.setattr(OwnerAgent, "_hello", lambda self: asyncio.sleep(0))   # a text session has no TTS to say it with


def test_the_hello_has_no_calls_and_the_update_waits_for_an_answer():
    seen = []

    class Watch(Script):
        def chat(self, *, chat_ctx, **kw):
            seen.append(" ".join(i.text_content or "" for i in chat_ctx.items if getattr(i, "role", "") == "system"))
            return super().chat(chat_ctx=chat_ctx, **kw)

    async def run():
        async with AgentSession(llm=Watch(["Good. Couple of things.", "Rohan needs you.", "Sure."])) as session:
            await session.start(OwnerAgent("goose", "pranav", "goose"))
            for line in ("Good thanks.", "Yes please.", "Thanks."):
                await session.run(user_input=line)
    asyncio.run(run())
    assert "want the rundown" in seen[0] and "Rohan" in seen[0]
    assert "word for word" in seen[1] and "Rohan" in seen[1]
    assert "word for word" not in seen[2]
    hello = owner_hello(load_pack("goose"), "Goose", "Pranav")
    assert hello == "Hey Pranav, Goose here, how's it going?" and "call" not in hello


def test_a_call_gets_a_line_a_person_would_say():
    turns = [{"who": "goose", "text": "Who is it?"}, {"who": "caller", "text": "Hey, I wanted to get a PR done and I want it before the weekend."}]
    line = "Muhammad's after you on the PR, he wants it before the weekend."
    assert asyncio.run(recap.summarise(Script([line]), "Muhammad", "Pranav", turns)) == line
    assert asyncio.run(recap.summarise(Script(["He said I wanted to get a PR done and I want it."]), "Muhammad", "Pranav", turns)) is None


def test_join_as_reaches_the_contact_and_the_record():
    class Joiner:
        attributes = {"goose.caller": "Muhammad Rahman"}

    agent = GooseAgent("goose", caller=worker._number(Joiner, "pranav"), cfg=load_config())
    record = agent.call_record("x", [{"who": "caller", "text": "Hi", "ts": ""}])
    assert record["contact"]["name"] == "Muhammad Rahman" and not record["summary"].startswith("Someone")
    stranger = GooseAgent("goose", cfg=load_config()).call_record("y", [{"who": "caller", "text": "Yeah hello", "ts": ""}])
    assert stranger["contact"] is None and stranger["summary"] == "Someone called."
    named = GooseAgent("goose", cfg=load_config()).call_record("z", [{"who": "caller", "text": "Hi, it's Dave.", "ts": ""}])
    assert named["summary"] == "Dave called."


def test_keyterms_carry_the_names_stt_mangles():
    terms = providers._keyterms()
    assert "Bungalow" in terms and "Muhammad" in terms and "Connor" in terms and len(terms) <= 100


def test_stage_flow_adds_dinner_then_a_short_follow_up_moves_it():
    before = (vault.DATA / "calendar.json").read_text(encoding="utf-8")
    assert not [e for e in vault._load("calendar") if "2026-11-07T19" in e["start"]]
    out = play2([[("add_calendar_event", '{"title": "Dinner reservation", "start": "2026-11-07"}'), "Added."],
                 [("update_calendar_event", '{"event": "dinner", "where": "Bungalow"}'), "Moved."]])
    assert out[0][0].startswith("Added Dinner reservation") and "7" in out[0][0]
    assert out[1][0].startswith("Updated Dinner reservation") and out[1][0].endswith("Bungalow.")
    assert [e["where"] for e in vault._load("calendar") if e["title"] == "Dinner reservation"] == ["Bungalow"]
    assert (vault.DATA / "calendar.json").read_text(encoding="utf-8") == before


def test_a_follow_up_works_with_no_title_or_the_wrong_one():
    for event in ("", "the reservation at the restaurant"):
        out = play2([[("add_calendar_event", '{"title": "Lunch", "start": "2026-11-09T12:00:00"}'), "Added."],
                     [("update_calendar_event", json.dumps({"event": event, "where": "Bungalow"})), "Moved."]])
        assert out[1][0].startswith("Updated Lunch")


def test_two_matches_with_nothing_just_discussed_ask_which_one():
    assert vault.add_event("Dinner at home", "2026-11-09")
    out = play([("update_calendar_event", '{"event": "dinner", "where": "Bungalow"}'), "Which?"], "Move dinner.")
    assert out[0].startswith("Which one:") and "Dinner at home" in out[0]


def test_new_entry_is_private_and_a_task_lands():
    out = play([("add_calendar_event", '{"title": "Dentist", "start": "2026-11-09T09:00:00"}'), ("add_task", '{"text": "Buy wine"}'), "Done."], "Add both.")
    assert out[0].startswith("Added Dentist") and out[1] == "Added Buy wine."
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
