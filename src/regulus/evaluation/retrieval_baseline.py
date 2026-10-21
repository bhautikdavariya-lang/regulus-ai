"""Retrieval-only baseline: does each question's expected CFR section reach the model's prompt?

Phase 1 of the retrieval work that followed the read-only audit of 2026-10-20. For every question of a frozen
gold set it runs the production answering pipeline as scripts/serve_ui.py configures it (configured_rag_config,
the retriever and scope policy from regulus.retrieval.factory, top_k 8, grounding gate off) with a generator
stub in place of the model: nothing is generated, Qwen is never loaded, no external service is called. From the
pipeline's own objects it records, per expected target:

    exists_in_db      the section (paragraph, part, docket) is live in the database snapshot
    candidate_rank    1-based rank in the evidence registry: every candidate any retrieval leg found, in the
                      pipeline's own order, before any cut
    topk_rank         rank in the retriever's top_k result list
    selection         selected / dropped (with the selector's own reasons) / not a candidate
    in_context        one of the sources selected for the prompt
    reaches_prompt    in_context AND the pipeline would call the model (no gate blocked the question)

and, per question, the context-budget use, the answerability gate, the scope decision and the semantic fallback.

Gold keys are NOT expert-verified. Every row carries `key_status` and `sme_verified`; every metric is a
measurement against those keys, never an accuracy figure. Matching follows regulus.evaluation.retrieval_eval:
"21 CFR 820.10(b)" is met by (b) and its subparagraphs; at section level by any row of 820.10.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from regulus.config import PROJECT_ROOT
from regulus.evaluation.retrieval_eval import target_matches
from regulus.inference.types import GenerationResult

DATASET_VERSION = "retrieval_baseline_v1"
DEFAULT_DATASET = PROJECT_ROOT / "data" / "evaluation" / "datasets" / f"{DATASET_VERSION}.jsonl"
RETRIEVAL_V2 = PROJECT_ROOT / "data" / "evaluation" / "datasets" / "retrieval_v2.jsonl"
BENCHMARK_KEY = PROJECT_ROOT / "artifacts" / "benchmark_keys" / "regulus_acceptance_rev02@c009d5f9c649" / "baseline.json"

KEY_DEVELOPER = "developer_keyed_not_sme"   # retrieval_v2.jsonl: curated by the developers, never SME-reviewed
KEY_DRAFT = "draft_unverified"              # the acceptance benchmark's expected_citation_draft
KEY_AUDIT = "audit_reading_unverified"      # an alternative the 2026-10-20 audit proposed; needs an SME
KEY_NONE = "no_cfr_key"                     # the row's key names no CFR provision (statute, scope, refusal)

SOURCE_V2 = "retrieval_v2"
SOURCE_BENCHMARK = "benchmark_rev02"

CLASS_IDENTIFIER = "identifier"             # the pipeline's own plan names a CFR provision or a docket
CLASS_PLAIN = "plain_language"

STAGE_CORPUS_GAP = "corpus_gap"
STAGE_NOT_RETRIEVED = "not_retrieved"
STAGE_UNATTRIBUTED = "candidate_unattributed"   # a candidate the selector neither selected nor recorded as dropped
STAGE_DROPPED = "dropped"
STAGE_CONTEXT_BLOCKED = "in_context_model_not_called"
STAGE_IN_PROMPT = "in_prompt"
STAGES = (STAGE_CORPUS_GAP, STAGE_NOT_RETRIEVED, STAGE_UNATTRIBUTED, STAGE_DROPPED, STAGE_CONTEXT_BLOCKED, STAGE_IN_PROMPT)

RECALL_KS = (1, 3, 5, 8, 10, 20)
SOFT_BUDGET_NEAR_FULL = 0.95
VOLATILE_KEYS = ("timings",)

# The eight failures traced by the 2026-10-20 audit (docs: the audit report; scratch traces under the session).
AUDIT_FAILURE_CASES = {
    "retrieval-015": "803.50 was candidate #22 and was dropped by soft_budget behind AND-matched guidance",
    "D-016": "211.125 had the top score (5.00) but section-coverage rows are placed last; dropped",
    "S-007": "draft key 111.16 never retrieved; 111.15 (the audit's reading) had the top score and was dropped",
    "K-005": "56.111 trigram hit filtered (similarity 0.354 < 0.4); 56.107 coverage rank 6 > the 4 kept",
    "P-009": "812.2 / 812.3 never candidates (coverage rank 5 / 13 > the 4 kept)",
    "retrieval-037": "312.20 never a candidate (coverage rank 6 > the 4 kept)",
    "retrieval-027": "820.10(c): no Part 820 row contains 'design control' (QMSR incorporates ISO 13485 7.3)",
    "retrieval-032": "'new' and 'drug' are stop-listed; the OR fallback searched approved / medical / sold",
}
AUDIT_ALTERNATIVES = {
    "S-007": ("21 CFR 111.15", "111.16 is headed 'written procedures'; water supply sits in 111.15 (sanitation of "
                               "the physical plant). Audit reading only: an SME must confirm."),
}

_SECTION_TARGET = re.compile(r"^21 CFR (?P<section>\d{1,4}\.\d{1,4}[a-z]?)(?P<para>(?:\([A-Za-z0-9]{1,4}\))*)$")
_PART_TARGET = re.compile(r"^21 CFR part (?P<part>\d{1,4})$", re.I)
_WORD = re.compile(r"[a-z][a-z\-]+")


# ---------------------------------------------------------------- dataset

def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target_kind(target: str) -> str:
    if _SECTION_TARGET.match(target):
        return "paragraph" if _SECTION_TARGET.match(target).group("para") else "section"
    if _PART_TARGET.match(target):
        return "part"
    if target.startswith("docket:"):
        return "docket"
    if target.startswith("guidance:"):
        return "guidance"
    return "unknown"


def _row(rid: str, source: str, source_sha: str, question: str, category: str, expected: list[str], *,
         negative: bool, key_text: Any, key_status: str, sme_verified: bool, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    alt = AUDIT_ALTERNATIVES.get(rid)
    row = {
        "id": rid, "source": source, "source_sha256": source_sha, "question": question, "category": category,
        "expected": expected, "expected_kinds": sorted({target_kind(t) for t in expected}),
        "is_negative_control": negative, "key_text": key_text, "key_status": key_status, "sme_verified": sme_verified,
        "audit_failure_case": rid in AUDIT_FAILURE_CASES, "audit_note": AUDIT_FAILURE_CASES.get(rid),
        "alternative_expected": [alt[0]] if alt else [], "alternative_key_status": KEY_AUDIT if alt else None,
        "alternative_note": alt[1] if alt else None,
    }
    row.update(extra or {})
    return row


def build_dataset(retrieval_v2: Path = RETRIEVAL_V2, benchmark_key: Path = BENCHMARK_KEY) -> list[dict[str, Any]]:
    """The frozen gold set, deterministically: every retrieval_v2 query, then every benchmark question in key order.

    retrieval_v2 negatives follow retrieval_eval's convention (an empty `expected` list). Benchmark negative
    controls get NO expected target even when their key text mentions a section ("NO SUCH SECTION - ... 21 CFR
    111.900"): that text says what must not be found, not what should be. Benchmark keys are parsed with the
    pipeline's own reference scanner, so "21 CFR 211.122; 211.125" yields both sections."""
    from regulus.retrieval.references import parse_cfr_references

    rows: list[dict[str, Any]] = []
    v2_sha = _sha256_file(retrieval_v2)
    for line in retrieval_v2.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        expected = list(r.get("expected") or [])
        rows.append(_row(r["id"], SOURCE_V2, v2_sha, r["query"], r.get("category", ""), expected,
                         negative=not expected, key_text=expected, key_status=KEY_DEVELOPER, sme_verified=False,
                         extra={"identifier_exists_in_snapshot": r.get("identifier_exists_in_snapshot")}))
    bench_sha = _sha256_file(benchmark_key)
    for q in json.loads(benchmark_key.read_text(encoding="utf-8"))["questions"]:
        text = q.get("expected_citation_draft") or ""
        negative = bool(q.get("is_negative_control"))
        expected = [] if negative else list(dict.fromkeys(r.canonical for r in parse_cfr_references(text)))
        status = KEY_DRAFT if (expected or negative) else KEY_NONE
        rows.append(_row(q["question_id"], SOURCE_BENCHMARK, bench_sha, q["question"], q.get("question_type", ""), expected,
                         negative=negative, key_text=text, key_status=status, sme_verified=bool(q.get("key_is_verified")),
                         extra={"domain": q.get("domain")}))
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids across the gold-set sources")
    return rows


def load_dataset(path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------- matching and attribution

def covers(target: str, result, *, level: str = "provision") -> bool:
    """`result` (a RetrievalResult) satisfies `target`. level="section": any row of the target's section."""
    m = _PART_TARGET.match(target)
    if m:
        return result.corpus == "ecfr" and (result.citation.part or "") == m.group("part")
    if level == "section":
        s = _SECTION_TARGET.match(target)
        if s:
            return result.corpus == "ecfr" and result.citation.section == s.group("section")
    return target_matches(target, result)


def attribute(target: str, *, exists: bool | None, candidates: list, topk: list, selected: list[tuple[int, Any]],
              dropped: list[tuple[Any, str]], model_called: bool, level: str = "provision") -> dict[str, Any]:
    """Where one expected target stops: corpus_gap / not_retrieved / dropped / in context but the model is not
    called / in_prompt. `candidates` is the registry order, `topk` the retriever's result list, `selected` the
    (SOURCE number, result) pairs of the prompt context, `dropped` the selector's (result, reason) pairs."""
    cand = [n for n, r in enumerate(candidates, start=1) if covers(target, r, level=level)]
    top = [n for n, r in enumerate(topk, start=1) if covers(target, r, level=level)]
    indices = [i for i, r in selected if covers(target, r, level=level)]
    reasons = list(dict.fromkeys(reason for r, reason in dropped if covers(target, r, level=level)))
    if exists is False:
        stage = STAGE_CORPUS_GAP
    elif indices:
        stage = STAGE_IN_PROMPT if model_called else STAGE_CONTEXT_BLOCKED
    elif reasons:
        stage = STAGE_DROPPED
    elif cand:
        stage = STAGE_UNATTRIBUTED
    else:
        stage = STAGE_NOT_RETRIEVED
    return {"target": target, "kind": target_kind(target), "level": level, "exists_in_db": exists,
            "candidate_rank": cand[0] if cand else None, "candidate_rows": len(cand),
            "topk_rank": top[0] if top else None, "in_context": bool(indices), "prompt_indices": indices,
            "drop_reasons": reasons, "reaches_prompt": bool(indices) and model_called, "stage": stage}


# ---------------------------------------------------------------- database lookups (read-only)

class CorpusLookup:
    """Existence and headings of expected targets in the live snapshot; cached, SELECT only."""

    def __init__(self, db) -> None:
        self.db = db
        self._exists: dict[str, dict[str, Any]] = {}
        self._heading: dict[str, str | None] = {}

    def exists(self, target: str) -> dict[str, Any]:
        if target in self._exists:
            return self._exists[target]
        s, p = _SECTION_TARGET.match(target), _PART_TARGET.match(target)
        if s:
            para = s.group("para")
            n = self.db.query(
                "SELECT count(*) AS n FROM cfr_records WHERE section_number = %(s)s AND removed_on IS NULL AND NOT is_reserved"
                " AND (%(p)s = '' OR paragraph_path = %(p)s OR paragraph_path LIKE %(prefix)s)",
                {"s": s.group("section"), "p": para, "prefix": para + "(%"})[0]["n"]
            info = {"exists": n > 0, "live_rows": int(n)}
        elif p:
            n = self.db.query("SELECT count(*) AS n FROM cfr_records WHERE part_number = %(p)s AND removed_on IS NULL"
                              " AND NOT is_reserved", {"p": p.group("part")})[0]["n"]
            info = {"exists": n > 0, "live_rows": int(n)}
        elif target.startswith("docket:"):
            row = self.db.query("SELECT count(*) AS n, count(*) FILTER (WHERE retrievable) AS r FROM fda_guidance"
                                " WHERE upper(docket_number) = upper(%(d)s)", {"d": target[7:]})[0]
            info = {"exists": row["r"] > 0, "documents": int(row["n"]), "retrievable_documents": int(row["r"])}
        else:
            info = {"exists": None}
        self._exists[target] = info
        return info

    def heading(self, target: str) -> str | None:
        s = _SECTION_TARGET.match(target)
        if not s:
            return None
        sec = s.group("section")
        if sec not in self._heading:
            rows = self.db.query("SELECT heading FROM cfr_sections WHERE number = %(s)s", {"s": sec})
            self._heading[sec] = rows[0]["heading"] if rows else None
        return self._heading[sec]


def heading_overlap(question: str, heading: str | None) -> int | None:
    """Content words the question shares with a section heading (the OR fallback's stop lists applied). A
    review-priority signal for the key only - never a verdict on it."""
    if heading is None:
        return None
    from regulus.retrieval.query import _STOP_TERMS

    def words(text: str) -> set[str]:
        return {w[:-1] if w.endswith("s") and not w.endswith("ss") else w
                for w in _WORD.findall(text.lower()) if len(w) >= 3 and w not in _STOP_TERMS}
    return len(words(question) & words(heading))


# ---------------------------------------------------------------- the pipeline, without a model

class NoGenerator:
    """Stands in for the model: counts generation requests and returns no text. Qwen is never loaded."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, max_new_tokens=None, on_text=None) -> GenerationResult:
        self.calls += 1
        return GenerationResult(prompt="", response="", prompt_tokens=0, generated_tokens=0, seconds=0.0, finished=True)

    def describe(self) -> dict[str, Any]:
        return {"model_id": "none (retrieval baseline: generation is never run)"}


def production_pipeline(db, *, semantic: str = "production", top_k: int = 8, general_evidence_order: str | None = None,
                        min_trigram_similarity: float | None = None):
    """The answering pipeline as scripts/serve_ui.py builds it for a default request (grounding off, no adapter,
    top_k 8), with NoGenerator. semantic="off" disables the semantic fallback (a diagnostic, not production).
    general_evidence_order (ContextPolicy) is the one experimental switch; None keeps the configured value."""
    from regulus.config import load_settings
    from regulus.rag.pipeline import RagPipeline
    from regulus.retrieval.factory import build_retriever
    from regulus.retrieval.lexical import LexicalRetriever
    from regulus.system_identity import configured_rag_config

    config = configured_rag_config(load_settings())
    if semantic == "off":
        config = replace(config, semantic_fallback="off")
    if general_evidence_order is not None:
        config = replace(config, context=replace(config.context, general_evidence_order=general_evidence_order))
    if min_trigram_similarity is not None:   # Phase 4 experiment: the existing RagConfig cut-off, overridden for this run only
        config = replace(config, min_trigram_similarity=float(min_trigram_similarity))
    retriever, scope = build_retriever(db, config, lexical=LexicalRetriever(db))
    generator = NoGenerator()
    pipe = RagPipeline(retriever, generator, replace(config, top_k=top_k), grounding=None, scope_policy=scope)
    return pipe, generator


def _named(plan: dict[str, Any]) -> list[str]:
    return [r["canonical"] for r in plan.get("requirements") or ()]


def run_question(pipe, generator: NoGenerator, lookup: CorpusLookup, row: dict[str, Any]) -> dict[str, Any]:
    """One question through the pipeline; the record described in the module docstring."""
    base = {k: row[k] for k in ("id", "source", "question", "category", "key_status", "sme_verified", "is_negative_control",
                                "audit_failure_case", "expected", "alternative_expected", "alternative_key_status")}
    calls_before = generator.calls
    t0 = time.perf_counter()
    try:
        out = pipe.answer(row["question"])
    except Exception as exc:  # recorded, never hidden: one failing question must not stop the baseline
        return {**base, "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "timings": {"wall_ms": round((time.perf_counter() - t0) * 1000, 1)}}
    wall_ms = round((time.perf_counter() - t0) * 1000, 1)
    md = out.metadata
    plan = md.get("original_plan") or md.get("plan") or {}
    named = _named(plan)
    question_class = CLASS_IDENTIFIER if (named or plan.get("docket")) else CLASS_PLAIN
    candidates = [e.result for e in (out.evidence.evidence if out.evidence is not None else ())]
    topk = list(out.retrieved_results)
    sel = out.selection
    selected = [(s.index, s.evidence.result) for s in (sel.selected if sel is not None else ())]
    dropped = [(d.evidence.result, d.reason) for d in (sel.dropped if sel is not None else ())]
    model_called = bool(out.model_called)
    gen_requested = generator.calls > calls_before

    def trace(targets: Iterable[str]) -> list[dict[str, Any]]:
        out_rows = []
        for t in targets:
            info = lookup.exists(t)
            for level in ("section", "provision") if target_kind(t) == "paragraph" else ("provision",):
                exists = info.get("exists")
                if level == "section":
                    exists = lookup.exists(f"21 CFR {_SECTION_TARGET.match(t).group('section')}").get("exists")
                a = attribute(t, exists=exists, candidates=candidates, topk=topk, selected=selected, dropped=dropped,
                              model_called=model_called, level=level)
                a["db"] = info
                if target_kind(t) in ("section", "paragraph"):
                    a["heading"] = lookup.heading(t)
                    a["heading_overlap_words"] = heading_overlap(row["question"], a["heading"])
                out_rows.append(a)
        return out_rows

    selected_items = list(sel.selected) if sel is not None else []
    chars_by_corpus = Counter()
    for s in selected_items:
        chars_by_corpus[s.evidence.result.corpus] += s.chars
    policy = sel.policy if sel is not None else None
    prompt_keys = {s.key for s in out.package.sources} if out.package is not None else None
    retrieval = md.get("retrieval") or {}
    answerability = md.get("answerability") or {}
    semantic = dict(md.get("semantic_fallback") or {}) or None
    semantic_ms = {k: semantic.pop(k) for k in [k for k in (semantic or {}) if k.endswith("_ms")]} if semantic else {}
    record = {
        **base,
        "question_class": question_class,
        "plan": {"kind": plan.get("kind"), "query_type": plan.get("query_type"), "named": named, "docket": plan.get("docket"),
                 "reference_lookup": md.get("reference_lookup")},
        "targets": trace(row["expected"]),
        "alternative_targets": trace(row.get("alternative_expected") or ()),
        "named_identifiers": [{"target": n, **lookup.exists(n)} for n in named],
        "retrieval": {"mode": retrieval.get("retrieval_mode"), "fallback_used": retrieval.get("fallback_used"),
                      "fallback_terms": retrieval.get("fallback_terms"), "section_coverage": retrieval.get("section_coverage"),
                      "legs": md.get("retrieval_counts"), "candidates": len(candidates), "topk": len(topk),
                      "exact_cfr_in_topk": sum(1 for r in topk if r.retrieval_method == "exact_cfr"),
                      # the plan path fetches an existing parent paragraph as structural context under the exact_cfr
                      # method ("Explain 201.327(z)" -> the 201.327 lead-in); this count leaves those rows out
                      "exact_cfr_in_topk_excluding_parent_rows": sum(
                          1 for r in topk if r.retrieval_method == "exact_cfr" and (r.metadata or {}).get("match_kind") != "parent"),
                      "semantic_fallback": semantic},
        "context": {"sources": len(selected_items), "total_chars": sel.total_chars if sel is not None else 0,
                    "ecfr_chars": chars_by_corpus.get("ecfr", 0), "guidance_chars": chars_by_corpus.get("fda_guidance", 0),
                    "required_chars": sum(s.chars for s in selected_items if s.protected),
                    "optional_chars": sum(s.chars for s in selected_items if not s.protected),
                    "soft_budget_chars": policy.max_total_chars if policy else None,
                    "hard_ceiling_chars": policy.hard_max_total_chars if policy else None,
                    "dropped_by_reason": dict(Counter(r for _, r in dropped)),
                    "binding_reserved": (sel.diagnostics.get("binding_reserved") if sel is not None else None),
                    "required_only": bool(sel.diagnostics.get("required_only")) if sel is not None else False,
                    "evidence_gap": md.get("evidence_gap"),
                    "prompt_matches_selection": (prompt_keys == {s.evidence.key for s in selected_items}
                                                 if prompt_keys is not None else None)},
        # Decisions taken BEFORE generation only. When the model would be called, the pipeline's later fallback
        # (validation, repair, withholding) acts on the stub's empty text and says nothing about production, so
        # it is not recorded.
        "gate": {"state": answerability.get("state"), "blocked": bool(md.get("generation_blocked")),
                 "conditions": answerability.get("blocking_conditions"),
                 "pre_generation_fallback": None if model_called else md.get("fallback_type"),
                 "coverage_action": md.get("coverage_action"),
                 "scope": (md.get("scope_policy") or {}).get("status")},
        "model_would_be_called": model_called,
        "generation_requested": gen_requested,
        "timings": {"wall_ms": wall_ms, **{k: v for k, v in (out.timings_ms or {}).items() if k.endswith("_ms")},
                    **{f"semantic_fallback.{k}": v for k, v in semantic_ms.items()}},
    }
    return record


# ---------------------------------------------------------------- metrics

def _cfr_targets(rec: dict[str, Any], level: str) -> list[dict[str, Any]]:
    """The record's CFR section/paragraph targets at one level (section-level rows exist for paragraph targets;
    a section target's single row serves both levels)."""
    out = []
    for t in rec.get("targets") or ():
        if t["kind"] == "section" or (t["kind"] == "paragraph" and t["level"] == level):
            out.append(t)
    return out


def is_section_scored(rec: dict[str, Any]) -> bool:
    return not rec.get("is_negative_control") and not rec.get("error") and bool(_cfr_targets(rec, "section"))


def question_metrics(recs: list[dict[str, Any]], *, level: str = "section") -> dict[str, Any]:
    """Question-level: a question counts when ANY of its expected sections reaches the stage."""
    rows = [r for r in recs if is_section_scored(r)]
    n = len(rows)
    if not n:
        return {"n": 0}
    firsts = []
    for r in rows:
        ranks = [t["candidate_rank"] for t in _cfr_targets(r, level) if t["candidate_rank"] is not None]
        firsts.append(min(ranks) if ranks else None)

    def frac(k: int) -> dict[str, Any]:
        return {"count": k, "rate": round(k / n, 4)}

    ctx = [r["context"] for r in rows]
    totals = [c["total_chars"] for c in ctx]
    soft = next((c["soft_budget_chars"] for c in ctx if c["soft_budget_chars"]), None)
    guidance = sum(c["guidance_chars"] for c in ctx)
    return {
        "n": n,
        "key_status": dict(Counter(r["key_status"] for r in rows)),
        "any_expected_exists_in_db": frac(sum(1 for r in rows if any(t["exists_in_db"] for t in _cfr_targets(r, level)))),
        "any_in_candidates": frac(sum(1 for f in firsts if f is not None)),
        "recall_at_candidate_rank": {k: frac(sum(1 for f in firsts if f is not None and f <= k)) for k in RECALL_KS},
        "mrr_candidates": round(sum(1 / f for f in firsts if f) / n, 4),
        "any_in_topk": frac(sum(1 for r in rows if any(t["topk_rank"] for t in _cfr_targets(r, level)))),
        "any_in_context": frac(sum(1 for r in rows if any(t["in_context"] for t in _cfr_targets(r, level)))),
        "all_in_context": frac(sum(1 for r in rows if all(t["in_context"] for t in _cfr_targets(r, level)))),
        "any_reaches_prompt": frac(sum(1 for r in rows if any(t["reaches_prompt"] for t in _cfr_targets(r, level)))),
        "retrieved_but_not_in_context": frac(sum(1 for r, f in zip(rows, firsts)
                                                 if f is not None and not any(t["in_context"] for t in _cfr_targets(r, level)))),
        "model_would_be_called": frac(sum(1 for r in rows if r["model_would_be_called"])),
        "gate_states": dict(Counter(r["gate"]["state"] for r in rows)),
        "context_budget": {
            "soft_budget_chars": soft,
            "total_chars_median": statistics.median(totals),
            "total_chars_mean": round(statistics.fmean(totals), 1),
            "near_full_soft_budget": frac(sum(1 for t in totals if soft and t >= SOFT_BUDGET_NEAR_FULL * soft)),
            "over_soft_budget": frac(sum(1 for t in totals if soft and t > soft)),
            "guidance_share_of_context_chars": round(guidance / sum(totals), 4) if sum(totals) else None,
            "sources_median": statistics.median(c["sources"] for c in ctx),
        },
    }


def provision_metrics(recs: list[dict[str, Any]], *, level: str = "section") -> dict[str, Any]:
    """Target-level: one expected section (or paragraph) is one count; the first stage it fails to pass."""
    targets = [t for r in recs if is_section_scored(r) for t in _cfr_targets(r, level)]
    return {"targets": len(targets), "stages": {s: sum(1 for t in targets if t["stage"] == s) for s in STAGES},
            "drop_reasons": dict(Counter(reason for t in targets if t["stage"] == STAGE_DROPPED for reason in t["drop_reasons"]))}


def negative_control_outcomes(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Descriptive, per negative control. `retrieval_eval_rule_passed` applies retrieval_eval's rule (no
    exact_cfr result in the top_k list); it was designed for retrieval_v2's fake-identifier negatives and is
    reported for the benchmark's controls only as information - their correct behaviour is an answer-level
    decision (state that it does not exist, correct the premise), which retrieval alone cannot show."""
    out = []
    for r in recs:
        if not r.get("is_negative_control"):
            continue
        if r.get("error"):
            out.append({"id": r["id"], "source": r["source"], "error": r["error"]})
            continue
        excl = r["retrieval"].get("exact_cfr_in_topk_excluding_parent_rows")
        out.append({"id": r["id"], "source": r["source"], "question_class": r["question_class"],
                    "named_identifiers": r["named_identifiers"], "exact_cfr_in_topk": r["retrieval"]["exact_cfr_in_topk"],
                    "exact_cfr_in_topk_excluding_parent_rows": excl,
                    "retrieval_eval_rule_passed": r["retrieval"]["exact_cfr_in_topk"] == 0,
                    "rule_passed_excluding_parent_rows": excl == 0,
                    "gate_state": r["gate"]["state"], "gate_blocked": r["gate"]["blocked"],
                    "scope": r["gate"]["scope"], "model_would_be_called": r["model_would_be_called"],
                    "pre_generation_fallback": r["gate"].get("pre_generation_fallback")})
    return out


def summarise(recs: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {"all": recs}
    for cls in (CLASS_IDENTIFIER, CLASS_PLAIN):
        groups[cls] = [r for r in recs if r.get("question_class") == cls]
        for src in (SOURCE_V2, SOURCE_BENCHMARK):
            groups[f"{cls}/{src}"] = [r for r in groups[cls] if r["source"] == src]
    metrics = {}
    for name, rows in groups.items():
        metrics[name] = {"section_level": question_metrics(rows, level="section"),
                         "provision_level": question_metrics(rows, level="provision"),
                         "targets_section_level": provision_metrics(rows, level="section"),
                         "targets_provision_level": provision_metrics(rows, level="provision")}
    ncs = negative_control_outcomes(recs)
    part_only = [r for r in recs if not r.get("is_negative_control") and not r.get("error") and r["expected"]
                 and all(target_kind(t) == "part" for t in r["expected"])]
    return {
        "dataset_rows": len(recs),
        "errors": [{"id": r["id"], "error": r["error"]} for r in recs if r.get("error")],
        "rows_by_kind": {
            "section_scored": sum(1 for r in recs if is_section_scored(r)),
            "negative_control": sum(1 for r in recs if r.get("is_negative_control")),
            "part_only_key": len(part_only),
            "no_cfr_key": sum(1 for r in recs if r.get("key_status") == KEY_NONE),
            "docket_targets": sum(1 for r in recs for t in r.get("expected") or () if target_kind(t) == "docket"),
        },
        "sme_verified_rows": sum(1 for r in recs if r.get("sme_verified")),
        "metrics": metrics,
        "negative_controls": {
            "rows": ncs,
            "retrieval_v2_rule_passed": sum(1 for o in ncs if o.get("source") == SOURCE_V2 and o.get("retrieval_eval_rule_passed")),
            "retrieval_v2_rule_passed_excluding_parent_rows": sum(
                1 for o in ncs if o.get("source") == SOURCE_V2 and o.get("rule_passed_excluding_parent_rows")),
            "retrieval_v2_total": sum(1 for o in ncs if o.get("source") == SOURCE_V2),
            "benchmark_gate_blocked": sum(1 for o in ncs if o.get("source") == SOURCE_BENCHMARK and o.get("gate_blocked")),
            "benchmark_model_would_be_called": sum(1 for o in ncs if o.get("source") == SOURCE_BENCHMARK and o.get("model_would_be_called")),
            "benchmark_total": sum(1 for o in ncs if o.get("source") == SOURCE_BENCHMARK),
        },
        "part_only_rows": [{"id": r["id"], "expected": r["expected"],
                            "any_in_context": any(t["in_context"] for t in r["targets"])} for r in part_only],
        "docket_targets": [{"id": r["id"], **{k: t[k] for k in ("target", "exists_in_db", "candidate_rank", "stage")}}
                           for r in recs if not r.get("error") for t in r.get("targets") or () if t["kind"] == "docket"],
        "audit_failure_cases": [audit_case_view(r) for r in recs if r.get("audit_failure_case")],
        "unresolved_gold_keys": unresolved_keys(recs),
    }


def audit_case_view(r: dict[str, Any]) -> dict[str, Any]:
    if r.get("error"):
        return {"id": r["id"], "error": r["error"]}

    def brief(targets):
        return [{k: t.get(k) for k in ("target", "level", "exists_in_db", "candidate_rank", "topk_rank", "stage", "drop_reasons",
                                        "prompt_indices")} for t in targets]
    return {"id": r["id"], "question_class": r["question_class"], "key_status": r["key_status"], "targets": brief(r["targets"]),
            "alternative": brief(r["alternative_targets"]), "alternative_key_status": r.get("alternative_key_status"),
            "context_chars": r["context"]["total_chars"], "guidance_chars": r["context"]["guidance_chars"],
            "gate": r["gate"]["state"]}


def unresolved_keys(recs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Gold-key questions an SME must settle before any number here is treated as accuracy. Heuristic flags
    (zero heading overlap) set review priority only."""
    ok = [r for r in recs if not r.get("error")]
    out: dict[str, list[dict[str, Any]]] = {
        "audit_alternatives": [{"id": r["id"], "key": r["expected"], "alternative": r["alternative_expected"]}
                               for r in ok if r.get("alternative_expected")],
        "key_target_not_in_snapshot": [], "part_only_key": [], "no_cfr_key": [],
        "named_identifier_not_in_key": [], "zero_heading_overlap_and_never_retrieved": [],
        "negative_control_key_mentions_sections": [],
    }
    for r in ok:
        if r.get("is_negative_control"):
            if r["source"] == SOURCE_BENCHMARK and re.search(r"\b\d{1,4}\.\d{1,4}\b", str(r.get("key_text") or "")):
                out["negative_control_key_mentions_sections"].append({"id": r["id"], "named": r["plan"]["named"]})
            continue
        if r.get("key_status") == KEY_NONE:
            out["no_cfr_key"].append({"id": r["id"], "category": r["category"]})
            continue
        if r["expected"] and all(target_kind(t) == "part" for t in r["expected"]):
            out["part_only_key"].append({"id": r["id"], "key": r["expected"]})
        for t in r["targets"]:
            if t["level"] == "provision" and t["exists_in_db"] is False:
                out["key_target_not_in_snapshot"].append({"id": r["id"], "target": t["target"]})
        cfr = [t for t in r["targets"] if t["kind"] in ("section", "paragraph") and t["level"] in ("provision",)]
        if cfr and all(t["candidate_rank"] is None and t.get("heading_overlap_words") == 0 for t in cfr):
            out["zero_heading_overlap_and_never_retrieved"].append(
                {"id": r["id"], "key": [t["target"] for t in cfr], "headings": [t.get("heading") for t in cfr]})
        if r["question_class"] == CLASS_IDENTIFIER and r["plan"]["named"]:
            keyed_secs = {(_SECTION_TARGET.match(t).group("section") if _SECTION_TARGET.match(t) else None) for t in r["expected"]}
            keyed_parts = {(_PART_TARGET.match(t).group("part") if _PART_TARGET.match(t) else None) for t in r["expected"]}
            keyed_parts |= {s.split(".")[0] for s in keyed_secs if s}
            named_ok = False
            for n in r["plan"]["named"]:
                s, p = _SECTION_TARGET.match(n), _PART_TARGET.match(n)
                if (s and (s.group("section") in keyed_secs or s.group("section").split(".")[0] in keyed_parts)) or \
                        (p and p.group("part") in keyed_parts):
                    named_ok = True
            if not named_ok:
                out["named_identifier_not_in_key"].append({"id": r["id"], "named": r["plan"]["named"], "key": r["expected"]})
    return out


# ---------------------------------------------------------------- comparison against a baseline run

def _in_context(r: dict[str, Any], level: str = "section") -> bool:
    return any(t["in_context"] for t in _cfr_targets(r, level))


def _in_candidates(r: dict[str, Any], level: str = "section") -> bool:
    return any(t["candidate_rank"] is not None for t in _cfr_targets(r, level))


def compare_to_baseline(base: list[dict[str, Any]], new: list[dict[str, Any]], *, recover_min: int = 20,
                        identifier_min: int = 108) -> dict[str, Any]:
    """Per-question comparison of a candidate run with the baseline, and the Phase 2 acceptance criteria:

      1. plain-language questions retrieved but not in context in the baseline: >= recover_min now in context
      2. plain-language questions in context in the baseline: none lost
      3. identifier questions in context: >= identifier_min
      4. negative controls blocked before the model: the same set
      5. limits: optional context within the soft budget, every context within the hard ceilings, required
         evidence unchanged; and no question changes whether the model would be called (gating intact)
    """
    B, N = {r["id"]: r for r in base}, {r["id"]: r for r in new}
    if set(B) != set(N):
        raise ValueError(f"different question sets: {sorted(set(B) ^ set(N))[:10]}")
    ids = sorted(B)
    errors = [i for i in ids if B[i].get("error") or N[i].get("error")]
    ok = [i for i in ids if i not in errors]
    plain = [i for i in ok if is_section_scored(B[i]) and B[i]["question_class"] == CLASS_PLAIN]
    ident = [i for i in ok if is_section_scored(B[i]) and B[i]["question_class"] == CLASS_IDENTIFIER]
    targets = [i for i in plain if _in_candidates(B[i]) and not _in_context(B[i])]
    recovered = [i for i in targets if _in_context(N[i])]
    plain_base_ctx = [i for i in plain if _in_context(B[i])]
    plain_lost = [i for i in plain_base_ctx if not _in_context(N[i])]
    plain_gained_other = [i for i in plain if i not in targets and not _in_context(B[i]) and _in_context(N[i])]
    ident_new_ctx = [i for i in ident if _in_context(N[i])]
    ident_lost = [i for i in ident if _in_context(B[i]) and not _in_context(N[i])]
    nc_blocked = lambda R: sorted(i for i in ok if R[i]["is_negative_control"] and R[i]["gate"]["blocked"])  # noqa: E731
    gating_changes = [{"id": i, "base": (B[i]["gate"]["state"], B[i]["gate"]["blocked"], B[i]["model_would_be_called"]),
                       "new": (N[i]["gate"]["state"], N[i]["gate"]["blocked"], N[i]["model_would_be_called"])}
                      for i in ok if (B[i]["gate"]["state"], B[i]["gate"]["blocked"], B[i]["model_would_be_called"])
                      != (N[i]["gate"]["state"], N[i]["gate"]["blocked"], N[i]["model_would_be_called"])]
    limit_violations = []
    for i in ok:
        c = N[i]["context"]
        if not c["required_chars"] and c["soft_budget_chars"] and c["total_chars"] > c["soft_budget_chars"]:
            limit_violations.append({"id": i, "issue": "optional-only context over the soft budget", "chars": c["total_chars"]})
        if c["hard_ceiling_chars"] and c["total_chars"] > c["hard_ceiling_chars"]:
            limit_violations.append({"id": i, "issue": "context over the hard ceiling", "chars": c["total_chars"]})
        if c["sources"] > 24:
            limit_violations.append({"id": i, "issue": "more than hard_max_results sources", "sources": c["sources"]})
        if c["required_chars"] != B[i]["context"]["required_chars"]:
            limit_violations.append({"id": i, "issue": "required evidence changed",
                                     "base": B[i]["context"]["required_chars"], "new": c["required_chars"]})
    unchanged = lambda i: (json.dumps({k: v for k, v in B[i].items() if k not in VOLATILE_KEYS}, sort_keys=True, default=str)  # noqa: E731
                           == json.dumps({k: v for k, v in N[i].items() if k not in VOLATILE_KEYS}, sort_keys=True, default=str))
    by_class = {}
    for cls in (CLASS_IDENTIFIER, CLASS_PLAIN):
        rows = [i for i in ok if B[i].get("question_class") == cls]
        by_class[cls] = {"rows": len(rows), "records_identical": sum(1 for i in rows if unchanged(i))}
    transitions = Counter()
    for i in plain:
        for tb, tn in zip(_cfr_targets(B[i], "section"), _cfr_targets(N[i], "section")):
            if tb["stage"] != tn["stage"]:
                transitions[f"{tb['stage']} -> {tn['stage']}"] += 1
    docket_changes = [{"id": i, "target": tb["target"], "base": tb["stage"], "new": tn["stage"]}
                      for i in ok for tb, tn in zip(B[i]["targets"], N[i]["targets"])
                      if tb["kind"] == "docket" and tb["stage"] != tn["stage"]]
    criteria = {
        "1_recovered_plain_targets": {"required": f">= {recover_min} of {len(targets)}", "value": len(recovered),
                                      "passed": len(recovered) >= recover_min},
        "2_plain_in_context_lost": {"required": f"0 of {len(plain_base_ctx)}", "value": len(plain_lost), "passed": not plain_lost},
        "3_identifier_in_context": {"required": f">= {identifier_min} of {len(ident)}", "value": len(ident_new_ctx),
                                    "passed": len(ident_new_ctx) >= identifier_min},
        "4_negative_controls_blocked_set": {"required": "unchanged", "base": nc_blocked(B), "new": nc_blocked(N),
                                            "passed": nc_blocked(B) == nc_blocked(N)},
        "5_limits_and_gating": {"required": "no limit violation; no change in whether the model is called",
                                "limit_violations": limit_violations, "gating_changes": gating_changes,
                                "passed": not limit_violations and not any(g["base"][2] != g["new"][2] or g["base"][1] != g["new"][1]
                                                                           for g in gating_changes)},
    }
    return {
        "criteria": criteria, "all_passed": all(c["passed"] for c in criteria.values()), "errors": errors,
        "targets": targets, "recovered": recovered, "not_recovered": [i for i in targets if i not in recovered],
        "plain_lost": plain_lost, "plain_gained_outside_targets": plain_gained_other, "identifier_lost": ident_lost,
        "by_class": by_class, "plain_target_stage_transitions": dict(transitions), "docket_target_changes": docket_changes,
        "metrics": {"plain_in_context": {"baseline": len(plain_base_ctx), "new": sum(1 for i in plain if _in_context(N[i]))},
                    "identifier_in_context": {"baseline": sum(1 for i in ident if _in_context(B[i])), "new": len(ident_new_ctx)},
                    "plain_in_context_provision_level": {
                        "baseline": sum(1 for i in plain if _in_context(B[i], "provision")),
                        "new": sum(1 for i in plain if _in_context(N[i], "provision"))}},
    }


# ---------------------------------------------------------------- reproducibility

def canonical_records(recs: list[dict[str, Any]]) -> str:
    """The records without volatile fields (timings), one sorted-key JSON line each, sorted by id."""
    lines = []
    for r in sorted(recs, key=lambda x: x["id"]):
        lines.append(json.dumps({k: v for k, v in r.items() if k not in VOLATILE_KEYS}, sort_keys=True, default=str))
    return "\n".join(lines) + "\n"


def canonical_sha256(recs: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_records(recs).encode("utf-8")).hexdigest()


REGULATORY_TABLES = ("cfr_records", "cfr_sections", "cfr_parts", "cfr_subparts", "cfr_definitions", "cfr_cross_references",
                     "cfr_lexeme_stats", "cfr_iso_crosswalk", "legacy_qsr_terms", "fda_guidance", "fda_guidance_chunks")


def database_fingerprint(db) -> dict[str, Any]:
    """Read-only identity of the regulatory data: corpus content hashes (regulus.traceability.corpus), exact row
    counts, and the server's cumulative write counters for the regulatory tables (unchanged counters across a
    run = no row was inserted, updated or deleted)."""
    from regulus.traceability.corpus import corpus_identity

    counts = {t: int(db.query(f"SELECT count(*) AS n FROM {t}")[0]["n"]) for t in REGULATORY_TABLES}
    stats = {r["relname"]: {k: int(r[k]) for k in ("n_tup_ins", "n_tup_upd", "n_tup_del")}
             for r in db.query("SELECT relname, n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables"
                               " WHERE relname = ANY(%(t)s) ORDER BY relname", {"t": list(REGULATORY_TABLES)})}
    return {"corpus_identity": corpus_identity(db), "row_counts": counts, "write_counters": stats,
            "session": {k: v for k, v in db.status().items() if k != "url"}}
