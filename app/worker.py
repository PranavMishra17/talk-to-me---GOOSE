"""LiveKit-touching: REWRITE against the starter kit tomorrow (copy the two entrypoints' bodies).

Named agents ash/maya, explicit dispatch only. Commands:
  uv run python -m app.worker console          # talk to Ash in the terminal (spends credits; Ctrl+C when done)
  uv run python -m app.worker dev              # register Ash with LiveKit Cloud (phone + dispatch)
  GOOSE_PERSONA=maya uv run python -m app.worker dev   # second terminal: Maya (PowerShell: $env:GOOSE_PERSONA='maya'; uv run ...)
"""
import asyncio
import json
import logging
import os
import time

from livekit import rtc
from livekit.agents import AgentServer, JobContext, cli, room_io

from app.agent import GooseAgent
from app.providers import build_session
from proxy_core.config import load_config, load_env
from proxy_core.personality import load_pack

load_env()
logger = logging.getLogger("goose")
server = AgentServer()


def _noise(cfg):
    if cfg["providers"]["noise_cancellation"]["kind"] != "bvc_telephony":
        return None
    from livekit.plugins import noise_cancellation   # Cloud only: install with `uv sync --extra nc`
    return lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else None


async def _run(ctx: JobContext, persona: str):
    cfg = load_config()
    meta = json.loads(ctx.job.metadata or "{}")            # job metadata is a string; carries task + caller
    pack = load_pack(cfg["personas"][persona]["pack"])
    voice = pack["fish_voice"] if cfg["providers"]["tts"]["model"].startswith("fishaudio/") else pack["voice"]
    voice = None if voice == "TODO" else voice              # TODO voice ids: set in personalities/*.yaml
    session = build_session(persona, cfg, voice)
    # S1-05: every module's timing as METRIC json; proxy_core/latency.py turns these into one row per turn.
    def metric(d):
        logger.info("METRIC %s", json.dumps(d, default=str))
    session.on("metrics_collected", lambda ev: metric(ev.metrics.model_dump(exclude={"metadata"})))
    session.on("function_tools_executed", lambda ev: metric({"type": "tools_done", "ts": time.time()}))
    session.on("conversation_item_added", lambda ev: getattr(ev.item, "role", "") == "assistant" and metric(
        {"type": "assistant_turn", **(getattr(ev.item, "metrics", None) or {})}))
    agent = GooseAgent(persona, caller=meta.get("caller", ""), task=meta.get("task", "Take a message and coordinate."),
                       cfg=cfg, lead=meta.get("lead"))
    agent.room = ctx.room
    session.on("user_input_transcribed", lambda ev: ev.is_final and agent.on_stt_final(ev.transcript))
    session.on("agent_state_changed", lambda ev: ev.old_state == "speaking" and agent.echo.ended(time.time()))
    session.on("user_state_changed", lambda ev: agent.on_user_state(ev.new_state))
    session.on("close", lambda ev: agent.record())
    session.on("conversation_item_added", lambda ev: agent.publish())
    session.on("function_tools_executed", lambda ev: agent.publish())

    def caller_id(p):   # S8-06: the tier comes from the number the phone network gave us
        number = p.attributes.get("sip.phoneNumber")
        if number:
            asyncio.ensure_future(agent.set_caller(number))
    ctx.room.on("participant_connected", caller_id)

    await session.start(room=ctx.room, agent=agent, room_options=room_io.RoomOptions(
        participant_kinds=[rtc.ParticipantKind.PARTICIPANT_KIND_SIP, rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                           rtc.ParticipantKind.PARTICIPANT_KIND_AGENT],   # AGENT so the other agent's speech is visible
        audio_input=room_io.AudioInputOptions(noise_cancellation=_noise(cfg))))
    for p in ctx.room.remote_participants.values():
        caller_id(p)
    agent.publish()


# livekit-agents 1.8.11: ONE rtc_session per AgentServer, so ash and maya are two worker processes.
# The persona comes from GOOSE_PERSONA (default ash); the dispatch agent_name equals the persona.
PERSONA = os.environ.get("GOOSE_PERSONA", "ash")


@server.rtc_session(agent_name=PERSONA)
async def entry(ctx: JobContext):
    await _run(ctx, PERSONA)


if __name__ == "__main__":
    cli.run_app(server)
