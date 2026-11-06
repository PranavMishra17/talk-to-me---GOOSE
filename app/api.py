"""Web API. Run: uv run uvicorn app.api:app --port 8000
GOOSE_MOCK=1 needs no keys and serves web/mock-state.json plus the seed calls, so the frontend can be built with nothing else running.
Live room state comes from each agent's `goose.state` participant attribute; call history from proxy_core.calls.
"""
import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from livekit import api
from pydantic import BaseModel

from proxy_core.calls import get_call, list_calls
from proxy_core.config import ROOT, agent_name, load_config, load_env
from proxy_core.personality import cards, list_packs
from proxy_core.policy import TIERS
from proxy_core.vault import OWNER, _load, _rank, contacts as all_contacts, owner_dir

load_env()
MOCK = os.environ.get("GOOSE_MOCK") == "1"
MOCK_FILE = ROOT / "web" / "mock-state.json"
STATIC = ROOT / "web" / "static"
AGENT_KIND = 4   # ParticipantInfo.Kind.AGENT
app = FastAPI(title="Goose")
LAST: dict[str, dict] = {}   # the panel keeps a finished call's summary after LiveKit closes the room


class Talk(BaseModel):
    pack: str | None = None   # None keeps the persona's own pack


class Join(BaseModel):
    name: str | None = None   # a contact's name; None joins as an unknown caller
    owner: str = OWNER        # whose contact book the name is in


class NewRoom(BaseModel):
    owner: str
    pack: str | None = None
    allowed: list[str] = []   # assistant ids summon_agent may bring in


def _phone() -> str:
    """Only ever from the environment: the repo is public."""
    return os.environ.get("GOOSE_PHONE_NUMBER") or os.environ.get("GOOSE_DIAL_IN") or ("+1 555 0100" if MOCK else "")


def _book(owner: str) -> list[dict]:
    """One owner's contacts. Checked against config: this comes from a URL and becomes a folder name."""
    home = owner_dir(owner) if owner in [p["owner"] for p in load_config()["personas"].values()] else None
    return all_contacts(home) if home else []


def _pack(name: str | None, default: str) -> str:
    pack = name or default
    if pack not in list_packs():
        raise HTTPException(400, f"unknown personality {pack!r}")
    return pack


def _lk():
    return api.LiveKitAPI(os.environ["LIVEKIT_URL"], os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])


def live_state(name: str, floor_json: str, people: list) -> dict:
    """Pure: raw LiveKit rows -> the contract. Agents that have not published yet show empty panels."""
    agents, participants = {}, []
    for p in people:
        attrs = dict(p.attributes)
        is_agent = p.kind == AGENT_KIND
        s = json.loads(attrs["goose.state"]) if is_agent and attrs.get("goose.state") else None
        participants.append({"identity": p.identity, "kind": "agent" if is_agent else "human", "persona": s and s["persona"],
                             "agent_state": attrs.get("lk.agent.state")})
        if s:
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
    return {"owner": _first_persona()[1].title(), "dial_in": _phone(),
            "personalities": list_packs()}


@app.get("/config")
async def config():
    owners = [{"id": p["owner"], "name": p["owner"].title(), "pack": p["pack"]} for p in load_config()["personas"].values()]
    return {"phone": _phone(), "owners": owners}


@app.get("/packs")
async def packs():
    return cards()


@app.get("/health")
async def health(room: str | None = None):
    """LiveKit lists no workers. An agent in a room is proof, and for a named room so is a job a worker took:
    a dispatch nobody can serve has no jobs. With no room and no agent on a call, nothing can be said."""
    if MOCK:
        return {"livekit": "ok", "agent": "offline" if room == "mock-offline" else "online"}
    lk = None
    try:
        lk = _lk()
        found = (await lk.room.list_rooms(api.ListRoomsRequest(names=[room] if room else []))).rooms
        online = False
        for r in found:
            people = (await lk.room.list_participants(api.ListParticipantsRequest(room=r.name))).participants
            online = online or any(p.kind == AGENT_KIND for p in people)
        if room and found and not online:
            jobs = [j for d in await lk.agent_dispatch.list_dispatch(room) for j in d.state.jobs]
            online = any(j.state.status in (0, 1) for j in jobs)   # JS_PENDING, JS_RUNNING
        return {"livekit": "ok", "agent": "online" if online else "offline" if room else "unknown"}
    except Exception:
        return {"livekit": "down", "agent": "unknown"}
    finally:
        if lk:
            await lk.aclose()


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


@app.get("/api/callers")
async def callers(owner: str = OWNER):
    """Join as: names only, the owner first."""
    found = [{"name": c["name"], "owner": c.get("relationship") == "owner"} for c in _book(owner)]
    return sorted(found, key=lambda c: not c["owner"])


@app.get("/api/data")
async def data():
    """Everything Goose can draw on, with the tier code enforces: a record with no valid tier shows as private."""
    return {name: [{**r, "tier": TIERS[_rank(r.get("tier"))]} for r in _load(name)]
            for name in ("gmail", "slack", "calendar", "notes", "tasks")}


