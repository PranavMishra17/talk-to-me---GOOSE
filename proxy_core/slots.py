"""Deterministic slots from what the caller said: no model, no latency. No livekit.

Regex covers what it is good at: a name, a day, a time. The message itself comes from take_message's arguments.
ponytail: English phrasings only, and the name needs STT's capital letter. A miss falls back to the tool's from_name.
"""
import re

_DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tonight|tomorrow"
_NUM = r"\d{1,2}(?::\d{2})?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
_MERIDIEM = r"[ap]\.?m\b\.?"
_DAY = re.compile(rf"\b({_DAYS})\b", re.I)
_TIME = re.compile(rf"\b(?:at|around|to|it)\s+(?P<a>(?:{_NUM})(?:\s*{_MERIDIEM})?)|\b(?P<b>\d{{1,2}}(?::\d{{2}})?\s*{_MERIDIEM})|\b(?P<c>noon|midnight)\b", re.I)
_NAME = re.compile(r"\b(?i:this is|it'?s|i'?m|i am|my name is|name'?s)\s+([A-Z][a-z]+)\b(?!')")
_NOT_NAMES = set(_DAYS.split("|")) | {"not", "just", "sorry", "fine", "good", "okay", "busy", "free", "calling", "here", "great"}


def extract(text: str) -> dict:
    """The last mention wins, so "Saturday... actually Sunday" gives Sunday."""
    out = {}
    if (m := _NAME.search(text)) and m[1].lower() not in _NOT_NAMES:
        out["name"] = m[1]
    if days := _DAY.findall(text):
        out["day"] = days[-1].title()
    if times := list(_TIME.finditer(text)):
        out["time"] = (times[-1]["a"] or times[-1]["b"] or times[-1]["c"]).strip().lower()
    return out


def corrected(slots: dict, found: dict) -> dict:
    """A changed day or time is also rewritten inside the message, so the read-back cannot repeat the old value."""
    out = dict(found)
    for k in ("day", "time"):
        old, new = slots.get(k), found.get(k)
        if old and new and old != new:
            for field in ("topic", "details"):
                if text := out.get(field, slots.get(field)):
                    out[field] = re.sub(rf"\b{re.escape(old)}\b", new, text, flags=re.I)
    return out


def _message(s: dict) -> str:
    what = (s.get("details") or s.get("topic") or "").rstrip(" .")
    plan = [v for v, shown in ((s.get("day"), s.get("day")), (s.get("time") and f"at {s['time']}", s.get("time")))
            if v and shown.lower() not in what.lower()]
    return " ".join([what, *plan]).strip()


def read_back(s: dict, owner: str) -> str:
    who = f"From {s['name']}: " if s.get("name") else ""
    return f"Let me read that back. {who}{_message(s)}. That goes to {owner}. Is that right?"


def summary(s: dict, owner: str, ended: str) -> str:
    what = _message(s) or "no message taken"
    said = "read back and confirmed" if s.get("confirmed") else "not read back"
    return f"{s.get('name') or 'Unknown caller'} for {owner}: {what} ({said}). Ended: {ended}."


if __name__ == "__main__":
    assert extract("Hi, it's Sam.") == {"name": "Sam"}
    assert extract("I'm his boss") == {} and extract("It's Saturday") == {"day": "Saturday"}
    assert "name" not in extract("I'm Pranav's brother")
    assert extract("Dinner Saturday at 7 p.m. works") == {"day": "Saturday", "time": "7 p.m."}
    assert extract("Saturday... actually Sunday")["day"] == "Sunday"
    assert extract("make it eight")["time"] == "eight"
    assert extract("a table for 2") == {}
    s = {"name": "Sam", "details": "dinner Saturday at 7", "day": "Saturday", "time": "7"}
    c = corrected(s, {"day": "Sunday"})
    assert c["details"] == "dinner Sunday at 7"
    assert "dinner Sunday at 7. That goes to Pranav" in read_back({**s, **c}, "Pranav")
    assert "dinner Saturday at 7" in read_back({"topic": "dinner", "day": "Saturday", "time": "7"}, "Pranav")
    assert "Unknown caller" in summary({}, "Pranav", "caller went quiet")
