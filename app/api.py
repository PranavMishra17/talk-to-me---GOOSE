"""Web API. Run: uv run uvicorn app.api:app --port 8000
GOOSE_MOCK=1 needs no keys and serves web/mock-state.json, so the frontend can be built with nothing else running.
The contract is the shape of web/mock-state.json. Live state comes from each agent's `goose.state` participant attribute.
"""
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from livekit import api
from pydantic import BaseModel

from proxy_core.config import ROOT, load_env

load_env()
MOCK = os.environ.get("GOOSE_MOCK") == "1"
MOCK_FILE = ROOT / "web" / "mock-state.json"
AGENT_KIND = 4   # ParticipantInfo.Kind.AGENT
app = FastAPI(title="Goose")


class NewRoom(BaseModel):
    agent: str | None = "ash"   # None makes an empty room, with no credits spent
    task: str = "Take a message and coordinate."


class Join(BaseModel):
    identity: str


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


@app.post("/api/rooms")
async def create_room(body: NewRoom):
    if MOCK:
        return {"room": "mock-room"}
    name = f"goose-{os.urandom(4).hex()}"
    lk = _lk()
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=120))
        if body.agent:
            await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                agent_name=body.agent, room=name, metadata=json.dumps({"task": body.task})))
    finally:
        await lk.aclose()
    return {"room": name}


@app.get("/api/rooms/{name}")
async def room_state(name: str):
    if MOCK:
        return {**json.loads(MOCK_FILE.read_text(encoding="utf-8")), "room": name}
    lk = _lk()
    try:
        rooms = (await lk.room.list_rooms(api.ListRoomsRequest(names=[name]))).rooms
        if not rooms:
            raise HTTPException(404, "no such room")
        people = (await lk.room.list_participants(api.ListParticipantsRequest(room=name))).participants
    finally:
        await lk.aclose()
    return live_state(name, rooms[0].metadata, people)


@app.post("/api/rooms/{name}/token")
async def token(name: str, body: Join):
    if MOCK:
        return {"url": "", "token": "mock"}
    jwt = api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]) \
        .with_identity(body.identity).with_name(body.identity) \
        .with_grants(api.VideoGrants(room_join=True, room=name)).to_jwt()
    return {"url": os.environ["LIVEKIT_URL"], "token": jwt}


@app.get("/")
async def home():
    return RedirectResponse("/web/index.html")


app.mount("/web", StaticFiles(directory=Path(ROOT) / "web"), name="web")
