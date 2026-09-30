"""Deterministic answer-quality helpers (answer-quality Stage 3).

Three things, none of which calls a model:

* `normalize_answer`: two presentation fixes applied to the generated text
  *before* validation, so the validator judges what the reader sees:
    - a citation marker written at the START of a line ("[1] 21 CFR ...") is
      moved to the end of that line's first sentence. The model uses that style
      in about a quarter of its answers, and the validator attaches a marker to
      the sentence BEFORE it, so leaving it there misattributes every such citation;
    - a first sentence that only restates the question is removed.
  Nothing else in the text changes: no words added, reordered or rephrased.
* `out_of_scope_answer`, `mixed_scope_note`: fixed wording for the scope cases
  decided by regulus.planning.intent.
* `quality_flags`: review signals for a human, never a score and never proof of
  failure. Each flag names the evidence that raised it.
"""

from __future__ import annotations

import re
from typing import Any

from regulus.evaluation.grounding_eval import REFUSAL, classify_answer, split_sentences

MARK_RE = re.compile(r"(?<![A-Za-z0-9])\[(\d{1,2})\]")
_LEADING_MARKS_RE = re.compile(r"^(\s*(?:[-*•]\s+|\d+[.)]\s+)?)((?:\[\d{1,2}\]\s*)+)(\S.*)$")
_SENTENCE_END_RE = re.compile(r"[.!?](?=[\"')\]]?(?:\s|$))")
_WORD_RE = re.compile(r"[a-z][a-z'-]{2,}")
_UNCERTAIN_RE = re.compile(
    r"\b(not\s+found|do(?:es)?\s+not\s+(?:provide|state|say|specify|contain|mention|include|address)|not\s+specified|"
    r"cannot|could\s+not|unable|not\s+enough|insufficient|no\s+(?:information|source|evidence))\b", re.I)
_YES_NO_LEAD_RE = re.compile(r"^\s*(?:\*\*)?\s*(yes|no|not|the\s+(?:available\s+)?(?:regulatory\s+)?sources?\s+do(?:es)?\s+not|"
                             r"the\s+cited|the\s+provision\s+does\s+not|21\s+cfr\s+\S+\s+does\s+not)\b", re.I)
_STOP = {"the", "and", "for", "with", "that", "this", "does", "what", "which", "must", "shall", "are", "any", "under",
         "require", "requires", "required", "requirement", "requirements", "cfr", "part", "section", "from", "into", "have",
         "has", "been", "their", "there", "when", "where", "how", "who", "whom", "whose", "why", "can", "could", "should",
         "would", "will", "may", "might", "fda", "regulation", "regulations", "manufacturer", "manufacturers", "device",
         "devices", "provision", "say", "says", "about", "specify", "specifies"}


# ------------------------------------------------------------ normalisation


def _move_leading_markers(line: str) -> tuple[str, int]:
    m = _LEADING_MARKS_RE.match(line)
    if not m:
        return line, 0
    prefix, marks, rest = m.groups()
    tokens = " ".join(f"[{n}]" for n in MARK_RE.findall(marks))
    if MARK_RE.fullmatch(rest.strip()) or not re.search(r"[A-Za-z]", rest):
        return line, 0  # nothing but markers on the line: leave it to the existing trailing-marker handling
    end = _SENTENCE_END_RE.search(rest)
    if end is None:
        return f"{prefix}{rest.rstrip()} {tokens}", 1
    i = end.start()
    return f"{prefix}{rest[:i].rstrip()} {tokens}{rest[i:]}", 1


def _norm(text: str) -> str:
    return " ".join(_WORD_RE.findall(MARK_RE.sub("", text.lower())))


def normalize_answer(text: str, question: str) -> tuple[str, dict[str, Any]]:
    """Presentation fixes only (see module docstring). Returns (text, what changed)."""
    lines = text.split("\n")
    moved = 0
    out_lines = []
    for line in lines:
        new, n = _move_leading_markers(line)
        moved += n
        out_lines.append(new)
    out = "\n".join(out_lines)
    echo = False
    sentences = split_sentences(out)
    if len(sentences) > 1 and _norm(sentences[0]) and _norm(sentences[0]) == _norm(question):
        first = sentences[0]
        at = out.find(first)
        rest = re.sub(r"^(?:\[\d{1,2}\]\s*)+", "", (out[:at] + out[at + len(first):]).lstrip(" \n")) if at >= 0 else ""
        if re.search(r"[A-Za-z]", rest):  # only when an answer follows; the echoed sentence's markers go with it
            out = rest
            echo = True
    return out.strip(), {"markers_moved": moved, "question_echo_removed": echo, "changed": out.strip() != text.strip()}


# ------------------------------------------------------------ scope wording


def out_of_scope_answer(reason: str) -> str:
    return ("This question is outside what Regulus AI can answer. Regulus AI answers from U.S. FDA regulations (21 CFR) "
            f"and FDA guidance only, and the question {reason}; no source for it is available, so no answer is given.")


