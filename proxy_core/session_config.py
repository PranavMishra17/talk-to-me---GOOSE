"""Pure: cfg['turn'] -> kwargs for livekit TurnHandlingOptions. No livekit import."""


def turn_kwargs(cfg: dict) -> dict:
    t = cfg["turn"]
    det = t["turn_detection"]
    if det not in ("audio", "stt", "vad"):
        raise ValueError(f"bad turn_detection {det!r}")
    ep = t["endpointing"]
    return {
        "turn_detection": det,
        "endpointing": {
            "mode": "dynamic",
            "min_delay": 0 if det == "stt" else ep["min_delay"],  # Flux owns endpointing
            "max_delay": ep["max_delay"],
        },
        "interruption": {**t["interruption"], "mode": "adaptive"},
        "preemptive_generation": {**t["preemptive_generation"], "preemptive_tts": False},
        "user_turn_limit": {**t["user_turn_limit"], "max_duration": 30},
    }
