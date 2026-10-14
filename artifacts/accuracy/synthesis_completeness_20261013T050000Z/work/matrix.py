"""Phase 2 matrix: each case under production and each candidate rule set.

F = verbatim 21 CFR 312.32 / 211.25 fixtures through the configured pipeline (TableDatabase; every row fits,
    so complete / missing-deadline / missing-follow-up answers are distinguishable).
P = the production database through serve_ui.Engine (only the model output scripted).
"""
from __future__ import annotations
import contextlib, json, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[3])); sys.path.insert(0, str(HERE.parents[3] / "src"))
from proto import patched  # noqa: E402

RULES = ["production"]


def fixture_cases():
    from tests.test_accuracy_completeness_focus import (BROAD_SECTION, CORRECT_SEVEN, FOLLOW_UP, S312, SEVEN, body)
    from tests.test_accuracy_pass_integrity import A, B, C, FOCUSED, S211
    m = lambda *ps: " ".join(f"{body(p)} [{i}]" for p, i in ps)  # noqa: E731
    B_, C1, C1I, C2, D1, D2, D3 = ("(b)", 2), ("(c)(1)", 3), ("(c)(1)(i)", 4), ("(c)(2)", 5), ("(d)(1)", 7), ("(d)(2)", 8), ("(d)(3)", 9)
    return [
        ("F1 broad: (c)(1) only", BROAD_SECTION, m(C1), S312, "not_pass"),
        ("F2 broad: complete", BROAD_SECTION, m(B_, C1, C2, D1, D2, D3), S312, "pass"),
        ("F2x broad: complete incl. (c)(1)(i) lead-in", BROAD_SECTION, m(B_, C1, C1I, C2, D1, D2, D3), S312, "record"),
        ("F3 broad: missing the 7-day rule", BROAD_SECTION, m(B_, C1, D1, D2, D3), S312, "not_pass"),
        ("F4 broad: missing follow-up (d)", BROAD_SECTION, m(B_, C1, C2), S312, "not_pass"),
        ("F5 focused 7-day: correct", SEVEN, CORRECT_SEVEN, S312, "pass"),
        ("F6 focused 7-day: drops the trigger", SEVEN,
         "An unexpected fatal or life-threatening suspected adverse reaction must be reported to FDA no later than 7 calendar days [5].",
         S312, "not_pass"),
        ("F7 focused 7-day: wrong deadline", SEVEN, CORRECT_SEVEN.replace("7 calendar", "15 calendar"), S312, "not_pass"),
        ("F8 focused follow-up: correct (known false fail)", FOLLOW_UP, m(D1, D2, D3), S312, "known_fail"),
        ("F9a 211.25 (c) only", FOCUSED, f"{C} [3]", S211, "not_pass"),
        ("F9b 211.25 (a) only", FOCUSED, f"{A} [1]", S211, "not_pass"),
        ("F9c 211.25 all three", FOCUSED, f"{A} [1] {B} [2] {C} [3]", S211, "pass"),
        ("F9d 'What does 211.25 require?' (c) only", "What does 21 CFR 211.25 require?", f"{C} [3]", S211, "pass_after_repair"),
    ]


def run_fixture(question, answer, table):
    from tests.test_accuracy_pass_integrity import production
    v, d, out = production(question, answer, table)
    comp = next(x for x in d["dimensions"] if x["dimension"] == "completeness")
    return {"label": v["label"], "score": v["live_check_score"], "completeness": comp["state"], "detail": comp["detail"],
            "delivered": out.answer, "mode": (out.metadata.get("answer_shape") or {}).get("mode"),
            "claims": [(c["support"], (c.get("evidence") or [{}])[0].get("citation")) for c in d.get("checked", {}).get("claims") or []]}


def run_production(question, answer):
    from engine_harness import ask
    r = ask(question, answer)
    acc = r["accuracy"]; rv = acc["question_review"]
    comp = next(x for x in acc["dimensions"] if x["dimension"] == "completeness")
    return {"label": rv["label"], "score": rv["live_check_score"], "completeness": comp["state"], "detail": comp["detail"],
            "delivered": r["answer"], "sources": [s["citation"] for s in r["sources"]],
            "claims": [(c["support"], (c.get("evidence") or [{}])[0].get("citation")) for c in acc["checked"]["claims"]]}


def main():
    out = {}
    cases = [(cid, q, a, t, exp, "F") for cid, q, a, t, exp in fixture_cases()]
    # production-database cases: the broad question's (c)(1)-only answer, and the focused 7-day answer
    cases += [("P1 broad: (c)(1) only [production DB]", "What does 21 CFR 312.32 require?", None, None, "not_pass", "P"),
              ("P5 focused 7-day: correct [production DB]",
               "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32?",
               "The reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32 is no "
               "later than 7 calendar days after the sponsor's initial receipt of the information [9].", None, "pass", "P")]
    for cid, q, a, table, expect, where in cases:
        row = {"expect": expect, "question": q}
        for rule in RULES:
            ctx = contextlib.nullcontext() if rule == "production" else patched(rule)
            with ctx:
                if where == "F":
                    row[rule] = run_fixture(q, a, table)
                else:
                    if a is None:   # (c)(1) verbatim with its real marker
                        from engine_harness import run_pipeline
                        o, _ = run_pipeline(q, "x")
                        c1 = next(s for s in o.package.sources if s.citation == "21 CFR 312.32(c)(1)")
                        a = c1.text.split(". ", 1)[1].strip() + f" [{c1.index}]"
                    row[rule] = run_production(q, a)
        out[cid] = row
        print(f"{cid:<48} expect={expect:<17} " + " ".join(f"{r}={row[r]['label'][:4]}{row[r]['score']}" for r in RULES), flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
