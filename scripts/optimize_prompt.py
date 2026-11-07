"""Tune the style part of the phone agent's prompt with DSPy (GEPA). Spends LiveKit Inference credits.

  uv run --extra optimize python scripts/optimize_prompt.py --eval-only            # score the prompt as it is
  uv run --extra optimize python scripts/optimize_prompt.py --budget light         # optimize, write runtime/prompt_opt/
  uv run --extra optimize python scripts/optimize_prompt.py --eval-only --prompt runtime/prompt_opt/candidate.txt
  uv run --extra optimize python scripts/optimize_prompt.py --apply runtime/prompt_opt/candidate.txt
A run that stops (out of Inference credit, Ctrl+C) resumes from runtime/prompt_opt/gepa when run again; --export writes
the best candidate so far without any model calls, and --fresh sets the old run aside to start over (do that after
changing the cases or the scoring, or old and new scores mix). Ties go to the shorter block, and a block longer than
1.3x the current one loses points: the live agent reads it on every turn.

What is tuned: only the block of app/prompts/system.txt from "# VOICE STYLE" up to "# PRIVACY RULES" (voice style,
dates and numbers, honesty). Identity, privacy, floor rules, agenda and non-negotiables stay fixed and are given to the
model as context, so the optimizer can never trade a privacy rule for a nicer-sounding reply.

How it is scored: scripts/prompt_cases.yaml, one caller turn each, with the context the real GooseAgent builds for that
caller ID. Code checks the hard rules (right tool, silence on a gated tool, two sentences, one question, no digit dates
or clock times, no apology, no goodbye, no leak); a judge model grades how human it sounds against the case's
expectation. GEPA reads the written feedback and rewrites the block. Every third case is held out for validation.

Models: the task model is the live agent's (config.yaml providers.llm), so the prompt is tuned for what runs on calls.
Tool calls are predicted as a field, not through native tool calling, so tool choice here is a close proxy, not proof:
run tests/bench.py and a real call before shipping a candidate. Nothing touches system.txt without --apply.
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dspy
import yaml

from proxy_core import shape
from proxy_core.config import load_config, load_env

PROMPT_FILE = ROOT / "app" / "prompts" / "system.txt"
CASES_FILE = ROOT / "scripts" / "prompt_cases.yaml"
OUT = ROOT / "runtime" / "prompt_opt"
START, END = "# VOICE STYLE", "# PRIVACY RULES"
PLACEHOLDERS = ("{owner}", "{now}", "{style}")
GATED = {"take_message", "propose_slot", "summon_agent", "request_permission_from_owner", "end_call"}
TOOLS = ("none", "take_message", "propose_slot", "summon_agent", "request_permission_from_owner", "end_call",
         "get_facts", "get_profile", "get_calendar", "search_email", "search_slack", "search_notes")
NOTHING = "(nothing)"
REFLECTION_MODEL = "openai/gpt-5.6"          # on LiveKit Inference; reasoning models need temperature 1
JUDGE_MODEL = "google/gemini-3.8-flash"

CHECKS = [   # (regex on the spoken reply, what to tell the optimizer)
    (r"\b\d{1,2}/\d{1,2}\b", "said a date as digits like 12/21; say 'next Monday' or 'December 21st'"),
    (r"\b\d{1,2}:\d{2}\b", "said a clock time like 7:30; say 'half past 7'"),
    (r"\b\d{1,2}\s?[ap]\.?m\b|\b[ap]\.m\.", "said am/pm; say 'in the evening'"),
    (r"\b(sorry|apologi[sz]e)", "apologised; the prompt says never apologetic"),
    (r"\b(tier|caller id|unknown caller|unknown number)\b", "said tier, caller ID or 'unknown caller' aloud"),
    (r"\b(good)?bye\b", "said goodbye; end_call says it, never the model"),
]


# ---------- the program ----------

class CallTurn(dspy.Signature):
    """(replaced by the tuned style rules)"""
    context: str = dspy.InputField(desc="Who you are, the privacy and floor rules, the agenda, and what you know about this caller")
    conversation: str = dspy.InputField(desc="The call so far, oldest first; empty at the start of the call")
    caller_said: str = dspy.InputField(desc="What the caller just said")
    tool: Literal[TOOLS] = dspy.OutputField(desc="The one tool to call this turn, or none")
    reply: str = dspy.OutputField(desc=f"Exactly what you say aloud this turn. Write {NOTHING} if the rules say to say nothing")


class Goose(dspy.Module):
    """One predictor whose instructions are the tuned block. {owner}, {now} and {style} are filled per call, so the
    block GEPA reads and rewrites keeps them as placeholders and drops straight back into system.txt."""

    def __init__(self, block: str, contexts: dict):
        super().__init__()
        self.turn = dspy.Predict(CallTurn.with_instructions(block))
        self.contexts = contexts

    def forward(self, case_id, caller, conversation, caller_said):
        context, values = self.contexts[caller]
        block = self.turn.signature.instructions
        text = block
        for k, v in values.items():
            text = text.replace(k, v)
        pred = guarded(self.turn, signature=self.turn.signature.with_instructions(text),
                       context=context, conversation=conversation, caller_said=caller_said)
        pred.block_words = len(block.split())     # the metric holds the block to a length: every live turn reads it
        return pred


# ---------- LiveKit Inference credit ----------

class OutOfCredit(Exception):
    """The project's Inference credit is used up. Stop the whole run: every later call would fail and score as 0."""


