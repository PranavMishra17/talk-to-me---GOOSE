"""Flip the phone between demos: stop this with Ctrl+C, then start the other one. Needs no dispatch rule change.
  uv run python scripts/demo.py goose
  uv run python scripts/demo.py jesse
Runs the worker under the agent name dispatch-rule.json routes to, with the persona you name behind it. Spends credits.
A native crash takes the whole worker down on Windows, so anything but Ctrl+C restarts it.
"""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from proxy_core.config import load_config


def main():
    personas = load_config()["personas"]
    persona = sys.argv[1] if len(sys.argv) > 1 else ""
    if persona not in personas:
        raise SystemExit(f"usage: demo.py {'|'.join(personas)}")
    rule = json.loads((ROOT / "dispatch-rule.json").read_text(encoding="utf-8"))
    name = rule["dispatch_rule"]["room_config"]["agents"][0]["agent_name"]
    print(f"LIVE: {persona.title()} answers for {personas[persona]['owner'].title()} on the phone rule's agent name '{name}'. Ctrl+C to stop.", flush=True)
    env = {**os.environ, "GOOSE_PERSONA": persona, "GOOSE_DISPATCH_AS": name, "PYTHONUTF8": "1"}
    try:
        while True:
            code = subprocess.call([sys.executable, "-m", "app.worker", "dev"], cwd=ROOT, env=env)
            print(f"worker exited with {code}; restarting {persona.title()} in 1 s", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
