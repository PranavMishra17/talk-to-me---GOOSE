"""Web API. Run: uv run uvicorn app.api:app --port 8000
GOOSE_MOCK=1 needs no keys and serves web/mock-state.json plus the seed calls, so the frontend can be built with nothing else running.
Live room state comes from each agent's `goose.state` participant attribute; call history from proxy_core.calls.
"""
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from livekit import api
from pydantic import BaseModel

from proxy_core.calls import get_call, list_calls
from proxy_core.config import ROOT, load_config, load_env
from proxy_core.personality import list_packs
from proxy_core.policy import TIERS
from proxy_core.vault import _load, _rank, contacts as all_contacts

load_env()
MOCK = os.environ.get("GOOSE_MOCK") == "1"
MOCK_FILE = ROOT / "web" / "mock-state.json"
AGENT_KIND = 4   # ParticipantInfo.Kind.AGENT
app = FastAPI(title="Goose")
LAST: dict[str, dict] = {}   # the panel keeps a finished call's summary after LiveKit closes the room


class Talk(BaseModel):
    pack: str | None = None   # None keeps the persona's own pack


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


def _first_persona() -> tuple[str, str, str]:
    """(agent name, owner, pack) of the first persona in config.yaml, the one Pranav talks to."""
    persona, p = next(iter(load_config()["personas"].items()))
    return persona, p["owner"], p["pack"]


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


@app.get("/api/contacts")
async def contacts():
    """Local contacts hold real numbers, so the masking happens here and the full number never reaches the browser."""
    return [{"name": c["name"], "relationship": c.get("relationship"), "tier": c.get("tier"),
             "numbers": ["\u2022\u2022\u2022\u2022 " + "".join(d for d in n if d.isdigit())[-4:] for n in c.get("numbers", [])]}
            for c in all_contacts()]


@app.get("/api/data")
async def data():
    """Everything Goose can draw on, with the tier code enforces: a record with no valid tier shows as private."""
    return {name: [{**r, "tier": TIERS[_rank(r.get("tier"))]} for r in _load(name)]
            for name in ("gmail", "slack", "calendar", "notes", "tasks")}


@app.post("/api/talk")
async def talk(body: Talk = Talk()):
    """Pranav's private line: a room with only him and his agent. Phone rooms are `call-*`, these are `talk-*`."""
    agent, owner, default_pack = _first_persona()
    pack = body.pack or default_pack
    if pack not in list_packs():
        raise HTTPException(400, f"unknown personality {pack!r}")
    if MOCK:
        return {"room": "mock-room", "url": "", "token": "mock"}
    name = f"talk-{os.urandom(4).hex()}"
    lk = _lk()
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=120))
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=agent, room=name, metadata=json.dumps({"mode": "owner", "pack": pack})))
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
