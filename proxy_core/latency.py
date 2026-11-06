"""Per-module latency: turns the worker's METRIC lines into one row per caller turn. No livekit imports.
Worker logs: METRIC {json}. Run on a log: python -m proxy_core.latency .harness/worker.log
"""
import json, sys

COLS = ["vad_infer_ms", "stt_ms", "eot_model_ms", "endpoint_wait_ms", "hook_ms", "llm_ttft_ms", "llm_total_ms",
        "tool_plus_filler_ms", "tts_ttfb_ms", "tts_total_ms", "e2e_ms"]


def _ms(v):
    return round(v * 1000)


def parse(text: str) -> list[dict]:
    return [json.loads(line.split("METRIC ", 1)[1].split("\x1b")[0]) for line in text.splitlines() if "METRIC {" in line]


def turns(events: list[dict]) -> list[dict]:
    """One row per caller turn, in ms. The eou_metrics event opens a turn; a greeting comes before any and is row 0.
    llm_ttft_ms and tts_ttfb_ms are lists: a tool call means a second generation.
    tool_plus_filler_ms runs from the end of the LLM call to tools done, so it includes the filler line playing."""
    def new():
        return {"llm_ttft_ms": [], "llm_total_ms": [], "tool_plus_filler_ms": [], "tts_ttfb_ms": [], "tts_total_ms": []}

    # Preemptive generation runs before the turn commits, so file LLM and TTS by speech_id, not by arrival order.
    eous = [e for e in events if e.get("type") == "eou_metrics"]
    row_of = {e["speech_id"]: i + 1 for i, e in enumerate(eous) if e.get("speech_id")}
    rows = [new() for _ in range(len(eous) + 1)]
    n, vad, eot, last_llm_end = 0, [], [], None
    for e in events:
        t = e.get("type")
        if t == "vad_metrics" and e["inference_count"]:
            vad.append(e["inference_duration_total"] / e["inference_count"])
        elif t == "eot_inference_metrics":
            eot.append(e["prediction_duration"])
        elif t == "eou_metrics":
            n += 1
            cur = rows[n]
            cur.update(stt_ms=_ms(e["transcription_delay"]), endpoint_wait_ms=_ms(e["end_of_utterance_delay"]),
                       hook_ms=_ms(e["on_user_turn_completed_delay"]))
            if eot:
                cur["eot_model_ms"] = _ms(sum(eot) / len(eot))
            if vad:
                cur["vad_infer_ms"] = round(sum(vad) / len(vad) * 1000, 1)
            vad, eot = [], []
        elif t == "llm_metrics":
            r = rows[row_of.get(e.get("speech_id"), n)]
            r["llm_ttft_ms"].append(_ms(e["ttft"]))
            r["llm_total_ms"].append(_ms(e["duration"]))
            last_llm_end = e["timestamp"]
        elif t == "tts_metrics":
            r = rows[row_of.get(e.get("speech_id"), n)]
            r["tts_ttfb_ms"].append(_ms(e["ttfb"]))
            r["tts_total_ms"].append(_ms(e["duration"]))
        elif t == "tools_done":
            rows[n]["tool_plus_filler_ms"].append(_ms(e["ts"] - last_llm_end) if last_llm_end else None)
        elif t == "assistant_turn" and e.get("e2e_latency") is not None:
            rows[n]["e2e_ms"] = _ms(e["e2e_latency"])
    return rows


def table(rows: list[dict]) -> str:
    fmt = lambda v: "-" if v in (None, []) else "+".join(map(str, v)) if isinstance(v, list) else str(v)
    head = ["turn"] + COLS
    body = [[("greet" if i == 0 else str(i))] + [fmt(r.get(c)) for c in COLS] for i, r in enumerate(rows)]
    w = [max(len(x[i]) for x in [head] + body) for i in range(len(head))]
    return "\n".join("  ".join(c.rjust(w[i]) for i, c in enumerate(row)) for row in [head] + body)


if __name__ == "__main__":
    print(table(turns(parse(open(sys.argv[1], encoding="utf-8", errors="replace").read()))))
