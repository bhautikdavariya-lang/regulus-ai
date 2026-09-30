"""Stage 13 grounding metrics for a saved RAG evaluation run.

Stage 12 regressed on exactly the behaviour the mean reviewer score measures
least well: it kept answering when it should have refused. These metrics
separate that behaviour from answer quality, and report the two directions of
error separately so an improvement cannot be manufactured by refusing more
often.

Every metric is computed from a saved result file plus the benchmark's own
`expected_behavior` field. Nothing here re-runs the model, and nothing here
depends on the reviewer scores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from regulus.grounding.identifiers import extract_identifier

# Phrases the project uses to decline. Kept in one place so "refusal" means the
# same thing in the metrics as it does in the training data and the gate.
REFUSAL_PHRASES = (
    "do not provide enough information",
    "does not provide enough information",
    "could not verify",
    "could not find",
    "does not establish",
    "do not establish",
    "cannot provide",
    "cannot state",
    "cannot answer",
    "cannot describe",
    "cannot summarize",
    "not enough information",
    "is reserved in the available",
    "no paragraph",
    # second sentence of the pipeline's deterministic no-context refusal
    "no sufficiently relevant",
    "was retrieved for the question",
)

# Sentences that describe what the sources are rather than answer the question.
# A refusal is usually accompanied by such an explanation ("The provided source
# is 21 CFR 11.1(a), which is in Part 11, not Part 945"), and counting that
# explanation as substantive content would misclassify the refusal as an answer.
SOURCE_COMMENTARY_PHRASES = (
    "the provided source",
    "the provided context",
    "the provided passage",
    "the retrieved source",
    "the other provided sources",
    "the available context",
    "the available eCFR data contains",
    "its paragraphs are",
    "a different document",
    # varied refusal openings introduced in the v3 data
    "the only source provided",
    "was supplied, and it",
    "what the context actually contains",
    "is the only source",
)
_MARK_RE = re.compile(r"(?<![A-Za-z0-9])\[(\d{1,2})\]")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# Abbreviations whose trailing period does not end a sentence. Without these,
# "the U.S. Food and Drug Administration" splits into two fragments and a pure
# refusal is misread as containing substantive content.
_ABBREVIATIONS = {
    "u.s", "u.k", "e.g", "i.e", "etc", "no", "nos", "inc", "ltd", "co", "corp", "dr", "mr", "mrs", "ms",
    "vs", "cf", "fig", "figs", "sec", "secs", "approx", "st", "jr", "sr", "al", "ca", "pp", "ed", "eds",
    "min", "max", "cfr", "u.s.c", "f.r", "para", "paras", "vol", "ch",
}


def split_sentences(text: str) -> list[str]:
    """Sentence split that does not break on common abbreviations or initials."""
    parts = [p for p in _SENTENCE_RE.split(text or "") if p.strip()]
    out: list[str] = []
    for part in parts:
        if out:
            tail = out[-1].rstrip()
            last = tail.split()[-1].rstrip(".").lower() if tail.split() else ""
            # merge when the previous fragment ended on an abbreviation or a
            # single-letter initial such as "J." in "J. Smith"
            if last in _ABBREVIATIONS or (len(last) == 1 and last.isalpha()):
                out[-1] = tail + " " + part
                continue
        out.append(part)
    return [s.strip() for s in out if s.strip()]

REFUSAL = "refusal"
HEDGED = "hedged"
ANSWER = "answer"
# below this many characters of non-refusal text, what remains is not an answer
_SUBSTANTIVE_CHARS = 60


def classify_answer(answer: str | None) -> str:
    """Distinguish a refusal from an answer that merely appends a refusal.

    The un-finetuned model frequently produces "A clinical trial is a study
    that ... The available regulatory sources do not provide enough information
    to answer this." Counting that as a refusal would overstate its refusal
    rate and understate its unsupported-answer rate, so the three cases are
    separated: `refusal` declines and offers nothing else, `hedged` supplies
    content and also disclaims, `answer` supplies content only.
    """
    text = (answer or "").strip()
    if not text:
        return REFUSAL
    sentences = split_sentences(text)
    if not any(p in text.lower() for p in REFUSAL_PHRASES):
        return ANSWER
    substantive = [
        s for s in sentences
        if not any(p in s.lower() for p in REFUSAL_PHRASES)
        and not any(p.lower() in s.lower() for p in SOURCE_COMMENTARY_PHRASES)
    ]
    return REFUSAL if len(" ".join(substantive).strip()) < _SUBSTANTIVE_CHARS else HEDGED


def is_refusal(answer: str | None) -> bool:
    """True only for an answer that declines without supplying content."""
    return classify_answer(answer) == REFUSAL


def provides_content(answer: str | None) -> bool:
    """True when the answer asserts something, whether or not it also hedges."""
    return classify_answer(answer) in (ANSWER, HEDGED)


def _sources(result: dict[str, Any]) -> list[dict[str, Any]]:
    return ((result.get("diagnostics") or {}).get("context") or {}).get("sources", []) or []


def _cited_indices(answer: str | None) -> set[int]:
    return {int(m) for m in _MARK_RE.findall(answer or "")}


@dataclass
class GroundingMetrics:
    """Counts kept alongside every rate so small denominators stay visible."""

    values: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def evaluate_grounding(run: dict[str, Any]) -> GroundingMetrics:
    """Compute the Stage 13 metrics over one saved evaluation run."""
    results = run.get("results", [])
    v: dict[str, Any] = {}

    # --- refusal behaviour on questions the benchmark says should be refused
    should_refuse = [r for r in results if r.get("expected_behavior") == "acknowledge_uncertainty"]
    answerable = [r for r in results if r.get("expected_behavior") == "answer"]
    # An "unsupported answer" asserts content with no qualification. A hedged
    # answer on a refusal-required question quotes real retrieved text and then
    # says it does not establish the claim, which is the behaviour Stage 13
    # trains for, so it is counted separately rather than as a failure.
    correct_refusals = [r for r in should_refuse if is_refusal(r.get("model_answer"))]
    unsupported = [r for r in should_refuse if classify_answer(r.get("model_answer")) == ANSWER]
    v["refusal_required"] = len(should_refuse)
    v["correct_refusals"] = len(correct_refusals)
    v["refusal_rate"] = _rate(len(correct_refusals), len(should_refuse))
    v["unsupported_answers"] = len(unsupported)
    v["unsupported_answer_rate"] = _rate(len(unsupported), len(should_refuse))
    v["unsupported_answer_ids"] = [r["question_id"] for r in unsupported]
    v["hedged_on_refusal_required"] = sum(1 for r in should_refuse if classify_answer(r.get("model_answer")) == HEDGED)

    # --- false refusals: answerable questions the system declined anyway
    false_refusals = [r for r in answerable if is_refusal(r.get("model_answer"))]
    v["answerable"] = len(answerable)
    v["false_refusals"] = len(false_refusals)
    v["false_refusal_rate"] = _rate(len(false_refusals), len(answerable))
    v["false_refusal_ids"] = [r["question_id"] for r in false_refusals]
    v["hedged_answers"] = sum(1 for r in answerable if classify_answer(r.get("model_answer")) == HEDGED)

    # --- identifier grounding: when a question names an identifier, does the
    # answer either cite that identifier or decline? Claiming to answer about
    # an identifier that appears nowhere in the retrieved context is the
    # Stage 12 failure.
    identifier_qs = 0
    grounded = 0
    ungrounded_ids: list[str] = []
    for r in results:
        ident = extract_identifier(r.get("question", ""))
        if ident is None:
            continue
        identifier_qs += 1
        if is_refusal(r.get("model_answer")):
            grounded += 1
            continue
        retrieved = " ".join(s.get("citation", "") for s in _sources(r))
        key = ident.section or ident.part or (ident.docket or "")
        if key and key in retrieved:
            grounded += 1
        else:
            ungrounded_ids.append(r["question_id"])
    v["identifier_questions"] = identifier_qs
    v["identifier_grounded"] = grounded
    v["identifier_grounding_accuracy"] = _rate(grounded, identifier_qs)
    v["ungrounded_identifier_ids"] = ungrounded_ids

    # --- citation grounding: every [n] in an answer must point at a source
    # that was actually in the context
    with_citations = 0
    valid_citations = 0
    invalid_ids: list[str] = []
    for r in results:
        marks = _cited_indices(r.get("model_answer"))
        if not marks:
            continue
        with_citations += 1
        n = len(_sources(r))
        if marks and all(1 <= m <= n for m in marks):
            valid_citations += 1
        else:
            invalid_ids.append(r["question_id"])
    v["answers_with_citations"] = with_citations
    v["answers_with_valid_citations"] = valid_citations
    v["citation_validity_rate"] = _rate(valid_citations, with_citations)
    v["invalid_citation_ids"] = invalid_ids

    # --- degeneration: repeated citation markers or repeated quoted phrases
    degenerate = []
    for r in results:
        a = r.get("model_answer") or ""
        quoted = re.findall(r'"[^"]{6,}"', a)
        if len(_MARK_RE.findall(a)) > 12 or (len(quoted) - len(set(quoted))) >= 2:
            degenerate.append(r["question_id"])
    v["degenerate_answers"] = len(degenerate)
    v["degenerate_ids"] = degenerate

    # --- what the deterministic gate did, when one was active
    gated = [r for r in results if ((r.get("diagnostics") or {}).get("grounding") or {}).get("checked")]
    refused_by_gate = [r for r in gated if ((r.get("diagnostics") or {}).get("grounding") or {}).get("action") == "refuse"]
    v["gate_active"] = bool(gated)
    v["gate_checked"] = len(gated)
    v["gate_refusals"] = len(refused_by_gate)
    v["gate_refusal_reasons"] = sorted({((r.get("diagnostics") or {}).get("grounding") or {}).get("reason") for r in refused_by_gate} - {None})
    v["gate_refusal_ids"] = [r["question_id"] for r in refused_by_gate]
    return GroundingMetrics(v)


SUMMARY_ORDER = (
    "refusal_required",
    "correct_refusals",
    "refusal_rate",
    "unsupported_answers",
    "unsupported_answer_rate",
    "hedged_on_refusal_required",
    "answerable",
    "false_refusals",
    "false_refusal_rate",
    "hedged_answers",
    "identifier_questions",
    "identifier_grounding_accuracy",
    "answers_with_citations",
    "citation_validity_rate",
    "degenerate_answers",
    "gate_checked",
    "gate_refusals",
)
