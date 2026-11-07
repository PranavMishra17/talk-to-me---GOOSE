"""Owner session: Pranav talks to Goose. A separate agent, so none of this runs on a caller's phone call.
Dispatch metadata {"mode": "owner"} selects it for the web app; a SIP dispatch carries no metadata. A number marked
relationship owner in the contact book gets it on the phone too, with the tier capped: caller ID can be spoofed.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from livekit.agents import Agent, function_tool

from app.tools import DataTools
from proxy_core import calls, vault
from proxy_core.personality import load_pack, owner_hello, render_style

logger = logging.getLogger("goose")
BRIEF_TRIES, BRIEF_WAIT_S = 3, 5
PROMPT = (Path(__file__).parent / "prompts" / "owner.txt").read_text(encoding="utf-8")


class OwnerAgent(DataTools, Agent):
    def __init__(self, persona, owner, pack_name, number="", tier="private"):
        self.persona, self.owner, self.pack_name, self.number, self.caller_tier = persona, owner, pack_name, number, tier
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self._last_event = ""
        records = calls.list_calls(self.owner)
        self._offer, self._brief = calls.offer(records), calls.brief(records, owner.title())
        now = datetime.now()
        today = f"{now:%A} {now.date()}, so tomorrow is {now.date() + timedelta(days=1)}"
        super().__init__(instructions=PROMPT.format(assistant=persona.title(), owner=owner.title(), today=today, style=render_style(load_pack(pack_name), "own")))

    async def on_enter(self):
        asyncio.ensure_future(self._hello())

    async def _hello(self):
        """Code opens, with a person's hello and no calls. Two real sessions never greeted, so a stall is retried."""
        line = owner_hello(load_pack(self.pack_name), self.persona.title(), self.owner.title())
        for attempt in range(BRIEF_TRIES):
            speech = self.session.say(line)
            for _ in range(int(BRIEF_WAIT_S * 10)):
                if self.session.agent_state == "speaking" or speech.done():
                    return
                await asyncio.sleep(0.1)
            logger.warning("owner hello stalled, attempt %d", attempt + 1)
            speech.interrupt(force=True)

    def _next_step(self, turns):
        """The update comes after the hello is answered, in words code wrote from the records, so the model cannot invent one."""
        if turns == 1:
            return (f'They just answered your hello. Say a few warm words back, then say: "{self._offer}" '
                    f'If they already asked what they need to do or who called, skip that and say this, word for word: "{self._brief}"')
        if turns == 2:
            return f'If they want the rundown, say this, word for word: "{self._brief}" If they asked something else, answer that.'

    async def llm_node(self, chat_ctx, tools, model_settings):
        """Counted from the conversation, not a flag: preemptive generation can run a turn twice."""
        if note := self._next_step(sum(getattr(i, "role", "") == "user" for i in chat_ctx.items)):
            chat_ctx = chat_ctx.copy()
            chat_ctx.add_message(role="system", content=note)
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk

    def call_record(self, call_id, turns):
        return {"id": call_id, "started_at": self.started_at, "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "kind": "owner", "number": self.number, "contact": None, "persona": self.persona, "pack": self.pack_name,
                "summary": f"{self.owner.title()} talked to {self.persona.title()}.", "outcome": "info", "actions": [], "transcript": turns}

    @function_tool
    async def add_calendar_event(self, title: str, start: str, end: str = "", where: str = "") -> str:
        """Add an entry to the owner's diary. start and end are ISO, like 2026-11-07T19:00:00. end defaults to an hour later."""
        try:
            event = vault.add_event(title, start, end, where)
        except ValueError:
            return "That needs a full date and time."
        self._last_event = event["id"]
        return f"Added {vault.event_text(event)}."

    @function_tool
    async def update_calendar_event(self, event: str, title: str = "", start: str = "", end: str = "", where: str = "") -> str:
        """Change a diary entry. event is words from its title, or empty for the entry just added or changed. Leave a field empty to keep it. start and end are ISO."""
        try:
            found = vault.update_event(event, self.caller_tier, last=self._last_event, title=title, start=start, end=end, where=where)
        except ValueError:
            return "That needs a full date and time."
        if isinstance(found, dict):
            self._last_event = found["id"]
            return f"Updated {vault.event_text(found)}."
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
                           for c in calls.list_calls(self.owner) if c["kind"] == "phone"], ensure_ascii=False)

    @function_tool
    async def get_call(self, call_id: str) -> str:
        """One call with its transcript. call_id comes from list_calls."""
        return json.dumps(calls.get_call(call_id) or "No such call.", ensure_ascii=False)

    @function_tool
    async def mark_done(self, call_id: str) -> str:
        """Close the open actions on one call. call_id comes from list_calls."""
        return "Marked done." if calls.mark_done(call_id) else "No such call."
