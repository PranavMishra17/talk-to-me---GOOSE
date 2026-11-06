"""List Cartesia's voices with their metadata, to pick a voice per pack. Free: it only reads the catalog.
Needs CARTESIA_API_KEY in .env (free account at play.cartesia.ai). LiveKit Inference plays Cartesia's default voices.
  uv run python scripts/voices.py                    # English voices
  uv run python scripts/voices.py young male casual  # every word must match the name or description
"""
import os, sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proxy_core.config import load_env

load_env()
key = os.environ.get("CARTESIA_API_KEY")
if not key:
    raise SystemExit("Add CARTESIA_API_KEY to .env first.")
words = [w.lower() for w in sys.argv[1:]]
url, after, n = "https://api.cartesia.ai/voices", None, 0
headers = {"Authorization": f"Bearer {key}", "Cartesia-Version": "2025-04-16"}
while True:
    r = httpx.get(url, headers=headers, params={"limit": 100, **({"starting_after": after} if after else {})}, timeout=15)
    if r.status_code >= 400:
        raise SystemExit(f"Cartesia {r.status_code}: {r.text[:200]}")
    body = r.json()
    for v in body["data"]:
        text = f"{v.get('name', '')} {v.get('description', '')} {v.get('gender', '')}".lower()
        if str(v.get("language", "en")).startswith("en") and all(w in text for w in words):
            n += 1
            print(f"{v['id']}  {v.get('gender') or '-':14} {v.get('name', '')[:24]:24} {(v.get('description') or '')[:90]}")
    if not body.get("has_more"):
        break
    after = body["data"][-1]["id"]
print(f"\n{n} voices")
