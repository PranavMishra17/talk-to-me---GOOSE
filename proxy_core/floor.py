"""Shared conversational floor (who may speak). Pure, stdlib only, no livekit.

State lives in room metadata as a JSON string. Every function returns a NEW
FloorState and takes `now` explicitly so tests need no clock.
Agents never interrupt: a request while someone holds the floor is queued.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Callable

AGENTS = ("goose", "maya")
LEASE_S = 20.0  # mirrors config limits.floor_lease_s


@dataclass(frozen=True)
class FloorState:
    holder: str | None = None  # "goose" | "maya" | "human:<id>" | None
    since: float = 0.0
    addressed_to: str | None = None
    queue: list[str] = field(default_factory=list)
    agent_streak: int = 0  # consecutive agent turns since a human last spoke
    last_agent: str | None = None  # who took the floor last; a second speech in one turn is not a new turn

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str | None) -> "FloorState":
        return cls(**json.loads(s)) if s else cls()  # empty metadata = free floor


def expire_lease(st: FloorState, now: float, lease_s: float = LEASE_S) -> FloorState:
    """Free the floor if the holder has sat on it past the lease (crashed agent)."""
    if st.holder and now - st.since >= lease_s:
        return replace(st, holder=None, since=now)
    return st


def request_floor(st: FloorState, agent: str, now: float, lease_s: float = LEASE_S) -> FloorState:
    st = expire_lease(st, now, lease_s)
    if st.holder == agent:
        return st  # idempotent; do not refresh the lease
    if st.holder is None:
        return replace(st, holder=agent, since=now)
    if agent in st.queue:
        return st
    return replace(st, queue=[*st.queue, agent])


def release_floor(st: FloorState, agent: str, now: float) -> FloorState:
    if st.holder != agent:  # not the holder: just drop any queued request
        return replace(st, queue=[q for q in st.queue if q != agent])
    nxt, rest = (st.queue[0], st.queue[1:]) if st.queue else (None, [])
    return replace(st, holder=nxt, since=now, queue=rest)


def human_preempt(st: FloorState, human_id: str, now: float) -> FloorState:
    """Human speech always wins. A holding agent is dropped, not re-queued."""
    return replace(st, holder=f"human:{human_id}", since=now, agent_streak=0)


def agent_spoke(st: FloorState, agent: str) -> FloorState:
    return replace(st, last_agent=agent, agent_streak=st.agent_streak + (st.last_agent != agent))


def must_yield(st: FloorState, cap: int = 2) -> bool:
    """After cap consecutive agent turns, agents stop and wait for a human."""
    return st.agent_streak >= cap


def try_claim(st: FloorState, agent: str, now: float, human_stopped: float | None = None,
              cap: int = 2, lease_s: float = LEASE_S) -> tuple[str, FloorState]:
    """"take", "wait" or "drop", with the state to write on take.
    human_stopped: this speech answers the human turn that ended then; None = an agent-driven line."""
    st = expire_lease(st, now, lease_s)
    rival = st.holder or st.last_agent
    if human_stopped is not None and rival not in (None, agent) and st.since >= human_stopped:
        return "drop", st  # the other agent already took this human turn
    if st.holder == agent:
        return "take", st
    if st.holder:
        return "wait", st
    if human_stopped is not None:
        st = replace(st, agent_streak=0, last_agent=None)
    elif must_yield(st, cap) and st.last_agent != agent:
        return "drop", st  # agents have had their turns; a human goes next
    return "take", agent_spoke(replace(st, holder=agent, since=now), agent)


class RoomMetadata:
    """Adapter over room metadata: inject get/set callables (LiveKit wiring or a test dict)."""

    def __init__(self, get: Callable[[], str | None], set: Callable[[str], None]):
        self._get, self._set = get, set

    def read(self) -> FloorState:
        return FloorState.from_json(self._get())

    def write(self, st: FloorState) -> None:
        self._set(st.to_json())


def choose_speaker(addressee: str | None, floor: FloorState, lead: str,
                   mid_tool_call: str | None = None, nobody_means_silence: bool = False) -> str | None:
    """Pick the one agent that replies; the other raises StopResponse.

    `addressee` is the decider's Choice: goose | maya | other_human | none (or None).
    `lead` is the agent whose owner was called. Returns None = nobody speaks.
    nobody_means_silence: the addressee is a confident "not an agent" and the room has more than one
    agent or human. Off for keyword answers and for one agent alone with one human.
    """
    if floor.holder and floor.holder.startswith("human:"):
        return None  # human speech pre-empts everything, even a tool-call hold
    if mid_tool_call:
        return mid_tool_call  # keeps the floor until its tool call finishes
    if addressee in AGENTS:
        return addressee
    return None if nobody_means_silence else lead
