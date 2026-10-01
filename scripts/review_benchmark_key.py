"""Controlled SME review of the acceptance benchmark's answer key.

    python scripts/review_benchmark_key.py status
    python scripts/review_benchmark_key.py packet X-004
    python scripts/review_benchmark_key.py queue --state REQUIRES_SME --limit 20
    python scripts/review_benchmark_key.py decide X-004 --state CORRECTED \\
        --reviewer "Name, Title" --rationale "..." \\
        --corrected-citation "21 CFR 4.100 through 4.105" \\
        [--corrected-key-elements "..." --evidence "eCFR 21 CFR 4.102(c)"] \\
        --substantive correct --substantive-rationale "..." \\
        --completeness correct --completeness-rationale "..."
    python scripts/review_benchmark_key.py sign-off --reviewer "Name" --title "..." \\
        --ecfr-revision-date 2026-09-03 --iso-edition "ISO 13485:2016(E)"

Decisions are append-only. Nothing here writes to the workbook, and a
correction never replaces the draft key: both are kept, so the change and its
reason stay auditable.

Sign-off refuses while any row is unresolved or missing its substantive and
completeness judgments. It is the only route to a locked key, and the locked
key is what opens the scoring and training gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from regulus.evaluation.acceptance_benchmark import (  # noqa: E402
    DEFAULT_WORKBOOK,
    load_acceptance_benchmark,
)
from regulus.evaluation.acceptance_gate import DEFAULT_KEY_ROOT, gate_status  # noqa: E402
from regulus.evaluation.key_review import (  # noqa: E402
    DECISIONS,
    REASON_CATEGORIES,
    verification_counts,
    JUDGMENT_VALUES,
    Judgment,
    ReviewError,
    append_decision,
    load_review,
    write_baseline,
    write_locked_key,
    write_signoff,
)
from regulus.evaluation.key_verification import VerificationArtifact  # noqa: E402

VERIFICATION_ROOT = ROOT / "artifacts" / "benchmark_verification"


def _latest_verification() -> tuple[str, dict]:
    runs = sorted(p for p in VERIFICATION_ROOT.glob("*/verification.json"))
    if not runs:
        raise SystemExit(
            "no verification run found. Run `python scripts/verify_benchmark_key.py` first."
        )
    path = runs[-1]
    return path.parent.name, json.loads(path.read_text(encoding="utf-8"))


class _Artifact(VerificationArtifact):
    """A verification artifact rebuilt from its JSON, for review purposes."""


def _rebuild(payload: dict) -> VerificationArtifact:
    from regulus.evaluation.key_verification import Finding, RowVerification

    rows = tuple(
        RowVerification(
            benchmark_id=r["benchmark_id"], question_id=r["question_id"],
            verification_status=r["verification_status"], verification_source=r["verification_source"],
            verified_citation=r["verified_citation"], verified_answer_elements=r["verified_answer_elements"],
            verified_iso_clause=r["verified_ISO_clause"], verification_notes=r["verification_notes"],
            verifier=r["verifier"], verification_timestamp=r["verification_timestamp"],
            findings=tuple(Finding(f["dimension"], f["status"], f["detail"], f.get("evidence") or {})
                           for f in r["findings"]),
            expected_citation_draft=r.get("expected_citation_draft", ""),
            expected_iso_clause_draft=r.get("expected_ISO_clause_draft", ""),
        )
        for r in payload["rows"]
    )
    return VerificationArtifact(
        benchmark_id=payload["benchmark_id"], benchmark_key=payload["benchmark_key"],
        workbook_sha256=payload["workbook_sha256"], workbook_path=payload["workbook_path"],
        generated_at=payload["generated_at"], sources=payload.get("sources") or {},
        rows=rows, verifier=payload.get("verifier"),
    )


def _open_review(args):
    benchmark = load_acceptance_benchmark(args.workbook)
    run_id, payload = _latest_verification()
    if payload["benchmark_key"] != benchmark.benchmark_key:
        raise SystemExit(
            f"the latest verification run is of benchmark {payload['benchmark_key']}, but the "
            f"workbook is {benchmark.benchmark_key}. Re-run verification for this workbook."
        )
    key_root = Path(args.key_root) / benchmark.benchmark_key.replace("/", "_").replace(":", "_")
    review_root = key_root / "review" / f"v{args.review_version}"
    write_baseline(benchmark, key_root)
    review = load_review(benchmark, _rebuild(payload), run_id, review_root, args.review_version)
    return benchmark, review, key_root, review_root


def cmd_status(args) -> int:
    benchmark, review, key_root, _ = _open_review(args)
    s = review.summary()
    print(f"benchmark     : {benchmark.label}")
    print(f"identity      : {s['benchmark_key']}")
    print(f"verification  : run {s['verification_run_id']}")
    print(f"review version: v{s['review_version']}")
    print(f"baseline      : {key_root / 'baseline.json'}")
    v = verification_counts(review)
    print(f"\nKEY STATUS    : {v['total']} total / {v['expert_verified']} expert verified / {v['pending']} pending / "
          f"{v['disputed']} disputed ({v['accepted_unsigned']} accepted, awaiting sign-off)")
    if v["reason_categories"]:
        print(f"  open reasons: {v['reason_categories']}")
    print(f"\nquestions     : {s['questions']}")
    print(f"by state      : {s['by_state']}")
    print(f"decisions     : {s['decisions_recorded']}")
    print(f"open rows     : {s['open_rows']}")
    print(f"missing judgments: {s['rows_missing_judgments']}")
    print(f"\nreferred by the automated pass:")
    print(f"  contradicted  : {len(s['contradicted_by_automation'])} {s['contradicted_by_automation']}")
    print(f"  ISO conflicts : {len(s['iso_conflicts'])}")
    print(f"  absence claims: {len(s['absence_claims'])}")
    print(f"\nsigned off    : {s['signed_off']}")
    gate = gate_status(benchmark.benchmark_key, args.key_root)
    print(f"gate          : {'OPEN' if gate['open'] else 'CLOSED'} — {gate['reason'] or 'key locked'}")
    return 0


def cmd_queue(args) -> int:
    _, review, _, _ = _open_review(args)
    shown = 0
    for question in review.benchmark.questions:
        state = review.state(question.question_id)
        if args.state and state != args.state:
            continue
        print(f"  {question.question_id:8} {state:15} {question.question_type:18} "
              f"{question.question[:60]}")
        shown += 1
        if shown >= args.limit:
            break
    print(f"\n{shown} row(s) shown")
    return 0


def _sources():
    """The read-only snapshot, so packets can carry the provision's own text."""
    from regulus.evaluation.key_verification import DatabaseSources
    from regulus.retrieval import Database

    db = Database.from_env()
    db.connect()
    if str(db.status().get("default_transaction_read_only", "")).lower() not in ("on", "true", "1"):
        raise SystemExit("refusing: the database connection is not read-only")
    return DatabaseSources(db)


