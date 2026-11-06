"""Personality packs: style goes into the prompt, knobs are read only by code. No livekit."""
from pathlib import Path
import yaml
from proxy_core.config import ROOT

DIR = ROOT / "personalities"
_NEEDED = {"name", "voice", "style", "knobs", "examples"}


def load_pack(name: str, dir: Path = DIR) -> dict:
    path = Path(dir) / f"{name}.yaml"
    if not path.is_file():
        raise ValueError(f"unknown personality pack {name!r}; have {list_packs(dir)}")
    pack = yaml.safe_load(path.read_text(encoding="utf-8"))
    if missing := _NEEDED - set(pack):
        raise ValueError(f"pack {name!r} missing {sorted(missing)}")
    return pack


def list_packs(dir: Path = DIR) -> list[str]:
    return sorted(p.stem for p in Path(dir).glob("*.yaml"))


def render_style(pack: dict) -> str:
    s = pack["style"]
    ex = " ".join(f'"{e}"' for e in pack["examples"])
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
