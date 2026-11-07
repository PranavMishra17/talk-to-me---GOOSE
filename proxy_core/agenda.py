"""Dynamic agenda: items close in ANY order as slots fill; turn limits are enforced in code."""
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# Judges' rubric: these never fire on the model's say-so. The caller must say yes first.
CONFIRM_TOOLS = {"take_message", "propose_slot", "summon_agent", "request_permission_from_owner", "end_call"}
_YES = re.compile(r"\b(yes|yeah|yep|yup|sure|ok|okay|please do|go ahead|do it|sounds good|correct|that's right|perfect|absolutely)\b", re.I)
_NO = re.compile(r"\b(no(?! (?:problem|worries))|nope|not|don't|wait|hold on|never mind|nevermind|cancel)\b", re.I)
_CHANGE = re.compile(r"\b(but|actually|instead|change)\b", re.I)
_CLAIM = re.compile(r"\b(i.ll|i will|i.ve|i have|let (him|her|them)|pass\w*|radio\w*|sav\w+|note\w*|message|want me|should i|shall i|done|sent)\b", re.I)
_ACTED = (r"added|saved|sent|passed|told|asked|booked|logged|left|recorded|forwarded|scheduled|updated|put|radioed|let (?:him|her|them)",
          r"add|save|send|pass|tell|let (?:him|her|them)|book|log|leave|forward|schedule|update|put|radio|get (?:that|it)")
_FIRED = re.compile(rf"\b(?:i.ve|i have|i just|already)\s+(?:\w+\s+)?(?:{_ACTED[0]})\b|\b(?:i.ll|i will|i shall)\s+(?:\w+\s+)?(?:{_ACTED[1]})\b"
                    rf"|\b(?:been|is|was)\s+(?:{_ACTED[0]})\b|\bgot that down\b|\bleave it with me\b", re.I)
_OFFER = re.compile(r"\b(want me|shall i|should i|would you like|do you want|can i)\b", re.I)
_REQUEST = re.compile(r"\b(tell|let (?:him|her|them)|pass|also|add|ask|book|remind|one more thing|leave|send)\b", re.I)
_CHECKING = re.compile(r"^\W*(did|have|has|was|is)\b", re.I)
_BYE = re.compile(r"\b(goodbye|good bye|bye)\b|that'?s all", re.I)


def is_offer(said: str) -> bool:
    """The agent asked in words whether to act, so a yes to this line is the yes the gate wants."""
    return bool(_OFFER.search(said))


def check_claim(reply: str, caller_text: str, pending: bool, acted: bool) -> str:
    """What to do with a reply on a turn where no action fired. keep | confirm (the action waits on a yes, so say that) |
    fire (the caller said yes to a spoken offer, so make the claim true) | ask (nothing is queued: queue it, ask for the yes)."""
    if not _FIRED.search(reply) or is_offer(reply):
        return "keep"
    if pending:
        return "confirm"
    if is_yes(caller_text):
        return "fire"
    if acted and (not _REQUEST.search(caller_text) or _CHECKING.search(caller_text)):
        return "keep"                # "thanks" after a real save: the claim is true
    return "ask"


def is_no(text: str) -> bool:
    return bool(_NO.search(text))


def is_yes(text: str) -> bool:
    return bool(_YES.search(text)) and not is_no(text) and not _CHANGE.search(text)


def claims_action(text: str) -> bool:
    """Words that announce or ask about an action. On a gated turn only code may say those."""
    return bool(_CLAIM.search(text))


def is_bye(text: str) -> bool:
    """A caller saying goodbye has already given the yes that end_call needs."""
    return bool(_BYE.search(text))


@dataclass
class AgendaItem:
    id: str
    goal: str
    needs: list[str] = field(default_factory=list)
    done_when: Optional[Callable[[dict], bool]] = None  # default: every `needs` slot is filled
    max_turns: int = 2      # two asks, then code moves on
    owner_agent: str = ""
    turns_used: int = 0
    done: bool = False

    def satisfied(self, slots: dict) -> bool:
        if self.done_when:
            return bool(self.done_when(slots))
        return bool(self.needs) and all(slots.get(n) not in (None, "") for n in self.needs)

def mock_planner(task_text: str) -> list[AgendaItem]:
    # Deterministic stand-in for the future LLM planner (same signature: str -> items).
    return [
        AgendaItem("identify", "Learn who is calling", ["name"]),
        AgendaItem("learn_ask", f"Understand the ask: {task_text}", ["topic", "details"]),
        AgendaItem("read_back", "Check the gist in a few words and get a yes", ["name", "details", "day", "time", "confirmed"],
                   done_when=lambda s: s.get("confirmed") is True),
        AgendaItem("close", "Wrap up and say goodbye", ["goodbye"]),
    ]

