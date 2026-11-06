"""A/B two models for one slot and decide from our own numbers. Spends credits (LLM: about a cent or two).
  uv run python scripts/model_ab.py llm --a google/gemma-4-31b-it --b google/gemini-2.5-flash-lite
  uv run python scripts/model_ab.py tts --a-log a.log --b-log b.log     # same for stt and turn
LLM: same 5 text turns against each config, 2 of them tool turns. Tools are not executed.
stt | tts | turn: run console with each config, say the same 3 short lines, save each worker log, pass both logs.
A is the incumbent (the starter default). The decision rule is printed with the result.
"""
import argparse, asyncio, json, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import plan
from proxy_core import latency

WIN = 0.15
TURNS = [("Hi, it's Sam.", None), ("Is he around?", None), ("Just tell him dinner Saturday works for me.", "take_message"),
         ("Does he like Italian food?", None), ("That's all, thanks, goodbye.", "end_call")]
LOG_KEYS = {"stt": ("stt_ms", "finalize"), "turn": ("endpoint_wait_ms", "end of turn"), "tts": ("tts_ttfb_ms", "first audio")}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]


async def llm_side(model):
    from livekit.agents import inference, llm
    from app.agent import GooseAgent
    from proxy_core.config import load_config
    agent = GooseAgent("ash", caller="+15550100222", cfg=load_config())
    lm = inference.LLM(model=model)

    async def one(text):
        ctx = llm.ChatContext()
        ctx.add_message(role="system", content=agent.instructions)
        ctx.add_message(role="assistant", content="Hi, I'm Ash, Pranav's assistant. Who's calling?")
        ctx.add_message(role="user", content=text)
        t, first, words, tools = time.perf_counter(), None, "", []
        async with lm.chat(chat_ctx=ctx, tools=agent.tools) as stream:
            async for c in stream:
                if c.delta and (c.delta.content or c.delta.tool_calls):
                    first = first or (time.perf_counter() - t) * 1000
                    words += c.delta.content or ""
                    tools += [x.name for x in c.delta.tool_calls]
        return first, words, tools

    await one("Hello.")   # warm the connection: a cold first call is not what callers feel for long
    ms, right, empty = [], 0, 0
    for text, want in TURNS:
        first, words, tools = await one(text)
        ms.append(first or 9999)
        ok = want in tools if want else not (set(tools) & {"end_call", "take_message"})
        right += bool(want and ok)
        empty += "end_call" in tools and not words.strip()
        print(f"  {model[:32]:32} {ms[-1]:6.0f} ms  {'ok ' if ok else 'BAD'} tools={tools} {words[:50]!r}")
    return {"p50": pct(ms, .5), "p90": pct(ms, .9), "tool_right": right, "bad": 2 - right, "empty_end_call": empty}


def log_side(path, key):
    rows = latency.turns(latency.parse(Path(path).read_text(encoding="utf-8", errors="replace")))[1:]
    xs = []
    for r in rows:
        v = r.get(key)
        xs += [v[0]] if isinstance(v, list) and v else [v] if isinstance(v, (int, float)) else []
    if not xs:
        raise SystemExit(f"no {key} in {path}; was this a worker log from a console run?")
    return {"p50": pct(xs, .5), "p90": pct(xs, .9), "tool_right": 0, "bad": 0, "empty_end_call": 0}


def decide(a, b):
    """Switch only if B beats A's p50 by more than 15% and is no worse on correctness."""
    faster = a["p50"] and (a["p50"] - b["p50"]) / a["p50"] > WIN
    if not faster:
        return False, f"challenger not >{WIN:.0%} faster on p50"
    if b["bad"] > a["bad"] or b["empty_end_call"] > a["empty_end_call"]:
        return False, "challenger faster but worse on correctness"
    return True, f"challenger >{WIN:.0%} faster on p50 and no worse on correctness"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slot", choices=["llm", "stt", "tts", "turn"])
    ap.add_argument("--a", default="A")
    ap.add_argument("--b", default="B")
    ap.add_argument("--a-log")
    ap.add_argument("--b-log")
    ap.add_argument("--no-log", action="store_true")
    x = ap.parse_args()
    t0 = time.time()
    if x.slot == "llm":
        from proxy_core.config import load_env
        load_env()
        a, b = asyncio.run(llm_side(x.a)), asyncio.run(llm_side(x.b))
    else:
        if not (x.a_log and x.b_log):
            raise SystemExit("stt, tts and turn compare two console worker logs: pass --a-log and --b-log")
        key, _ = LOG_KEYS[x.slot]
        a, b = log_side(x.a_log, key), log_side(x.b_log, key)
    switch, why = decide(a, b)
    print(f"\nA {x.a}: {json.dumps(a)}\nB {x.b}: {json.dumps(b)}")
    print(f"RULE: switch only if B wins p50 by >{WIN:.0%} AND is not worse on tool correctness or audio checks")
    print(f"DECISION: {'SWITCH to ' + x.b if switch else 'KEEP ' + x.a} ({why})  [{time.time() - t0:.0f} s]")
    if not x.no_log:
        plan.log(f"model_ab {x.slot}: A {x.a} {a}; B {x.b} {b}; {'SWITCH to ' + x.b if switch else 'KEEP ' + x.a}: {why}", who="model_ab")


if __name__ == "__main__":
    main()