@app.post("/api/talk")
async def talk(body: Talk = Talk()):
    """Pranav's private line: a room with only him and his agent. Phone rooms are `call-*`, these are `talk-*`."""
    agent, owner, default_pack = _first_persona()
    pack = _pack(body.pack, default_pack)
    if MOCK:
        return {"room": "mock-room", "url": "", "token": "mock"}
    name = f"talk-{os.urandom(4).hex()}"
    lk = _lk()
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=120))
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=agent_name(agent), room=name, metadata=json.dumps({"mode": "owner", "pack": pack})))
    finally:
        await lk.aclose()
    jwt = api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]) \
        .with_identity(owner).with_name(owner.title()) \
        .with_grants(api.VideoGrants(room_join=True, room=name)).to_jwt()
    return {"room": name, "url": os.environ["LIVEKIT_URL"], "token": jwt}


@app.get("/api/rooms")
async def rooms():
    """Live rooms, newest first. Phone calls create their own rooms, so this is how the page finds one."""
    dial_in = _phone()
    if MOCK:
        return {"dial_in": dial_in, "rooms": [{"room": "call-mock", "people": 2}]}
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
        if name == "mock-skyler":
            jesse = {"persona": "jesse", "owner": "skyler", "caller_tier": "public", "focus": "identify", "agenda": [],
                     "slots": {}, "pending_confirm": None, "log": [], "summary": ""}
            return {"room": name, "agents": {"jesse": jesse}, "floor": {"holder": None, "addressed_to": None},
                    "participants": [{"identity": "agent-seed-0003", "kind": "agent", "persona": "jesse", "agent_state": "listening"}]}
        if name == "mock-offline":
            return {"room": name, "participants": [], "agents": {}, "floor": {"holder": None, "addressed_to": None}}
        return {**json.loads(MOCK_FILE.read_text(encoding="utf-8")), "room": name}
    lk = _lk()
    try:
        rooms = (await lk.room.list_rooms(api.ListRoomsRequest(names=[name]))).rooms
        try:
            people = (await lk.room.list_participants(api.ListParticipantsRequest(room=name))).participants if rooms else None
        except api.TwirpError:   # LiveKit lists a room for a moment after it closes
            people = None
        if people is None:
            if name in LAST:
                return {**LAST[name], "ended": True}
            raise HTTPException(404, "no such room")
    finally:
        await lk.aclose()
    state = live_state(name, rooms[0].metadata, people)
    state["agents"] = {**LAST.get(name, {}).get("agents", {}), **state["agents"]}   # an agent that left keeps its panel
    LAST[name] = state
    return state


@app.post("/rooms")
async def open_room(body: NewRoom):
    """The floor owns room metadata (a whole-value write, and it rejects other keys), so `allowed` travels in the
    dispatch and summon_agent reads it from there."""
    personas = load_config()["personas"]
    persona = next((n for n, p in personas.items() if p["owner"] == body.owner), None)
    if persona is None:
        raise HTTPException(400, f"no assistant for {body.owner!r}")
    pack = _pack(body.pack, personas[persona]["pack"])
    if MOCK:
        return {"url": f"/rooms/{'mock-skyler' if body.owner == 'skyler' else 'mock-room'}?owner={body.owner}"}
    name = f"goose-{os.urandom(3).hex()}"
    lk = _lk()
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=300))
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=agent_name(persona), room=name,
            metadata=json.dumps({"persona": body.owner, "pack": pack, "allowed": body.allowed})))
    finally:
        await lk.aclose()
    return {"url": f"/rooms/{name}?owner={body.owner}"}


@app.get("/rooms/{name}")
async def room_page(name: str):
    return FileResponse(STATIC / "room.html")


@app.post("/rooms/{name}/token")
async def room_token(name: str, body: Join = Join()):
    """Only rooms opened from the page: no login here, so a `call-*` or `talk-*` room must not be joinable by name."""
    if MOCK:
        return {"url": "", "token": "mock"}
    if not name.startswith("goose-"):
        raise HTTPException(403, "this room cannot be joined from the browser")
    if body.name and body.name not in [c["name"] for c in _book(body.owner)]:
        raise HTTPException(400, "not in the contact book")
    # The token reaches the browser, so it names the contact and the worker looks the number up. Participants cannot
    # change their own attributes, so only this server can make someone a contact.
    who = f"{(body.name or 'guest').split()[0].lower()}-{os.urandom(2).hex()}"
    jwt = api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]) \
        .with_identity(who).with_name(body.name or "Guest").with_grants(api.VideoGrants(room_join=True, room=name)) \
        .with_attributes({"goose.caller": body.name} if body.name else {}).to_jwt()
    return {"url": os.environ["LIVEKIT_URL"], "token": jwt}


@app.get("/demo")
async def demo():
    return FileResponse(STATIC / "demo.html")


@app.get("/app")
async def pranav_app():
    return FileResponse(STATIC / "app.html")


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")   # last: / is index.html
