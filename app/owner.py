"""Owner session: Pranav talks to Goose from the web app. A separate agent, so nothing here runs on a phone call.
Dispatch metadata {"mode": "owner"} selects it, and a SIP dispatch carries no metadata, so a caller cannot reach it.
"""
import json
from pathlib import Path

from livekit.agents import Agent, function_tool

from app.tools import DataTools
from proxy_core import calls
from proxy_core.personality import render_style

PROMPT = (Path(__file__).parent / "prompts" / "owner.txt").read_text(encoding="utf-8")


class OwnerAgent(DataTools, Agent):
    def __init__(self, persona, owner, pack):
        self.persona, self.owner, self.caller_tier = persona, owner, "private"
        self.log: list[str] = []
        super().__init__(instructions=PROMPT.format(assistant=persona.title(), owner=owner.title(), style=render_style(pack)))

    async def on_enter(self):
        self.session.say(calls.brief(calls.list_calls(), self.owner.title()))

    @function_tool
    async def list_calls(self) -> str:
        """Every call, newest first: id, who, what happened, what is still open."""
        return json.dumps([{"id": c["id"], "who": (c["contact"] or {}).get("name", "unknown caller"), "summary": c["summary"],
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
