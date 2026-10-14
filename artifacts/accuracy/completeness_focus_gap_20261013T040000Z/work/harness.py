"""Production evaluation packages for completeness experiments. No model, no generation.

`package_for(question)` runs the production pipeline's retrieval, selection and package build (the
answering UI's configuration, top_k 8), so each package carries the real focused answer plan and
section headings. `evaluate(question, answer)` scores an answer TEXT against that package, exactly
as the live evaluator would. `focus_gap_rule(...)` swaps evaluator._focus_gap for a candidate rule
for the duration of a block, so old and new can be compared on identical inputs.
"""
from __future__ import annotations
import contextlib, sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))


class Stub:
    def describe(self): return {"generator": "none"}
    def generate(self, *a, **k): raise AssertionError("no generation")


_STATE: dict = {}


def _setup():
    if _STATE:
        return _STATE
    from regulus.config import load_settings
    from regulus.rag import RagPipeline
    from regulus.retrieval import Database, LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config
    settings = load_settings(); db = Database.from_env(); db.connect()
    config = replace(configured_rag_config(settings), top_k=8)
    retriever, scope = build_retriever(db, config, lexical=LexicalRetriever(db))
    _STATE.update(db=db, config=config, retriever=retriever,
                  pipe=RagPipeline(retriever, Stub(), config, scope_policy=scope))
    return _STATE


@lru_cache(maxsize=None)
def package_for(question: str):
    from regulus.planning import plan_query
    from regulus.rag.generation import build_package
    from regulus.retrieval import Filters
    st = _setup(); pipe, retriever, config = st["pipe"], st["retriever"], st["config"]
    plan = pipe.complete_plan(plan_query(question)); shape, analysis = pipe.question_view(plan)
    out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k, filters=Filters())
    bundle, coverage, sel = pipe.build_bundle(out.response, out.registry, shape, question)
    if sel is None or coverage is None:
        return None, None
    pkg = build_package(plan, coverage, sel, notes=bundle.notes, budget=pipe.config.generation_budget,
                        answer_shape=shape, question_analysis=analysis)
    return pkg, coverage


def evaluate(question: str, answer: str):
    from regulus.accuracy import evaluate_safely
    pkg, coverage = package_for(question)
    return evaluate_safely(question, answer, package=pkg, coverage=coverage)


def completeness(a) -> tuple[str, str]:
    d = next(x for x in a.to_dict()["dimensions"] if x["dimension"] == "completeness")
    return d["state"], str(d.get("detail") or "")


@contextlib.contextmanager
def focus_gap_rule(rule):
    """rule: None for the production _focus_gap, else a replacement with the same signature."""
    from regulus.accuracy import evaluator as E
    original = E._focus_gap
    if rule is not None:
        E._focus_gap = rule
    try:
        yield
    finally:
        E._focus_gap = original


def explain_focus_gap(package, intent, answering, claims, passages, *, rule="production"):
    """A line-for-line copy of evaluator._focus_gap that also records WHY each group was or was not
    demanded. rule="production" must reproduce the real function's result exactly (checked by the
    caller); rule="distinguishing" adds the candidate filter. Returns (result, per-group trace)."""
    from regulus.accuracy import answer as AN, operators as OP, relevance as RV
    from regulus.accuracy.intent import matched, terms
    plan = getattr(package, "answer_plan", None)
    if plan is None or getattr(getattr(plan, "shape", None), "mode", None) != "focused" or not intent.topic:
        return None, []
    requested = {rid for rid, _ in (getattr(package, "requirements", None) or ())}
    by_index = {p.source_index: p for p in passages}
    decided = (AN.SUPPORTED, AN.SUPPORTED_WITH_CITATION_DEFECT, AN.PARTIALLY_SUPPORTED, AN.CONTRADICTED)
    covered = {e.get("source_index") for c in answering if c.final in decided for e in c.evidence[:1]}
    by_citation = {p.citation: p.source_index for p in passages}
    touched = {e.get("source_index") for c in claims if c.final == AN.UNVERIFIABLE for e in c.evidence}
    touched |= {by_citation.get(c.candidate_evidence[0]) for c in claims
                if c.final == AN.UNVERIFIABLE and c.candidate_evidence}
    # obligation-bearing requirement groups of the requested provision (the candidate's population)
    eligible = []
    for g in getattr(plan, "groups", ()) or ():
        if getattr(g, "kind", None) != "requirement" or not set(g.requirement_ids) & requested:
            continue
        members = [by_index[i] for i in g.members if i in by_index]
        if members and any(OP.strength(p.text) == OP.MANDATORY for p in members) and RV.on_topic(intent, members):
            eligible.append((g, members))
    group_terms = {g.key: set(matched(intent.topic, terms(" ".join(f"{p.heading or ''} {p.text}" for p in m))))
                   for g, m in eligible}
    present = set().union(*group_terms.values()) if group_terms else set()
    shared = set.intersection(*group_terms.values()) if group_terms else set()
    distinguishing = present - shared if len(eligible) >= 2 else set()
    missing, maybe, trace = [], [], []
    for g in getattr(plan, "groups", ()) or ():
        row = {"group": g.label, "members": list(g.members)}
        trace.append(row)
        if getattr(g, "kind", None) != "requirement" or not set(g.requirement_ids) & requested:
            row["decision"] = "not a requirement group of the requested provision"; continue
        members = [by_index[i] for i in g.members if i in by_index]
        if not members or covered & set(g.members):
            row["decision"] = "covered" if members else "no passages"; continue
        if not any(OP.strength(p.text) == OP.MANDATORY for p in members):
            row["decision"] = "states no obligation"; continue
        on = RV.on_topic(intent, members)
        row["on_topic_hits"] = {p.source_index: list(h) for p, h in on}
        if not on:
            row["decision"] = "off the question's topic"; continue
        if rule == "distinguishing" and distinguishing and not (group_terms.get(g.key, set()) & distinguishing):
            row["decision"] = f"on topic only through words every group shares ({sorted(shared)}); none of {sorted(distinguishing)}"
            continue
        label = g.label + (f" ({g.heading})" if getattr(g, "heading", None) else "")
        if touched & set(g.members):
            maybe.append(label); row["decision"] = "addressed only by unverifiable statements"
        else:
            missing.append(label); row["decision"] = "DEMANDED, not covered"
    return (missing, maybe), trace + [{"shared": sorted(shared), "distinguishing": sorted(distinguishing),
                                      "eligible_groups": [g.label for g, _ in eligible]}]


def recording_rule(store, rule):
    """A _focus_gap replacement that runs explain_focus_gap and records its trace into `store`."""
    from regulus.accuracy import evaluator as E
    production = E._focus_gap

    def run(package, intent, answering, claims, passages):
        result, trace = explain_focus_gap(package, intent, answering, claims, passages, rule=rule)
        if rule == "production":
            assert result == production(package, intent, answering, claims, passages), "the copy drifted"
        store.append({"result": result, "trace": trace, "topic": list(intent.topic)})
        return result
    return run
