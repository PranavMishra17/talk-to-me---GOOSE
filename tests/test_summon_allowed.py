"""The room's opener decides who may join: an assistant outside `allowed` never gets a dispatch."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from app.agent import GooseAgent
from proxy_core.config import load_config


async def summon(metadata: str):
    agent = GooseAgent("goose", cfg=load_config())
    agent.room, agent.floor = SimpleNamespace(name="goose-test", isconnected=lambda: False), MagicMock(take=AsyncMock())
    job = SimpleNamespace(job=SimpleNamespace(metadata=metadata), api=MagicMock())
    job.api.agent_dispatch.create_dispatch = AsyncMock()
    session = MagicMock()
    session.room_io.linked_participant = None
    with patch("app.agent.get_job_context", return_value=job), patch.object(GooseAgent, "session", new_callable=PropertyMock, return_value=session):
        reply = await agent._summon("rohan", "Is he free?")
    return reply, job.api.agent_dispatch.create_dispatch


async def test_outside_allowed_is_refused():
    reply, dispatch = await summon(json.dumps({"allowed": []}))
    assert "not allowed" in reply and not dispatch.called


async def test_inside_allowed_and_phone_calls_dispatch():
    for metadata in (json.dumps({"allowed": ["maya"]}), ""):
        _, dispatch = await summon(metadata)
        assert dispatch.called