def summoned_planner(request: str) -> list[AgendaItem]:
    """A summoned agent gets a request, not the caller's agenda: check the tier, then answer or decline."""
    return [AgendaItem("check_tier", "Know the caller's tier", ["tier"]),
            AgendaItem("answer", f"Answer or decline: {request}", ["answered"])]


class Agenda:
    def __init__(self, max_turns_per_call: int = 40):
        self.items: list[AgendaItem] = []
        self.slots: dict = {}
        self.total_turns, self.max_turns_per_call = 0, max_turns_per_call
        self.pending: dict[str, dict] = {}  # tool -> args waiting for the caller's yes; a corrected call replaces its own entry

    def ask(self, tool: str, args: dict) -> None:
        self.pending[tool] = args

    def resolve(self, caller_text: str) -> list[tuple[str, dict]]:
        """The caller's answer to what is pending. Returns it once on yes; a no drops it; anything else waits."""
        if self.pending and is_yes(caller_text):
            actions, self.pending = list(self.pending.items()), {}
            return actions
        if is_no(caller_text):
            self.pending = {}
        return []

    def plan(self, task_text: str, planner: Callable[[str], list[AgendaItem]] = None) -> list[AgendaItem]:
        self.items = (planner or mock_planner)(task_text)
        return self.items

    def add_ask(self, text: str) -> None:
        """A new request mid-call, worked before the read-back. Closes by its slot or by the turn limit, one at a time."""
        if (f := self.focus()) and f.id.startswith("ask_"):
            return
        id = f"ask_{sum(i.id.startswith('ask_') for i in self.items) + 1}"
        at = next((n for n, i in enumerate(self.items) if i.id == "read_back"), len(self.items))
        self.items.insert(at, AgendaItem(id, f"New request: {text}", [id]))

    def update_slots(self, extraction: dict) -> None:
        # A changed value for a filled slot = contradiction: reopen its dependents. They skip this
        # pass's close check so the agent re-confirms. ponytail: no "reconfirmed" flag.
        reopened = set()
        for k, v in extraction.items():
            if k in self.slots and self.slots[k] != v:
                for it in (i for i in self.items if k in i.needs and i.done):
                    it.done, it.turns_used = False, 0
                    reopened.add(it.id)
                    if "confirmed" in it.needs:   # the old yes was for the old value
                        self.slots.pop("confirmed", None)
            self.slots[k] = v
        self.mark_done(skip=reopened)

    def mark_done(self, skip=()) -> None:
        for it in self.items:
            it.done = it.done or (it.id not in skip and it.satisfied(self.slots))

    def focus(self) -> Optional[AgendaItem]:
        return next((i for i in self.items if not i.done), None)

    def tick(self) -> None:  # one user turn, against the call and the focus item
        self.total_turns += 1
        if f := self.focus(): f.turns_used += 1

    def exhausted(self, item: Optional[AgendaItem] = None) -> bool:
        used, cap = (item.turns_used, item.max_turns) if item else (self.total_turns, self.max_turns_per_call)
        return used >= cap

    def should_force_advance(self) -> bool:
        return bool((f := self.focus()) and self.exhausted(f))

    def force_advance(self) -> None:  # code, not the model, abandons the focus item
        if f := self.focus(): f.done = True

    def render_prompt_block(self) -> str:
        lines = ["AGENDA (items may finish in any order; steer toward the focus item):"]
        lines += [f"{'[x]' if i.done else '[>] FOCUS' if i is self.focus() else '[ ]'} {i.id}: {i.goal}" for i in self.items]
        lines.append("Known so far: " + (", ".join(f"{k}={v}" for k, v in self.slots.items()) or "none yet"))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        # done_when callables don't serialise; restored items fall back to the `needs` rule.
        items = [{k: v for k, v in vars(i).items() if k != "done_when"} for i in self.items]
        return {"items": items, "slots": self.slots, "total_turns": self.total_turns,
                "max_turns_per_call": self.max_turns_per_call}

    @classmethod
    def from_dict(cls, d: dict) -> "Agenda":
        a = cls(d["max_turns_per_call"])
        a.items, a.slots, a.total_turns = [AgendaItem(**i) for i in d["items"]], dict(d["slots"]), d["total_turns"]
        return a
