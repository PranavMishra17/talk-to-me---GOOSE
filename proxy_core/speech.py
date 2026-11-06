"""Text the agent is about to speak, said the way a person would on the phone. No livekit, no model.

A prompt asks for "next Monday" and "five five five, one two three"; this makes sure of it. Every spoken line
goes through humanize() in the agent's tts_node, so code-spoken lines (read-back, confirmations) are covered too.
"""
import re
from datetime import date, datetime, timedelta

_ORD = {1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"}


def _ordinal(n: int) -> str:
    return f"{n}{_ORD.get(n, 'th')}"


def spoken_day(d: date, today: date) -> str:
    """today / tomorrow / this Sunday / next Monday / last Tuesday, else "Monday, December 21st".
    "This" is the rest of the current Monday-to-Sunday week, "next" is the week after it, "last" the past six days."""
    delta = (d - today).days
    if delta in (-1, 0, 1):
        return ("yesterday", "today", "tomorrow")[delta + 1]
    if -6 <= delta < 0:
        return f"last {d:%A}"
    week = (d - timedelta(days=d.weekday()) - (today - timedelta(days=today.weekday()))).days // 7
    if delta > 0 and week in (0, 1):
        return f"{('this', 'next')[week]} {d:%A}"
    year = f", {d.year}" if d.year != today.year else ""
    return f"{d:%A}, {d:%B} {_ordinal(d.day)}{year}"


def _part(h: int) -> str:
    return "in the morning" if h < 12 else "in the afternoon" if h < 17 else "in the evening" if h < 22 else "at night"


def spoken_time(h: int, m: int, part: bool = True) -> str:
    """2 in the afternoon, half past 9, quarter to 5, noon. Never 14:00 or 2:00 PM."""
    if m == 0 and h in (0, 12):
        return "midnight" if h == 0 else "noon"
    h12 = h % 12 or 12
    words = {0: f"{h12}", 15: f"quarter past {h12}", 30: f"half past {h12}", 45: f"quarter to {h12 % 12 + 1}"}
    text = words.get(m, f"{h12}:{m:02d}")
    return f"{text} {_part(h)}" if part else text


def spoken_span(start: datetime, end: datetime, today: date) -> str:
    """"tomorrow, 7 to half past 9 in the evening". The part of day is said once when both ends share it."""
    a, b = (start.hour, start.minute), (end.hour, end.minute)
    named = lambda t: t in ((0, 0), (12, 0))
    if not named(a) and not named(b) and _part(a[0]) == _part(b[0]):
        times = f"{spoken_time(*a, part=False)} to {spoken_time(*b)}"
    else:
        times = f"{spoken_time(*a)} to {spoken_time(*b)}"
    day = spoken_day(start.date(), today)
    if end.date() != start.date():
        return f"{day} {spoken_time(*a)} to {spoken_day(end.date(), today)} {spoken_time(*b)}"
    return f"{day}, {times}"


def _blocks(digits: str) -> list[str]:
    """3-3-4 for a ten digit number, a leading 1 on its own, otherwise threes, never a block of one."""
    if len(digits) == 11 and digits[0] == "1":
        return [digits[0], *_blocks(digits[1:])]
    if len(digits) == 10:
        return [digits[:3], digits[3:6], digits[6:]]
    out = [digits[i:i + 3] for i in range(0, len(digits), 3)]
    if len(out) > 1 and len(out[-1]) == 1:
        out[-2:] = [out[-2] + out[-1]]
    return out


def spoken_phone(number: str) -> str:
    """"5 5 5, 1 2 3, 4 5 6 7": TTS reads spaced digits one by one, and the commas are the pauses."""
    digits = re.sub(r"\D", "", number)
    plus = "plus " if number.strip().startswith("+") else ""
    return plus + ", ".join(" ".join(b) for b in _blocks(digits))


_ISO_DT = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
_ISO_D = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?![\d/])")
_PHONE = re.compile(r"(?<![\w$.:/])\+?\(?\d[\d ().-]{5,}\d(?![\w:/])")
_MER = r"([ap])(?:\.\s?m\.|\s?m\b)"
_CLOCK = re.compile(rf"(?<![\d:])(\d{{1,2}}):(\d{{2}})(?![\d:])(?:\s*{_MER})?", re.I)
_HOUR = re.compile(rf"(?<![\d:])(\d{{1,2}})\s*{_MER}", re.I)


