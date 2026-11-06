"""Personality packs: style goes into the prompt, knobs are read only by code. No livekit."""
from pathlib import Path
import yaml
from proxy_core.config import ROOT

DIR = ROOT / "personalities"
_NEEDED = {"name", "voice", "style", "greeting", "confirm", "knobs", "title", "from", "tag", "ext", "own", "dials"}


def load_pack(name: str, dir: Path = DIR) -> dict:
    path = Path(dir) / f"{name}.yaml"
    if not path.is_file():
        raise ValueError(f"unknown personality pack {name!r}; have {list_packs(dir)}")
    pack = yaml.safe_load(path.read_text(encoding="utf-8"))
    if missing := _NEEDED - set(pack):
        raise ValueError(f"pack {name!r} missing {sorted(missing)}")
    d = pack["dials"]   # the dials are the one source; code reads these knobs, the landing page shows the dials
    pack["knobs"] = {**pack["knobs"], "eagerness": d["Eager"] / 100, "directness": d["Direct"] / 100,
                     "patience_turns": max(1, round(d["Patience"] / 20)), "humour": d["Humour"] / 100}
    return pack


def cards() -> list[dict]:
    """GET /packs: the landing page's shape, in its order."""
    packs = sorted((load_pack(n) for n in list_packs()), key=lambda p: p.get("order", 99))
    return [{"id": p["name"], "name": p["title"], **{k: p[k] for k in ("from", "tag", "ext", "own", "dials")}} for p in packs]


def list_packs(dir: Path = DIR) -> list[str]:
    return sorted(p.stem for p in Path(dir).glob("*.yaml"))


def render_style(pack: dict, stance: str = "ext") -> str:
    s = pack["style"]
    ex = " ".join(f'"{e}"' for e in pack[stance][:2])   # ext to strangers, own to the owner
    return (
        f"Voice: {s['register']}. Favour words like {', '.join(s['vocabulary'])}. "
        f"Sentences: {s['sentence_length']}. Humour: {s['humour']}. Formality: {s['formality']}. "
        f"Use any catchphrase {s['catchphrase_budget']} at most. "
        "Never sound like an apologetic assistant: no sorry, no hedging. "
        "\"I don't have that, I'll ask him\" is a complete answer. "
        "Refusals may be in character, but the privacy filter is unaffected by style. "
        f"Examples: {ex}"
    )


def knob(pack: dict, name: str):
    return pack["knobs"][name]


def nudge_text(pack: dict, step: int) -> str:
    """step 0 nudge, 1 restate, 2 close-with-summary."""
    return knob(pack, "nudge_style")[step]


def tool_filler(pack: dict, n: int) -> str:
    """The nth line to say before a tool call; rotates so the agent does not repeat itself."""
    lines = pack["tool_filler"]
    return lines[n % len(lines)]


def farewell(pack: dict, n: int = 0) -> str:
    """Spoken by code before end_call: several Inference models hang up silently."""
    lines = pack["farewell"]
    return lines[n % len(lines)]


def greeting(pack: dict, assistant: str, owner: str, name: str | None = None) -> str:
    """Code speaks the first line, so a known caller is never asked who is calling, and no model delays it."""
    return pack["greeting"]["known" if name else "unknown"].format(assistant=assistant, owner=owner, name=name)


def confirm_line(pack: dict, tool: str, owner: str) -> str:
    """One in-character line that asks for a yes before an action."""
    return pack["confirm"][tool].format(owner=owner)
