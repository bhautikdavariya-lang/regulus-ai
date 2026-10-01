"""Controlled SME review of the acceptance benchmark's answer key.

The workbook says the key must be verified by a subject-matter expert before
the test is administered, and that an unverified key invalidates the result.
Automated verification (`key_verification`) settles what a machine can settle
and marks the rest REQUIRES_SME. This module is the controlled path from there
to a locked key:

    benchmark (immutable)
        -> verification run (immutable)
            -> SME review, one auditable decision per question
                -> sign-off
                    -> locked key version  -> scoring may unlock

Four properties it is built to guarantee:

* **Nothing is edited in place.** The workbook is never written. A correction
  is a new decision record carrying the original key beside the corrected one,
  and a locked key is a new version, so historical results stay reproducible.
* **REQUIRES_SME is not VERIFIED.** A row becomes VERIFIED only when a person
  accepted or corrected it, recorded the substantive and completeness
  judgments, and signed the review off. No automated path reaches that state.
* **Every decision is attributable.** Reviewer, timestamp, rationale and the
  evidence consulted are recorded, append-only.
* **The crosswalk is evidence, not authority.** The review packet labels each
  piece of evidence with what it can and cannot establish, so an internal
  mapping is never mistaken for the controlled ISO standard.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from regulus.evaluation.acceptance_benchmark import AcceptanceBenchmark, BenchmarkQuestion
from regulus.evaluation.key_verification import (
    CONTRADICTED,
    DIM_COMPLETENESS,
    DIM_SUBSTANTIVE,
    REQUIRES_SME,
    UNVERIFIABLE,
    RowVerification,
    VerificationArtifact,
)

# ----------------------------------------------------------------- states

STATE_UNREVIEWED = "UNREVIEWED"        # no one has looked at it yet
STATE_REQUIRES_SME = "REQUIRES_SME"    # the verifier referred it to a person
STATE_ACCEPTED = "ACCEPTED"            # the draft key is right as written
STATE_CORRECTED = "CORRECTED"          # the draft key was wrong; a correction is recorded
STATE_REJECTED = "REJECTED"            # the row itself is unusable and is withdrawn from scoring
STATE_NEEDS_RESEARCH = "NEEDS_RESEARCH"  # cannot be settled yet; parked with a reason
STATE_VERIFIED = "VERIFIED"            # resolved, judged and signed off

STATES = (
    STATE_UNREVIEWED, STATE_REQUIRES_SME, STATE_ACCEPTED, STATE_CORRECTED,
    STATE_REJECTED, STATE_NEEDS_RESEARCH, STATE_VERIFIED,
)

# What a reviewer may record. VERIFIED is deliberately absent: it is derived
# at sign-off, never asserted directly.
DECISIONS = (STATE_ACCEPTED, STATE_CORRECTED, STATE_REJECTED, STATE_NEEDS_RESEARCH)
# Stage 7: why a row cannot be accepted yet (recorded with NEEDS_RESEARCH or REJECTED; optional)
REASON_CATEGORIES = ("ambiguous", "insufficient_evidence", "needs_clarification")

# States that settle a row's key. REJECTED settles it too - by removing it.
RESOLVED = (STATE_ACCEPTED, STATE_CORRECTED, STATE_REJECTED)

# A row that still needs work before the key can be locked.
OPEN = (STATE_UNREVIEWED, STATE_REQUIRES_SME, STATE_NEEDS_RESEARCH)

# The two judgments the automated verifier always defers.
JUDGMENT_DIMENSIONS = (DIM_SUBSTANTIVE, DIM_COMPLETENESS)
JUDGMENT_VALUES = ("correct", "partially_correct", "incorrect", "not_applicable")


class ReviewError(ValueError):
    """An invalid transition, a missing field, or an attempt to mutate history."""


# ------------------------------------------------------------- evidence


EVIDENCE_SECTION_EXISTS = "section_exists"
EVIDENCE_CITATION_RESOLVES = "citation_resolves"
EVIDENCE_TEMPORAL_STATE = "temporal_state"
EVIDENCE_ISO_CROSSWALK = "iso_crosswalk"
EVIDENCE_ISO_AUTHORITY = "iso_controlled_standard"
EVIDENCE_SUBSTANTIVE = "regulatory_meaning"

# What each kind of evidence can and cannot establish. The packet carries this
# text so a reviewer is never invited to treat a lookup as a legal conclusion.
EVIDENCE_WEIGHT = {
    EVIDENCE_SECTION_EXISTS: (
        "Establishes only that a section number is present in the eCFR snapshot, "
        "or absent from it. It says nothing about what the section requires."
    ),
    EVIDENCE_CITATION_RESOLVES: (
        "Establishes that the cited section and paragraph resolve in the snapshot. "
        "It does not establish that the citation supports the claim made."
    ),
    EVIDENCE_TEMPORAL_STATE: (
        "Establishes whether the snapshot holds the provision as live, reserved or "
        "removed. The effective date and the reason for reservation come from the "
        "Federal Register, not from this."
    ),
    EVIDENCE_ISO_CROSSWALK: (
        "An internal mapping approved inside this project. It is NOT the ISO standard "
        "and is not authority for what a clause requires; where it disagrees with the "
        "benchmark's key, the controlled copy of ISO 13485:2016 decides."
    ),
    EVIDENCE_ISO_AUTHORITY: (
        "The controlled copy of ISO 13485:2016. Not held in this system; the reviewer "
        "must consult it directly and record what it says."
    ),
    EVIDENCE_SUBSTANTIVE: (
        "The provision's own text. Whether it requires what the key says is a judgment "
        "for a qualified reviewer, not a lookup."
    ),
}


# ------------------------------------------------------------- decisions


@dataclass(frozen=True)
class Judgment:
    """A reviewer's verdict on one of the two deferred dimensions."""

    dimension: str
    value: str
    rationale: str

    def __post_init__(self) -> None:
        if self.dimension not in JUDGMENT_DIMENSIONS:
            raise ReviewError(f"judgment dimension must be one of {JUDGMENT_DIMENSIONS}")
        if self.value not in JUDGMENT_VALUES:
            raise ReviewError(f"judgment value must be one of {JUDGMENT_VALUES}")
        if not self.rationale.strip():
            raise ReviewError("a judgment needs a rationale")

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "value": self.value, "rationale": self.rationale}


