import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # no pytest pythonpath configured

from proxy_core.floor import (FloorState, RoomMetadata, choose_speaker, expire_lease,
                              human_preempt, release_floor, request_floor, try_claim)


def test_grant_when_free_and_idempotent():
    s = request_floor(FloorState(), "goose", 1)
    assert (s.holder, s.since) == ("goose", 1)
    assert request_floor(s, "goose", 5) == s  # lease not refreshed


def test_queue_when_held_no_duplicates():
    s = request_floor(request_floor(FloorState(), "goose", 1), "maya", 2)
    assert s.holder == "goose" and s.queue == ["maya"]
    assert request_floor(s, "maya", 3).queue == ["maya"]


def test_release_pops_queue_head():
    s = request_floor(request_floor(FloorState(), "goose", 1), "maya", 2)
    s = release_floor(s, "goose", 3)
    assert (s.holder, s.since, s.queue) == ("maya", 3, [])
    assert release_floor(s, "maya", 4).holder is None


def test_release_by_non_holder_only_dequeues():
    s = request_floor(request_floor(FloorState(), "goose", 1), "maya", 2)
    s = release_floor(s, "maya", 3)
    assert s.holder == "goose" and s.queue == []


def test_human_preempt_drops_agent_keeps_queue():
    s = request_floor(request_floor(FloorState(), "goose", 1), "maya", 2)
    s = human_preempt(s, "pranav", 3)
    assert s.holder == "human:pranav" and s.queue == ["maya"]


def test_lease_expiry():
    s = request_floor(FloorState(), "goose", 0)
    assert expire_lease(s, 19.9).holder == "goose"
    assert expire_lease(s, 20).holder is None
    assert request_floor(s, "maya", 25).holder == "maya"  # request also reaps expired holder


def test_json_round_trip_and_empty():
    s = human_preempt(request_floor(FloorState(), "goose", 1), "rohan", 2)
    assert FloorState.from_json(s.to_json()) == s
    assert FloorState.from_json("") == FloorState()


def test_room_metadata_adapter():
    box = {"v": ""}
    m = RoomMetadata(lambda: box["v"], lambda v: box.update(v=v))
    assert m.read() == FloorState()
    m.write(request_floor(m.read(), "maya", 1))
    assert m.read().holder == "maya"


def test_named_addressee_wins():
    assert choose_speaker("maya", FloorState(), lead="goose") == "maya"


def test_non_agent_addressee_goes_to_lead():
    for a in ("both", "none", "other_human", None):
        assert choose_speaker(a, FloorState(), lead="goose") == "goose"


def test_mid_tool_call_keeps_floor():
    assert choose_speaker("maya", FloorState(), "maya", mid_tool_call="goose") == "goose"


def test_human_holding_floor_means_silence():
    f = human_preempt(FloorState(), "pranav", 1)
    assert choose_speaker("goose", f, "goose") is None
    assert choose_speaker("goose", f, "goose", mid_tool_call="goose") is None


def test_claim_counts_turns_and_yields_to_human():
    s = FloorState()
    v, s = try_claim(s, "goose", 1); assert v == "take" and s.agent_streak == 1
    assert try_claim(s, "maya", 2)[0] == "wait"
    s = release_floor(s, "goose", 3)
    v, s = try_claim(s, "goose", 4); assert v == "take" and s.agent_streak == 1   # same agent, same turn
    s = release_floor(s, "goose", 5)
    v, s = try_claim(s, "maya", 6); assert v == "take" and s.agent_streak == 2
    s = release_floor(s, "maya", 7)
    assert try_claim(s, "goose", 8)[0] == "drop"                                  # cap: agents stop
    v, s = try_claim(s, "goose", 9, human_stopped=8.5); assert v == "take" and s.agent_streak == 1


def test_claim_loses_a_human_turn_the_other_agent_took():
    s = try_claim(FloorState(), "maya", 5, human_stopped=4)[1]
    assert try_claim(s, "goose", 6, human_stopped=4)[0] == "drop"                 # while she holds it
    assert try_claim(release_floor(s, "maya", 7), "goose", 8, human_stopped=4)[0] == "drop"   # and after she finished
    old = try_claim(FloorState(), "maya", 1)[1]
    assert try_claim(old, "goose", 6, human_stopped=4)[0] == "wait"               # she was cut off: wait for her release
