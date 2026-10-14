"""A population with power for named-section synthesis questions, built from the regulation itself.

For sections of the read-only snapshot whose rows all fit in the evidence (nothing withheld) and that
state at least two top-level obligations: "What does 21 CFR <s> require?" (synthesis), answered
  COMPLETE   every top-level obligation, verbatim, each with its own marker      -> a correct rule passes it
  DROP-k     the same with top-level obligation k left out (each k in turn)      -> a correct rule does not
No model, no generation; production retrieval, selection, package and evaluator.
"""
from __future__ import annotations
import contextlib, json, os, random, sys
from pathlib import Path
HERE = Path(__file__).parent
FG = HERE.parents[1] / "completeness_focus_gap_20261013T040000Z" / "work"
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(FG))
from harness import _STATE, completeness, evaluate, package_for  # noqa: E402
from proto import patched  # noqa: E402

RULES = ["production"]


def label(a, q):
    from regulus.accuracy.review import question_review
    return question_review(a.to_dict(), question=q)["label"]


def top_obligations(pkg):
    from regulus.accuracy import operators as OP
    by = {s.index: s for s in pkg.sources if s.tier == "exact"}
    mand = {i for i, s in by.items() if OP.strength(s.text) == OP.MANDATORY}
    path = {i: (s.citation_fields or {}).get("paragraph") or "" for i, s in by.items()}
    return [i for i in sorted(mand)
            if not any(j != i and j in mand and path[j] and path[i].startswith(path[j] + "(") for j in by)], by


def main():
    import psycopg
    random.seed(13)
    with psycopg.connect(os.environ["REGULUS_DATABASE_URL"]) as c, c.cursor() as cur:
        cur.execute("""SELECT section_number, count(*), sum(length(body_text)) FROM cfr_records
                       WHERE removed_on IS NULL AND section_number IS NOT NULL GROUP BY section_number
                       HAVING count(*) BETWEEN 3 AND 14 AND sum(length(body_text)) < 6500""")
        candidates = [r[0] for r in cur.fetchall()]
    random.shuffle(candidates)
    out, used = [], 0
    for sec in candidates:
        if used >= int(sys.argv[2]):
            break
        q = f"What does 21 CFR {sec} require?"
        with patched("T"):
            pkg, _ = package_for(q)
        if pkg is None or pkg.answer_plan is None or pkg.answer_plan.shape.mode != "synthesis":
            continue
        if getattr(pkg, "withheld", ()) or not pkg.requirements:
            continue
        tops, by = top_obligations(pkg)
        if len(tops) < 2:
            continue
        used += 1
        body = lambda i: by[i].text.strip().rstrip(".") + f". [{i}]"  # noqa: E731
        variants = [("COMPLETE", None)] + [(f"DROP-{by[k].citation.replace('21 CFR ', '')}", k) for k in tops]
        for name, drop in variants:
            ans = " ".join(body(i) for i in tops if i != drop)
            rec = {"section": sec, "variant": name, "expect": "pass" if drop is None else "not_pass", "tops": len(tops)}
            for rule in RULES:
                ctx = contextlib.nullcontext() if rule == "production" else patched(rule)
                with ctx:
                    a = evaluate(q, ans)
                st, det = completeness(a)
                rec[rule] = {"label": label(a, q), "score": a.to_dict()["accuracy"], "completeness": st, "detail": det[:160]}
            out.append(rec)
        print(f"  {used:>3} {sec:<12} top obligations={len(tops)}", flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str))
    _STATE["db"].close()


if __name__ == "__main__":
    main()
