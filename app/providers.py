"""LiveKit-touching: REWRITE against the starter kit tomorrow (starter's own session factory wins).

build_session(persona) maps config `kind` -> plugin constructors. `mock` kinds return None so a
session can run text-only with the test LLM. Nothing here calls a network API at build time.
"""
import os

from livekit.agents import APIConnectOptions, AgentSession, TurnHandlingOptions, inference
from livekit.plugins import cartesia, openai
from livekit.agents.voice.agent_session import SessionConnectOptions

from proxy_core import vault
from proxy_core.config import load_config, load_env
from proxy_core.session_config import turn_kwargs

NOT_SET = object()
PLACES = {"Bungalow", "Goose", "Neptune Oyster", "Northwind", "Logan", "Central Rock Gym", "The Bristol"}
# The SDK default gives up after about 4 s, and a 429 from Inference then closes the session before any audio.
# A late greeting beats a dead call: this rides out about 20 s. A healthy call never reaches it.
_RETRY = APIConnectOptions(max_retry=10, retry_interval=2.0)


def _keyterms():
    """Names a call depends on. Deepgram takes up to 100 terms; Nova-3 heard Bungalow as Bangalore without this."""
    names = {w for c in vault.contacts() for w in c["name"].split()}
    return sorted(PLACES | names)[:100]


def _stt(c, cfg):
    if c["kind"] == "mock":
        return None
    if c["kind"] == "cartesia":     # own key: works when LiveKit's Inference gateway answers 429
        return cartesia.STT(model=c["model"], language=c.get("language", "en"))
    # deepgram_flux is the same Inference class with the flux model id.
    model = "deepgram/flux-general-en" if c["kind"] == "deepgram_flux" else c["model"]
    extra = dict(c["flux"]) if "flux" in model and c.get("flux") else {}
    if model.startswith("deepgram/") and os.environ.get("GOOSE_KEYTERMS") != "0":   # the off switch: not yet tried on a live call
        extra["keyterm"] = _keyterms()
    return inference.STT(model=model, language=c.get("language", "en"), **({"extra_kwargs": extra} if extra else {}))


def _llm(c, cfg):
    if c["kind"] == "mock":
        return None  # tests pass their own llm to AgentSession
    # TODO: kind "realtime" (skip STT/TTS) -- best guess: livekit.plugins.openai.realtime.RealtimeModel; not installed, unused.
    if c["kind"] == "realtime":
        raise NotImplementedError("realtime branch is a stub; install the plugin and wire it here")
    if c["kind"] == "openrouter":   # our own key: runs when LiveKit's Inference credit is gone. Strict schemas are OpenAI-only.
        return openai.LLM(model=c["model"], base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"],
                          _strict_tool_schema=False)
    kw = {"reasoning": c["reasoning"]} if c.get("reasoning") else {}   # low-latency: skip model thinking
    return inference.LLM(model=c["model"], **kw)


def _tts(c, cfg, voice=None):
    if c["kind"] == "mock":
        return None
    kw = {"voice": voice} if voice else {}
    if c["kind"] == "cartesia":     # the packs' voice ids are Cartesia's, so Goose and Maya keep their voices
        return cartesia.TTS(model=c["model"], language=c.get("language", "en"), **kw)
    return inference.TTS(model=c["model"], language=c.get("language", "en"), **kw)


def _vad(c, cfg):
    return None if c["kind"] == "mock" else inference.VAD(model=c["model"])


def turn_handling(cfg):
    kw = turn_kwargs(cfg)
    if kw["turn_detection"] == "audio":
        kw["turn_detection"] = inference.TurnDetector()
    return TurnHandlingOptions(**kw)


def build_session(persona_name: str, cfg: dict | None = None, voice: str | None = None) -> AgentSession:
    load_env()
    cfg = cfg or load_config()
    if persona_name not in cfg["personas"]:
        raise ValueError(f"unknown persona {persona_name!r}")
    p = cfg["providers"]
    return AgentSession(
        stt=_stt(p["stt"], cfg),
        llm=_llm(p["llm"], cfg),
        tts=_tts(p["tts"], cfg, voice),
        vad=_vad(p["vad"], cfg),
        turn_handling=turn_handling(cfg),
        expressive=p["tts"].get("expressive", False),
        user_away_timeout=cfg["session"]["silence_nudges_s"][0],
        conn_options=SessionConnectOptions(stt_conn_options=_RETRY, llm_conn_options=_RETRY, tts_conn_options=_RETRY),
    )
