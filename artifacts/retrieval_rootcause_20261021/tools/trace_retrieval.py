"""Retrieval-only trace of current production behaviour for a bounded question sample. No model, no switch.

    python trace_retrieval.py <out_dir> <question_id> [<question_id> ...]

Guards (installed by ../../cosmetics_benchmark/retrieval_decision_20261021/tools/guarded.py on import):
  * the semantic loader raises (the only path to an embedding model), so any attempt is counted;
  * Database.query allows SELECT/WITH only (the session is read-only as well).
REGULUS_ECFR_LITERAL_OR must be unset: this traces production. Writes only <out_dir>/<ID>.json and summary.json.

Per question:
  * the plan;
  * every retrieval leg: its input and the tsquery PostgreSQL built from it, plus its rows with rank, score and metadata;
  * each stage gate, with the values that decided it;
  * the merged registry in the order selection walks;
  * top-k;
  * the actual selection, and for general questions a step-by-step budget replay checked against it;
  * the final context;
  * for every required section: its live rows, with completeness, duplicates and whether the stored search_vector
    equals its definition recomputed from the stored text;
  * where each required paragraph was lost.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
assert os.environ.get("REGULUS_ECFR_LITERAL_OR") in (None, ""), "trace production: the experimental switch must be unset"
import guarded  # noqa: E402,F401  (installs the guards)
from guarded import SEMANTIC_ATTEMPTS  # noqa: E402

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import selection as SELM  # noqa: E402
from regulus.retrieval import lexical as L  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.evidence import TIER_DISCOVERY, TIER_STRUCTURAL, TIER_SUPPORTING  # noqa: E402
from regulus.retrieval.query import content_terms, definition_term, definitional_terms, fallback_terms  # noqa: E402

assert L.ECFR_LITERAL_OR_ENABLED is False
SEL = {q["ID"]: q for q in json.loads((ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/selection.json")
                                      .read_text(encoding="utf-8"))["questions"]}
LEGS = [n for n in dir(L.LexicalRetriever) if (n.endswith("_ecfr") or n.endswith("_guidance") or n.startswith("exact_"))
        and callable(getattr(L.LexicalRetriever, n))]
CITE = re.compile(r"(\d{2,3}\.\d+[a-z]?)((?:\s*\([a-z0-9]+\)(?:\s*[-–]\s*\([a-z0-9]+\))?\s*,?)*)")


def required(q):
    """{section: set of required top-level paragraph letters} from the verified key citation (empty = whole section)."""
    out = {}
    for m in CITE.finditer(str(q["Expected Citation — VERIFIED KEY"])):
        paras = set()
        for a, b in re.findall(r"\(([a-z])\)(?:\s*[-–]\s*\(([a-z])\))?", m.group(2)):
            paras |= {chr(c) for c in range(ord(a), ord(b or a) + 1)}
        out.setdefault(m.group(1), set()).update(paras)
    return out


def split_cit(label):
    m = re.match(r"21 CFR (\d+\.\d+[a-z]?)((?:\([^)]+\))*)$", label or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def is_required(label, req):
    sec, path = split_cit(label)
    if sec not in req:
        return False
    top = re.match(r"\(([a-z])\)", path or "")
    return not req[sec] or not path or (top is not None and top.group(1) in req[sec])


def tsq(db, text):
    if not isinstance(text, str) or not text:
        return None
    return db.query("SELECT websearch_to_tsquery('english', %(q)s)::text AS q", {"q": text})[0]["q"]


def row(r, i):
    return {"rank": i, "citation": r.citation.label, "corpus": r.corpus, "method": r.retrieval_method,
            "score": round(float(r.relevance_score), 4), "chars": len(r.text or ""),
            "metadata": {k: v for k, v in (r.metadata or {}).items() if k in ("ts_rank_cd", "section_coverage", "paragraph_coverage", "similarity", "heading_match", "ordinal")}}


def budget_replay(out, pipe):
    registry, sel = out.evidence, out.selection
    policy = sel.policy
    steps, chosen, dropped, handled = [], [], [], set()
    used = 0
    gap = lambda: 2 if chosen else 0
    limit = min(policy.max_total_chars, policy.hard_max_total_chars)
    binding_first = policy.general_evidence_order == SELM.ORDER_BINDING_FIRST and SELM._binding_reserve_applies(registry)
    reserve = min(policy.binding_reserve_chars, policy.max_total_chars)
    if reserve > 0 and SELM._binding_reserve_applies(registry) and not binding_first:
        spent = 0
        for tier in (TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY):
            for e in registry.evidence:
                if e.tier != tier or e.evidence_id in handled or e.result.corpus != "ecfr":
                    continue
                if tier != TIER_STRUCTURAL and not pipe.is_useful(e.result):
                    continue
                if len(chosen) >= policy.max_results:
                    continue
                text, trunc = SELM._truncate(SELM._clean(e.text), policy.max_chars_per_result)
                chars = SELM._block_chars(e, text, len(chosen) + 1, trunc)
                st = {"phase": "eCFR reserve", "citation": e.citation, "tier": e.tier, "block_chars": chars, "used_before": used,
                      "reserve_spent_before": spent}
                if spent + chars > reserve or used + gap() + chars > limit:
                    st["outcome"] = "not reserved"
                else:
                    spent += chars
                    used += gap() + chars
                    chosen.append(e.evidence_id)
                    handled.add(e.evidence_id)
                    st["outcome"] = "reserved"
                steps.append(st)
    for e in SELM._optional_order(registry, binding_first):
        if e.evidence_id in handled:
            continue
        st = {"phase": "soft budget", "citation": e.citation, "tier": e.tier, "used_before": used}
        if e.tier != TIER_STRUCTURAL and not pipe.is_useful(e.result):
            st["outcome"] = "dropped: filtered"; dropped.append((e.citation, "filtered")); steps.append(st); continue
        if len(chosen) >= policy.max_results:
            st["outcome"] = "dropped: max_results"; dropped.append((e.citation, "max_results")); steps.append(st); continue
        text, trunc = SELM._truncate(SELM._clean(e.text), policy.max_chars_per_result)
        chars = SELM._block_chars(e, text, len(chosen) + 1, trunc)
        st["block_chars"] = chars
        if used + gap() + chars > limit:
            remaining = limit - used - gap()
            if remaining - (chars - len(text)) >= SELM.MIN_SQUEEZED_CHARS:
                text, trunc = SELM._truncate(text, remaining - (chars - len(text)))
                chars = SELM._block_chars(e, text, len(chosen) + 1, True)
                st["outcome"], st["block_chars"] = "selected (squeezed)", chars
            else:
                st["outcome"] = "dropped: soft_budget"; st["remaining"] = remaining
                dropped.append((e.citation, "soft_budget")); steps.append(st); continue
        else:
            st["outcome"] = "selected"
        used += gap() + chars
        chosen.append(e.evidence_id)
        steps.append(st)
    ok = sorted(chosen) == sorted(s.evidence.evidence_id for s in sel.selected) and \
        sorted(dropped) == sorted((d.evidence.citation, d.reason) for d in sel.dropped)
    return {"steps": steps, "replay_matches_selection": ok}


SV_SQL = """
SELECT column_name, is_generated, generation_expression FROM information_schema.columns
WHERE table_name = 'cfr_records' AND column_name = 'search_vector'
"""


def source_rows(db, sections, sv_expr):
    out = {}
    for sec in sorted(sections):
        rows = db.query("SELECT section_number, paragraph_path, ordinal, length(body_text) AS chars, right(body_text, 90) AS tail, "
                        "removed_on, is_reserved, section_heading FROM cfr_records WHERE section_number = %(s)s ORDER BY ordinal", {"s": sec})
        live = [r for r in rows if r["removed_on"] is None]
        paths = [r["paragraph_path"] or "" for r in live]
        dup = sorted({p for p in paths if paths.count(p) > 1})
        sv_ok = None
        if sv_expr:
            sv_ok = db.query(f"SELECT bool_and(search_vector = ({sv_expr})) AS ok FROM cfr_records r WHERE section_number = %(s)s AND removed_on IS NULL",
                             {"s": sec})[0]["ok"]
        out[sec] = {"live_rows": [{"path": r["paragraph_path"] or "(section)", "ordinal": r["ordinal"], "chars": r["chars"],
                                   "tail": (r["tail"] or "").rstrip(), "reserved": r["is_reserved"],
                                   "ends_open": (r["tail"] or "").rstrip().endswith((":", "following", "—")),
                                   "has_children": any(q.startswith((r["paragraph_path"] or "") + "(") for q in paths) if r["paragraph_path"] else None}
                                  for r in live],
                    "removed_rows": len(rows) - len(live), "duplicate_live_paths": dup, "search_vector_matches_text": sv_ok,
                    "heading": live[0]["section_heading"] if live else None}
    return out


def main() -> int:
    out_dir = Path(sys.argv[1]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = sys.argv[2:]
    db = Database.from_env()
    db.connect()
    summary = {}
    try:
        st = {k: v for k, v in db.status().items() if k != "url"}
        assert st["default_transaction_read_only"] == "on", st
        fp0 = RB.database_fingerprint(db)
        sv = db.query(SV_SQL)
        sv_expr = sv[0]["generation_expression"] if sv and sv[0]["is_generated"] == "ALWAYS" else None
        pipe, gen = RB.production_pipeline(db)
        lex = pipe.retriever.lexical
        calls: list = []
        for name in LEGS:
            fn = getattr(lex, name)

            def wrapped(*a, _fn=fn, _name=name, **k):
                rows = _fn(*a, **k)
                inp = next((x for x in a if isinstance(x, str)), None)
                calls.append({"leg": _name, "input": inp if inp is not None else repr(a[0])[:200],
                              "tsquery": tsq(db, inp) if _name.startswith(("full_text", "section_coverage")) else None,
                              "limit": next((x for x in reversed(a) if isinstance(x, int)), None),
                              "rows": [row(r, i) for i, r in enumerate(rows, 1)]})
                return rows
            setattr(lex, name, wrapped)
        for qid in ids:
            q = SEL[qid]
            question = q["Question (ask verbatim)"]
            calls.clear()
            out = pipe.answer(question)
            md = out.metadata
            plan = plan_query(question)
            nq = plan.normalized_question or plan.question
            ret = md.get("retrieval") or {}
            req = required(q)
            counts = {}
            for c in calls:
                counts[c["leg"]] = counts.get(c["leg"], 0) + len(c["rows"])
            registry = [{"pos": i, "citation": e.citation, "corpus": e.result.corpus, "method": e.result.retrieval_method, "tier": e.tier,
                         "score": round(float(e.result.relevance_score), 4), "heading_match": bool((e.result.metadata or {}).get("heading_match")),
                         "required": is_required(e.citation, req)} for i, e in enumerate(out.evidence.evidence, 1)]
            topk = [r.citation.label for r in out.retrieved_results]
            sel = out.selection
            final = [{"index": s.index, "citation": s.result.citation.label, "tier": s.tier, "method": s.result.retrieval_method,
                      "chars": len(s.text), "truncated": s.truncated, "required": is_required(s.result.citation.label, req)}
                     for s in out.context.sources]
            general = not plan.requirements and plan.docket is None
            gates = {
                "plan_kind": plan.kind, "query_type": plan.query_type.name, "requirements": [r.canonical for r in plan.requirements],
                "docket": plan.docket, "normalized_question": nq,
                "definition_term": definition_term(nq) if not plan.requirements else None,
                "full_text_ran": any(c["leg"] == "full_text_ecfr" for c in calls),
                "ecfr_all_words_rows": counts.get("full_text_ecfr", 0),
                "primary_min_results": lex.primary_min_results,
                "section_coverage_gate": general and counts.get("full_text_ecfr", 0) < lex.primary_min_results,
                "section_coverage_terms": " ".join(content_terms(nq)) if general else None,
                "section_coverage": ret.get("section_coverage"),
                "or_fallback_used": ret.get("fallback_used"), "or_fallback_terms": ret.get("fallback_terms") or fallback_terms(nq, lex.fallback_max_terms),
                "primary_result_count": ret.get("primary_result_count"),
                "defined_terms_weights": definitional_terms(nq) if general else None,
                "heading_corroboration": lex.heading_corroboration, "cross_references": lex.cross_references,
                "semantic_fallback": md.get("semantic_fallback") or ret.get("semantic_fallback"),
                "legs_called": [c["leg"] for c in calls],
            }
            all_cands = {r["citation"] for c in calls for r in c["rows"]}
            req_status = {}
            src = source_rows(db, set(req), sv_expr)
            for sec, paras in req.items():
                labels = [f"21 CFR {sec}{'(' + p + ')' if p else ''}" for p in (sorted(paras) or [""])]
                for lab in labels:
                    s0, p0 = split_cit(lab)
                    match = lambda c: split_cit(c)[0] == s0 and (not p0 or (split_cit(c)[1] or "").startswith(p0))
                    in_store = any((r["path"] if r["path"] != "(section)" else "").startswith(p0 or "") for r in src[sec]["live_rows"])
                    stage = ("in final context" if any(match(f["citation"]) for f in final) else
                             "dropped at selection" if any(match(d.evidence.citation) for d in sel.dropped) else
                             "in registry, not selected" if any(match(r["citation"]) for r in registry) else
                             "returned by a leg, lost before registry" if any(match(c) for c in all_cands) else
                             "never returned by any leg" if in_store else "absent from the source store")
                    req_status[lab] = {"in_store": in_store, "stage": stage,
                                       "drop_reason": next((d.reason for d in sel.dropped if match(d.evidence.citation)), None)}
            rec = {"id": qid, "question": question, "key_citation": str(q["Expected Citation — VERIFIED KEY"]), "required": {k: sorted(v) for k, v in req.items()},
                   "gates": gates, "legs": list(calls), "registry": registry, "topk": topk,
                   "selection": {"total_chars": sel.total_chars, "dropped": [(d.evidence.citation, d.reason) for d in sel.dropped],
                                 "diagnostics": {k: v for k, v in sel.diagnostics.items() if k in ("required_count", "required_chars", "binding_reserved", "tier_counts", "required_dropped", "required_truncated")}},
                   "budget_replay": budget_replay(out, pipe) if general else None,
                   "final_context": final, "source": src, "required_status": req_status,
                   "search_vector_definition": sv_expr}
            (out_dir / f"{qid}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            summary[qid] = {"required_status": {k: v["stage"] for k, v in req_status.items()},
                            "legs": gates["legs_called"], "replay_ok": rec["budget_replay"]["replay_matches_selection"] if rec["budget_replay"] else None}
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    summary["_run"] = {"semantic_load_attempts": len(SEMANTIC_ATTEMPTS), "generation_stub_calls": gen.calls,
                       "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
                       "search_vector_generated": bool(sv_expr)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
