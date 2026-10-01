"""Claim-level validation (Stage 7): does each statement's content come from the evidence it names?

Existing validation checks that citations exist and point at the right provision. These checks
look at the WORDS of each statement:

  paragraph_misattribution  a statement presents provision X, but its wording is copied from a
                            different, unrelated supplied provision Y and not from X
                            (source "(a) A. (b) B." -> answer "(b): A.")
  invented_condition        a statement carries a condition ("if applicable", "as appropriate",
                            "unless", "except", "to the extent") that none of the sources it cites
                            contains (source "(b) B." -> answer "(b) B, except when X.")
  unsupported_premise       a yes/no answer affirms terms of the question that no supplied source
                            contains ("Does X require annual audits?" -> "X requires annual audits.")
  unsupported_claim         a statement whose content words mostly appear in NO supplied source

Dropped conditions are already detected by shape validation (`qualifier_dropped`); this module does
not duplicate that check. All checks are lexical and deterministic: they detect copying and absence,
not meaning, and every threshold is reported with the finding. Severities are decided by
`SEVERITY` below from Stage 7 measurements (docs/retrieval_validation_stage7.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from regulus.rag.answer_plan import QUALIFIER_EQUIVALENTS

PARAGRAPH_MISATTRIBUTION = "paragraph_misattribution"
INVENTED_CONDITION = "invented_condition"
CONDITION_NOT_IN_CITED = "condition_not_in_cited_source"
UNSUPPORTED_PREMISE = "unsupported_premise"
UNSUPPORTED_CLAIM = "unsupported_claim"
CLAIM_CODES = (PARAGRAPH_MISATTRIBUTION, INVENTED_CONDITION, CONDITION_NOT_IN_CITED, UNSUPPORTED_PREMISE, UNSUPPORTED_CLAIM)

# measured before being enforced (see module docstring); "warning" findings are reported, never repaired
# Stage 7 measurement on the 63 recorded Stage 6 answers (artifacts/validation_eval/):
#   paragraph_misattribution: fired only on answers already reviewed as wrong        -> error (repaired per row)
#   invented_condition (in NO supplied source): the 0.6B "If applicable, the requirement
#     limits the scope to ..." sentence (an echo of the prompt's own instruction)      -> error
#   unsupported_premise: one hit, a false premise affirmed                              -> error
#   condition_not_in_cited_source (the condition is real but cited to another source)  -> warning
#   unsupported_claim: few true positives, lexical overlap cannot judge paraphrase      -> warning (metric)
SEVERITY = {
    PARAGRAPH_MISATTRIBUTION: "error",
    INVENTED_CONDITION: "error",
    CONDITION_NOT_IN_CITED: "warning",
    UNSUPPORTED_PREMISE: "error",
    UNSUPPORTED_CLAIM: "warning",
}

MISATTRIBUTION_OWN_MAX = 0.25     # at most this share of the statement's word 3-grams in the named provision
MISATTRIBUTION_OTHER_MIN = 0.60   # and at least this share in one other, unrelated supplied provision
UNSUPPORTED_MIN_WORDS = 5
UNSUPPORTED_MAX_SUPPORT = 0.30    # share of content words found in any supplied source

_MARK = re.compile(r"(?<![A-Za-z0-9])\[(\d{1,2})\]")
_LABEL = re.compile(r"(?:21\s*CFR\s*)?(?:§+\s*)?\d{1,4}\.\d{1,4}[a-z]?(?:\([a-z0-9]{1,4}\))*\s*:?", re.I)
_TOKEN = re.compile(r"[a-z0-9]+")
_WORD = re.compile(r"[a-z][a-z'-]{3,}")
_STOP = frozenset(
    "that this these those with from have which their there where when what shall must will would could should such "
    "into upon under other than also each only more most very being been were does your they them then subject part "
    "section paragraph chapter title requires required require requirement requirements provision provisions states "
    "stated according following described specified means include includes including".split()
)
_NEGATED = re.compile(r"\b(?:not|no|never|neither|nor|does not|do not|is not|are not)\b", re.I)
_CONDITION_GROUPS = {
    "applicable": re.compile(r"\b(?:if|where|when|as)\s+applicable\b", re.I),
    "appropriate": re.compile(r"\b(?:as|where|when|if)\s+appropriate\b", re.I),
    "extent": re.compile(r"\bto the extent\b", re.I),
    "exception": re.compile(r"\b(?:unless|except(?:ing)?|other than|exempt(?:ed|ion)?)\b(?! as provided)", re.I),
}
# which group a source wording satisfies (a source "except" supports an answer "unless", and so on)
# a source supports a condition group only with a conditional PHRASE of that group, not the bare word
# ("other applicable requirements" is not "if applicable")
_SUPPORTED_BY = {
    "applicable": re.compile(r"\b(?:if|where|when|as)\s+applicable\b", re.I),
    "appropriate": re.compile(r"\b(?:as|where|when|if)\s+appropriate\b", re.I),
    "extent": re.compile(r"\bto the extent\b", re.I),
    "exception": re.compile(r"\b(?:unless|except|exempt|other than|exception)", re.I),
}
# pipeline-authored and refusal sentences are not claims about the evidence
_NOT_A_CLAIM = re.compile(r"could not be validated|do(?:es)? not provide enough information|do(?:es)? not (?:cover|establish)|"
                          r"not found in the available|were not verified|no answer is given|verbatim\)?:|"
                          r"sources? do(?:es)? not provide", re.I)
_LEAD = 45  # a provision label within the first characters of a statement names what it presents


@dataclass(frozen=True)
class ClaimFinding:
    code: str
    severity: str
    detail: str
    citation: int | None = None
    sentence: str | None = None
    requirement_id: str | None = None


def _grams(text: str, n: int = 3) -> set[tuple[str, ...]]:
    t = _TOKEN.findall((text or "").lower())
    return {tuple(t[i:i + n]) for i in range(len(t) - n + 1)}


def _coverage(segment: str, source: str) -> float:
    g = _grams(segment)
    return len(g & _grams(source)) / len(g) if g else 0.0


def _words(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower())) - _STOP


def check_claims(sentences: list[str], package, *, question: str | None = None, is_yes_no: bool = False,
                 identity=None, related=None) -> list[ClaimFinding]:
    """`identity(source)` and `related(a, b)` come from regulus.rag.validation (provision identity and
    parent/child relation), passed in to avoid a circular import."""
    from regulus.retrieval.references import parse_cfr_references

    by_index = {s.index: s for s in package.sources}
    identities = {i: identity(s) for i, s in by_index.items()} if identity else {}
    findings: list[ClaimFinding] = []
    all_words = set().union(*(_words(s.text) for s in package.sources)) if package.sources else set()

    for sentence in sentences:
        marks = [int(m) for m in _MARK.findall(sentence) if int(m) in by_index]
        body = _MARK.sub(" ", sentence)
        content = _LABEL.sub(" ", body)

        # -- paragraph attribution: the named provision's own text vs another supplied provision
        if _NOT_A_CLAIM.search(body):
            continue
        refs = [r for r in parse_cfr_references(body[:_LEAD]) if r.section is not None]
        if refs and identity and len(_grams(content)) >= 4:
            named = (refs[0].title, refs[0].section, refs[0].paragraph_path)
            own = [s for i, s in by_index.items() if identities.get(i) == named]
            if own:
                own_cov = max(_coverage(content, s.text) for s in own)
                others = [(i, _coverage(content, s.text)) for i, s in by_index.items()
                          if identities.get(i) and not related(named, identities[i])]
                best = max(others, key=lambda x: x[1], default=(None, 0.0))
                if own_cov <= MISATTRIBUTION_OWN_MAX and best[1] >= MISATTRIBUTION_OTHER_MIN:
                    findings.append(ClaimFinding(PARAGRAPH_MISATTRIBUTION, SEVERITY[PARAGRAPH_MISATTRIBUTION],
                                                 f"presented as {refs[0].canonical}, but {best[1]:.0%} of its wording is from "
                                                 f"{by_index[best[0]].citation} and {own_cov:.0%} from {refs[0].canonical}",
                                                 citation=own[0].index, sentence=sentence,  # the named provision's own source
                                                 requirement_id=next(iter(own[0].requirement_ids), None)))

        # -- conditions the cited sources do not contain
        cited_texts = [by_index[i].text for i in marks]
        all_texts = [s.text for s in package.sources]
        for group, pattern in _CONDITION_GROUPS.items():
            m = pattern.search(content)
            if not m:
                continue
            if not any(_SUPPORTED_BY[group].search(t or "") for t in all_texts):
                findings.append(ClaimFinding(INVENTED_CONDITION, SEVERITY[INVENTED_CONDITION],
                                             f"condition '{m.group(0)}' appears in no supplied source",
                                             citation=marks[0] if marks else None, sentence=sentence))
            elif cited_texts and not any(_SUPPORTED_BY[group].search(t or "") for t in cited_texts):
                findings.append(ClaimFinding(CONDITION_NOT_IN_CITED, SEVERITY[CONDITION_NOT_IN_CITED],
                                             f"condition '{m.group(0)}' is in a supplied source, but not in the one(s) cited",
                                             citation=marks[0], sentence=sentence))

        # -- statements whose content no supplied source supports
        words = _words(content)
        if len(words) >= UNSUPPORTED_MIN_WORDS and all_words:
            support = len(words & all_words) / len(words)
            if support <= UNSUPPORTED_MAX_SUPPORT:
                findings.append(ClaimFinding(UNSUPPORTED_CLAIM, SEVERITY[UNSUPPORTED_CLAIM],
                                             f"only {support:.0%} of its content words appear in any supplied source",
                                             citation=marks[0] if marks else None, sentence=sentence))

    # -- yes/no questions: an affirmed premise that no source contains
    if is_yes_no and question:
        premise = _words(question) - all_words
        for sentence in sentences:
            asserted = premise & _words(sentence)
            if asserted and not _NEGATED.search(sentence) and not _NOT_A_CLAIM.search(sentence):
                findings.append(ClaimFinding(UNSUPPORTED_PREMISE, SEVERITY[UNSUPPORTED_PREMISE],
                                             f"affirms {sorted(asserted)}, which no supplied source contains", sentence=sentence))
                break
    return findings
