import pytest

from proxy_core.session_config import turn_kwargs


def cfg(det="audio"):
    return {"turn": {
        "turn_detection": det,
        "endpointing": {"mode": "static", "min_delay": 0.3, "max_delay": 3.0},
        "interruption": {"mode": "vad", "min_duration": 0.5},
        "preemptive_generation": {"enabled": True, "preemptive_tts": True},
        "user_turn_limit": {"max_duration": 99},
    }}


def test_rules_audio():
    k = turn_kwargs(cfg())
    assert k["turn_detection"] == "audio"
    assert k["endpointing"] == {"mode": "dynamic", "min_delay": 0.3, "max_delay": 3.0}
    assert k["interruption"]["mode"] == "adaptive" and k["interruption"]["min_duration"] == 0.5
    assert k["preemptive_generation"] == {"enabled": True, "preemptive_tts": False}
    assert k["user_turn_limit"]["max_duration"] == 30


def test_stt_zeroes_min_delay():
    assert turn_kwargs(cfg("stt"))["endpointing"]["min_delay"] == 0


def test_bad_mode():
    with pytest.raises(ValueError):
        turn_kwargs(cfg("x"))


def test_own_keys_is_off_and_one_line_moves_all_three(tmp_path):
    from proxy_core.config import ROOT, load_config
    p = load_config()["providers"]
    assert not p["own_keys"] and {p[k]["kind"] for k in ("stt", "llm", "tts")} == {"livekit_inference"}
    on = tmp_path / "config.yaml"
    on.write_text((ROOT / "config.yaml").read_text(encoding="utf-8").replace("own_keys: false", "own_keys: true"), encoding="utf-8")
    p = load_config(on)["providers"]
    assert [p[k]["kind"] for k in ("stt", "llm", "tts")] == ["cartesia", "openrouter", "cartesia"]
