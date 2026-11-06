"""Pranav's mock data, filtered by tier in code so the model never sees a record above the caller's tier. No livekit."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from proxy_core.config import ROOT
from proxy_core.policy import TIERS
from proxy_core.speech import spoken_day, spoken_span

DATA = ROOT / "data"
OWNER = "pranav"              # whose data this is; another owner's assistant reads nothing from here
PREFETCH_WORDS = 150         # the bundle rides on every turn's prompt, so it stays short
PHONE_MAX = "family"          # caller ID can be spoofed, so no phone call reaches private data, not even the owner's number


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


def _span(start: str, end: str, today: date | None = None) -> str:
    """Spoken time: the model repeats "tomorrow, 7 to half past 9 in the evening" as given, and reads an ISO stamp
    or "11/7 7:00 PM" out loud as digits."""
    return spoken_span(datetime.fromisoformat(start), datetime.fromisoformat(end), today or datetime.now().date())


def get_calendar(tier: str, dir=DATA, today: date | None = None) -> list[dict]:
    """The whole diary: a date filter a model gets wrong reads as free. Public sees busy blocks only. Above that
    a block keeps its details only if its own tier allows, so a friend sees "busy" over a private appointment."""
    rows = sorted(_load("calendar", dir), key=lambda e: e["start"])
    shown = {e["id"]: e for e in visible(rows, tier)} if tier != "public" else {}
    return [{"when": _span(e["start"], e["end"], today), **({k: v for k, v in shown[e["id"]].items() if k not in ("id", "start", "end")}
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
    return list({c["name"]: c for c in _load("contacts", dir) + _local(dir)}.values())


def find_contact(number: str, owner: str = OWNER, dir=DATA) -> dict | None:
    """Only a number from caller ID finds a contact. A name the caller says never reaches this."""
    digits = _digits(number or "")
    if owner != OWNER or not digits:
        return None
    return next((c for c in contacts(dir) if digits in map(_digits, c.get("numbers", []))), None)


def _relevant(rows: list[dict], first: str, topics: list[str]) -> list[dict]:
    """With or about this person, on what they share with the owner: a colleague gets work, a friend gets the rest."""
    return [r for r in rows if first in json.dumps(r) and set(r.get("topics", ["personal"])) & set(topics)]


def prefetch(owner: str, contact: dict, past_calls: list[dict], today: date | None = None, dir=DATA, max_words: int = PREFETCH_WORDS) -> str:
    """What the agent knows before it says hello, so its first replies need no tool. Tier-filtered like every read."""
    if owner != OWNER:
        return ""
    tier, first = phone_tier(contact["tier"]), contact["name"].split()[0]
    topics = contact.get("topics", ["personal"])
    newest = lambda name: sorted(_relevant(visible(_load(name, dir), tier), first, topics), key=lambda r: r["date"], reverse=True)
    today = today or datetime.now().date()
    week = [e for e in _load("calendar", dir) if today <= date.fromisoformat(e["start"][:10]) <= today + timedelta(days=7)]
    shown = {e["id"] for e in visible(week, tier) if set(e.get("topics", ["personal"])) & set(topics)} if tier != "public" else set()
    lines = [f"Caller: {contact['name']}, the owner's {contact['relationship']}. {contact.get('notes', '')}".strip()]
    lines += [f"Open task: {t['text']}, due {spoken_day(date.fromisoformat(t['due']), today)}." for t in _relevant(visible(_load("tasks", dir), tier), first, topics) if not t["done"]][:2]
    lines += [f"Last call {spoken_day(date.fromisoformat(c['started_at'][:10]), today)}: {c['summary']}" for c in past_calls[:2]]
    lines += [f"Email from {m['from']}: {m['subject']}. {m['body']}" for m in newest("gmail")[:2]]
    lines += [f"Slack {m['channel']}, {m['from']}: {m['text']}" for m in newest("slack")[:2]]
    lines += ["This week: " + "; ".join(f"{_span(e['start'], e['end'], today)} {e['title'] if e['id'] in shown else 'busy'}"
                                        for e in sorted(week, key=lambda e: e["start"])[:4])] if week else []
    kept, words = [], 0
    for line in lines:                  # most useful first; what does not fit stays behind the tools
        words += len(line.split())
        if words > max_words:
            break
        kept.append(line)
    return "\n".join(kept)
