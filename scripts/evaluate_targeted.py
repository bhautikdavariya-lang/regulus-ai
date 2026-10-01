"""Targeted generation-control evaluation (Stage 8): the 12 questions of the repetition-fix brief.

    python scripts/evaluate_targeted.py [--label targeted]

Runs each question through the configured pipeline (model loaded) and records, per question:
retrieval success, evidence uniqueness, exact-section accuracy, citation validity, repetition
counts (raw and final), answer length, unsupported-content findings, timing and whether the
repetition stop / prefix trimming acted. Answer correctness is left to review of the saved answers:
no expected answers are invented here.

Output: artifacts/generation_control/<label>_<utc>/ (results.jsonl, summary.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from regulus.config import load_settings  # noqa: E402
from regulus.evaluation.grounding_eval import split_sentences  # noqa: E402
from regulus.inference.repetition_text import normalise_sentence  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import RagPipeline  # noqa: E402
from regulus.rag.remote_generator import load_generator  # noqa: E402
from regulus.retrieval import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from regulus.retrieval.references import parse_cfr_references  # noqa: E402
from regulus.system_identity import configured_generation_config  # noqa: E402
from run_diagnostics import configured_rag_config  # noqa: E402

QUESTIONS = [
    "What does 21 CFR Part 11 cover?",
    "What does 21 CFR 11.10 require?",
    "What are the requirements for electronic signatures under 21 CFR 11.100?",
    "What is the difference between open and closed systems under 21 CFR Part 11?",
    "What does 21 CFR 11.10(c) require?",
    "What does 21 CFR 314.90 address?",
    "Under 21 CFR 314.90, what must an applicant include in a waiver request?",
    "What does 21 CFR 820.10 require?",
    "What does 21 CFR 820.10(b)(3) require?",
    "What does 21 CFR 830.20 address?",
    "What are the requirements of 21 CFR 314.999?",
    "What does 21 CFR Part 1400 say about artificial intelligence in drug labeling?",
]
CLAIM_CODES = {"paragraph_misattribution", "invented_condition", "unsupported_premise", "unsupported_figure",
               "asserted_missing_provision", "unsupported_claim"}


def max_repeat(text: str) -> int:
    counts = Counter(s for s in (normalise_sentence(x) for x in split_sentences(text or "")) if len(s) >= 20)
    return max(counts.values(), default=0)


def within(requested, ref) -> bool:
    """A named/cited provision is the requested one, or a subparagraph of it, or (part request) in that part."""
    if requested.section is None:
        return ref.part == requested.part
    return ref.section == requested.section and (ref.paragraph_path or "").startswith(requested.paragraph_path or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="targeted")
    args = ap.parse_args()
    s = load_settings()
    s.generation = configured_generation_config(s)
    db = Database.from_env(); db.connect()
    cfg = configured_rag_config(s)
    retriever, scope = build_retriever(db, cfg)
    pipe = RagPipeline(retriever, load_generator(s, local_files_only=True), cfg, scope_policy=scope)
    out_dir = ROOT / "artifacts/generation_control" / f"{args.label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for q in QUESTIONS:
        t0 = time.perf_counter()
        out = pipe.answer(q)
        secs = round(time.perf_counter() - t0, 1)
        m = out.metadata
        plan = plan_query(q)
        requested = [r.reference for r in plan.requirements]
        texts = [re.sub(r"\W+", " ", src.text.lower()).strip() for src in out.context.sources]
        dup_items = sum(v - 1 for v in Counter(hashlib.sha256(t.encode()).hexdigest() for t in texts).values() if v > 1)
        cited = [c.label for c in out.citations]
        named = [r for r in parse_cfr_references(out.answer) if r.title == "21"]
        off_target = sorted({r.canonical for r in named if requested and not any(within(req, r) for req in requested)})
        initial = (m.get("validation") or {}).get("initial") or {}
        final = (m.get("validation") or {}).get("final") or {}
        rows.append({
            "question": q,
            "requested": [r.canonical for r in requested],
            "retrieval_success": (m.get("coverage") or {}).get("state"),
            "answerability": (m.get("answerability") or {}).get("state"),
            "model_called": out.model_called,
            "evidence_items": len(out.context.sources), "duplicate_evidence_items": dup_items,
            "evidence": [src.result.citation.label for src in out.context.sources],
            "citations": cited,
            "named_provisions_outside_request": off_target,
            "invalid_citations_in_raw": len(initial.get("invalid_citations") or []),
            "repetition_raw_max": max_repeat(m.get("raw_model_output") or ""),
            "repetition_final_max": max_repeat(out.answer),
            "repetition_trimmed_sentences": (m.get("generation") or {}).get("repetition_trimmed_sentences"),
            "stop_reason": (m.get("generation") or {}).get("stop_reason"),
            "generated_tokens": (m.get("generation") or {}).get("generated_tokens"),
            "answer_chars": len(out.answer),
            "unsupported_findings_initial": sorted(set(initial.get("codes") or []) & CLAIM_CODES),
            "final_validation": final.get("status"),
            "repair": (m.get("validation") or {}).get("repair"),
            "fallback": m.get("fallback_type"),
            "seconds": secs,
            "raw_model_output": m.get("raw_model_output"),
            "answer": out.answer,
        })
        print(f"{secs:6}s {q[:70]:70} rep raw/final={rows[-1]['repetition_raw_max']}/{rows[-1]['repetition_final_max']} "
              f"dup={dup_items} off={off_target} fb={m.get('fallback_type')}", flush=True)
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
