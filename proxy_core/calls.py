"""Call records: one JSON file per call. Seeds are committed in data/calls; live ones land in GOOSE_DATA_DIR/calls.
Shape, which the web app depends on: {id, started_at, ended_at, kind, number, contact, persona, pack, summary,
outcome, actions, transcript}. Pure: no livekit, and no model, so a record cannot fail at hang-up.
"""
import json
import os
from pathlib import Path

from proxy_core.config import ROOT
from proxy_core.slots import _message

SEED = ROOT / "data" / "calls"
OUTCOMES = ("resolved", "needs_you", "info")


def runtime_dir() -> Path:
    return Path(os.environ.get("GOOSE_DATA_DIR") or ROOT / "runtime") / "calls"


def list_calls() -> list[dict]:
    """Newest first. A runtime file replaces the seed with the same id, which is how mark_done survives."""
    found = {}
    for path in [*sorted(SEED.glob("*.json")), *sorted(runtime_dir().glob("*.json"))]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            found[record["id"]] = record
        except (ValueError, KeyError, OSError):      # one bad file must not hide the rest
            continue
    return sorted(found.values(), key=lambda c: c["started_at"], reverse=True)


def get_call(call_id: str) -> dict | None:
    """Looked up in the list, never joined into a path: the id may come from a model or a URL."""
    return next((c for c in list_calls() if c["id"] == call_id), None)


def write_call(record: dict) -> Path:
    """tmp then rename, so a reader never sees half a record."""
    out = runtime_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{record['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def mark_done(call_id: str) -> dict | None:
    record = get_call(call_id)
    if record:
        record["actions"] = [{**a, "done": True} for a in record["actions"]]
        write_call(record)
    return record


def calls_with(name: str) -> list[dict]:
    """This person's phone calls, newest first."""
    return [c for c in list_calls() if c["kind"] == "phone" and (c.get("contact") or {}).get("name") == name]


def outcome(who: str, log: list[str], slots: dict, turns: list[dict]) -> tuple[str, str, list[dict]]:
    """(summary, outcome, actions) from what the call did: the agent's task log, its slots, the transcript."""
    first = who.split()[0]
    heard = [t["text"] for t in turns if t["who"] == "caller"]
    actions = []
    for entry in log:
        if entry.startswith("message from "):
            actions.append(f"Reply to {first}: {entry.split(': ', 1)[1]}")
        elif entry.startswith("slot "):
            actions.append(f"Confirm {entry[5:]} with {first}")
        elif entry.startswith("permission? "):
            actions.append(f"Decide if {first} may know: {entry[12:]}")
    what = _message(slots)
    summary = f"{first} left a message: {what}." if what else f"{first} said: {heard[0]}" if heard else f"{first} hung up without a word."
    ended = next((e[5:] for e in reversed(log) if e.startswith("end: ")), "")
    status = "needs_you" if actions else "resolved" if heard and ended in ("caller said goodbye", "caller confirmed") else "info"
    return summary, status, [{"text": a, "done": False} for a in actions]


def brief(records: list[dict], owner: str) -> str:
    """What the owner hears on opening the app. From records only, so it cannot invent a call."""
    phone = [c for c in records if c["kind"] == "phone"]
    if not phone:
        return f"Hi {owner}. No calls yet."
    words = [f"Hi {owner}. {len(phone)} call{'s' * (len(phone) > 1)} so far."]
    sorted_out = [c for c in phone if c["outcome"] == "resolved"]
    if sorted_out:
        words.append(f"Sorted: {sorted_out[0]['summary']}")
    waiting = [c for c in phone if any(not a["done"] for a in c["actions"])]
    if not waiting:
        return " ".join([*words, "Nothing needs you."])
    words += [f"{len(waiting)} need{'s' * (len(waiting) == 1)} you.", *(c["summary"] for c in waiting[:2])]
    names = [(c.get("contact") or {}).get("name", "the unknown caller").split()[0] for c in waiting[:2]]
    if len(names) == 2:
        words.append(f"Which first, {names[0]} or {names[1]}?")
    return " ".join(words)


if __name__ == "__main__":
    assert len(list_calls()) >= 4 and get_call("../../.env") is None
    log = ["message from Sam: dinner works", "end: caller confirmed"]
    s, o, a = outcome("Sam Okafor", log, {"details": "dinner works"}, [{"who": "caller", "text": "hi"}])
    assert (o, a[0]["text"]) == ("needs_you", "Reply to Sam: dinner works") and s == "Sam left a message: dinner works."
    assert outcome("Unknown caller", [], {}, [])[:2] == ("Unknown hung up without a word.", "info")
    assert outcome("Sam", ["end: caller said goodbye"], {}, [{"who": "caller", "text": "bye"}])[1] == "resolved"
    assert outcome("Sam", ["end: hostile caller"], {}, [{"who": "caller", "text": "x"}])[1] == "info"
    assert brief([], "Pranav") == "Hi Pranav. No calls yet."
    print(brief(list_calls(), "Pranav"))
