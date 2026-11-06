"""The mock world between test and demo. No network, no credits.
  uv run python scripts/stage.py reset    # wipe runtime, then the committed calls in data/calls, moved to end just before now
  uv run python scripts/stage.py clear    # wipe runtime and hide the committed calls: an empty history
Wipes only the names below under GOOSE_DATA_DIR (default runtime/): call records, diary and task overlays, tagged test runs.
Stop the worker first if a call is live: its record lands when it hangs up.
"""
import json, os, shutil, sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("GOOSE_AGENT_TAG", None)     # the real history, not a tagged test folder
from proxy_core import calls
from proxy_core.config import data_root

WIPED = ("calls", "data", "test", calls.CLEARED)
NEWEST_AGO = timedelta(minutes=25)          # the last seeded call ended a little before the demo starts


def wipe() -> None:
    root = data_root()
    for name in WIPED:
        path = root / name
        if path.is_dir():
            n = sum(p.is_file() for p in path.rglob("*"))
            shutil.rmtree(path)
            print(f"wiped {path} ({n} files)")
        elif path.exists():
            path.unlink()
            print(f"removed {path}")


def moved(record: dict, by: timedelta) -> dict:
    stamp = lambda s: (datetime.fromisoformat(s) + by).isoformat(timespec="seconds")
    return {**record, "started_at": stamp(record["started_at"]), "ended_at": stamp(record["ended_at"]),
            "transcript": [{**t, "ts": stamp(t["ts"])} for t in record["transcript"]]}


def seed() -> None:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(calls.SEED.glob("*.json"))]
    now = datetime.now().astimezone()
    by = now - NEWEST_AGO - max(datetime.fromisoformat(r["ended_at"]) for r in rows)
    for r in rows:
        calls.write_call(moved(r, by))
    for c in calls.list_calls():
        print(f"seeded {c['started_at'][:16]} {(c['contact'] or {}).get('name', 'unknown caller'):14} {c['outcome']:10} {c['summary']}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("reset", "clear"):
        raise SystemExit(__doc__)
    wipe()
    if cmd == "reset":
        seed()
    else:
        data_root().mkdir(parents=True, exist_ok=True)
        (data_root() / calls.CLEARED).touch()
    who = calls.list_calls()
    print(f"{cmd}: {len(who)} calls in {data_root()}; briefing: {calls.brief(calls.list_calls('pranav'), 'Pranav')}")


if __name__ == "__main__":
    main()
