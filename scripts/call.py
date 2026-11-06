"""Talk to Goose in the terminal, as Pranav, as someone in the contact book, or as a stranger.
  uv run python scripts/call.py
  uv run python scripts/call.py --as muhammad --pack jesse
  uv run python scripts/call.py --as owner --voice      # microphone instead of typing
Runs the real agent through console mode, so owner mode, the greeting and the prefetch behave as on a real call.
Ctrl+C ends it. Needs LiveKit keys in .env: the models run on LiveKit Inference.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from proxy_core import calls, vault
from proxy_core.personality import list_packs

UNKNOWN = "+15550100999"    # in no contact book


def choose(label, options):
    print(label)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    while True:
        got = input("> ").strip().lower()
        if got.isdigit() and 0 < int(got) <= len(options):
            return options[int(got) - 1]
        if match := [o for o in options if o.lower().startswith(got)] if got else None:
            return match[0]


def main():
    ap = argparse.ArgumentParser(description="Talk to Goose in the terminal.")
    ap.add_argument("--as", dest="who", help="owner, unknown, or a contact's name")
    ap.add_argument("--pack", help="a personality pack, as in personalities/")
    ap.add_argument("--voice", action="store_true", help="talk into the microphone instead of typing")
    a = ap.parse_args()
    book = {c["name"]: c for c in vault.contacts() if c["relationship"] != "owner"}
    who = a.who or choose("Who is calling?", ["Owner (Pranav)", *book, "Unknown caller"])
    low = who.lower()
    if low.startswith("owner"):
        meta = {"mode": "owner"}
    elif low.startswith("unknown"):
        meta = {"caller": UNKNOWN}
    else:
        name = next((n for n in book if n.lower().startswith(low)), None)
        if not name:
            sys.exit(f"No contact called {who}. Have: {', '.join(book)}")
        meta = {"caller": book[name]["numbers"][0]}
    pack = a.pack or (None if a.who else choose("Which personality?", ["config default", *list_packs()]))
    if pack and pack != "config default":
        if pack not in list_packs():
            sys.exit(f"No pack called {pack}. Have: {', '.join(list_packs())}")
        meta["pack"] = pack
    # Console worker: it runs the entrypoint with GOOSE_CALL as its dispatch metadata. Real jobs ignore this variable.
    cmd = [sys.executable, "-m", "app.worker", "console", "--log-level", "warn", *([] if a.voice else ["--text"])]
    before = {c["id"] for c in calls.list_calls()}
    proc = subprocess.Popen(cmd, cwd=ROOT, env={**os.environ, "GOOSE_CALL": json.dumps(meta), "PYTHONUTF8": "1"})
    while proc.poll() is None:          # Ctrl+C reaches the worker too: wait while it writes the call record
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
    for c in calls.list_calls():
        if c["id"] not in before:
            print(f"\nCall saved: {c['id']}. {c['summary']}")


if __name__ == "__main__":
    main()
