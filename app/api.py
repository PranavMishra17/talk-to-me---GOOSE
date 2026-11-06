"""Web API. Run: uv run uvicorn app.api:app --port 8000
GOOSE_MOCK=1 needs no keys and serves web/mock-*.json, so the frontend can be built with nothing else running.
Live room state comes from each agent's `goose.state` participant attribute; call history from proxy_core.calls.
"""
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from livekit import api

from proxy_core.config import ROOT, load_config, load_env
from proxy_core.personality import list_packs

load_env()
MOCK = os.environ.get("GOOSE_MOCK") == "1"
MOCK_FILE = ROOT / "web" / "mock-state.json"
MOCK_CALLS = ROOT / "web" / "mock-calls.json"
AGENT_KIND = 4   # ParticipantInfo.Kind.AGENT
app = FastAPI(title="Goose")
LAST: dict[str, dict] = {}   # the panel keeps a finished call's summary after LiveKit closes the room


try:
    from proxy_core.calls import get_call, list_calls
except ImportError:   # until proxy_core/calls.py lands
    def list_calls() -> list[dict]:
        return sorted(json.loads(MOCK_CALLS.read_text(encoding="utf-8")), key=lambda c: c["started_at"], reverse=True)

    def get_call(id: str) -> dict | None:
        return next((c for c in list_calls() if c["id"] == id), None)


def _lk():
    return api.LiveKitAPI(os.environ["LIVEKIT_URL"], os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])


def live_state(name: str, floor_json: str, people: list) -> dict:
    """Pure: raw LiveKit rows -> the contract. Agents that have not published yet show empty panels."""
    agents, participants = {}, []
    for p in people:
        attrs = dict(p.attributes)
        is_agent = p.kind == AGENT_KIND
        participants.append({"identity": p.identity, "kind": "agent" if is_agent else "human",
                             "agent_state": attrs.get("lk.agent.state")})
        if is_agent and attrs.get("goose.state"):
            s = json.loads(attrs["goose.state"])
            agents[s["persona"]] = s
    floor = json.loads(floor_json) if floor_json else {}
    return {"room": name, "participants": participants, "agents": agents,
            "floor": {"holder": floor.get("holder"), "addressed_to": floor.get("addressed_to")}}


def _first_persona() -> tuple[str, str]:
    """(agent name, owner) of the first persona in config.yaml, the one Pranav talks to."""
    persona, p = next(iter(load_config()["personas"].items()))
    return persona, p["owner"]


@app.get("/api/me")
async def me():
    return {"owner": _first_persona()[1].title(), "dial_in": os.environ.get("GOOSE_DIAL_IN") or ("+1 555 0100" if MOCK else ""),
            "personalities": list_packs()}


@app.get("/api/calls")
async def calls():
    return list_calls()


@app.get("/api/calls/{id}")
async def call(id: str):
    found = get_call(id)
    if not found:
        raise HTTPException(404, "no such call")
    return found


@app.post("/api/talk")
async def talk():
    """Pranav's private line: a room with only him and his agent. Phone rooms are `call-*`, these are `talk-*`."""
    if MOCK:
        return {"room": "mock-room", "url": "", "token": "mock"}
    agent, owner = _first_persona()
    name = f"talk-{os.urandom(4).hex()}"
    lk = _lk()
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=120))
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=agent, room=name, metadata=json.dumps({"mode": "owner"})))
    finally:
        await lk.aclose()
    jwt = api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]) \
        .with_identity(owner).with_name(owner.title()) \
        .with_grants(api.VideoGrants(room_join=True, room=name)).to_jwt()
    return {"room": name, "url": os.environ["LIVEKIT_URL"], "token": jwt}


@app.get("/api/rooms")
async def rooms():
    """Live rooms, newest first. Phone calls create their own rooms, so this is how the page finds one."""
    dial_in = os.environ.get("GOOSE_DIAL_IN", "")
    if MOCK:
        return {"dial_in": dial_in or "+1 555 0100", "rooms": [{"room": "call-mock", "people": 2}]}
    lk = _lk()
    try:
        found = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
    finally:
        await lk.aclose()
    found = sorted(found, key=lambda r: r.creation_time, reverse=True)
    return {"dial_in": dial_in, "rooms": [{"room": r.name, "people": r.num_participants} for r in found]}


@app.get("/api/rooms/{name}")
async def room_state(name: str):
    if MOCK:
        return {**json.loads(MOCK_FILE.read_text(encoding="utf-8")), "room": name}
    lk = _lk()
    try:
        rooms = (await lk.room.list_rooms(api.ListRoomsRequest(names=[name]))).rooms
        if not rooms:
            if name in LAST:
                return LAST[name]
            raise HTTPException(404, "no such room")
        people = (await lk.room.list_participants(api.ListParticipantsRequest(room=name))).participants
    finally:
        await lk.aclose()
    state = live_state(name, rooms[0].metadata, people)
    state["agents"] = {**LAST.get(name, {}).get("agents", {}), **state["agents"]}   # an agent that left keeps its panel
    LAST[name] = state
    return state


@app.get("/")
async def home():
    return RedirectResponse("/web/index.html")


app.mount("/web", StaticFiles(directory=Path(ROOT) / "web"), name="web")
