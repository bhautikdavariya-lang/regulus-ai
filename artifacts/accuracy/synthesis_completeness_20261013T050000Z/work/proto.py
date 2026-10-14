"""Candidate synthesis-completeness rules, patched in at runtime (no src/ edits).

build_package is wrapped to attach `withheld` - the requested provision's EXACT rows the hard ceiling
dropped (citation, text) - to the package, which is the data a production version would carry as a
non-rendered field. evaluator._focus_gap is wrapped: focused plans go to the production function
unchanged; synthesis plans get the candidate rule. Returned (missing, maybe) is applied by the
evaluator's existing code: `missing` turns a completeness PASS into FAIL, `maybe` into NOT ESTABLISHED.

  T  withheld obligations -> maybe (completeness cannot be established)
  G  an obligation-bearing group with no obligation-bearing member covered by an answering claim -> missing
  U  every obligation-bearing row not subordinate to another obligation-bearing row must be covered -> missing
"""
from __future__ import annotations
import contextlib, re

VERBATIM_RUN = 8          # words of an obligation's own text reproduced in the answer
VERBATIM_SHARE = 0.6      # ... and at least this share of its words (G3 / U3)
_ANSWER = {"text": ""}


def _withheld(selection):
    out = []
    for d in getattr(selection, "dropped", ()) or ():
        if d.required and d.evidence.corpus == "ecfr":
            out.append((d.evidence.citation, d.evidence.text))
    return tuple(out)


@contextlib.contextmanager
def patched(rules: str):
    from regulus.accuracy import answer as AN, evaluator as E, operators as OP
    from regulus.rag import generation as GEN, pipeline as PIPE
    orig_build, orig_gap = GEN.build_package, E._focus_gap

    def build(plan, coverage, selection, *a, **k):
        pkg = orig_build(plan, coverage, selection, *a, **k)
        object.__setattr__(pkg, "withheld", _withheld(selection))
        return pkg

    orig_eval = E._evaluate

    def evaluate(question, answer, *a, **k):
        _ANSWER["text"] = answer or ""
        return orig_eval(question, answer, *a, **k)

    def gap(package, intent, answering, claims, passages):
        plan = getattr(package, "answer_plan", None)
        mode = getattr(getattr(plan, "shape", None), "mode", None)
        if mode != "synthesis":
            return orig_gap(package, intent, answering, claims, passages)
        requested = {rid for rid, _ in (getattr(package, "requirements", None) or ())}
        by_src = {s.index: s for s in package.sources}
        decided = (AN.SUPPORTED, AN.SUPPORTED_WITH_CITATION_DEFECT, AN.PARTIALLY_SUPPORTED, AN.CONTRADICTED)
        covered = {e.get("source_index") for c in answering if c.final in decided for e in c.evidence[:1]}
        by_citation = {p.citation: p.source_index for p in passages}
        touched = {e.get("source_index") for c in claims if c.final == AN.UNVERIFIABLE for e in c.evidence}
        touched |= {by_citation.get(c.candidate_evidence[0]) for c in claims
                    if c.final == AN.UNVERIFIABLE and c.candidate_evidence}
        mandatory = {i for i, s in by_src.items() if OP.strength(s.text) == OP.MANDATORY}
        missing, maybe = [], []
        if "G" in rules:
            from regulus.accuracy.attribution import longest_run, normalise
            answer_words = normalise(_ANSWER["text"]).split()
            def verbatim(i):
                run = longest_run(answer_words, normalise(by_src[i].text))[0]
                if "3" in rules:   # G3/U3: the run must be a real share of the obligation, not shared boilerplate
                    n = len(normalise(by_src[i].text).split())
                    return run >= max(min(VERBATIM_RUN, n), VERBATIM_SHARE * n)
                return run >= VERBATIM_RUN
            for g in plan.groups:
                if g.kind != "requirement" or not set(g.requirement_ids) & requested:
                    continue
                obligations = [i for i in g.members if i in mandatory]
                represented = (covered & set(obligations)) if ("2" not in rules and "3" not in rules) else \
                    (covered & set(obligations)) or {i for i in obligations if verbatim(i)}
                if obligations and not represented:
                    label = g.label + (f" ({g.heading})" if g.heading else "")
                    (maybe if ("3" in rules and touched & set(obligations)) else missing).append(label)
        if "U" in rules and "3" in rules:
            from regulus.accuracy.attribution import longest_run, normalise
            answer_words = normalise(_ANSWER["text"]).split()
            paths = {i: (src.citation_fields or {}).get("paragraph") or "" for i, src in by_src.items()}
            for g in plan.groups:
                if g.kind != "requirement" or not set(g.requirement_ids) & requested:
                    continue
                for i in [i for i in g.members if i in mandatory]:
                    under_obligation = any(j != i and j in mandatory and paths[j] and paths[i].startswith(paths[j] + "(")
                                           for j in g.members)
                    if under_obligation:
                        continue
                    def rep(k):
                        n = len(normalise(by_src[k].text).split())
                        run = longest_run(answer_words, normalise(by_src[k].text))[0]
                        return k in covered or run >= max(min(VERBATIM_RUN, n), VERBATIM_SHARE * n)
                    # a lead-in ("... must be:") says nothing by itself: it is represented when it or any of its items is
                    items = [k for k in g.members if paths[k].startswith(paths[i] + "(")] if by_src[i].text.rstrip().endswith(":") else []
                    if not (rep(i) or any(rep(k) for k in items)):
                        (maybe if (i in touched or touched & set(items)) else missing).append(by_src[i].citation)
        if "U" in rules and "3" not in rules:
            paths = {i: (s.citation_fields or {}).get("paragraph") or "" for i, s in by_src.items()}
            for i in sorted(mandatory):
                parent_obligation = any(j != i and j in mandatory and paths[j] and paths[i].startswith(paths[j] + "(")
                                        for j in by_src)
                if not parent_obligation and i not in covered and by_src[i].tier == "exact":
                    missing.append(by_src[i].citation)
        if "T" in rules:
            dropped = [c for c, t in getattr(package, "withheld", ()) if OP.strength(t) == OP.MANDATORY]
            if dropped and not missing:
                maybe.append(f"{len(dropped)} obligation-bearing paragraph(s) of the requested provision that were not in "
                             f"the evidence ({', '.join(sorted(set(dropped))[:4])}{' ...' if len(set(dropped)) > 4 else ''})")
        return (missing, maybe) if (missing or maybe) else ([], [])

    GEN.build_package = PIPE.build_package = build
    E._focus_gap = gap
    E._evaluate = evaluate
    try:
        yield
    finally:
        GEN.build_package = PIPE.build_package = orig_build
        E._focus_gap = orig_gap
        E._evaluate = orig_eval
