"""Ticket S0-07. Run: uv run python scripts/jev_ping.py
Makes 3 REAL Jev calls (a fraction of a cent total) and prints latency. Errors are shown, not hidden.
Then paste the printed 'median' into PORT.html (section 3, Jev latency row)."""
import statistics, sys, time
sys.path.insert(0, ".")
from proxy_core.config import load_config, load_env
from proxy_core.decider import _jev
load_env()
cfg = load_config()
state = {"turns": [{"speaker": "caller", "text": "Maya, is Rohan free Saturday?"}, {"speaker": "ash", "text": "Let me ask her."}],
         "participants": ["caller", "ash", "maya"], "agenda_ids": ["identify", "learn_ask", "read_back"]}
ms = []
for i in range(3):
    t = time.time()
    try:
        d = _jev(state, cfg)
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}"); sys.exit(1)
    ms.append((time.time() - t) * 1000)
    print(f"call {i+1}: {ms[-1]:.0f} ms  addressee={d.addressee} tone={d.tone} injection={d.injection} done={d.done}")
print(f"median {statistics.median(ms):.0f} ms  (expect 70-500; over 500: set decider.backend: keyword in config.yaml)")
