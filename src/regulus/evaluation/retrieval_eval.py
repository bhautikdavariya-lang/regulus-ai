"""Retrieval evaluation: Recall@K and MRR over a curated query set.

Target syntax in the dataset's `expected` list:
    "21 CFR 820.10"        any eCFR result from section 820.10 (any paragraph)
    "21 CFR 820.10(b)"     eCFR result whose paragraph is (b) or nested under it
    "docket:FDA-2016-D-2565"  any guidance result with that docket number
    "guidance:<title prefix>" guidance result whose document title starts with it
A query "hits" at rank r if the r-th result satisfies any expected target.
Queries with an empty `expected` list are negative controls: they count as
correct only if no exact_cfr result is returned; they are excluded from
Recall/MRR averages and reported separately.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from regulus.config import PROJECT_ROOT
from regulus.retrieval.models import RetrievalResult

DEFAULT_RETRIEVAL_DATASET = PROJECT_ROOT / "data" / "evaluation" / "datasets" / "retrieval_v1.jsonl"
K_VALUES = (1, 3, 5, 10)
_CFR_TARGET = re.compile(r"^(?P<title>\d{1,2}) CFR (?P<section>\d{1,4}\.\d{1,4}[a-z]?)(?P<para>(?:\([A-Za-z0-9]{1,4}\))*)$")


class RetrievalDatasetError(ValueError):
    pass


@dataclass(frozen=True)
class RetrievalQuery:
    id: str
    category: str
    query: str
    expected: tuple[str, ...]
    notes: str = ""
    # Stage 10: for identifier-style negative controls, whether the named
    # identifier exists in the snapshot (verified against the database when the
    # dataset was written; re-checked against the lexical exact lookup at run time).
    identifier_exists_in_snapshot: bool | None = None

    @property
    def is_negative(self) -> bool:
        return not self.expected


def load_retrieval_dataset(path: str | Path | None = None) -> list[RetrievalQuery]:
    path = Path(path) if path else DEFAULT_RETRIEVAL_DATASET
    if not path.is_file():
        raise RetrievalDatasetError(f"dataset not found: {path}")
    out: list[RetrievalQuery] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RetrievalDatasetError(f"line {n}: invalid JSON ({exc.msg})") from exc
        for f in ("id", "category", "query", "expected"):
            if f not in rec:
                raise RetrievalDatasetError(f"line {n}: missing field {f!r}")
        if not isinstance(rec["expected"], list) or not all(isinstance(t, str) and t for t in rec["expected"]):
            raise RetrievalDatasetError(f"line {n}: 'expected' must be a list of non-empty strings")
        for t in rec["expected"]:
            if not (_CFR_TARGET.match(t) or t.startswith("docket:") or t.startswith("guidance:")):
                raise RetrievalDatasetError(f"line {n}: unrecognised target {t!r}")
        if rec["id"] in seen:
            raise RetrievalDatasetError(f"line {n}: duplicate id {rec['id']!r}")
        seen.add(rec["id"])
        exists = rec.get("identifier_exists_in_snapshot")
        if exists is not None and not isinstance(exists, bool):
            raise RetrievalDatasetError(f"line {n}: identifier_exists_in_snapshot must be true/false")
        out.append(RetrievalQuery(rec["id"], rec["category"], rec["query"].strip(), tuple(rec["expected"]), rec.get("notes", ""), exists))
    if not out:
        raise RetrievalDatasetError("dataset is empty")
    return out


def target_matches(target: str, result: RetrievalResult) -> bool:
    m = _CFR_TARGET.match(target)
    if m:
        if result.corpus != "ecfr" or result.citation.section != m.group("section"):
            return False
        want = m.group("para")
        have = result.citation.paragraph or ""
        return not want or have == want or have.startswith(want + "(")
    if target.startswith("docket:"):
        return result.corpus == "fda_guidance" and (result.citation.docket_number or "").upper() == target[7:].upper()
    if target.startswith("guidance:"):
        return result.corpus == "fda_guidance" and (result.citation.document_title or "").lower().startswith(target[9:].lower())
    return False


def first_hit_rank(expected: tuple[str, ...], results: list[RetrievalResult]) -> int | None:
    for rank, r in enumerate(results, start=1):
        if any(target_matches(t, r) for t in expected):
            return rank
    return None


def hits_at(expected: tuple[str, ...], results: list[RetrievalResult], k: int) -> int:
    """Number of the top-k results that match any expected target ("target-match
    precision": every paragraph of a target section counts as relevant)."""
    return sum(1 for r in results[:k] if any(target_matches(t, r) for t in expected))


def crowding(expected: tuple[str, ...], results: list[RetrievalResult]) -> dict[str, Any]:
    """Stage 10 crowding fields: what sits above the first hit, and the mix of
    the top 10 (corpus and corpus_role where the semantic leg provides it)."""
    rank = first_hit_rank(expected, results)
    above = results[: (rank - 1)] if rank else results[:10]
    top = results[:10]
    return {
        "target_rank": rank,
        "results_above_target": len(above) if rank else None,
        "distractors_above_target": sum(1 for r in above if r.metadata.get("corpus_role") == "distractor") if rank else None,
        "semantic_above_target": sum(1 for r in above if "semantic" in r.methods) if rank else None,
        "top10_ecfr": sum(1 for r in top if r.corpus == "ecfr"),
        "top10_guidance": sum(1 for r in top if r.corpus == "fda_guidance"),
        "top10_semantic": sum(1 for r in top if "semantic" in r.methods),
        "top10_distinct_documents": len({(r.citation.section if r.corpus == "ecfr" else r.source_url) for r in top}),
    }


@dataclass
class QueryOutcome:
    id: str
    category: str
    query: str
    expected: list[str]
    first_hit_rank: int | None
    negative_control: bool
    negative_control_passed: bool | None
    top_results: list[dict[str, Any]]
    total_ms: float
    timings_ms: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    retrieval: dict[str, Any] = field(default_factory=dict)  # Stage 7 retriever diagnostics
    hits_at_k: dict[str, int] = field(default_factory=dict)  # Stage 10: {"1": n, "3": n, "5": n}
    crowding: dict[str, Any] = field(default_factory=dict)  # Stage 10
    identifier_exists_in_snapshot: bool | None = None  # dataset claim (Stage 10)
    exact_match_present: bool | None = None  # lexical/database observation (Stage 10)


def summarise(outcomes: list[QueryOutcome], k_values: tuple[int, ...] = K_VALUES) -> dict[str, Any]:
    scored = [o for o in outcomes if not o.negative_control and o.error is None]
    negatives = [o for o in outcomes if o.negative_control]
    failed = [o for o in outcomes if o.error is not None]

    def recall_at(k: int, rows: list[QueryOutcome]) -> float | None:
        if not rows:
            return None
        return round(sum(1 for o in rows if o.first_hit_rank is not None and o.first_hit_rank <= k) / len(rows), 4)

    def mrr(rows: list[QueryOutcome]) -> float | None:
        if not rows:
            return None
        return round(sum(1.0 / o.first_hit_rank for o in rows if o.first_hit_rank) / len(rows), 4)

    def precision_at(k: int, rows: list[QueryOutcome]) -> float | None:
        rows = [o for o in rows if str(k) in o.hits_at_k]
        if not rows:
            return None
        return round(sum(o.hits_at_k[str(k)] / k for o in rows) / len(rows), 4)

    by_category: dict[str, dict[str, Any]] = {}
    for cat in sorted({o.category for o in outcomes}):
        rows = [o for o in scored if o.category == cat]
        negs = [o for o in outcomes if o.category == cat and o.negative_control]
        by_category[cat] = {
            "queries": sum(1 for o in outcomes if o.category == cat),
            "scored": len(rows),
            **{f"recall@{k}": recall_at(k, rows) for k in k_values},
            "mrr": mrr(rows),
            **{f"precision@{k}": precision_at(k, rows) for k in (1, 3, 5)},
            "negative_controls": len(negs),
            "negative_controls_passed": sum(1 for o in negs if o.negative_control_passed),
        }
    latencies = [o.total_ms for o in outcomes if o.error is None]
    ok = [o for o in outcomes if o.error is None]
    n_fb = sum(1 for o in ok if o.retrieval.get("fallback_used"))
    fallback = {
        "activations": n_fb,
        "zero_primary_results": sum(1 for o in ok if o.retrieval.get("primary_result_count", 1) == 0),
        "zero_final_results": sum(1 for o in ok if o.retrieval.get("final_result_count", 1) == 0),
        "avg_fallback_candidates": round(sum(o.retrieval.get("fallback_candidate_count", 0) for o in ok if o.retrieval.get("fallback_used")) / n_fb, 2) if n_fb else None,
        "hits_via_fallback": sum(1 for o in ok if not o.negative_control and o.first_hit_rank and o.retrieval.get("retrieval_mode") == "fallback"),
        "modes": {m: sum(1 for o in ok if o.retrieval.get("retrieval_mode") == m) for m in ("exact", "primary", "fallback", "none")},
    }
    return {
        "queries": len(outcomes),
        "scored": len(scored),
        "negative_controls": len(negatives),
        "negative_controls_passed": sum(1 for o in negatives if o.negative_control_passed),
        "failed": len(failed),
        **{f"recall@{k}": recall_at(k, scored) for k in k_values},
        "mrr": mrr(scored),
        **{f"precision@{k}": precision_at(k, scored) for k in (1, 3, 5)},
        "existence_mismatches": [o.id for o in ok if o.identifier_exists_in_snapshot is not None and o.exact_match_present is not None and o.identifier_exists_in_snapshot != o.exact_match_present],
        "misses": [o.id for o in scored if o.first_hit_rank is None],
        "avg_total_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "max_total_ms": round(max(latencies), 2) if latencies else None,
        "fallback": fallback,
        "by_category": by_category,
    }
