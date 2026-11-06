"""Pranav's mock data, filtered by tier in code so the model never sees a record above the caller's tier. No livekit."""
import json
from datetime import datetime

from proxy_core.config import ROOT
from proxy_core.policy import TIERS

DATA = ROOT / "data"
OWNER = "pranav"              # whose data this is; another owner's assistant reads nothing from here


def _rank(tier) -> int:
    """A record with a missing or unknown tier counts as private, the opposite of an unknown caller."""
    return TIERS.index(tier) if tier in TIERS else len(TIERS) - 1


def _load(name: str, dir=DATA) -> list[dict]:
    path = dir / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def visible(records: list[dict], tier: str) -> list[dict]:
    """Records at or below the tier, without the tier label."""
    return [{k: v for k, v in r.items() if k != "tier"} for r in records if _rank(r.get("tier")) <= TIERS.index(tier)]


def _search(name: str, query: str, tier: str, dir=DATA, limit: int = 3) -> list[dict]:
    """Every query word must appear, so "dinner Saturday" narrows. An empty query gives the newest few."""
    rows = sorted(visible(_load(name, dir), tier), key=lambda r: r.get("date", ""), reverse=True)
    words = query.lower().split()
    return [r for r in rows if all(w in json.dumps(r).lower() for w in words)][:limit]


def search_email(query: str, tier: str, dir=DATA) -> list[dict]:
    return _search("gmail", query, tier, dir)


def search_slack(query: str, tier: str, dir=DATA) -> list[dict]:
    return _search("slack", query, tier, dir)


def search_notes(query: str, tier: str, dir=DATA) -> list[dict]:
    return _search("notes", query, tier, dir) + _search("tasks", query, tier, dir)


def _span(start: str, end: str) -> str:
    """Spoken time: a small model reads "Sat 7 Nov 7:00 PM to 9:30 PM" reliably and an ISO stamp badly."""
    a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    return f"{a:%a} {a.day} {a:%b} {a:%I:%M %p} to {b:%I:%M %p}".replace(" 0", " ")


def get_calendar(tier: str, dir=DATA) -> list[dict]:
    """The whole diary: a date filter a model gets wrong reads as free. Public sees busy blocks only. Above that
    a block keeps its details only if its own tier allows, so a friend sees "busy" over a private appointment."""
    rows = sorted(_load("calendar", dir), key=lambda e: e["start"])
    shown = {e["id"]: e for e in visible(rows, tier)} if tier != "public" else {}
    return [{"when": _span(e["start"], e["end"]), **({k: v for k, v in shown[e["id"]].items() if k not in ("id", "start", "end")}
             if e["id"] in shown else {"busy": True})} for e in rows]


def _digits(number: str) -> str:
    return "".join(c for c in number if c.isdigit())


def contacts(dir=DATA) -> list[dict]:
    """contacts.json merged with the gitignored contacts.local.json. A local entry replaces the same name."""
    return list({c["name"]: c for c in _load("contacts", dir) + _load("contacts.local", dir)}.values())


def find_contact(number: str, owner: str = OWNER, dir=DATA) -> dict | None:
    """Only a number from caller ID finds a contact. A name the caller says never reaches this."""
    digits = _digits(number or "")
    if owner != OWNER or not digits:
        return None
    return next((c for c in contacts(dir) if digits in map(_digits, c.get("numbers", []))), None)


def caller_context(contact: dict, past_calls: list[dict], dir=DATA) -> str:
    """The short brief a known caller's prompt carries. past_calls are this person's own, newest first."""
    tier, first = contact["tier"], contact["name"].split()[0]
    lines = [f"Caller: {contact['name']}, {contact['relationship']} of the owner. {contact.get('notes', '')}".strip()]
    lines += [f"Last call {c['started_at'][:10]}: {c['summary']}" for c in past_calls[:2]]
    mine = sorted((m for m in visible(_load("gmail", dir), tier) if first in m["from"]), key=lambda m: m["date"])
    lines += [f"Their last email: {m['subject']}: {m['body']}" for m in mine[-1:]]
    said = sorted((m for m in visible(_load("slack", dir), tier) if first in m["from"]), key=lambda m: m["date"])
    lines += [f"Their last Slack: {m['text']}" for m in said[-1:]]
    return "\n".join(lines)
