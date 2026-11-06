"""Run: uv run python scripts/check_env.py   -> shows which .env names are SET/MISSING. Never prints values."""
import os, sys
sys.path.insert(0, ".")
from proxy_core.config import load_env
load_env()
need = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
jev = ["TYPESAFE_API_KEY", "OPENROUTER_API_KEY"]
bad = 0
for k in need + jev:
    ok = bool(os.environ.get(k))
    print(f"{'SET    ' if ok else 'MISSING'} {k}")
    bad += (not ok) and k in need
if not any(os.environ.get(k) for k in jev):
    print("-> need ONE of TYPESAFE_API_KEY / OPENROUTER_API_KEY for the Jev decider (keyword backend works without).")
u = os.environ.get("LIVEKIT_URL", "")
if u and not u.startswith("wss://"):
    print("-> LIVEKIT_URL should start with wss:// (copy it from cloud.livekit.io > Settings)"); bad += 1
sys.exit(1 if bad else 0)
