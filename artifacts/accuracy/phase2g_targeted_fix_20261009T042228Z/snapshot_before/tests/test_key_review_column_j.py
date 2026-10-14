"""Column J (key answer elements) can be corrected by an SME, safely.

The review record could correct the citation (G) and the ISO clause (H) but
not the answer elements (J), although J is what substantive correctness (G4)
is scored against. These tests pin the properties the correction must keep:
the original J is preserved, a corrected J exists only in a reviewed key
version, every correction is attributable, an unreviewed J can never reach
scoring, and a historical key version still rebuilds exactly.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from regulus.evaluation.acceptance_gate import AcceptanceGateError, require_locked_key
from regulus.evaluation.key_review import (
    STATE_ACCEPTED,
    STATE_CORRECTED,
    STATE_NEEDS_RESEARCH,
    STATE_REJECTED,
    STATE_VERIFIED,
    Decision,
    ReviewError,
    append_decision,
    load_review,
    read_decisions,
    write_baseline,
    write_locked_key,
    write_signoff,
)

from .test_key_review import RUN_ID, judgments, make_review

ROOT = Path(__file__).resolve().parent.parent
NEW_J = "Records of review, evaluation and investigation, and the justification when no investigation is made."
EVIDENCE = ("eCFR 21 CFR 820.35(a), snapshot 2026-09-03",)


def correct_j(review, qid="Q-1", j=NEW_J, **kw):
    return review.decide(qid, STATE_CORRECTED, "SME, Title", "J overstated the requirement",
                         corrected_key_elements=j, judgments=judgments(), evidence_refs=EVIDENCE, **kw)


# ----------------------------------------------------- original J is preserved


def test_the_original_column_j_is_kept_beside_the_correction():
    review = make_review()
    original = review.benchmark.get("Q-1").key_answer_elements
    decision = correct_j(review)
    assert decision.original_key_elements == original
    assert decision.corrected_key_elements == NEW_J
    # the benchmark question itself is untouched
    assert review.benchmark.get("Q-1").key_answer_elements == original


def test_correcting_j_never_touches_the_frozen_baseline(tmp_path):
    review = make_review()
    path = write_baseline(review.benchmark, tmp_path)
    before = path.read_bytes()
    append_decision(correct_j(review), tmp_path / "review" / "v1")
    write_baseline(review.benchmark, tmp_path)          # re-freezing is a no-op
    assert path.read_bytes() == before
    assert all(q["key_answer_elements"] == "e" for q in json.loads(before)["questions"])


def test_the_locked_key_carries_both_the_original_and_the_accepted_j():
    review = make_review()
    correct_j(review, "Q-1")
    review.decide("Q-2", STATE_ACCEPTED, "SME", "fine", judgments=judgments())
    review.sign_off("SME", "Director", "2026-09-03", "ISO 13485:2016(E)")
    rows = {r["question_id"]: r for r in review.locked_key()["rows"]}
    assert rows["Q-1"]["original_key_elements"] == "e"
    assert rows["Q-1"]["accepted_key_elements"] == NEW_J
    assert rows["Q-1"]["key_elements_corrected"] is True
    assert rows["Q-2"]["accepted_key_elements"] == "e"          # accepted as written
    assert rows["Q-2"]["key_elements_corrected"] is False


# ------------------------------------------------------ what a J correction is


def test_a_j_only_correction_is_a_complete_correction():
    review = make_review()
    decision = correct_j(review)
    assert decision.corrected_citation is None and decision.corrected_iso_clause is None
    assert review.state("Q-1") == STATE_CORRECTED
    review.decide("Q-2", STATE_ACCEPTED, "SME", "fine", judgments=judgments())
    review.sign_off("SME", "Director", "2026-09-03", "ISO")
    row = next(r for r in review.locked_key()["rows"] if r["question_id"] == "Q-1")
    assert row["accepted_citation"] == row["original_citation"]   # G unchanged
    assert row["accepted_key_elements"] == NEW_J


@pytest.mark.parametrize("state", [STATE_ACCEPTED, STATE_REJECTED, STATE_NEEDS_RESEARCH])
def test_only_a_correction_may_carry_a_corrected_j(state):
    review = make_review()
    with pytest.raises(ReviewError, match="only a CORRECTED decision"):
        review.decide("Q-1", state, "SME", "why", corrected_key_elements=NEW_J,
                      judgments=judgments(), evidence_refs=EVIDENCE)


def test_a_j_correction_must_cite_its_evidence():
    review = make_review()
    with pytest.raises(ReviewError, match="record the evidence"):
        review.decide("Q-1", STATE_CORRECTED, "SME", "why", corrected_key_elements=NEW_J,
                      judgments=judgments())


def test_a_blank_or_unchanged_j_is_not_a_correction():
    review = make_review()
    with pytest.raises(ReviewError):
        correct_j(review, j="   ")
    with pytest.raises(ReviewError, match="identical to the original"):
        correct_j(review, j="e")


# ------------------------------------------------------- auditable, append-only


def test_a_j_correction_is_attributable_and_append_only(tmp_path):
    review = make_review()
    first = review.decide("Q-1", STATE_NEEDS_RESEARCH, "SME A, Reviewer", "J wording unclear")
    second = correct_j(review)
    for d in (first, second):
        append_decision(d, tmp_path)

    lines = [json.loads(l) for l in (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [l["state"] for l in lines] == [STATE_NEEDS_RESEARCH, STATE_CORRECTED]
    record = lines[-1]
    for field in ("reviewer", "rationale", "decided_at", "evidence_refs", "review_version",
                  "original_key_elements", "corrected_key_elements"):
        assert record[field], field
    assert record["original_key_elements"] == "e" and record["corrected_key_elements"] == NEW_J
    # the history survives a reload, earlier decision included
    rebuilt = load_review(review.benchmark, review.verification, RUN_ID, tmp_path)
    assert [d.state for d in rebuilt.history("Q-1")] == [STATE_NEEDS_RESEARCH, STATE_CORRECTED]
    assert rebuilt.latest("Q-1").corrected_key_elements == NEW_J


def test_decisions_recorded_before_j_could_be_corrected_still_load():
    legacy = {
        "benchmark_id": "regulus_acceptance_rev02", "benchmark_key": "b@1", "verification_run_id": RUN_ID,
        "question_id": "Q-1", "state": STATE_CORRECTED, "reviewer": "SME", "rationale": "old record",
        "decided_at": "2026-01-01T00:00:00+00:00", "original_citation": "21 CFR 111.1",
        "original_iso_clause": "—", "corrected_citation": "21 CFR 111.3", "corrected_iso_clause": None,
        "judgments": [], "evidence_refs": [], "review_version": 1,
    }
    decision = Decision.from_dict(legacy)
    assert decision.corrected_key_elements is None
    assert decision.original_key_elements == ""


def test_the_summary_counts_j_corrections():
    review = make_review()
    correct_j(review)
    assert review.summary()["key_element_corrections"] == 1


# ------------------------------------------------ unreviewed J cannot be scored


def test_a_corrected_j_does_not_reach_scoring_until_the_review_is_signed_off(tmp_path):
    review = make_review()
    correct_j(review)                                        # Q-2 still open
    with pytest.raises(ReviewError):
        review.locked_key()                                  # nothing to score against
    with pytest.raises(AcceptanceGateError):
        require_locked_key(review.benchmark.benchmark_key, "Scoring", tmp_path)


def test_no_j_is_offered_for_scoring_on_a_row_that_is_not_verified():
    review = make_review()
    correct_j(review, "Q-1")
    review.decide("Q-2", STATE_REJECTED, "SME", "row withdrawn")
    review.sign_off("SME", "Director", "2026-09-03", "ISO")
    rows = {r["question_id"]: r for r in review.locked_key()["rows"]}
    assert rows["Q-1"]["state"] == STATE_VERIFIED and rows["Q-1"]["in_scope_for_scoring"]
    assert rows["Q-2"]["in_scope_for_scoring"] is False
    assert rows["Q-2"]["accepted_key_elements"] is None      # withdrawn, so no J to score against
    assert rows["Q-2"]["original_key_elements"] == "e"       # but the record still shows it


def test_a_correction_missing_its_judgments_cannot_be_signed_off():
    review = make_review()
    review.decide("Q-1", STATE_CORRECTED, "SME", "why", corrected_key_elements=NEW_J, evidence_refs=EVIDENCE)
    review.decide("Q-2", STATE_ACCEPTED, "SME", "fine", judgments=judgments())
    with pytest.raises(ReviewError, match="no substantive/completeness judgment"):
        review.sign_off("SME", "Director", "2026-09-03", "ISO")


# --------------------------------------------------- versioned and reproducible


def test_a_corrected_j_exists_only_in_the_version_that_corrected_it(tmp_path):
    v1 = make_review(("Q-1",))
    v1.decide("Q-1", STATE_ACCEPTED, "SME", "as written", judgments=judgments())
    v1.sign_off("SME", "Director", "2026-09-03", "ISO")
    locked_v1 = v1.locked_key()
    key_dir = tmp_path / v1.benchmark.benchmark_key.replace("@", "_")
    write_locked_key(locked_v1, key_dir / "locked" / "v1")

    v2 = make_review(("Q-1",))
    v2.review_version = 2
    correct_j(v2)
    v2.sign_off("SME", "Director", "2026-10-01", "ISO")
    locked_v2 = v2.locked_key()
    write_locked_key(locked_v2, key_dir / "locked" / "v2")

    assert locked_v1["rows"][0]["accepted_key_elements"] == "e"
    assert locked_v2["rows"][0]["accepted_key_elements"] == NEW_J
    assert locked_v2["rows"][0]["original_key_elements"] == "e"
    assert locked_v1["key_version_sha256"] != locked_v2["key_version_sha256"]
    on_disk = json.loads((key_dir / "locked" / "v1" / "locked_key.json").read_text(encoding="utf-8"))
    assert on_disk["rows"][0]["accepted_key_elements"] == "e"   # v1 unaffected by v2


def test_a_locked_key_rebuilds_byte_for_byte_from_its_record(tmp_path):
    review = make_review()
    root = tmp_path / "review" / "v1"
    for d in (correct_j(review, "Q-1"),
              review.decide("Q-2", STATE_ACCEPTED, "SME", "fine", judgments=judgments())):
        append_decision(d, root)
    write_signoff(review.sign_off("SME", "Director", "2026-09-03", "ISO"), root)
    original = review.locked_key()

    rebuilt = load_review(review.benchmark, review.verification, RUN_ID, root)
    assert rebuilt.locked_key() == original
    assert rebuilt.locked_key()["key_version_sha256"] == original["key_version_sha256"]
    assert [d.to_dict() for d in read_decisions(root)] == [d.to_dict() for d in review.decisions]


# ----------------------------------------------------------------- the CLI path


WORKBOOK = ROOT / "Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx"


@pytest.mark.skipif(not WORKBOOK.is_file() or not any((ROOT / "artifacts" / "benchmark_verification").glob("*/verification.json")),
                    reason="needs the workbook and a verification run")
def test_the_review_tool_records_a_j_correction_into_an_isolated_key_root(tmp_path):
    before = WORKBOOK.read_bytes()
    base = [sys.executable, str(ROOT / "scripts" / "review_benchmark_key.py"), "--key-root", str(tmp_path),
            "decide", "S-001", "--state", "CORRECTED", "--reviewer", "Test SME, Tester",
            "--rationale", "test", "--corrected-key-elements", "a corrected J",
            "--substantive", "correct", "--completeness", "correct"]
    refused = subprocess.run(base, capture_output=True, text=True, cwd=ROOT)
    assert refused.returncode == 2 and "evidence" in refused.stderr

    ok = subprocess.run(base + ["--evidence", "eCFR 21 CFR 111.1"], capture_output=True, text=True, cwd=ROOT)
    assert ok.returncode == 0, ok.stderr
    log = next(tmp_path.glob("*/review/v1/decisions.jsonl"))
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["corrected_key_elements"] == "a corrected J"
    assert record["original_key_elements"].startswith("Manufacture, package, label, or hold")
    assert WORKBOOK.read_bytes() == before                  # the workbook is never written
