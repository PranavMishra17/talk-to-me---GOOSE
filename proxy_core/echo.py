"""Echo guard: a caller transcript that mostly repeats an agent's recent speech is our own audio leaking back.
Pure, no livekit. Text counts as recent while it plays and for window_s after it ends."""
import re

MIN_TOKENS = 4  # short replies ("yes, Saturday works") overlap by chance and must always get through


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


class EchoGuard:
    def __init__(self, window_s: float = 3.0, overlap: float = 0.7):
        self.window_s, self.overlap = window_s, overlap
        self.recent: list[list] = []  # [text, ended_at or None while playing]

    def said(self, text: str) -> None:
        self.recent.append([text, None])

    def ended(self, now: float) -> None:
        for r in self.recent:
            if r[1] is None:
                r[1] = now

    def heard(self, text: str, now: float) -> None:
        """Speech from the other agent: already finished when we learn of it."""
        self.recent.append([text, now])

    def is_echo(self, transcript: str, now: float) -> bool:
        self.recent = [r for r in self.recent if r[1] is None or now - r[1] <= self.window_s]
        words = _tokens(transcript)
        if len(words) < MIN_TOKENS:
            return False
        pool = {w for r in self.recent for w in _tokens(r[0])}
        return sum(w in pool for w in words) / len(words) >= self.overlap
