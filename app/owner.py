"""Owner session: Pranav talks to Goose. A separate agent, so none of this runs on a caller's phone call.
Dispatch metadata {"mode": "owner"} selects it for the web app; a SIP dispatch carries no metadata. A number marked
relationship owner in the contact book gets it on the phone too, with the tier capped: caller ID can be spoofed.
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from livekit.agents import Agent, function_tool

from app.tools import DataTools
from proxy_core import calls, vault
from proxy_core.personality import load_pack, render_style

logger = logging.getLogger("goose")
BRIEF_TRIES, BRIEF_WAIT_S = 3, 5
PROMPT = (Path(__file__).parent / "prompts" / "owner.txt").read_text(encoding="utf-8")


class OwnerAgent(DataTools, Agent):
    def __init__(self, persona, owner, pack_name, number="", tier="private"):
        self.persona, self.owner, self.pack_name, self.number, self.caller_tier = persona, owner, pack_name, number, tier
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        today = f"{datetime.now():%A} {datetime.now().day} {datetime.now():%B %Y}"
        super().__init__(instructions=PROMPT.format(assistant=persona.title(), owner=owner.title(), today=today, style=render_style(load_pack(pack_name), "own")))

    async def on_enter(self):
        asyncio.ensure_future(self._brief())

    async def _brief(self):
        """Two real sessions never greeted, with no error logged and the cause unknown, so a stalled briefing is retried."""
        line = calls.brief(calls.list_calls(), self.owner.title())
        for attempt in range(BRIEF_TRIES):
            speech = self.session.say(line)
            for _ in range(int(BRIEF_WAIT_S * 10)):
                if self.session.agent_state == "speaking" or speech.done():
                    return
                await asyncio.sleep(0.1)
            logger.warning("owner briefing stalled, attempt %d", attempt + 1)
            speech.interrupt(force=True)

    def call_record(self, call_id, turns):
        return {"id": call_id, "started_at": self.started_at, "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "kind": "owner", "number": self.number, "contact": None, "persona": self.persona, "pack": self.pack_name,
                "summary": f"{self.owner.title()} talked to {self.persona.title()}.", "outcome": "info", "actions": [], "transcript": turns}

    @function_tool
    async def add_calendar_event(self, title: str, start: str, end: str = "", where: str = "") -> str:
        """Add an entry to the owner's diary. start and end are ISO, like 2026-11-07T19:00:00. end defaults to an hour later."""
        try:
            return f"Added {vault.add_event(title, start, end, where)['title']}."
        except ValueError:
            return "That needs a full date and time."

    @function_tool
    async def update_calendar_event(self, event: str, title: str = "", start: str = "", end: str = "", where: str = "") -> str:
        """Change a diary entry. event is words from its title; leave a field empty to keep it. start and end are ISO."""
        try:
            found = vault.update_event(event, self.caller_tier, title=title, start=start, end=end, where=where)
        except ValueError:
            return "That needs a full date and time."
        if isinstance(found, dict):
            return f"Updated {found['title']}."
        return f"Which one: {', '.join(found)}?" if found else "No entry like that."

    @function_tool
    async def add_task(self, text: str, due: str = "") -> str:
        """Add a task for the owner. due is YYYY-MM-DD, or empty for today."""
        return f"Added {vault.add_task(text, due)['text']}."

    @function_tool
    async def list_calls(self) -> str:
        """Every call, newest first: id, who, what happened, what is still open."""
        return json.dumps([{"id": c["id"], "who": (c["contact"] or {}).get("name", "unknown caller"), "summary": calls.to_owner(c["summary"], self.owner.title()),
                            "outcome": c["outcome"], "open": [a["text"] for a in c["actions"] if not a["done"]]}
                           for c in calls.list_calls() if c["kind"] == "phone"], ensure_ascii=False)

    @function_tool
    async def get_call(self, call_id: str) -> str:
        """One call with its transcript. call_id comes from list_calls."""
        return json.dumps(calls.get_call(call_id) or "No such call.", ensure_ascii=False)

    @function_tool
    async def mark_done(self, call_id: str) -> str:
        """Close the open actions on one call. call_id comes from list_calls."""
        return "Marked done." if calls.mark_done(call_id) else "No such call."