OUT_OF_CREDIT = {"hit": False}


def guarded(fn, *args, **kwargs):
    """Retries a rate limit with backoff; a used-up credit quota stops the run at once."""
    for attempt in range(4):
        if OUT_OF_CREDIT["hit"]:
            raise OutOfCredit()
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if "quota" in msg or "credit" in msg:
                OUT_OF_CREDIT["hit"] = True
                raise OutOfCredit(str(e)[:200]) from e
            if attempt == 3 or not ("429" in msg or "rate limit" in msg or "ratelimit" in msg):
                raise
            time.sleep(5 * 2 ** attempt)


# ---------- the score ----------

class Judge(dspy.Signature):
    """You grade one turn of a phone assistant that answers calls for its owner. A great turn sounds like a warm,
    natural person on the phone: short, plain spoken words, no lists, nothing robotic, no apologies, at most one
    question, and it does what the expectation says. Grade only the reply and tool given."""
    expectation: str = dspy.InputField()
    conversation: str = dspy.InputField()
    caller_said: str = dspy.InputField()
    tool: str = dspy.InputField(desc="The tool the assistant called, or none")
    reply: str = dspy.InputField(desc="What the assistant said aloud, or (nothing)")
    score: int = dspy.OutputField(desc="1 = wrong or robotic, 3 = acceptable, 5 = exactly what a great human assistant would say")
    critique: str = dspy.OutputField(desc="One sentence: the main thing to change, or 'good'")


JUDGE = dspy.Predict(Judge)
JUDGE_LM = None
MAX_WORDS = None    # set from the current block: GEPA pads instructions unless length costs it something


def _spoken(pred) -> str:
    text = (getattr(pred, "reply", "") or "").strip()
    return "" if text.strip("() .").lower() in ("nothing", "") else text


def grade(case: dict, pred) -> tuple[float, str, dict]:
    """(score 0..1, feedback for GEPA, details for the report)."""
    tool = str(getattr(pred, "tool", "none") or "none").strip()
    said = _spoken(pred)
    want = case["tool"] if isinstance(case["tool"], list) else [case["tool"]]
    fails, fatal = [], []
    if tool not in want:
        fatal.append(f"called {tool}, should have called {' or '.join(want)}")
    if tool in GATED and said:
        fails.append(f"spoke while calling {tool}; a gated tool means say nothing, code asks the caller to confirm")
    if tool == "none" and not said:
        fails.append("said nothing and called no tool")
    fails += [f"shape: {p}" for p in shape.problems(said)]
    if said.count("?") > 1:
        fails.append("asked more than one question")
    fails += [why for pattern, why in CHECKS if re.search(pattern, said, re.I)]
    fails += [f"should have said something matching /{m}/" for m in case.get("must", []) if not re.search(m, said, re.I)]
    words = getattr(pred, "block_words", 0)
    if MAX_WORDS and words > MAX_WORDS:
        fails.append(f"the style rules grew to {words} words; the live agent reads them on every turn, so keep them "
                     f"under {MAX_WORDS}: cut repetition, and do not restate the privacy or floor rules from the context")
    fatal += [f"said /{m}/, which must never be said here" for m in case.get("must_not", []) if re.search(m, said, re.I)]
    if tool in GATED and not said and not fails and not fatal:
        judged, critique = 5, "good"
    else:
        with dspy.context(lm=JUDGE_LM):
            j = guarded(JUDGE, expectation=case["expect"], conversation=_conversation(case) or "(start of call)",
                        caller_said=case["say"], tool=tool, reply=said or NOTHING)
        judged, critique = max(1, min(5, int(j.score))), j.critique
    hard = 0.0 if fatal else max(0.0, 1 - 0.25 * len(fails))
    score = 0.0 if fatal else round(0.7 * hard + 0.3 * (judged - 1) / 4, 3)
    problems = fatal + fails
    feedback = (f"Expected: {case['expect']}\nGot tool={tool}, said: {said or NOTHING!r}\n"
                f"Score {score}. Problems: {'; '.join(problems) or 'none'}. Judge {judged}/5: {critique}")
    return score, feedback, {"tool": tool, "said": said, "problems": problems, "judge": judged, "critique": critique}


def metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
    score, feedback, _ = grade(gold.case, pred)
    return dspy.Prediction(score=score, feedback=feedback)


# ---------- data ----------

def _conversation(case: dict) -> str:
    return "\n".join(case.get("history", []))


def load_cases():
    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    examples = [dspy.Example(case_id=c["id"], caller=c["caller"], conversation=_conversation(c), caller_said=c["say"], case=c)
                .with_inputs("case_id", "caller", "conversation", "caller_said") for c in cases]
    return examples, [e for i, e in enumerate(examples) if i % 3 != 2], [e for i, e in enumerate(examples) if i % 3 == 2]


def split(text: str) -> tuple[str, str, str]:
    i, j = text.index(START), text.index(END)
    return text[:i], text[i:j], text[j:]


def build_contexts(callers) -> dict:
    """The real agent's prompt for each caller ID, minus the tuned block, plus the values its placeholders take."""
    import logging
    logging.getLogger("goose").setLevel(logging.WARNING)
    from app.agent import GooseAgent
    from proxy_core.personality import render_style
    from proxy_core.speech import spoken_time
    cfg, out = load_config(), {}
    now = datetime.now().astimezone()
    for number in sorted(set(callers)):
        a = GooseAgent("goose", caller=number, cfg=cfg)
        head, _, tail = split(a.instructions)
        values = {"{owner}": a.owner.title(), "{assistant}": a.persona.title(),
                  "{now}": f"{now:%A}, {now:%B} {now.day}, {now.year}, {spoken_time(now.hour, now.minute)}",
                  "{style}": "\n".join([render_style(a.pack), *a.pack.get("rules", [])])}
        # The live model reads each tool's description with its schema; here it reads them as text.
        tools = "\n".join(f"- {t.info.name}: {' '.join((t.info.description or '').split())}" for t in a.tools
                          if t.info.name in TOOLS)
        out[number] = (head + "(Your voice and style rules are in your instructions.)\n\n" + tail +
                       f"\n\n# TOOLS YOU CAN CALL\n{tools}", values)
    return out


