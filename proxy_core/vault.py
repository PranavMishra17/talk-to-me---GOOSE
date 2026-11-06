"""Each owner's mock data, filtered by tier in code so the model never sees a record above the caller's tier. No livekit."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from proxy_core.config import ROOT
from proxy_core.policy import TIERS

DATA = ROOT / "data"
OWNER = "pranav"              # data/ itself is his; any other owner reads data/<owner>/ and nothing else
PREFETCH_WORDS = 150         # the bundle rides on every turn's prompt, so it stays short
PHONE_MAX = "family"          # caller ID can be spoofed, so no phone call reaches private data, not even the owner's number


def owner_dir(owner: str) -> Path | None:
    """The one folder this owner's assistant reads. None = this owner has no data."""
    d = DATA if owner == OWNER else DATA / owner
    return d if d.is_dir() else None


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
    text = [(r, json.dumps(r).lower()) for r in rows]
    hits = [r for r, t in text if all(w in t for w in words)]
    return (hits or [r for r, t in text if any(w in t for w in words if len(w) > 3)])[:limit]   # a model's query rarely matches word for word


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


def get_profile(tier: str, dir=DATA) -> dict:
    """The owner himself: role, work, preferences, routines, as far as the tier allows."""
    return {r["key"]: r["value"] for r in visible(_load("profile", dir), tier)}


def _digits(number: str) -> str:
    return "".join(c for c in number if c.isdigit())


def phone_tier(tier: str) -> str:
    return TIERS[min(TIERS.index(tier), TIERS.index(PHONE_MAX))]


def _local(dir) -> list[dict]:
    """Real numbers, pasted in by hand, so a bad file or entry is skipped: it must never take a call down."""
    try:
        rows = json.loads(Path(os.environ.get("GOOSE_CONTACTS_LOCAL") or dir / "contacts.local.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = rows.get("contacts", []) if isinstance(rows, dict) else rows
    return [{"relationship": "contact", "notes": "", **c, "tier": c.get("tier") if c.get("tier") in TIERS else "public"}
            for c in rows if isinstance(c, dict) and c.get("name") and isinstance(c.get("numbers"), list)]


def contacts(dir=DATA) -> list[dict]:
    """contacts.json merged with the gitignored local file. A local entry replaces the same name."""
    local = [] if DATA in dir.parents else _local(dir)      # the real numbers are Pranav's; an owner folder never merges them
    return list({c["name"]: c for c in _load("contacts", dir) + local}.values())


def number_for(name: str | None, dir=DATA) -> str | None:
    """The web Join as names a contact. The number stays on the server: an attribute would reach every browser in the room."""
    c = next((c for c in contacts(dir) if c["name"] == name), None)
    return c["numbers"][0] if c and c.get("numbers") else None


def find_contact(number: str, owner: str = OWNER, dir=None) -> dict | None:
    """Only a number from caller ID finds a contact. A name the caller says never reaches this."""
    digits, home = _digits(number or ""), owner_dir(owner)
    if home is None or not digits:
        return None
    dir = dir or home
    return next((c for c in contacts(dir) if digits in map(_digits, c.get("numbers", []))), None)


def _relevant(rows: list[dict], first: str, topics: list[str]) -> list[dict]:
    """With or about this person, on what they share with the owner: a colleague gets work, a friend gets the rest."""
    return [r for r in rows if first in json.dumps(r) and set(r.get("topics", ["personal"])) & set(topics)]


def prefetch(owner: str, contact: dict, past_calls: list[dict], today: date | None = None, dir=None, max_words: int = PREFETCH_WORDS) -> str:
    """What the agent knows before it says hello, so its first replies need no tool. Tier-filtered like every read."""
    dir = dir or owner_dir(owner)
    if dir is None:
        return ""
    tier, first = phone_tier(contact["tier"]), contact["name"].split()[0]
    topics = contact.get("topics", ["personal"])
    newest = lambda name: sorted(_relevant(visible(_load(name, dir), tier), first, topics), key=lambda r: r["date"], reverse=True)
    today = today or datetime.now().date()
    week = [e for e in _load("calendar", dir) if today <= date.fromisoformat(e["start"][:10]) <= today + timedelta(days=7)]
    shown = {e["id"] for e in visible(week, tier) if set(e.get("topics", ["personal"])) & set(topics)} if tier != "public" else set()
    lines = [f"Caller: {contact['name']}, the owner's {contact['relationship']}. {contact.get('notes', '')}".strip()]
    lines += [f"Open task: {t['text']}, due {t['due']}." for t in _relevant(visible(_load("tasks", dir), tier), first, topics) if not t["done"]][:2]
    lines += [f"Last call {c['started_at'][:10]}: {c['summary']}" for c in past_calls[:2]]
    lines += [f"Email from {m['from']}: {m['subject']}. {m['body']}" for m in newest("gmail")[:2]]
    lines += [f"Slack {m['channel']}, {m['from']}: {m['text']}" for m in newest("slack")[:2]]
    lines += ["This week: " + "; ".join(f"{_span(e['start'], e['end'])} {e['title'] if e['id'] in shown else 'busy'}"
                                        for e in sorted(week, key=lambda e: e["start"])[:4])] if week else []
    kept, words = [], 0
    for line in lines:                  # most useful first; what does not fit stays behind the tools
        words += len(line.split())
        if words > max_words:
            break
        kept.append(line)
    return "\n".join(kept)