def cmd_packet(args) -> int:
    _, review, _, _ = _open_review(args)
    packet = review.packet(args.question_id, None if args.no_text else _sources())
    if args.json:
        print(json.dumps(packet.to_dict(), indent=2, ensure_ascii=False))
        return 0
    p = packet
    print(f"{'='*78}\n{p.question_id}   [{p.question_type} / {p.difficulty}]   {p.domain}")
    print(f"state: {p.current_state}   (automated: {p.automated_state})")
    print(f"\nQUESTION\n  {p.question}")
    print(f"\nDRAFT KEY (workbook column G)\n  {p.draft_citation}")
    print(f"DRAFT ISO CLAUSE (column H)\n  {p.draft_iso_clause}   title: {p.draft_iso_clause_title}")
    print(f"\nKEY ANSWER ELEMENTS (column J)\n  {p.key_answer_elements}")
    print(f"\nEVIDENCE — note what each kind can and cannot establish")
    for e in p.evidence:
        print(f"\n  [{e['dimension']}] {e['status']}")
        print(f"    {e['detail']}")
        print(f"    evidence kind: {e['kind']}")
        print(f"    weight       : {e['establishes']}")
    if p.provision_text:
        print("\nPROVISION TEXT — eCFR snapshot, the reviewer's primary source")
        for block in p.provision_text:
            print(f"\n  {block['citation']}   ({block['source']})")
            for record in block["records"][:12]:
                label = record["paragraph_path"] or "(section)"
                body = " ".join((record["text"] or "").split())
                print(f"    {label:12} {body[:300]}")
    if p.absence_search:
        print("\nABSENCE EVIDENCE — what the named part actually says on this subject")
        for block in p.absence_search:
            print(f"\n  part {block['part']}, searched for: {', '.join(block['terms'])}")
            if not block["hits"]:
                print("    no provision in this part mentions those terms")
            for hit in block["hits"][:6]:
                snippet = " ".join((hit["snippet"] or "").split())
                print(f"    {hit['section']}{hit['paragraph_path']}: {snippet[:190]}")
            print(f"    NOTE: {block['reading']}")

    print("\nWHAT THIS ROW NEEDS FROM YOU")
    for q in p.open_questions:
        print(f"  - {q}")
    return 0


def cmd_batch(args) -> int:
    benchmark, review, _, _ = _open_review(args)
    sources = None if args.no_text else _sources()
    chosen = [
        q for q in benchmark.questions
        if (not args.domain or q.domain == args.domain)
        and (not args.question_type or q.question_type == args.question_type)
        and (not args.iso_only or q.in_g7_scope)
    ]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = [review.packet(q.question_id, sources).to_dict() for q in chosen]
    name = (args.domain or args.question_type or ("iso" if args.iso_only else "all"))
    safe = "".join(c if c.isalnum() else "_" for c in name)[:48]
    path = out / f"packets_{safe}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(payload)} packet(s) -> {path}")
    with_text = sum(1 for p in payload if p["provision_text"])
    print(f"  carrying provision text: {with_text}")
    return 0