def inference_lm(model: str, **kw):
    from livekit.agents.inference._utils import create_access_token, get_default_inference_url
    token = create_access_token(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"], ttl=8 * 3600)
    return dspy.LM("openai/" + model, api_base=get_default_inference_url(), api_key=token, **kw)


# ---------- runs ----------

def evaluate(program, examples, threads: int) -> list[dict]:
    def one(ex):
        try:
            pred = program(**ex.inputs())
        except OutOfCredit:
            raise
        except Exception as e:    # a parse failure is a bad turn, not a crashed run
            pred = dspy.Prediction(tool="none", reply="", error=str(e)[:120])
        score, _, d = grade(ex.case, pred)
        return {"id": ex.case_id, "score": score, **d}
    with ThreadPoolExecutor(threads) as pool:
        return list(pool.map(one, examples))


def table(rows: list[dict], before: list[dict] | None = None) -> str:
    prev = {r["id"]: r for r in before or []}
    lines = ["| case | " + ("before | " if before else "") + "score | tool | said | problems |",
             "|---|" + ("---|" if before else "") + "---|---|---|---|"]
    for r in rows:
        b = f"{prev[r['id']]['score']:.2f} | " if before else ""
        said = r["said"].replace("|", "/").replace("\n", " ")[:90]
        lines.append(f"| {r['id']} | {b}{r['score']:.2f} | {r['tool']} | {said} | {'; '.join(r['problems'])[:120]} |")
    return "\n".join(lines)


def mean(rows):
    return sum(r["score"] for r in rows) / len(rows)


def check_block(block: str) -> list[str]:
    """Reasons a candidate must not go into system.txt as it is."""
    return [f"missing placeholder {p}" for p in PLACEHOLDERS if p not in block] + \
           [f"no longer names {t}" for t in sorted(GATED) if t not in block] + \
           ([f"mentions {NOTHING}, which only this script uses"] if NOTHING in block else []) + \
           [f"restates the fixed {s} section, which can drift from the real one" for s in ("PRIVACY", "FLOOR")
            if re.search(rf"^#.*\b{s}\b", block, re.M)]


def export_state(head: str, block: str, tail: str) -> None:
    """Writes the best candidate GEPA has found so far, from its saved state, with no model calls. Ties (within 0.01
    on validation) go to the shortest: every live turn reads the block, and a few words of score are noise here."""
    import pickle
    path = OUT / "gepa" / "gepa_state.bin"
    if not path.is_file():
        sys.exit(f"No saved GEPA state at {path.relative_to(ROOT)}.")
    state = pickle.loads(path.read_bytes())
    rows = []
    for i, (cand, sub) in enumerate(zip(state["program_candidates"], state["prog_candidate_val_subscores"])):
        vals = list(sub.values()) if isinstance(sub, dict) else list(sub)
        rows.append({"i": i, "score": sum(vals) / max(1, len(vals)), "words": len(cand["turn"].split()), "block": cand["turn"]})
    top = max(r["score"] for r in rows)
    pick = min((r for r in rows if r["score"] >= top - 0.01), key=lambda r: r["words"])
    new_block = pick["block"].rstrip() + "\n\n"
    issues = check_block(new_block)
    (OUT / "candidate.txt").write_text(head + new_block + tail, encoding="utf-8")
    (OUT / "block_before.txt").write_text(block, encoding="utf-8")
    (OUT / "block_after.txt").write_text(new_block, encoding="utf-8")
    lines = [f"| {r['i']} | {r['score']:.3f} | {r['words']} |" + (" picked |" if r is pick else " |") for r in rows]
    (OUT / "report.md").write_text(
        f"# Prompt optimization (from saved state, {datetime.now():%Y-%m-%d %H:%M})\n\n"
        f"Candidate {pick['i']}: validation {pick['score']:.3f} against {rows[0]['score']:.3f} for the current prompt, "
        f"{pick['words']} words against {rows[0]['words']}. Validation is {len(state['prog_candidate_val_subscores'][0])} "
        f"cases, so a gap of one judge point is noise: run --eval-only on candidate.txt before trusting it.\n\n"
        + (f"**Do not apply as is:** {'; '.join(issues)}\n\n" if issues else "")
        + "| candidate | validation | words | |\n|---|---|---|---|\n" + "\n".join(lines)
        + f"\n\n## Picked block\n\n```\n{new_block}```\n", encoding="utf-8")
    print(f"candidate {pick['i']}: {pick['score']:.3f} on validation ({pick['words']} words), current prompt "
          f"{rows[0]['score']:.3f} ({rows[0]['words']} words)" + (f"\nWARNING: {'; '.join(issues)}" if issues else ""))
    print(f"written {OUT.relative_to(ROOT)}/candidate.txt and report.md")


def apply(path: Path):
    head, _, tail = split(PROMPT_FILE.read_text(encoding="utf-8"))
    c_head, block, c_tail = split(path.read_text(encoding="utf-8"))
    if (c_head, c_tail) != (head, tail):
        sys.exit("The candidate's fixed sections differ from system.txt now. Re-run the optimizer on the current prompt.")
    if issues := check_block(block):
        sys.exit("Not applied: " + "; ".join(issues))
    PROMPT_FILE.write_text(head + block + tail, encoding="utf-8")
    print(f"Applied {path} to {PROMPT_FILE.relative_to(ROOT)}. Run pytest and tests/bench.py next.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-only", action="store_true", help="score the current prompt and stop")
    ap.add_argument("--budget", choices=["light", "medium", "heavy"], default="light")
    ap.add_argument("--max-calls", type=int, help="metric calls for GEPA instead of --budget")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--limit", type=int, help="use only the first N cases (smoke test)")
    ap.add_argument("--apply", type=Path, help="write a candidate.txt into app/prompts/system.txt")
    ap.add_argument("--export", action="store_true", help="write the best candidate from the saved run, no model calls")
    ap.add_argument("--fresh", action="store_true", help="set the saved run aside (renamed, not deleted) and start over")
    ap.add_argument("--prompt", type=Path, default=PROMPT_FILE, help="score this file instead, e.g. a candidate.txt")
    args = ap.parse_args()
    if args.apply:
        return apply(args.apply)
    head, block, tail = split(args.prompt.read_text(encoding="utf-8"))
    if args.export:
        return export_state(head, block, tail)

    global JUDGE_LM, MAX_WORDS
    MAX_WORDS = round(len(block.split()) * 1.3)
    load_env()
    task_model = load_config()["providers"]["llm"]["model"]
    task_lm = inference_lm(task_model, max_tokens=400, temperature=0)   # 0: two prompts compare on wording, not luck
    JUDGE_LM = inference_lm(JUDGE_MODEL, max_tokens=300, temperature=0)
    dspy.configure(lm=task_lm)

    examples, train, val = load_cases()
    if args.limit:
        examples = examples[:args.limit]
        train, val = examples[: max(1, len(examples) * 2 // 3)], examples[max(1, len(examples) * 2 // 3):] or examples[-1:]
    program = Goose(block, build_contexts(e.caller for e in examples))
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"task {task_model}, judge {JUDGE_MODEL}, {len(examples)} cases ({len(train)} train, {len(val)} val), "
          f"style block {len(block.split())} words (limit {MAX_WORDS})")

    t0 = time.time()
    try:
        before = evaluate(program, examples, args.threads)
    except OutOfCredit as e:
        sys.exit(f"LiveKit Inference credit is used up, nothing scored. {e}")
    name = args.prompt.relative_to(ROOT) if args.prompt.is_relative_to(ROOT) else args.prompt
    print(f"{name}: {mean(before):.3f} mean over {len(before)} cases ({time.time() - t0:.0f} s)")
    if args.eval_only:
        (OUT / "eval.md").write_text(f"# {name}: {mean(before):.3f}\n\n{table(before)}\n", encoding="utf-8")
        print(table(before))
        print(f"\nwritten {(OUT / 'eval.md').relative_to(ROOT)}")
        return

    run_dir = OUT / "gepa"
    if args.fresh and run_dir.exists():
        run_dir.rename(OUT / f"gepa-{datetime.now():%Y%m%d-%H%M%S}")
    reflection = inference_lm(REFLECTION_MODEL, temperature=1.0, max_tokens=16000)
    budget = {"max_metric_calls": args.max_calls} if args.max_calls else {"auto": args.budget}
    gepa = dspy.GEPA(metric=metric, reflection_lm=reflection, num_threads=args.threads, track_stats=True,
                     log_dir=str(run_dir), seed=0, **budget)
    try:
        best = gepa.compile(program, trainset=train, valset=val)
        new_block = best.turn.signature.instructions.rstrip() + "\n\n"
        after = evaluate(best, examples, args.threads)
    except Exception:
        if not OUT_OF_CREDIT["hit"]:
            raise
        print("\nLiveKit Inference credit ran out. GEPA's progress is saved: run the same command again to resume.")
        return export_state(head, block, tail)

    issues = check_block(new_block)
    (OUT / "candidate.txt").write_text(head + new_block + tail, encoding="utf-8")
    (OUT / "block_before.txt").write_text(block, encoding="utf-8")
    (OUT / "block_after.txt").write_text(new_block, encoding="utf-8")
    report = (f"# Prompt optimization, {datetime.now():%Y-%m-%d %H:%M}\n\n"
              f"Task model `{task_model}`, judge `{JUDGE_MODEL}`, reflection `{REFLECTION_MODEL}`, "
              f"budget {budget}, {time.time() - t0:.0f} s.\n\n"
              f"**Mean score: {mean(before):.3f} before, {mean(after):.3f} after** "
              f"(validation only: {mean([r for r in before if r['id'] in {e.case_id for e in val}]):.3f} -> "
              f"{mean([r for r in after if r['id'] in {e.case_id for e in val}]):.3f}).\n\n"
              + (f"**Do not apply as is:** {'; '.join(issues)}\n\n" if issues else "")
              + f"## Per case\n\n{table(after, before)}\n\n## New block\n\n```\n{new_block}```\n")
    (OUT / "report.md").write_text(report, encoding="utf-8")
    print(f"\nbefore {mean(before):.3f} -> after {mean(after):.3f}" + (f"  WARNING: {'; '.join(issues)}" if issues else ""))
    print(f"written {OUT.relative_to(ROOT)}/candidate.txt and report.md. Apply with --apply {OUT.relative_to(ROOT)}/candidate.txt")


if __name__ == "__main__":
    main()