def mixed_scope_note(part: str) -> str:
    return f'Not answered: "{part}". The available regulatory sources do not cover this part of the question.'


# ------------------------------------------------------------ quality flags


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(MARK_RE.sub("", (text or "").lower()))) - _STOP


def quality_flags(answer: str, package, analysis, validation: dict | None, *, coverage_action: str | None,
                  model_called: bool, question: str) -> list[dict[str, str]]:
    """Deterministic review signals for one answer. A flag is a reason to look, not a verdict."""
    flags: list[dict[str, str]] = []
    text = answer or ""
    codes = set((validation or {}).get("codes") or [])
    shape = (validation or {}).get("shape") or {}

    def add(flag: str, detail: str) -> None:
        flags.append({"flag": flag, "detail": detail})

    sources_text = " ".join(s.text for s in (package.sources if package is not None else ()))
    # the pipeline's own deterministic messages are not model answers: judge only what the model wrote
    system_message = text.startswith(("The generated answer could not be validated", "This question is outside",
                                      "The available eCFR data does not contain", "The available regulatory sources do not"))
    refused = system_message or (classify_answer(text) == REFUSAL if text else True)
    sentences = split_sentences(text)

    if model_called and not refused and sentences and not MARK_RE.search(text):
        add("missing_citation", "the answer carries no source number at all")
    if codes & {"citation_mismatch", "provision_citation_mismatch", "synthesis_citation_gap", "invalid_citation",
                "discovery_cited_for_requirement"}:
        add("citation_mismatch", "validator: " + ", ".join(sorted(codes & {"citation_mismatch", "provision_citation_mismatch",
                                                                         "synthesis_citation_gap", "invalid_citation",
                                                                         "discovery_cited_for_requirement"})))
    if codes & {"unsupported_figure", "asserted_missing_provision"}:
        add("possible_hallucination", "validator: " + ", ".join(sorted(codes & {"unsupported_figure", "asserted_missing_provision"})))
    if codes & {"degenerate_output", "repeated_statement"}:
        add("repeated_content", "validator: " + ", ".join(sorted(codes & {"degenerate_output", "repeated_statement"})))
    if codes & {"qualifier_dropped", "qualifier_misapplied", "applicability_dropped"}:
        add("missing_condition", "validator: " + ", ".join(sorted(codes & {"qualifier_dropped", "qualifier_misapplied",
                                                                         "applicability_dropped"})))
    if "evidence_by_evidence" in codes or (len(text.split()) > 150 and "\n" not in text.strip()):
        add("weak_structure", "row-by-row reproduction" if "evidence_by_evidence" in codes else "a long answer in one block")
    exact_words = sum(len(s.text.split()) for s in (package.sources if package is not None else ()) if s.tier == "exact")
    if model_called and exact_words and len(text.split()) > max(150, 3 * exact_words):
        add("excessive_length", f"{len(text.split())} words for {exact_words} words of exact source text")

    if analysis is not None:
        if analysis.is_yes_no and model_called and not refused and sentences and not _YES_NO_LEAD_RE.match(sentences[0]):
            add("missing_direct_answer", "a yes/no question whose answer does not open with yes, no or 'the sources do not say'")
        if analysis.is_yes_no and model_called and not refused:
            # terms the question assumes that no supplied source contains, repeated as fact by the answer
            premise = sorted((_words(question) - _words(sources_text)) & _words(text))
            if premise and not _UNCERTAIN_RE.search(text) and not re.search(r"^\s*no\b", text, re.I):
                add("unsupported_claim", f"the answer repeats terms the sources do not contain: {', '.join(premise)}")
        if analysis.scope_status == "out_of_scope" and model_called:
            add("scope_mismatch", "an out-of-scope question was answered by the model")
        if "no_regulatory_vocabulary" in analysis.signals and package is not None and package.weak_evidence and not refused:
            add("scope_mismatch", "a question with no regulatory vocabulary was answered from broad-search sources only")
        if package is not None and _norm(text).startswith(_norm(question)) and _norm(question):
            add("question_echo", "the answer begins by restating the question")
    incomplete = coverage_action in ("answer_partial",) or (package is not None and package.weak_evidence)
    if incomplete and model_called and not _UNCERTAIN_RE.search(text):
        add("uncertainty_not_disclosed", "evidence was partial or broad-search only, and the answer does not say so")
    plan = getattr(package, "answer_plan", None) if package is not None else None
    if plan is not None:
        cited = {int(m) for m in MARK_RE.findall(text)}
        for s in plan.sources:
            if s.role == "exception" and s.index in cited and not re.search(r"\b(except|unless|exempt|does not apply|not required)\b", text, re.I):
                add("missing_exception", f"SOURCE {s.index} is an exception but the answer states no exception")
                break
    if shape.get("uncovered_groups"):
        add("incomplete_coverage", "requirement groups not represented: " + ", ".join(shape["uncovered_groups"]))
    return flags
