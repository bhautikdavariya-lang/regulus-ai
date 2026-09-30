"""The acceptance-benchmark key review, as the dashboard sees it.

Read-only, like everything else in the dashboard: it opens the frozen
baseline, the latest verification run and the append-only decision log, and
reports where the review stands and whether the gate is open. It records no
decision of its own - reviewing happens through
`scripts/review_benchmark_key.py`, where every decision is attributable.

The gate shown here is the same function the execution paths call, so the
page cannot say "unlocked" while `train_model.py` refuses, or the reverse.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VERIFICATION_DIR = Path("artifacts") / "benchmark_verification"
KEY_DIR = Path("artifacts") / "benchmark_keys"
QUEUE_LIMIT = 300


def _latest_verification(root: Path) -> tuple[str, dict[str, Any]] | None:
    runs = sorted((root / VERIFICATION_DIR).glob("*/verification.json"))
    if not runs:
        return None
    return runs[-1].parent.name, json.loads(runs[-1].read_text(encoding="utf-8"))


def review_status(root: Path | str = Path(".")) -> dict[str, Any]:
    """Where the key review stands, and whether scoring and training are open."""
    root = Path(root)
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
    from regulus.evaluation.acceptance_gate import gate_status
    from regulus.evaluation.key_review import load_review
    from regulus.evaluation.key_verification import Finding, RowVerification, VerificationArtifact

    workbook = root / DEFAULT_WORKBOOK
    if not workbook.is_file():
        return {"available": False, "reason": f"the acceptance workbook is not at {workbook.as_posix()}"}

    benchmark = load_acceptance_benchmark(workbook)
    found = _latest_verification(root)
    if found is None:
        return {
            "available": False,
            "reason": "no verification run exists yet; run scripts/verify_benchmark_key.py",
            "benchmark": {"label": benchmark.label, "benchmark_key": benchmark.benchmark_key},
        }
    run_id, payload = found

    rows = tuple(
        RowVerification(
            benchmark_id=r["benchmark_id"], question_id=r["question_id"],
            verification_status=r["verification_status"], verification_source=r["verification_source"],
            verified_citation=r["verified_citation"],
            verified_answer_elements=r["verified_answer_elements"],
            verified_iso_clause=r["verified_ISO_clause"], verification_notes=r["verification_notes"],
            verifier=r["verifier"], verification_timestamp=r["verification_timestamp"],
            findings=tuple(Finding(f["dimension"], f["status"], f["detail"], f.get("evidence") or {})
                           for f in r["findings"]),
            expected_citation_draft=r.get("expected_citation_draft", ""),
            expected_iso_clause_draft=r.get("expected_ISO_clause_draft", ""),
        )
        for r in payload["rows"]
    )
    verification = VerificationArtifact(
        benchmark_id=payload["benchmark_id"], benchmark_key=payload["benchmark_key"],
        workbook_sha256=payload["workbook_sha256"], workbook_path=payload["workbook_path"],
        generated_at=payload["generated_at"], sources=payload.get("sources") or {},
        rows=rows, verifier=payload.get("verifier"),
    )

    key_root = root / KEY_DIR / benchmark.benchmark_key.replace("/", "_").replace(":", "_")
    review = load_review(benchmark, verification, run_id, key_root / "review" / "v1")

    queue = []
    for question in benchmark.questions[:QUEUE_LIMIT]:
        row = verification.row(question.question_id)
        reasons = [f.detail for f in (row.findings if row else ())
                   if f.status in ("CONTRADICTED", "REQUIRES_SME", "UNVERIFIABLE")
                   and f.dimension not in ("substantive_elements", "completeness")]
        queue.append({
            "question_id": question.question_id,
            "state": review.state(question.question_id),
            "question_type": question.question_type,
            "domain": question.domain,
            "referral_reasons": reasons[:2],
        })

    return {
        "available": True,
        "benchmark": {
            "label": benchmark.label, "benchmark_key": benchmark.benchmark_key,
            "workbook_sha256": benchmark.sha256, "questions": len(benchmark.questions),
        },
        "baseline_frozen": (key_root / "baseline.json").is_file(),
        "summary": review.summary(),
        "gate": gate_status(benchmark.benchmark_key, root / KEY_DIR),
        "queue": queue,
        "note": (
            "This page reports the review; it does not conduct it. Decisions are recorded through "
            "scripts/review_benchmark_key.py so that every one carries a reviewer, a rationale and a "
            "timestamp."
        ),
    }
