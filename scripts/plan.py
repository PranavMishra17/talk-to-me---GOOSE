"""Dashboard CLI: the only way code touches core-spec/goose-plan.html. Edits the plan JSON, never the renderer.
  uv run python scripts/plan.py set S0-07 done "median 951 ms"
  uv run python scripts/plan.py log "text"
  uv run python scripts/plan.py add '{"id": "S8-06", "stream": "S8", "phase": "V1", "title": "...", "owner": "orchestrator"}'
  uv run python scripts/plan.py next     # what is in progress, blocked and ready
"""
import json, os, re, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = Path(os.environ.get("GOOSE_PLAN") or ROOT / "core-spec" / "goose-plan.html")   # strategy stays local: worktrees point here
BLOCK = re.compile(r'(<script id="plan" type="application/json">)(.*?)(</script>)', re.S)
STATUS = {"todo", "doing", "done", "blocked", "dropped"}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load():
    return json.loads(BLOCK.search(FILE.read_text(encoding="utf-8")).group(2))


def _dump(plan):  # one ticket / log line per row, so the file stays readable
    def row(k, v):
        if isinstance(v, list):
            return f' {json.dumps(k)}: [\n  ' + ",\n  ".join(json.dumps(i, ensure_ascii=False) for i in v) + "\n ]"
        return f' {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}'
    return "\n{\n" + ",\n".join(row(k, v) for k, v in plan.items()) + "\n}\n"


def save(plan):
    plan["updated"] = now()
    with open(FILE, encoding="utf-8", newline="") as f:
        s = f.read()
    s = BLOCK.sub(lambda m: m.group(1) + _dump(plan).replace("</", "<\\/") + m.group(3), s, count=1)
    with open(FILE, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def log(msg, who="orchestrator"):
    plan = load()
    plan["log"].append({"ts": now(), "who": who, "msg": msg})
    save(plan)


def set_status(tid, status, note=""):
    if status not in STATUS:
        raise SystemExit(f"bad status {status!r}; use {sorted(STATUS)}")
    plan = load()
    t = next((t for t in plan["tickets"] if t["id"] == tid), None)
    if t is None:
        raise SystemExit(f"no ticket {tid}")
    t["status"] = status
    if note:
        t["notes"] = (t.get("notes", "") + " " + note).strip()
    plan["log"].append({"ts": now(), "who": "orchestrator", "msg": f"{tid} {status}" + (f": {note}" if note else "")})
    save(plan)


def add(ticket):
    plan = load()
    ticket = {"deps": [], "status": "todo", "owner": "", "accept": [], "notes": "", **ticket}
    if any(t["id"] == ticket["id"] for t in plan["tickets"]):
        raise SystemExit(f"{ticket['id']} exists")
    plan["tickets"].append(ticket)
    plan["log"].append({"ts": now(), "who": "orchestrator", "msg": f"added {ticket['id']}: {ticket['title']}"})
    save(plan)


def show_next():
    plan = load()
    T = plan["tickets"]
    st = {t["id"]: t["status"] for t in T}
    done = sum(s == "done" for s in st.values())
    print(f"{done}/{len(T)} done")
    for name, pick in (("doing", lambda t: t["status"] == "doing"), ("blocked", lambda t: t["status"] == "blocked"),
                       ("ready", lambda t: t["status"] == "todo" and all(st.get(d) == "done" for d in t["deps"]))):
        for t in filter(pick, T):
            print(f"{name:8}{t['id']:7}{t['phase']:7}{t['owner'] or '-':13}{t['title']}")


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("next", [])
    if cmd == "set":
        set_status(*args[:3])
    elif cmd == "log":
        log(args[0])
    elif cmd == "add":
        add(json.loads(args[0]))
    elif cmd == "next":
        show_next()
    else:
        raise SystemExit(__doc__)
