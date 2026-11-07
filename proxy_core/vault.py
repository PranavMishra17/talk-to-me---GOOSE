"""Each owner's mock data, filtered by tier in code so the model never sees a record above the caller's tier. No livekit."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from proxy_core.config import ROOT, data_root
from proxy_core.policy import TIERS
from proxy_core.speech import spoken_day, spoken_span

DATA = ROOT / "data"
OWNER = "pranav"              # data/ itself is his; any other owner reads data/<owner>/ and nothing else
PREFETCH_WORDS = 150         # the bundle rides on every turn's prompt, so it stays short
BRIEFING_DAYS = 7             # the diary every caller's prompt carries; later dates go through get_calendar
BRIEFING_ENTRIES = 10
PHONE_MAX = "family"          # caller ID can be spoofed, so no phone call reaches private data, not even the owner's number


def owner_dir(owner: str) -> Path | None:
    """The one folder this owner's assistant reads. None = this owner has no data."""
    d = DATA if owner == OWNER else DATA / owner
    return d if d.is_dir() else None


def _rank(tier) -> int:
    """A record with a missing or unknown tier counts as private, the opposite of an unknown caller."""
    return TIERS.index(tier) if tier in TIERS else len(TIERS) - 1


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _edits(name: str) -> Path:
    return data_root() / "data" / f"{name}.json"


def _load(name: str, dir=DATA) -> list[dict]:
    """The committed file, with the owner's own changes on top: a record with the same id replaces the original."""
    rows = _read(dir / f"{name}.json")
    if dir != DATA:
        return rows
    try:
        edits = _read(_edits(name))
    except ValueError:                # a broken overlay must not take reads down
        return rows
    return list({r.get("id", i): r for i, r in enumerate([*rows, *edits])}.values())


