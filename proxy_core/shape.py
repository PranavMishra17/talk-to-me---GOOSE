"""Voice shape: what a spoken reply must not look like. Pure, no livekit. Read by the bench."""
import re

END = re.compile(r"(?<![MD]r\.)(?<!Mrs\.)(?<!Ms\.)(?<=[.!?])\s+")
LIST = re.compile(r"(^|\n)\s*(\d+[.)]|[-*\u2022])\s", re.M)


def _split(text: str) -> list[str]:
    return [s for s in END.split(text.strip()) if s]


def sentences(text: str) -> int:
    return len(_split(text))


def clip(text: str) -> str:
    """At most two spoken sentences, keeping a closing question: models overrun the prompt's limit."""
    parts = _split(text)
    if len(parts) <= 2:
        return text
    return " ".join([parts[0], parts[-1] if parts[-1].endswith("?") else parts[1]])


def options(text: str) -> int:
    """Rough count of offered options in the longest "a, b, or c" run; 0 when nothing is offered."""
    best = 0
    for s in re.split(r"[.?!]", text):
        if not re.search(r"\bor\b", s):
            continue
        head = re.split(r"\bor\b", s)[-2].strip().rstrip(",")   # short items just before the "or"; a clause is no option
        items = 0
        for part in reversed(head.split(",")):
            if len(part.split()) > 3:
                break
            items += 1
        best = max(best, max(items, 1) + 1)
    return best


def problems(text: str, read_back: bool = False) -> list[str]:
    out = []
    if LIST.search(text):
        out.append("list")
    if options(text) > 2:
        out.append(f"{options(text)} options")
    if not read_back and sentences(text) > 2:
        out.append(f"{sentences(text)} sentences")
    return out