@dataclass(frozen=True)
class Decision:
    """One append-only review event for one question.

    A correction carries both keys: `original_*` is what the workbook says and
    is never overwritten, `corrected_*` is what the reviewer determined. That
    holds for the key answer elements (column J) exactly as for the citation
    (G) and the ISO clause (H): a corrected J lives only here and in the locked
    key built from it, never in the workbook or the baseline.
    """

    benchmark_id: str
    benchmark_key: str            # content hash of the workbook this decision is about
    verification_run_id: str
    question_id: str
    state: str
    reviewer: str
    rationale: str
    decided_at: str
    original_citation: str
    original_iso_clause: str
    corrected_citation: str | None = None
    corrected_iso_clause: str | None = None
    judgments: tuple[Judgment, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    review_version: int = 1
    # Column J. Defaults keep decisions recorded before J could be corrected loadable.
    original_key_elements: str = ""
    corrected_key_elements: str | None = None
    # Stage 7: ambiguous / insufficient_evidence / needs_clarification (NEEDS_RESEARCH or REJECTED only)
    reason_category: str | None = None

    def __post_init__(self) -> None:
        if self.reason_category is not None:
            if self.reason_category not in REASON_CATEGORIES:
                raise ReviewError(f"reason category must be one of {REASON_CATEGORIES}")
            if self.state not in (STATE_NEEDS_RESEARCH, STATE_REJECTED):
                raise ReviewError("a reason category is recorded only with NEEDS_RESEARCH or REJECTED")
        if self.state not in DECISIONS:
            raise ReviewError(
                f"a reviewer may record {DECISIONS}; {self.state!r} is not one of them "
                "(VERIFIED is derived at sign-off, never asserted)"
            )
        if not self.reviewer.strip():
            raise ReviewError("every decision must name its reviewer")
        if not self.rationale.strip():
            raise ReviewError("every decision must carry a rationale")
        corrections = (self.corrected_citation, self.corrected_iso_clause, self.corrected_key_elements)
        if self.state == STATE_CORRECTED and not any(corrections):
            raise ReviewError("a CORRECTED decision must record what the key should say")
        if self.state != STATE_CORRECTED and any(corrections):
            raise ReviewError("only a CORRECTED decision may carry a corrected key")
        if self.corrected_key_elements is not None:
            if not self.corrected_key_elements.strip():
                raise ReviewError("a corrected column J must say what the answer elements should be")
            if self.original_key_elements and \
                    self.corrected_key_elements.strip() == self.original_key_elements.strip():
                raise ReviewError("the corrected column J is identical to the original; that is not a correction")
            if not any(e.strip() for e in self.evidence_refs):
                raise ReviewError(
                    "correcting column J rewrites what a correct answer must say; record the evidence "
                    "(the provision text relied on) with it"
                )

    @property
    def judgment_values(self) -> dict[str, str]:
        return {j.dimension: j.value for j in self.judgments}

    @property
    def has_required_judgments(self) -> bool:
        """Accepting or correcting a row means judging its substance too."""
        if self.state in (STATE_REJECTED, STATE_NEEDS_RESEARCH):
            return True
        return all(d in self.judgment_values for d in JUDGMENT_DIMENSIONS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "benchmark_key": self.benchmark_key,
            "verification_run_id": self.verification_run_id,
            "question_id": self.question_id,
            "state": self.state,
            "reviewer": self.reviewer,
            "rationale": self.rationale,
            "decided_at": self.decided_at,
            "original_citation": self.original_citation,
            "original_iso_clause": self.original_iso_clause,
            "corrected_citation": self.corrected_citation,
            "corrected_iso_clause": self.corrected_iso_clause,
            "judgments": [j.to_dict() for j in self.judgments],
            "evidence_refs": list(self.evidence_refs),
            "review_version": self.review_version,
            "original_key_elements": self.original_key_elements,
            "corrected_key_elements": self.corrected_key_elements,
            "reason_category": self.reason_category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Decision":
        return cls(
            benchmark_id=data["benchmark_id"], benchmark_key=data["benchmark_key"],
            verification_run_id=data["verification_run_id"], question_id=data["question_id"],
            state=data["state"], reviewer=data["reviewer"], rationale=data["rationale"],
            decided_at=data["decided_at"], original_citation=data.get("original_citation", ""),
            original_iso_clause=data.get("original_iso_clause", ""),
            corrected_citation=data.get("corrected_citation"),
            corrected_iso_clause=data.get("corrected_iso_clause"),
            judgments=tuple(Judgment(**j) for j in data.get("judgments") or []),
            evidence_refs=tuple(data.get("evidence_refs") or []),
            review_version=int(data.get("review_version", 1)),
            original_key_elements=data.get("original_key_elements", ""),
            corrected_key_elements=data.get("corrected_key_elements"),
            reason_category=data.get("reason_category"),
        )


# ---------------------------------------------------------------- packet


@dataclass(frozen=True)
class ReviewPacket:
    """Everything a reviewer needs for one question, and nothing else."""

    question_id: str
    benchmark_id: str
    benchmark_key: str
    verification_run_id: str
    question: str
    domain: str
    question_type: str
    difficulty: str
    draft_citation: str
    draft_iso_clause: str
    draft_iso_clause_title: str
    key_answer_elements: str
    automated_state: str
    automated_findings: tuple[dict[str, Any], ...]
    referral_reasons: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    current_state: str
    open_questions: tuple[str, ...]
    # The provision's own words, so substance can be judged without leaving the
    # tool. eCFR only: no ISO text is ever carried here.
    provision_text: tuple[dict[str, Any], ...] = ()
    # For absence claims: what the named part actually says on the subject.
    absence_search: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id, "benchmark_id": self.benchmark_id,
            "benchmark_key": self.benchmark_key, "verification_run_id": self.verification_run_id,
            "question": self.question, "domain": self.domain,
            "question_type": self.question_type, "difficulty": self.difficulty,
            "draft_citation": self.draft_citation, "draft_iso_clause": self.draft_iso_clause,
            "draft_iso_clause_title": self.draft_iso_clause_title,
            "key_answer_elements": self.key_answer_elements,
            "automated_state": self.automated_state,
            "automated_findings": list(self.automated_findings),
            "referral_reasons": list(self.referral_reasons),
            "evidence": list(self.evidence),
            "current_state": self.current_state,
            "open_questions": list(self.open_questions),
            "provision_text": list(self.provision_text),
            "absence_search": list(self.absence_search),
        }


def _evidence_for(finding: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one automated finding into a labelled piece of evidence."""
    dimension = finding["dimension"]
    kind = {
        "citation": EVIDENCE_CITATION_RESOLVES,
        "provision_paragraph": EVIDENCE_CITATION_RESOLVES,
        "temporal_status": EVIDENCE_TEMPORAL_STATE,
        "negative_control": EVIDENCE_SECTION_EXISTS,
        "iso_clause": EVIDENCE_ISO_CROSSWALK,
        DIM_SUBSTANTIVE: EVIDENCE_SUBSTANTIVE,
        DIM_COMPLETENESS: EVIDENCE_SUBSTANTIVE,
    }.get(dimension)
    if kind is None or finding["status"] == "NOT_APPLICABLE":
        return None
    return {
        "kind": kind,
        "establishes": EVIDENCE_WEIGHT[kind],
        "dimension": dimension,
        "status": finding["status"],
        "detail": finding["detail"],
        "data": finding.get("evidence") or {},
    }


def build_packet(
    question: BenchmarkQuestion,
    verification: RowVerification,
    verification_run_id: str,
    current_state: str,
    benchmark_key: str = "",
    provision_text: Iterable[dict[str, Any]] = (),
    absence_search: Iterable[dict[str, Any]] = (),
) -> ReviewPacket:
    findings = tuple(f.to_dict() for f in verification.findings)
    referrals = tuple(
        f["detail"] for f in findings if f["status"] in (REQUIRES_SME, CONTRADICTED, UNVERIFIABLE)
    )
    evidence = tuple(e for e in (_evidence_for(f) for f in findings) if e is not None)

    open_questions: list[str] = []
    for f in findings:
        if f["status"] == CONTRADICTED:
            open_questions.append(f"Resolve the contradiction on {f['dimension']}: {f['detail']}")
        elif f["status"] == REQUIRES_SME and f["dimension"] not in JUDGMENT_DIMENSIONS:
            open_questions.append(f"Settle {f['dimension']}: {f['detail']}")
        elif f["status"] == UNVERIFIABLE:
            open_questions.append(f"No source here settles {f['dimension']}: {f['detail']}")
    open_questions.append(
        "Record the substantive judgment: does the cited provision actually require what the key "
        "answer elements say?"
    )
    open_questions.append(
        "Record the completeness judgment: does the key name every governing provision this "
        "question reaches?"
    )
    if question.in_g7_scope:
        open_questions.append(
            "Confirm the ISO clause against the controlled copy of ISO 13485:2016. The crosswalk "
            "in this system is an internal mapping and is not authority."
        )

    return ReviewPacket(
        question_id=question.question_id,
        benchmark_id=verification.benchmark_id,
        benchmark_key=benchmark_key,
        verification_run_id=verification_run_id,
        question=question.question,
        domain=question.domain,
        question_type=question.question_type,
        difficulty=question.difficulty,
        draft_citation=question.expected_citation_draft,
        draft_iso_clause=question.iso_clause_draft,
        draft_iso_clause_title=question.iso_clause_title,
        key_answer_elements=question.key_answer_elements,
        automated_state=verification.verification_status,
        automated_findings=findings,
        referral_reasons=referrals,
        evidence=evidence,
        current_state=current_state,
        open_questions=tuple(open_questions),
        provision_text=tuple(provision_text),
        absence_search=tuple(absence_search),
    )


# The words that carry no signal in a regulatory question, skipped when
# building an absence search so the query is about the subject, not the grammar.
_STOPWORDS = {
    "which", "what", "does", "require", "requires", "required", "under", "section",
    "part", "every", "each", "must", "that", "this", "there", "where", "when", "with",
    "from", "into", "have", "has", "the", "and", "for", "are", "is", "of", "to", "a",
    "an", "in", "on", "by", "or", "be", "any", "all", "how", "many", "much", "cfr",
}


def _search_terms(question: BenchmarkQuestion, limit: int = 4) -> list[str]:
    import re as _re

    words = [w.lower() for w in _re.findall(r"[A-Za-z]{4,}", question.question)]
    seen: list[str] = []
    for word in words:
        if word in _STOPWORDS or word in seen:
            continue
        seen.append(word)
    return seen[:limit]


def gather_provision_text(question: BenchmarkQuestion, sources: Any) -> tuple[dict[str, Any], ...]:
    """The eCFR text of every provision the draft key cites."""
    if not hasattr(sources, "provision_text"):
        return ()
    from regulus.retrieval.references import parse_cfr_references

    out: list[dict[str, Any]] = []
    for ref in parse_cfr_references(question.expected_citation_draft):
        if ref.section is None:
            continue
        rows = sources.provision_text(ref.section, ref.paragraph_path)
        if rows:
            out.append({
                "citation": ref.canonical,
                "source": "eCFR snapshot (US Government work)",
                "records": rows,
            })
    return tuple(out)


def gather_absence_search(question: BenchmarkQuestion, sources: Any) -> tuple[dict[str, Any], ...]:
    """For an absence claim, what the named part actually says on the subject."""
    if not question.is_negative_control or not hasattr(sources, "search_part"):
        return ()
    from regulus.retrieval.references import parse_cfr_references

    parts = {r.part for r in parse_cfr_references(question.question) if r.part}
    parts |= {r.part for r in parse_cfr_references(question.expected_citation_draft) if r.part}
    terms = _search_terms(question)
    out = []
    for part in sorted(parts):
        hits = sources.search_part(part, terms)
        out.append({
            "part": part,
            "terms": terms,
            "hits": hits,
            "reading": (
                "These are the provisions of the part whose text mentions those terms. An empty "
                "result is consistent with the absence claim but does not prove it: the requirement "
                "could be worded differently, or sit in another part. The reviewer decides."
            ),
        })
    return tuple(out)


# ----------------------------------------------------------------- review


@dataclass
class KeyReview:
    """The review of one benchmark version against one verification run.

    Decisions are append-only: recording a new one supersedes the previous
    decision for that question without erasing it, so the history of how a row
    reached its state is always recoverable.
    """

    benchmark: AcceptanceBenchmark
    verification: VerificationArtifact
    verification_run_id: str
    review_version: int = 1
    decisions: list[Decision] = field(default_factory=list)
    signoff: dict[str, Any] | None = None

    # ---- state

    def history(self, question_id: str) -> tuple[Decision, ...]:
        return tuple(d for d in self.decisions if d.question_id == question_id)

    def latest(self, question_id: str) -> Decision | None:
        history = self.history(question_id)
        return history[-1] if history else None

    def state(self, question_id: str) -> str:
        """A row's state now: signed off, decided, referred, or untouched."""
        decision = self.latest(question_id)
        if decision is not None:
            if self.is_signed_off and decision.state in (STATE_ACCEPTED, STATE_CORRECTED) \
                    and decision.has_required_judgments:
                return STATE_VERIFIED
            return decision.state
        row = self.verification.row(question_id)
        if row is None:
            return STATE_UNREVIEWED
        # the automated pass referred everything it could not settle
        return STATE_REQUIRES_SME if row.verification_status != "VERIFIED" else STATE_UNREVIEWED

    @property
    def is_signed_off(self) -> bool:
        return bool(self.signoff)

    def open_rows(self) -> tuple[str, ...]:
        return tuple(q.question_id for q in self.benchmark.questions if self.state(q.question_id) in OPEN)

    def rows_missing_judgments(self) -> tuple[str, ...]:
        out = []
        for q in self.benchmark.questions:
            decision = self.latest(q.question_id)
            if decision is not None and not decision.has_required_judgments:
                out.append(q.question_id)
        return tuple(out)

    # ---- recording

    def record(self, decision: Decision) -> Decision:
        if self.is_signed_off:
            raise ReviewError(
                "this review is signed off and sealed; record further work as a new review version"
            )
        if self.benchmark.get(decision.question_id) is None:
            raise ReviewError(f"{decision.question_id} is not a question in this benchmark")
        if decision.benchmark_key != self.benchmark.benchmark_key:
            raise ReviewError(
                f"decision is against benchmark {decision.benchmark_key}, this review is of "
                f"{self.benchmark.benchmark_key}"
            )
        self.decisions.append(decision)
        return decision

    def decide(
        self,
        question_id: str,
        state: str,
        reviewer: str,
        rationale: str,
        corrected_citation: str | None = None,
        corrected_iso_clause: str | None = None,
        judgments: Iterable[Judgment] = (),
        evidence_refs: Iterable[str] = (),
        corrected_key_elements: str | None = None,
        reason_category: str | None = None,
    ) -> Decision:
        """Record one decision, carrying the original key beside any correction."""
        question = self.benchmark.get(question_id)
        if question is None:
            raise ReviewError(f"{question_id} is not a question in this benchmark")
        return self.record(Decision(
            benchmark_id=self.benchmark.benchmark_id,
            benchmark_key=self.benchmark.benchmark_key,
            verification_run_id=self.verification_run_id,
            question_id=question_id,
            state=state,
            reviewer=reviewer,
            rationale=rationale,
            decided_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            original_citation=question.expected_citation_draft,
            original_iso_clause=question.iso_clause_draft,
            corrected_citation=corrected_citation,
            corrected_iso_clause=corrected_iso_clause,
            judgments=tuple(judgments),
            evidence_refs=tuple(evidence_refs),
            review_version=self.review_version,
            original_key_elements=question.key_answer_elements,
            corrected_key_elements=corrected_key_elements,
            reason_category=reason_category,
        ))

    # ---- packets

    def packet(self, question_id: str, sources: Any = None) -> ReviewPacket:
        """One review packet. With `sources`, the provision's own text is
        attached so substance can be judged without leaving the tool."""
        question = self.benchmark.get(question_id)
        if question is None:
            raise ReviewError(f"{question_id} is not a question in this benchmark")
        row = self.verification.row(question_id)
        if row is None:
            raise ReviewError(f"{question_id} has no verification record")
        texts, search = (), ()
        if sources is not None:
            texts = gather_provision_text(question, sources)
            search = gather_absence_search(question, sources)
        return build_packet(question, row, self.verification_run_id, self.state(question_id),
                            benchmark_key=self.benchmark.benchmark_key,
                            provision_text=texts, absence_search=search)

    def packets(self, sources: Any = None) -> tuple[ReviewPacket, ...]:
        return tuple(self.packet(q.question_id, sources) for q in self.benchmark.questions)

    # ---- sign-off

    def sign_off(self, reviewer: str, title: str, ecfr_revision_date: str,
                 iso_edition: str, notes: str = "") -> dict[str, Any]:
        """Seal the review. Refuses while any row is unresolved.

        This is the only route to VERIFIED, and it is a person's act.
        """
        if self.is_signed_off:
            raise ReviewError("this review is already signed off")
        if not reviewer.strip() or not title.strip():
            raise ReviewError("sign-off must name the reviewer and their title")
        if not ecfr_revision_date.strip():
            raise ReviewError(
                "sign-off must record the eCFR revision date the key was verified against"
            )
        open_rows = self.open_rows()
        if open_rows:
            raise ReviewError(
                f"{len(open_rows)} row(s) are still unresolved and must be decided before sign-off: "
                + ", ".join(open_rows[:10]) + ("..." if len(open_rows) > 10 else "")
            )
        missing = self.rows_missing_judgments()
        if missing:
            raise ReviewError(
                f"{len(missing)} row(s) have no substantive/completeness judgment: "
                + ", ".join(missing[:10]) + ("..." if len(missing) > 10 else "")
            )
        self.signoff = {
            "reviewer": reviewer, "title": title,
            "ecfr_revision_date": ecfr_revision_date, "iso_edition": iso_edition,
            "notes": notes,
            "signed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_key": self.benchmark.benchmark_key,
            "verification_run_id": self.verification_run_id,
            "review_version": self.review_version,
            "decisions": len(self.decisions),
        }
        return self.signoff

    # ---- the locked key

    def locked_key(self) -> dict[str, Any]:
        """The immutable result of a signed-off review.

        Each row carries the original key and, where it was corrected, the
        correction - so a later reader can always see what changed and why.
        """
        if not self.is_signed_off:
            raise ReviewError("a key can only be locked from a signed-off review")
        rows = []
        for question in self.benchmark.questions:
            decision = self.latest(question.question_id)
            state = self.state(question.question_id)
            rows.append({
                "question_id": question.question_id,
                "state": state,
                "in_scope_for_scoring": state == STATE_VERIFIED,
                "original_citation": question.expected_citation_draft,
                "original_iso_clause": question.iso_clause_draft,
                "accepted_citation": (decision.corrected_citation or question.expected_citation_draft)
                                     if state == STATE_VERIFIED else None,
                "accepted_iso_clause": (decision.corrected_iso_clause or question.iso_clause_draft)
                                       if state == STATE_VERIFIED else None,
                # Column J: the workbook's text is kept beside whatever the SME
                # accepted, and nothing is accepted for a row that is not VERIFIED.
                "original_key_elements": question.key_answer_elements,
                "accepted_key_elements": (decision.corrected_key_elements or question.key_answer_elements)
                                         if state == STATE_VERIFIED else None,
                "key_elements_corrected": bool(decision and decision.corrected_key_elements),
                "was_corrected": bool(decision and decision.state == STATE_CORRECTED),
                "judgments": decision.judgment_values if decision else {},
                "reviewer": decision.reviewer if decision else None,
                "rationale": decision.rationale if decision else None,
            })
        payload = {
            "benchmark_id": self.benchmark.benchmark_id,
            "benchmark_key": self.benchmark.benchmark_key,
            "workbook_sha256": self.benchmark.sha256,
            "verification_run_id": self.verification_run_id,
            "review_version": self.review_version,
            "signoff": self.signoff,
            "rows": rows,
            "scoring_rows": sum(1 for r in rows if r["in_scope_for_scoring"]),
            "withdrawn_rows": [r["question_id"] for r in rows if r["state"] == STATE_REJECTED],
        }
        payload["key_version_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        return payload

    # ---- reporting

    def summary(self) -> dict[str, Any]:
        by_state: dict[str, int] = {}
        for question in self.benchmark.questions:
            state = self.state(question.question_id)
            by_state[state] = by_state.get(state, 0) + 1
        contradicted = [r.question_id for r in self.verification.contradicted]
        iso_conflicts = [
            r.question_id for r in self.verification.rows
            for f in r.findings if f.dimension == "iso_clause" and f.status == REQUIRES_SME
        ]
        absence_claims = [
            r.question_id for r in self.verification.rows
            for f in r.findings if f.dimension == "negative_control" and f.status == REQUIRES_SME
        ]
        open_rows = self.open_rows()
        return {
            "benchmark_id": self.benchmark.benchmark_id,
            "benchmark_key": self.benchmark.benchmark_key,
            "verification_run_id": self.verification_run_id,
            "review_version": self.review_version,
            "questions": len(self.benchmark.questions),
            "by_state": by_state,
            "decisions_recorded": len(self.decisions),
            "key_element_corrections": sum(
                1 for q in self.benchmark.questions
                if (d := self.latest(q.question_id)) is not None and d.corrected_key_elements),
            "open_rows": len(open_rows),
            "open_ids": list(open_rows[:50]),
            "rows_missing_judgments": len(self.rows_missing_judgments()),
            "contradicted_by_automation": contradicted,
            "iso_conflicts": sorted(set(iso_conflicts)),
            "absence_claims": sorted(set(absence_claims)),
            "signed_off": self.is_signed_off,
            "signoff": self.signoff,
            "key_locked": self.is_signed_off and not open_rows,
        }


# ------------------------------------------------------------ persistence


DECISIONS_FILE = "decisions.jsonl"
SIGNOFF_FILE = "signoff.json"
BASELINE_FILE = "baseline.json"
LOCKED_FILE = "locked_key.json"


def write_baseline(benchmark: AcceptanceBenchmark, root: Path) -> Path:
    """Freeze the benchmark as an immutable baseline.

    Writing it twice is fine; writing *different* content under the same
    identity is refused, which is what makes the baseline trustworthy.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / BASELINE_FILE
    payload = {
        "benchmark_id": benchmark.benchmark_id,
        "benchmark_key": benchmark.benchmark_key,
        "workbook_sha256": benchmark.sha256,
        "workbook_path": benchmark.path,
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions": [q.to_dict() for q in benchmark.questions],
    }
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("workbook_sha256") != benchmark.sha256:
            raise ReviewError(
                f"{path} already holds a baseline for workbook {existing.get('workbook_sha256')}; "
                f"this workbook is {benchmark.sha256}. A different benchmark is a new version, not "
                "an overwrite."
            )
        return path
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def append_decision(decision: Decision, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / DECISIONS_FILE
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")
    return path


def read_decisions(root: Path) -> list[Decision]:
    path = root / DECISIONS_FILE
    if not path.is_file():
        return []
    return [Decision.from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_signoff(signoff: dict[str, Any], root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / SIGNOFF_FILE
    if path.is_file():
        raise ReviewError(f"{path} already exists; a signed review is sealed")
    path.write_text(json.dumps(signoff, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_signoff(root: Path) -> dict[str, Any] | None:
    path = root / SIGNOFF_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_locked_key(payload: dict[str, Any], root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOCKED_FILE
    if path.is_file():
        raise ReviewError(f"{path} already exists; a locked key version is immutable")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_review(
    benchmark: AcceptanceBenchmark,
    verification: VerificationArtifact,
    verification_run_id: str,
    root: Path,
    review_version: int = 1,
) -> KeyReview:
    """Rebuild a review from its append-only record on disk."""
    review = KeyReview(benchmark=benchmark, verification=verification,
                       verification_run_id=verification_run_id, review_version=review_version)
    review.decisions = read_decisions(root)
    review.signoff = read_signoff(root)
    return review


def verification_counts(review: "KeyReview") -> dict[str, Any]:
    """Stage 7: the honest one-line status of the answer key.

    expert_verified  VERIFIED: resolved, judged and signed off by a named reviewer (the only verified state)
    accepted_unsigned ACCEPTED by a reviewer but not yet signed off (NOT counted as verified)
    disputed         CORRECTED (the draft key was wrong) or REJECTED (the row is unusable)
    pending          everything else: UNREVIEWED, REQUIRES_SME, NEEDS_RESEARCH
    """
    counts = {"total": len(review.benchmark.questions), "expert_verified": 0, "accepted_unsigned": 0, "disputed": 0, "pending": 0}
    reasons: dict[str, int] = {}
    for q in review.benchmark.questions:
        state = review.state(q.question_id)
        if state == STATE_VERIFIED:
            counts["expert_verified"] += 1
        elif state == STATE_ACCEPTED:
            counts["accepted_unsigned"] += 1
        elif state in (STATE_CORRECTED, STATE_REJECTED):
            counts["disputed"] += 1
        else:
            counts["pending"] += 1
        d = review.latest(q.question_id)
        if d is not None and d.reason_category:
            reasons[d.reason_category] = reasons.get(d.reason_category, 0) + 1
    counts["reason_categories"] = reasons
    return counts