def _save(name: str, record: dict) -> dict:
    """Written to the overlay, so data/ stays as committed and a change survives a restart."""
    path = _edits(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = [r for r in _read(path) if r["id"] != record["id"]]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([*kept, record], indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return record


def _when(text: str) -> str:
    """An ISO date and time, or ValueError. A bare time gets the local zone, as everything else in the diary has one.
    A bare date is the evening: "a dinner reservation for tomorrow" names no time, and the tool's reply says the one it chose."""
    text = f"{text}T19:00:00" if len(text) == 10 else text
    return datetime.fromisoformat(text).astimezone().isoformat(timespec="seconds")


def event_text(e: dict) -> str:
    return ", ".join(filter(None, [e["title"], _span(e["start"], e["end"]), e.get("where")]))


def add_event(title: str, start: str, end: str = "", where: str = "", tier: str = "private") -> dict:
    """Private by default: a caller sees a new entry as busy until the owner says otherwise."""
    begin = _when(start)
    finish = _when(end) if end else (datetime.fromisoformat(begin) + timedelta(hours=1)).isoformat(timespec="seconds")
    return _save("calendar", {"id": f"c-{os.urandom(3).hex()}", "start": begin, "end": finish, "title": title, "where": where, "with": [], "tier": tier})


def update_event(event: str, tier: str, last: str = "", **changes) -> dict | list[str]:
    """event = words from its title. Returns the record, or the titles it could be when that is not exactly one.
    last = the entry just discussed, which "update the location to Bungalow" means, whatever the model calls it.
    Only entries the tier can see match, so a reply never names one it cannot."""
    words = event.lower().split()
    allowed = {e["id"] for e in visible(_load("calendar"), tier)}
    found = [e for e in _load("calendar") if e["id"] in allowed and all(w in e["title"].lower() for w in words)]
    if last and (len(found) != 1 or not words):
        found = [e for e in _load("calendar") if e["id"] == last and e["id"] in allowed] or found
    if len(found) != 1:
        return [e["title"] for e in found]
    changes = {k: _when(v) if k in ("start", "end") else v for k, v in changes.items() if v}
    return _save("calendar", {**found[0], **changes})


def add_task(text: str, due: str = "", tier: str = "private") -> dict:
    return _save("tasks", {"id": f"t-{os.urandom(3).hex()}", "text": text, "due": due or date.today().isoformat(), "people": [], "done": False, "tier": tier})


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
        # The override is Pranav's book: on another owner it would make his number that owner's too.
        rows = json.loads(Path(dir == DATA and os.environ.get("GOOSE_CONTACTS_LOCAL") or dir / "contacts.local.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = rows.get("contacts", []) if isinstance(rows, dict) else rows
    return [{"relationship": "contact", "notes": "", **c, "tier": c.get("tier") if c.get("tier") in TIERS else "public"}
            for c in rows if isinstance(c, dict) and c.get("name") and isinstance(c.get("numbers"), list)]


def contacts(dir=DATA) -> list[dict]:
    """contacts.json merged with the gitignored local file. A local entry replaces the same name."""
    local = [] if DATA in dir.parents else _local(dir)      # the real numbers are Pranav's; an owner folder never merges them
    return list({c["name"]: c for c in _load("contacts", dir) + local}.values())


def number_for(name: str | None, owner: str = OWNER) -> str | None:
    """The web Join as names a contact. The number stays on the server: an attribute would reach every browser in the room."""
    home = owner_dir(owner)
    c = next((c for c in contacts(home) if c["name"] == name), None) if home else None
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


def _diary(dir, tier: str, topics: list[str] | None, today: date, days: int = BRIEFING_DAYS) -> list[str]:
    """The next few days, one spoken line each. A title shows only if the tier allows it and, for a known contact,
    it is on a topic they share with the owner: a colleague hears "busy" over a dinner. Public hears busy only."""
    end = today + timedelta(days=days)
    rows = sorted((e for e in _load("calendar", dir) if today <= date.fromisoformat(e["start"][:10]) <= end), key=lambda e: e["start"])
    shown = {e["id"] for e in visible(rows, tier) if topics is None or set(e.get("topics", ["personal"])) & set(topics)} \
        if tier != "public" else set()
    return [f"{_span(e['start'], e['end'], today)}: {e['title'] if e['id'] in shown else 'busy'}" for e in rows[:BRIEFING_ENTRIES]]


def briefing(owner: str, tier: str, topics: list[str] | None = None, today: date | None = None, dir=None) -> str:
    """What every caller's prompt carries about the owner, so "is he free Monday?" or "when's best to reach him?"
    needs no tool. It holds nothing get_profile and get_calendar would not give this caller, and less: a work-only
    contact gets the public profile, and titles follow the caller's topics as in prefetch."""
    dir = dir or owner_dir(owner)
    if dir is None:
        return ""
    today = today or datetime.now().date()
    personal = topics is None or "personal" in topics
    profile = get_profile(tier if personal else "public", dir)
    lines = [f"{k.replace('_', ' ')}: {v}" for k, v in profile.items()]
    diary = _diary(dir, tier, topics, today)
    lines += [f"Diary, today to {spoken_day(today + timedelta(days=BRIEFING_DAYS), today)}:"] + \
        ([f"- {d}" for d in diary] or ["- nothing booked"])
    return "\n".join(lines)


def prefetch(owner: str, contact: dict, past_calls: list[dict], today: date | None = None, dir=None, max_words: int = PREFETCH_WORDS) -> str:
    """What the agent knows before it says hello, so its first replies need no tool. Tier-filtered like every read."""
    dir = dir or owner_dir(owner)
    if dir is None:
        return ""
    tier, first = phone_tier(contact["tier"]), contact["name"].split()[0]
    topics = contact.get("topics", ["personal"])
    newest = lambda name: sorted(_relevant(visible(_load(name, dir), tier), first, topics), key=lambda r: r["date"], reverse=True)
    today = today or datetime.now().date()
    lines = [f"Caller: {contact['name']}, the owner's {contact['relationship']}. {contact.get('notes', '')}".strip()]
    lines += [f"Open task: {t['text']}, due {spoken_day(date.fromisoformat(t['due']), today)}." for t in _relevant(visible(_load("tasks", dir), tier), first, topics) if not t["done"]][:2]
    lines += [f"Last call {spoken_day(date.fromisoformat(c['started_at'][:10]), today)}: {c['summary']}" for c in past_calls[:2]]
    lines += [f"Email from {m['from']}: {m['subject']}. {m['body']}" for m in newest("gmail")[:2]]
    lines += [f"Slack {m['channel']}, {m['from']}: {m['text']}" for m in newest("slack")[:2]]
    kept, words = [], 0
    for line in lines:                  # most useful first; what does not fit stays behind the tools
        words += len(line.split())
        if words > max_words:
            break
        kept.append(line)
    return "\n".join(kept)
