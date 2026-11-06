"""LiveKit-touching: REWRITE against the starter kit tomorrow (starter's own session factory wins).

build_session(persona) maps config `kind` -> plugin constructors. `mock` kinds return None so a
session can run text-only with the test LLM. Nothing here calls a network API at build time.
"""
from livekit.agents import AgentSession, TurnHandlingOptions, inference

from proxy_core.config import load_config, load_env
from proxy_core.session_config import turn_kwargs

NOT_SET = object()


def _stt(c, cfg):
    if c["kind"] == "mock":
        return None
    # deepgram_flux is the same Inference class with the flux model id.
    model = "deepgram/flux-general-en" if c["kind"] == "deepgram_flux" else c["model"]
    kw = {"extra_kwargs": c["flux"]} if "flux" in model and c.get("flux") else {}
    return inference.STT(model=model, language=c.get("language", "en"), **kw)


def _llm(c, cfg):
    if c["kind"] == "mock":
        return None  # tests pass their own llm to AgentSession
    # TODO: kind "realtime" (skip STT/TTS) -- best guess: livekit.plugins.openai.realtime.RealtimeModel; not installed, unused.
    if c["kind"] == "realtime":
        raise NotImplementedError("realtime branch is a stub; install the plugin and wire it here")
    kw = {"reasoning": c["reasoning"]} if c.get("reasoning") else {}   # low-latency: skip model thinking
    return inference.LLM(model=c["model"], **kw)


def _tts(c, cfg, voice=None):
    if c["kind"] == "mock":
        return None
    kw = {"voice": voice} if voice else {}
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
    )
