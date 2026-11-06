"""Voice shape: what a spoken reply must not look like. Pure, no livekit. Read by the bench."""
import re

LIST = re.compile(r"(^|\n)\s*(\d+[.)]|[-*\u2022])\s", re.M)


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def options(text: str) -> int:
    """Rough count of offered options in the longest "a, b, or c" run; 0 when nothing is offered."""
    runs = [s for s in re.split(r"[.?!]", text) if re.search(r"\bor\b", s)]
    return max((r.count(",") + (1 if re.search(r",\s*or\b", r) else 2) for r in runs), default=0)


def problems(text: str, read_back: bool = False) -> list[str]:
    out = []
    if LIST.search(text):
        out.append("list")
    if options(text) > 2:
        out.append(f"{options(text)} options")
    if not read_back and sentences(text) > 2:
        out.append(f"{sentences(text)} sentences")
    return out