def cmd_decide(args) -> int:
    benchmark, review, _, review_root = _open_review(args)
    judgments = []
    if args.substantive:
        judgments.append(Judgment("substantive_elements", args.substantive,
                                  args.substantive_rationale or args.rationale))
    if args.completeness:
        judgments.append(Judgment("completeness", args.completeness,
                                  args.completeness_rationale or args.rationale))
    try:
        decision = review.decide(
            args.question_id, args.state, args.reviewer, args.rationale,
            corrected_citation=args.corrected_citation,
            corrected_iso_clause=args.corrected_iso_clause,
            judgments=judgments, evidence_refs=args.evidence or (),
            corrected_key_elements=args.corrected_key_elements,
            reason_category=args.reason_category,
        )
    except ReviewError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    append_decision(decision, review_root)
    print(f"recorded {decision.state} for {decision.question_id} by {decision.reviewer}")
    if decision.state == "CORRECTED":
        if decision.corrected_citation:
            print(f"  original : {decision.original_citation}")
            print(f"  corrected: {decision.corrected_citation}")
        if decision.corrected_iso_clause:
            print(f"  original ISO : {decision.original_iso_clause}")
            print(f"  corrected ISO: {decision.corrected_iso_clause}")
        if decision.corrected_key_elements:
            print(f"  original J : {decision.original_key_elements}")
            print(f"  corrected J: {decision.corrected_key_elements}")
        print("  the workbook is unchanged; both keys are kept in the record")
    print(f"  state now: {review.state(args.question_id)}")
    return 0


def cmd_sign_off(args) -> int:
    benchmark, review, key_root, review_root = _open_review(args)
    try:
        signoff = review.sign_off(args.reviewer, args.title, args.ecfr_revision_date,
                                  args.iso_edition, args.notes or "")
    except ReviewError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    write_signoff(signoff, review_root)
    locked = review.locked_key()
    locked_dir = key_root / "locked" / f"v{review.review_version}"
    path = write_locked_key(locked, locked_dir)
    print(f"signed off by {signoff['reviewer']} ({signoff['title']})")
    print(f"locked key   : {path}")
    print(f"key version  : {locked['key_version_sha256'][:16]}...")
    print(f"scoring rows : {locked['scoring_rows']} of {len(locked['rows'])}")
    gate = gate_status(benchmark.benchmark_key, args.key_root)
    print(f"gate         : {'OPEN' if gate['open'] else 'CLOSED'} — {gate['reason'] or 'key locked'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workbook", default=str(ROOT / DEFAULT_WORKBOOK))
    parser.add_argument("--key-root", default=str(ROOT / DEFAULT_KEY_ROOT))
    parser.add_argument("--review-version", type=int, default=1)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    queue = sub.add_parser("queue")
    queue.add_argument("--state", default=None)
    queue.add_argument("--limit", type=int, default=30)
    queue.set_defaults(func=cmd_queue)

    packet = sub.add_parser("packet")
    packet.add_argument("question_id")
    packet.add_argument("--json", action="store_true")
    packet.add_argument("--no-text", action="store_true",
                        help="omit provision text (skips the database)")
    packet.set_defaults(func=cmd_packet)

    batch = sub.add_parser("batch", help="write every packet of a batch to a directory for offline review")
    batch.add_argument("--domain", default=None, help="restrict to one workbook domain")
    batch.add_argument("--question-type", default=None)
    batch.add_argument("--iso-only", action="store_true")
    batch.add_argument("--out", default="artifacts/benchmark_keys/packets")
    batch.add_argument("--no-text", action="store_true")
    batch.set_defaults(func=cmd_batch)

    decide = sub.add_parser("decide")
    decide.add_argument("question_id")
    decide.add_argument("--state", required=True, choices=DECISIONS)
    decide.add_argument("--reviewer", required=True)
    decide.add_argument("--rationale", required=True)
    decide.add_argument("--corrected-citation", default=None)
    decide.add_argument("--corrected-iso-clause", default=None)
    decide.add_argument("--corrected-key-elements", default=None,
                        help="corrected column J; requires --state CORRECTED and --evidence")
    decide.add_argument("--substantive", choices=JUDGMENT_VALUES, default=None)
    decide.add_argument("--substantive-rationale", default=None)
    decide.add_argument("--completeness", choices=JUDGMENT_VALUES, default=None)
    decide.add_argument("--completeness-rationale", default=None)
    decide.add_argument("--evidence", nargs="*", default=None)
    decide.add_argument("--reason-category", choices=REASON_CATEGORIES, default=None,
                        help="with NEEDS_RESEARCH or REJECTED: ambiguous, insufficient_evidence or needs_clarification")
    decide.set_defaults(func=cmd_decide)

    signoff = sub.add_parser("sign-off")
    signoff.add_argument("--reviewer", required=True)
    signoff.add_argument("--title", required=True)
    signoff.add_argument("--ecfr-revision-date", required=True)
    signoff.add_argument("--iso-edition", default="ISO 13485:2016(E), third edition, March 1, 2016")
    signoff.add_argument("--notes", default=None)
    signoff.set_defaults(func=cmd_sign_off)

    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
