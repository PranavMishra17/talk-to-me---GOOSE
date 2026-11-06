import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # no pytest pythonpath configured

from proxy_core.floor import (FloorState, RoomMetadata, choose_speaker, expire_lease,
                              human_preempt, release_floor, request_floor)


def test_grant_when_free_and_idempotent():
    s = request_floor(FloorState(), "ash", 1)
    assert (s.holder, s.since) == ("ash", 1)
    assert request_floor(s, "ash", 5) == s  # lease not refreshed


def test_queue_when_held_no_duplicates():
    s = request_floor(request_floor(FloorState(), "ash", 1), "maya", 2)
    assert s.holder == "ash" and s.queue == ["maya"]
    assert request_floor(s, "maya", 3).queue == ["maya"]


def test_release_pops_queue_head():
    s = request_floor(request_floor(FloorState(), "ash", 1), "maya", 2)
    s = release_floor(s, "ash", 3)
    assert (s.holder, s.since, s.queue) == ("maya", 3, [])
    assert release_floor(s, "maya", 4).holder is None


def test_release_by_non_holder_only_dequeues():
    s = request_floor(request_floor(FloorState(), "ash", 1), "maya", 2)
    s = release_floor(s, "maya", 3)
    assert s.holder == "ash" and s.queue == []


def test_human_preempt_drops_agent_keeps_queue():
    s = request_floor(request_floor(FloorState(), "ash", 1), "maya", 2)
    s = human_preempt(s, "pranav", 3)
    assert s.holder == "human:pranav" and s.queue == ["maya"]


def test_lease_expiry():
    s = request_floor(FloorState(), "ash", 0)
    assert expire_lease(s, 19.9).holder == "ash"
    assert expire_lease(s, 20).holder is None
    assert request_floor(s, "maya", 25).holder == "maya"  # request also reaps expired holder


def test_json_round_trip_and_empty():
    s = human_preempt(request_floor(FloorState(), "ash", 1), "rohan", 2)
    assert FloorState.from_json(s.to_json()) == s
    assert FloorState.from_json("") == FloorState()


def test_room_metadata_adapter():
    box = {"v": ""}
    m = RoomMetadata(lambda: box["v"], lambda v: box.update(v=v))
    assert m.read() == FloorState()
    m.write(request_floor(m.read(), "maya", 1))
    assert m.read().holder == "maya"


def test_named_addressee_wins():
    assert choose_speaker("maya", FloorState(), lead="ash") == "maya"


def test_non_agent_addressee_goes_to_lead():
    for a in ("both", "none", "other_human", None):
        assert choose_speaker(a, FloorState(), lead="ash") == "ash"


def test_mid_tool_call_keeps_floor():
    assert choose_speaker("maya", FloorState(), "maya", mid_tool_call="ash") == "ash"


def test_human_holding_floor_means_silence():
    f = human_preempt(FloorState(), "pranav", 1)
    assert choose_speaker("ash", f, "ash") is None
    assert choose_speaker("ash", f, "ash", mid_tool_call="ash") is None
