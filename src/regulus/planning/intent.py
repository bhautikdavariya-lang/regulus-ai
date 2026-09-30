"""QuestionAnalysis: what a question asks, and whether it is in scope (answer-quality Stage 3).

AnswerShape (regulus.planning.shape) decides how an answer is *organised*
(synthesis, focused, enumeration, comparison, direct). QuestionAnalysis
decides what kind of *answer* the question wants and whether the system
should answer it at all:

    question_type   definition | requirement | explanation | procedure |
                    applicability | exception_condition | comparison |
                    scenario | citation_lookup | out_of_scope
                    (insufficient_evidence is decided after retrieval, from
                    coverage, and reported as `evidence_status`)
    is_yes_no       "Does/Is/Must ... ?" questions: they need a yes/no/
                    "the sources do not say" answer, never an echo of the premise
    scope_status    in_scope | out_of_scope | mixed

Deterministic regular expressions over the question with CFR identifiers
masked out (the same masking the shape uses) plus the QueryPlan. No model,
no database. Every rule that fired is recorded in `signals`.

Scope is deliberately conservative, because a false refusal of a real
regulatory question is worse than an extra answer that validation and review
can catch. A question is `out_of_scope` only when it names no CFR provision
and no docket, names a non-U.S. regulatory framework (EU MDR, Health Canada,
...) and makes no U.S. reference. A vocabulary test ("no regulatory words") was
tried and rejected: it declined 33 of the 300 benchmark questions (FSVP, HACCP,
laser-product standards ...), because the domain's vocabulary is too wide for
any list; the evidence test "only broad-fallback sources" also declined 11 of
them, because retrieval finds only fallback evidence for those too. Questions
with no regulatory vocabulary are therefore answered normally but marked
(`no_regulatory_vocabulary` signal), and the answer shape tells the model when
its sources came only from a broad search. `mixed` requires an unrelated
clause that names something specific (a proper noun), has no regulatory term
and does not refer back to the rest of the question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from regulus.planning.plan import QueryPlan

TYPE_DEFINITION = "definition"
TYPE_REQUIREMENT = "requirement"
TYPE_EXPLANATION = "explanation"
TYPE_PROCEDURE = "procedure"
TYPE_APPLICABILITY = "applicability"
TYPE_EXCEPTION = "exception_condition"
TYPE_COMPARISON = "comparison"
TYPE_SCENARIO = "scenario"
TYPE_CITATION = "citation_lookup"
TYPE_OUT_OF_SCOPE = "out_of_scope"
TYPE_INSUFFICIENT = "insufficient_evidence"  # an evidence status, reported after retrieval
QUESTION_TYPES = (TYPE_DEFINITION, TYPE_REQUIREMENT, TYPE_EXPLANATION, TYPE_PROCEDURE, TYPE_APPLICABILITY, TYPE_EXCEPTION,
                  TYPE_COMPARISON, TYPE_SCENARIO, TYPE_CITATION, TYPE_OUT_OF_SCOPE)

SCOPE_IN = "in_scope"
SCOPE_OUT = "out_of_scope"
SCOPE_MIXED = "mixed"

# Subjects this system answers about. Broad on purpose: a false "out of scope"
# is worse than letting retrieval and validation handle an odd question.
_REGULATORY_RE = re.compile(
    r"\b(fda|cfr|c\.f\.r|regulations?|regulatory|regulated|federal\s+register|guidance|docket|devices?|medical|drugs?|"
    r"biologics?|biological|vaccines?|labell?(?:ing|ed|s)?|manufactur\w*|complaints?|udi|identifiers?|recalls?|510\s*\(k\)|"
    r"premarket|pma|clinical|investigational|investigators?|irbs?|institutional\s+review|informed\s+consent|cgmps?|gmps?|"
    r"good\s+manufacturing|quality\s+(?:management\s+)?systems?|qms|iso\s*\d+|adverse|traceab\w*|tracking|packag\w*|tamper\w*|"
    r"otc|over-the-counter|prescription|pharmac\w*|foods?|dietary|supplements?|cosmetics?|tobacco|veterinary|animal|"
    r"compliance|inspections?|establishments?|registration|listing|sterile|steriliz\w*|records?|recordkeeping|submissions?|"
    r"sponsors?|marketing|advisory\s+notices?|corrections?|removals?|reporting|reports?|nutrition|ingredients?|"
    r"electronic\s+(?:records?|signatures?)|part\s+\d+|section\s+\d|§)\b",
    re.IGNORECASE,
)
# Named non-U.S. regulatory frameworks and jurisdictions (the corpus is 21 CFR and FDA guidance only)
_FOREIGN_RE = re.compile(
    r"\b(eu|e\.u\.|european\s+union|european|mdr\s*\(eu\)|\(eu\)\s*2017/74[56]|2017/74[56]|ivdr|ce[\s-]mark\w*|notified\s+bod\w+|"
    r"health\s+canada|canadian|mhra|uk\s+mdr|pmda|japanese|tga|australian|nmpa|chinese|cdsco|anvisa|swissmedic)\b",
    re.IGNORECASE,
)
_US_RE = re.compile(r"\b(fda|cfr|c\.f\.r|u\.s\.|united\s+states|federal)\b", re.IGNORECASE)

_YES_NO_RE = re.compile(r"^\s*(does|do|did|is|are|was|were|must|can|could|should|shall|will|would|has|have|may)\b", re.I)
_DEFINITION_RE = re.compile(
    r"^\s*(?:what\s+is\s+(?:a|an|the)?|what's\s+(?:a|an|the)?|define|definition\s+of|meaning\s+of|what\s+is\s+meant\s+by)\b"
    r"|\bwhat\s+does\s+.{1,60}\s+mean\b|\bwhat\s+(?:is|are)\s+(?:considered|defined\s+as)\b",
    re.IGNORECASE,
)
_REQUIREMENT_WORDS_RE = re.compile(r"\b(require[sd]?|requirements?|must|shall|obligat\w+|mandat\w+|need(?:s|ed)?\s+to|comply)\b", re.I)
_CITATION_RE = re.compile(
    r"\b(?:which|what)\s+(?:cfr\s+)?(?:provision|section|paragraph|part|regulation|subpart|citation)s?\b|\bcite\b|"
    r"\bwhere\s+(?:in\s+the\s+)?(?:cfr|regulations?)\b|\b(?:citation|reference)\s+for\b",
    re.IGNORECASE,
)
_PROCEDURE_RE = re.compile(
    r"\bhow\s+(?:do|does|should|must|can|to|would)\b|\b(?:steps?|process(?:es)?|procedure\s+(?:for|to)|what\s+procedure)\b",
    re.IGNORECASE,
)
_EXCEPTION_RE = re.compile(
    r"\b(exceptions?|exempt\w*|unless|except|waive[rsd]?|waiver|under\s+what\s+conditions?|what\s+conditions?|"
    r"when\s+(?:is|are|does|do)\s+.{0,60}\bnot\s+(?:required|apply|needed))\b",
    re.IGNORECASE,
)
_APPLICABILITY_RE = re.compile(r"\b(appl(?:y|ies)\s+to|applicab\w*|who\s+must|who\s+is\s+required|subject\s+to|cover(?:s|ed)?\s+by)\b", re.I)
_SCENARIO_RE = re.compile(
    r"\b(if\s+(?:a|an|the|my|our|we|i)\b|suppose|scenario|in\s+a\s+case\s+where|a\s+company\s+that|our\s+(?:device|product|company)|"
    r"my\s+(?:device|product|company)|we\s+(?:are|have|make|manufacture|sell))",
    re.IGNORECASE,
)
_EXPLANATION_RE = re.compile(
    r"^\s*(explain|why|describe|summari[sz]e|summary|walk\s+me|tell\s+me\s+about|what\s+is\s+the\s+purpose|overview)\b|"
    r"\bin\s+plain\s+(?:english|language)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(r"\b(compare[sd]?|comparison|contrast|differ(?:s|ence|ences)?|versus|vs\.?|distinguish)\b", re.I)
_ANAPHORA_RE = re.compile(r"\b(it|its|they|them|their|this|that|these|those|one|such|else|which\s+(?:section|part|paragraph))\b", re.I)
_PROPER_NOUN_RE = re.compile(r"(?<!^)(?<![.?!]\s)\b[A-Z][a-z]{2,}\b")
_CLAUSE_SPLIT_RE = re.compile(r"\?|;|,\s*and\s+|\s+and\s+(?=(?:what|who|when|where|how|which|why)\b)", re.I)
_INTERROGATIVE_RE = re.compile(r"^\s*(what|who|when|where|how|which|why)\b", re.I)


@dataclass(frozen=True)
class QuestionAnalysis:
    question_type: str
    is_yes_no: bool
    requested_entities: tuple[str, ...]   # canonical CFR labels, or a docket, from the plan
    requires_comparison: bool
    requires_citation: bool
    requires_procedure: bool
    scope_status: str
    scope_reason: str
    out_of_scope_part: str | None = None  # the declined clause of a mixed question
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_type": self.question_type, "is_yes_no": self.is_yes_no,
            "requested_entities": list(self.requested_entities), "requires_comparison": self.requires_comparison,
            "requires_citation": self.requires_citation, "requires_procedure": self.requires_procedure,
            "scope_status": self.scope_status, "scope_reason": self.scope_reason,
            "out_of_scope_part": self.out_of_scope_part, "signals": list(self.signals),
        }


def _masked(plan: QueryPlan) -> str:
    text = plan.scan.text or plan.normalized_question or plan.question or ""
    for m in sorted(plan.scan.mentions, key=lambda m: m.start, reverse=True):
        text = text[: m.start] + " PROVISION " + text[m.end:]
    return re.sub(r"\s+", " ", text).strip()


def _scope(plan: QueryPlan, text: str) -> tuple[str, str, str | None]:
    named = bool(plan.requirements) or bool(plan.docket)
    if named:
        # a regulatory question with an unrelated clause attached ("..., and what is the population of Paris?")
        for clause in (c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c and c.strip()):
            if "PROVISION" in clause or not _INTERROGATIVE_RE.match(clause) or len(clause.split()) < 3:
                continue
            if (not _REGULATORY_RE.search(clause) and not _REQUIREMENT_WORDS_RE.search(clause)
                    and not _ANAPHORA_RE.search(clause) and _PROPER_NOUN_RE.search(clause)):
                return SCOPE_MIXED, "one part of the question names something outside U.S. FDA regulation", clause
        return SCOPE_IN, "names a CFR provision or FDA docket", None
    foreign = _FOREIGN_RE.search(text)
    if foreign and not _US_RE.search(text):
        return SCOPE_OUT, f"asks about a non-U.S. framework ({foreign.group(0)})", None
    return SCOPE_IN, "no CFR provision named" if _REGULATORY_RE.search(text) else "no regulatory vocabulary", None


def analyze_question(plan: QueryPlan) -> QuestionAnalysis:
    """Deterministic question analysis. Same plan, same result."""
    text = _masked(plan)
    signals: list[str] = []
    scope, reason, oos_part = _scope(plan, text)
    entities = tuple(r.canonical for r in plan.requirements) + ((plan.docket,) if plan.docket else ())
    yes_no = bool(_YES_NO_RE.match(text))
    comparison = bool(_COMPARISON_RE.search(text)) and (len(plan.requirements) != 1)
    citation = bool(_CITATION_RE.search(text))
    procedure = bool(_PROCEDURE_RE.search(text))

    def pick() -> str:
        if scope == SCOPE_OUT:
            signals.append("non_us_framework")
            return TYPE_OUT_OF_SCOPE
        checks = (
            (comparison, TYPE_COMPARISON, "comparison_wording"),
            (citation, TYPE_CITATION, "asks_for_a_provision"),
            (bool(_SCENARIO_RE.search(text)), TYPE_SCENARIO, "describes_a_situation"),
            (bool(_EXCEPTION_RE.search(text)), TYPE_EXCEPTION, "exception_or_condition_wording"),
            (bool(_APPLICABILITY_RE.search(text)) or (yes_no and not _DEFINITION_RE.search(text)), TYPE_APPLICABILITY,
             "applicability_or_yes_no"),
            (procedure, TYPE_PROCEDURE, "procedure_wording"),
            (bool(_DEFINITION_RE.search(text)) and not _REQUIREMENT_WORDS_RE.search(text), TYPE_DEFINITION, "definition_wording"),
            (bool(_EXPLANATION_RE.search(text)), TYPE_EXPLANATION, "explanation_wording"),
            (bool(_REQUIREMENT_WORDS_RE.search(text)) or bool(plan.requirements), TYPE_REQUIREMENT, "requirement_wording_or_provision"),
        )
        for fired, kind, signal in checks:
            if fired:
                signals.append(signal)
                return kind
        signals.append("default")
        return TYPE_EXPLANATION

    kind = pick()
    if yes_no:
        signals.append("yes_no")
    if scope == SCOPE_IN and not plan.requirements and not plan.docket and not _REGULATORY_RE.search(text):
        signals.append("no_regulatory_vocabulary")
    return QuestionAnalysis(
        question_type=kind, is_yes_no=yes_no, requested_entities=entities, requires_comparison=kind == TYPE_COMPARISON,
        requires_citation=kind == TYPE_CITATION, requires_procedure=kind == TYPE_PROCEDURE,
        scope_status=scope, scope_reason=reason, out_of_scope_part=oos_part, signals=tuple(signals),
    )