def _date(y, mo, d, today):
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _hour(h: int, mer: str | None) -> int:
    mer = (mer or "").lower()
    return h % 12 + 12 if mer == "p" else h % 12 if mer == "a" else h


def humanize(text: str, now: datetime | None = None) -> str:
    """Rewrite digit dates, clock times and phone numbers into speech. Anything it does not recognise is left alone."""
    now = now or datetime.now().astimezone()
    today = now.date()

    def iso_dt(m):
        dt = datetime.fromisoformat(m[0].replace("Z", "+00:00"))
        if dt.tzinfo and now.tzinfo:
            dt = dt.astimezone(now.tzinfo)
        return f"{spoken_day(dt.date(), today)} at {spoken_time(dt.hour, dt.minute)}"

    def iso_d(m):
        d = _date(int(m[1]), int(m[2]), int(m[3]), today)
        return spoken_day(d, today) if d else m[0]

    def slash(m):   # US order: 12/21 is December 21st
        mo, d = int(m[1]), int(m[2])
        y = int(m[3]) if m[3] else today.year
        y = y + 2000 if y < 100 else y
        found = _date(y, mo, d, today)
        if found and not m[3] and found < today - timedelta(days=60):
            found = _date(y + 1, mo, d, today)   # "1/5" said in November means next January
        return spoken_day(found, today) if found else m[0]

    def phone(m):
        return spoken_phone(m[0]) if len(re.sub(r"\D", "", m[0])) >= 7 else m[0]

    def clock(m):
        h, mi = int(m[1]), int(m[2])
        if h > 23 or mi > 59:
            return m[0]
        if m[3] or h > 12 or h == 0:
            return spoken_time(_hour(h, m[3]), mi)
        return spoken_time(h, mi, part=False)   # "7:30" alone: the part of day is not ours to guess

    def hour(m):
        h = int(m[1])
        return spoken_time(_hour(h, m[2]), 0) if 1 <= h <= 12 else m[0]

    for pattern, fn in ((_ISO_DT, iso_dt), (_ISO_D, iso_d), (_SLASH, slash), (_PHONE, phone), (_CLOCK, clock), (_HOUR, hour)):
        text = pattern.sub(fn, text)
    return text


class SpeechBuffer:
    """LLM text streams in pieces, and "555-12" then "3-4567" must be rewritten whole. Text is held back to the
    last clause break that is followed by a non-digit; TTS waits for a sentence break anyway, so this costs little."""
    _CUT = re.compile(r"[.!?;,]\s+(?=[^\d\s(+])")

    def __init__(self, now: datetime | None = None):
        self.now, self._held = now, ""

    def push(self, chunk: str) -> str:
        self._held += chunk
        cut = None
        for cut in self._CUT.finditer(self._held):
            pass
        if not cut:
            return ""
        out, self._held = self._held[:cut.end()], self._held[cut.end():]
        return humanize(out, self.now)

    def flush(self) -> str:
        out, self._held = self._held, ""
        return humanize(out, self.now) if out else ""


if __name__ == "__main__":
    fri = date(2026, 11, 6)
    assert spoken_day(date(2026, 11, 9), fri) == "next Monday"
    assert spoken_day(date(2026, 11, 8), fri) == "this Sunday"
    assert spoken_day(date(2026, 12, 21), fri) == "Monday, December 21st"
    assert spoken_time(14, 0) == "2 in the afternoon" and spoken_time(22, 30) == "half past 10 at night"
    now = datetime(2026, 11, 6, 15, 0)
    assert humanize("free 11/9 at 2:00 PM", now) == "free next Monday at 2 in the afternoon"
    assert humanize("call 555-123-4567.", now) == "call 5 5 5, 1 2 3, 4 5 6 7."
    print(humanize("2026-11-07T19:00:00 or 12/21, 14:00, 7:30, 9am, +1 (617) 555 0199, table for 2, 50/50", now))
