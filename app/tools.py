"""Read-only data tools, shared by the phone agent and the owner session. The tier comes from code, never the model."""
import json

from livekit.agents import function_tool

from proxy_core import vault


class DataTools:
    """The host class sets self.owner and self.caller_tier. Another owner's assistant reads nothing."""

    def _rows(self, read, *args) -> str:
        home = vault.owner_dir(self.owner)
        if home is None:
            return "Nothing found."
        rows = read(*args, self.caller_tier, home)
        return json.dumps(rows, ensure_ascii=False) if rows else "Nothing found."

    @function_tool
    async def get_profile(self) -> str:
        """About the owner: role, work, preferences, routines, as far as this caller may hear."""
        return self._rows(vault.get_profile)

    @function_tool
    async def search_email(self, query: str) -> str:
        """Search the owner's email for what this caller may hear. Query is a few keywords."""
        return self._rows(vault.search_email, query)

    @function_tool
    async def search_slack(self, query: str) -> str:
        """Search the owner's Slack for what this caller may hear. Query is a few keywords."""
        return self._rows(vault.search_slack, query)

    @function_tool
    async def get_calendar(self) -> str:
        """The owner's diary, as much of it as this caller may see. A busy entry has no details to give."""
        return self._rows(vault.get_calendar)

    @function_tool
    async def search_notes(self, query: str) -> str:
        """Search the owner's notes and tasks for what this caller may hear. Query is a few keywords."""
        return self._rows(vault.search_notes, query)
