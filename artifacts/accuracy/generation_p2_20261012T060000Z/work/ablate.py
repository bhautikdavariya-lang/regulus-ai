"""Single-factor prompt ablations through the PRODUCTION engine (greedy, configured adapter).

Each variant rewrites ONE thing in the user message on its way to the model; retrieval, selection,
validation, repair and citation mapping all run unchanged, so the delivered answer is what the
pipeline would deliver with that one change. No source file is edited. Diagnostic only: a variant
that removes evidence is a probe of WHY the model answers as it does, never a candidate fix.
"""
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

QUESTIONS = {
    "Q-howquickly": "How quickly must IND safety reports be submitted under 21 CFR 312.32?",
    "Q-timeframes": "What are the IND safety reporting timeframes under 21 CFR 312.32?",
    "Q-sevenday": "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32?",
    "Q-difference": "What is the difference between the 15-calendar-day and 7-calendar-day IND safety reporting deadlines in 21 CFR 312.32?",
}
FOCUS_ONLY = ("ANSWER FORMAT: plain sentences stating only what the requested provision says about the focus, each "
              "ending with the source number in brackets. Do not describe the rest of the provision. ")
FOCUS_OPEN = ("ANSWER FORMAT: plain sentences stating what the requested provision says about the focus, each "
              "ending with the source number in brackets. ")


def block(text, n):
    m = re.search(rf"(SOURCE {n}\n.*?)(?=\n\nSOURCE \d+\n|\n>>>END SOURCES)", text, re.S)
    return m.group(1) if m else None


def v_baseline(t): return t
def v_no_focus_restriction(t): return t.replace(FOCUS_ONLY, FOCUS_OPEN)
def v_no_focus_line(t): return re.sub(r"\n  focus: [^\n]*", "", t)
def v_no_subreq_line(t): return re.sub(r"\n  its sub-requirements: [^\n]*", "", t)


def v_c2_next_to_c1(t):
    b9 = block(t, 9)
    b2 = block(t, 2)
    if not (b9 and b2):
        return t
    t = t.replace("\n\n" + b9, "", 1)
    return t.replace(b2, b2 + "\n\n" + b9, 1)


def v_diag_one_fifteen(t):
    """DIAGNOSTIC: strip the two OTHER '15 calendar days' periods (SOURCES 8 and 14) to test frequency."""
    t = t.replace("Upon request from FDA, the sponsor must submit to FDA any additional data or information that the "
                  "agency deems necessary, as soon as possible, but in no case later than 15 calendar days after "
                  "receiving the request.", "")
    return t.replace(", but in no case later than 15 calendar days after the determination is made.", ".")


VALUE_A = ("ANSWER FORMAT: plain sentences stating only what the requested provision says about the focus, each "
           "ending with the source number in brackets. The question asks for a time period: give every time period "
           "the sources state for it and say what each one applies to. Do not describe the rest of the provision. ")
VALUE_B = ("ANSWER FORMAT: plain sentences stating only what the requested provision says about the focus, each "
           "ending with the source number in brackets. The question asks for a time period, so state each different "
           "time period the sources give and what each one applies to. Do not describe the rest of the provision. ")


VALUE_QUOTE = ("ANSWER FORMAT: the question asks for a time period. Quote, word for word, each sentence of the "
               "sources that states a time period for what the question asks about, each ending with its source "
               "number in brackets. Do not reword them and do not describe the rest of the provision. ")


def v_value_quote(t): return t.replace(FOCUS_ONLY, VALUE_QUOTE)


def v_value_a(t): return t.replace(FOCUS_ONLY, VALUE_A)
def v_value_b(t): return t.replace(FOCUS_ONLY, VALUE_B)


VARIANTS = {"value_quote": v_value_quote, "value_a": v_value_a, "value_b": v_value_b,"baseline": v_baseline, "no_focus_restriction": v_no_focus_restriction,
            "no_focus_line": v_no_focus_line, "no_subreq_line": v_no_subreq_line,
            "c2_next_to_c1": v_c2_next_to_c1, "DIAG_one_fifteen": v_diag_one_fifteen}


def main() -> int:
    out_path = Path(sys.argv[1])
    want_q = [a for a in sys.argv[2:] if a in QUESTIONS] or list(QUESTIONS)
    want_v = [a for a in sys.argv[2:] if a in VARIANTS] or list(VARIANTS)
    from regulus.config import load_settings
    from regulus.rag import generator as G
    from serve_ui import Engine

    state = {"variant": v_baseline, "changed": None}
    real = G.QwenGenerator.generate

    def patched(self, messages, max_new_tokens=None, on_text=None):
        msgs = [dict(m) for m in messages]
        before = msgs[-1]["content"]
        msgs[-1]["content"] = state["variant"](before)
        state["changed"] = msgs[-1]["content"] != before
        return real(self, msgs, max_new_tokens=max_new_tokens, on_text=on_text)

    G.QwenGenerator.generate = patched
    engine = Engine(load_settings(), offline=True)
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    for qid in want_q:
        for vname in want_v:
            state["variant"], state["changed"] = VARIANTS[vname], None
            r = engine.ask(QUESTIONS[qid], accuracy=False)
            a = r.get("answer") or ""
            rec = {"answer": a, "sha": hashlib.sha256(a.encode()).hexdigest()[:16], "prompt_changed": state["changed"],
                   "out_tokens": r.get("output_tokens"), "fallback": r.get("fallback_type"),
                   "seven": "7 calendar" in a, "fifteen": "15 calendar" in a,
                   "cited": [c.get("label") for c in r.get("citations") or [] if c.get("cited_in_answer")]}
            out.setdefault(qid, {})[vname] = rec
            print(f"{qid:<13} {vname:<21} changed={str(rec['prompt_changed']):<5} 7d={str(rec['seven']):<5} "
                  f"15d={str(rec['fifteen']):<5} out={rec['out_tokens']:<4} sha={rec['sha']}", flush=True)
            out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
