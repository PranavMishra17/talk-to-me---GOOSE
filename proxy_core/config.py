"""config.yaml loader + validation, and .env loading. No livekit imports."""
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
# Allowed `kind` per provider; `mock` is valid everywhere so tests need zero network.
KINDS = {
    "stt": {"livekit_inference", "deepgram_flux", "cartesia", "mock"},
    "llm": {"livekit_inference", "openrouter", "realtime", "mock"},   # realtime skips STT/TTS (branch kept, unused)
    "tts": {"livekit_inference", "cartesia", "mock"},
    "vad": {"livekit_inference", "mock"},
    "noise_cancellation": {"none", "bvc_telephony", "mock"},
}
REQUIRED = {
    "turn": ["turn_detection", "endpointing", "interruption", "preemptive_generation", "user_turn_limit"],
    "limits": ["max_turns_per_item", "max_turns_per_call", "max_summons", "floor_lease_s"],
    "session": ["silence_nudges_s", "backchannel_allowlist"],
    "decider": ["backend"],
}


def agent_name(persona: str) -> str:
    """Dispatch name. GOOSE_AGENT_TAG keeps a test run off workers other sessions registered on this project."""
    return persona + os.environ.get("GOOSE_AGENT_TAG", "")


def load_env() -> None:
    """Load ROOT/.env into os.environ. Values are never printed or logged."""
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("GOOSE_ENV") or ROOT / ".env")   # worktrees point at the one real .env


def load_config(path: str | Path = ROOT / "config.yaml") -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    """Fail at startup, not mid-call."""
    for name, allowed in KINDS.items():
        kind = cfg.get("providers", {}).get(name, {}).get("kind")
        if kind not in allowed:
            raise ValueError(f"providers.{name}.kind={kind!r} unknown; allowed: {sorted(allowed)}")
    for section, keys in REQUIRED.items():
        for k in keys:
            if k not in cfg.get(section, {}):
                raise ValueError(f"config missing {section}.{k}")
    if cfg["turn"]["turn_detection"] not in {"audio", "stt", "vad"}:
        raise ValueError("turn.turn_detection must be audio|stt|vad")
    if cfg["decider"]["backend"] not in {"jev", "keyword", "llm", "mock", "laya_local"}:
        raise ValueError("decider.backend must be jev|keyword|llm|mock|laya_local")
    if not cfg.get("personas"):
        raise ValueError("config missing personas")
