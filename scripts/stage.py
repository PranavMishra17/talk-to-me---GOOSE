"""The mock world between test and demo. No network, no credits.
  uv run python scripts/stage.py reset    # wipe runtime, then the committed calls in data/calls, moved to end just before now
  uv run python scripts/stage.py clear    # wipe runtime and hide the committed calls: an empty history
  uv run python scripts/stage.py up       # the web demo: one worker per persona and uvicorn on 8000. SPENDS CREDITS while calls run
up restarts anything that dies (a native crash takes a whole worker down on Windows); Ctrl+C stops all of it. Output goes to
.harness/stage-<name>.log. Maya runs too: /demo's first button lets Goose summon her. The phone rule reaches Goose.
Wipes only the names below under GOOSE_DATA_DIR (default runtime/): call records, diary and task overlays, tagged test runs.
Stop the worker first if a call is live: its record lands when it hangs up.
"""
import importlib.util, json, os, shutil, subprocess, sys, threading, time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("GOOSE_AGENT_TAG", None)     # the real history, not a tagged test folder
from proxy_core import calls
from proxy_core.config import data_root, load_config

WIPED = ("calls", "data", "test", calls.CLEARED)
OUT, PORT = ROOT / ".harness", "8000"
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


def services() -> list[dict]:
    """A plain env for each: a stray tag, mock flag or dispatch alias would leave a button with no worker behind it."""
    env = {k: v for k, v in os.environ.items() if k not in ("GOOSE_AGENT_TAG", "GOOSE_MOCK", "GOOSE_DISPATCH_AS")}
    env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    workers = [{"name": p, "cmd": [sys.executable, "-m", "app.worker", "dev"], "env": {**env, "GOOSE_PERSONA": p},
                "ready": "registered worker"} for p in load_config()["personas"]]
    web = {"name": "web", "cmd": [sys.executable, "-m", "uvicorn", "app.api:app", "--port", PORT], "env": env,
           "ready": "Uvicorn running on", "url": f"http://localhost:{PORT}/demo"}
    return [*workers, web]


def _kill(p) -> None:
    if os.name == "nt":      # dev mode has child processes
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    else:
        p.kill()


def _keep_up(s: dict, stop: threading.Event, running: dict) -> None:
    OUT.mkdir(exist_ok=True)
    with open(OUT / f"stage-{s['name']}.log", "a", encoding="utf-8") as log:
        while not stop.is_set():
            p = subprocess.Popen(s["cmd"], cwd=ROOT, env=s["env"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 encoding="utf-8", errors="replace")
            running[s["name"]] = p
            last = ""
            for line in p.stdout:
                log.write(line)
                log.flush()
                last = line.strip() or last
                if s["ready"] in line:
                    print(f"READY {s['name']}" + (f"  {s['url']}" if s.get("url") else ""), flush=True)
            code = p.wait()
            if not stop.is_set():
                print(f"{s['name']} exited with {code}, restarting in 1 s. Last line: {last[:120]}", flush=True)
                stop.wait(1)


def serve(items: list[dict], stop: threading.Event) -> None:
    """Runs until stop is set, then takes every process tree down, however the stop came."""
    running: dict = {}
    threads = [threading.Thread(target=_keep_up, args=(s, stop, running), daemon=True) for s in items]
    for t in threads:
        t.start()
    print(f"starting {', '.join(s['name'] for s in items)}. Ctrl+C stops all of them.", flush=True)
    try:
        while not stop.wait(0.2):
            pass
    except KeyboardInterrupt:
        print("stopping...", flush=True)
    finally:
        stop.set()
        for p in running.values():
            _kill(p)
        for t in threads:
            t.join(10)
        print("stopped", flush=True)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("reset", "clear", "up"):
        raise SystemExit(__doc__)
    if cmd == "up":
        if load_config()["providers"]["noise_cancellation"]["kind"] == "bvc_telephony" and \
                not importlib.util.find_spec("livekit.plugins.noise_cancellation"):
            raise SystemExit("noise cancellation plugin missing, phone calls would crash: run uv sync --extra nc")
        return serve(services(), threading.Event())
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
