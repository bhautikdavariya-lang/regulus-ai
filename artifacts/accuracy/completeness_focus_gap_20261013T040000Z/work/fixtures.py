"""Step 2a: focused fixtures, production packages, answers built from VERBATIM source text (or the
live model answer). Each case states the outcome a correct completeness check must give, and both
rules are scored on identical inputs."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from harness import _STATE, completeness, evaluate, focus_gap_rule, package_for, recording_rule  # noqa: E402

SEVEN = "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32?"
QUICK = "How quickly must IND safety reports be submitted under 21 CFR 312.32?"
FOLLOW = "What follow-up does 21 CFR 312.32 require after an IND safety report?"
FOLLOW2 = "What are the follow-up requirements for IND safety reports under 21 CFR 312.32?"
BROAD_F = "What are the IND safety reporting requirements under 21 CFR 312.32?"
BROAD_S = "Summarize 21 CFR 312.32."
COMPARE = ("What is the difference between the 15-calendar-day and 7-calendar-day IND safety reporting deadlines in "
           "21 CFR 312.32?")
PERSONNEL = "What are the personnel qualification requirements in 21 CFR 211.25?"
COMPLAINTS = "What must complaint records include under 21 CFR 820.35?"


def verbatim(question, *labels):
    """The package's own text for these citations, each ending with its own marker."""
    pkg, _ = package_for(question)
    by_label = {}
    for s in pkg.sources:
        by_label.setdefault(s.citation, []).append(s)
    parts = []
    for label in labels:
        for s in by_label.get(label, []):
            parts.append(f"{s.text.strip()} [{s.index}]")
    if not parts:
        raise KeyError(f"{labels} not in the package for {question!r}: {sorted(by_label)}")
    return "\n\n".join(parts)


LIVE_SEVEN = ("The reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR "
              "312.32 is no later than 7 calendar days after the sponsor's initial receipt of the information [9].")
LIVE_QUICK_BOTH = ("- IND safety reports: in no case later than 15 calendar days after the sponsor determines that the "
                   "information qualifies for reporting under paragraph (c)(1)(i), (c)(1)(ii), (c)(1)(iii), or (c)(1)(iv) "
                   "of this section [2].\n- Unexpected fatal or life-threatening suspected adverse reaction reports: The "
                   "sponsor must also notify FDA of any unexpected fatal or life-threatening suspected adverse reaction as "
                   "soon as possible but in no case later than 7 calendar days after the sponsor's initial receipt of the "
                   "information [9].")

CASES = [
    # id, question, answer builder, what a correct completeness check must do
    ("seven-correct-live", SEVEN, lambda: LIVE_SEVEN, "pass"),
    ("seven-correct-verbatim", SEVEN, lambda: verbatim(SEVEN, "21 CFR 312.32(c)(2)"), "pass"),
    ("seven-wrong-deadline", SEVEN, lambda: LIVE_SEVEN.replace("7 calendar", "15 calendar"), "not_pass_overall"),
    ("seven-drops-trigger", SEVEN, lambda: ("An unexpected fatal or life-threatening suspected adverse reaction must be "
                                            "reported to FDA no later than 7 calendar days [9]."), "record"),
    ("quick-both-live", QUICK, lambda: LIVE_QUICK_BOTH, "record"),
    ("quick-fifteen-only", QUICK, lambda: verbatim(QUICK, "21 CFR 312.32(c)(1)"), "record"),
    ("follow-d-only", FOLLOW, lambda: verbatim(FOLLOW, "21 CFR 312.32(d)(1)", "21 CFR 312.32(d)(2)", "21 CFR 312.32(d)(3)"), "pass"),
    ("follow-c-only", FOLLOW, lambda: verbatim(FOLLOW, "21 CFR 312.32(c)(1)"), "fail"),
    ("follow2-d-only", FOLLOW2, lambda: verbatim(FOLLOW2, "21 CFR 312.32(d)(1)", "21 CFR 312.32(d)(2)", "21 CFR 312.32(d)(3)"), "pass"),
    ("follow2-c-only", FOLLOW2, lambda: verbatim(FOLLOW2, "21 CFR 312.32(c)(1)"), "fail"),
    ("broadF-c-only", BROAD_F, lambda: verbatim(BROAD_F, "21 CFR 312.32(c)(1)", "21 CFR 312.32(c)(2)"), "fail"),
    ("broadF-c-and-d", BROAD_F, lambda: verbatim(BROAD_F, "21 CFR 312.32(c)(1)", "21 CFR 312.32(c)(2)", "21 CFR 312.32(d)(2)", "21 CFR 312.32(d)(3)"), "pass"),
    ("broadS-c-only", BROAD_S, lambda: verbatim(BROAD_S, "21 CFR 312.32(c)(1)"), "record"),
    ("compare-both-live", COMPARE, lambda: LIVE_QUICK_BOTH, "record"),
    ("personnel-c-only", PERSONNEL, lambda: verbatim(PERSONNEL, "21 CFR 211.25(c)"), "fail"),
    ("personnel-a-only", PERSONNEL, lambda: verbatim(PERSONNEL, "21 CFR 211.25(a)"), "fail"),
    ("personnel-all", PERSONNEL, lambda: verbatim(PERSONNEL, "21 CFR 211.25(a)", "21 CFR 211.25(b)", "21 CFR 211.25(c)"), "pass"),
]


def main():
    rows = []
    for cid, q, build, expect in CASES:
        try:
            answer = build()
        except KeyError as exc:
            print(f"{cid:<24} SKIPPED: {exc}"); continue
        pkg, _ = package_for(q)
        mode = pkg.answer_plan.shape.mode if pkg and pkg.answer_plan else None
        res = {"id": cid, "question": q, "mode": mode, "expect": expect, "answer": answer}
        for rule in ("production", "distinguishing"):
            store = []
            with focus_gap_rule(recording_rule(store, rule)):
                a = evaluate(q, answer)
            d = a.to_dict()
            st, det = completeness(a)
            res[rule] = {"completeness": st, "detail": det, "verdict": d["answer_verdict"]["verdict"],
                         "score": d["accuracy"], "label": None,
                         "focus_trace": store[-1]["trace"] if store else None}
        rows.append(res)
        p, n = res["production"], res["distinguishing"]
        changed = "CHANGED" if (p["completeness"], p["score"]) != (n["completeness"], n["score"]) else "same   "
        print(f"{cid:<24} {mode or '-':<10} expect={expect:<17} prod={p['completeness']:<15}{str(p['score']):<5} "
              f"cand={n['completeness']:<15}{str(n['score']):<5} {changed} verdict={n['verdict']}")
    Path(sys.argv[1]).write_text(json.dumps(rows, indent=1, default=str))
    _STATE["db"].close()


if __name__ == "__main__":
    main()
