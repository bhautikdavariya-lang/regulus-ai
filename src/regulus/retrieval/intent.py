"""What kind of answer a question asks for, and what kind of rule a section states: the same labels for both.

Why (23 Oct 2026): wrong section picks often matched a question's topic words but not what it asked. "By when should
it be filed" went to 720.9 (misbranding by reference to filing) instead of 720.2 (Times for filing); "Can we say
'FDA Registered'" went to 710.6 (registration number) instead of 710.8 (misbranding by reference to registration).
Question intent comes from deterministic cue phrases below. A section's functions come from
data/reference/section_functions_v1.json, written from each section's text for all 360 sections of the cosmetics
programme and checked by a second reviewer (section-resolution benchmark build).

The labels (glosses in the reference file):
definition, scope_applicability, permitted_use, specification_limits, labeling_requirement, claim_misbranding,
procedure_submission, deadline_timing, records_access, exemption, status_effective, prohibition_adulteration,
certification_fees, reporting_safety, agency_authority
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

FUNCTIONS_FILE = Path(__file__).resolve().parents[3] / "data" / "reference" / "section_functions_v1.json"

# cue phrases, most specific first; a question may carry several intents
_CUES: tuple[tuple[str, re.Pattern], ...] = tuple((label, re.compile(rx, re.I)) for label, rx in (
    ("deadline_timing", r"\bby when\b|\bhow (?:soon|long|quickly|often)\b|\bdeadline|\bwithin \d+|\bwhen (?:must|should|do|does|is|are)\b|"
                        r"\btime limit|\bhow many (?:days|months|years)\b|\bdue\b|\bexpire|\bannual(?:ly)?\b|\bevery year\b"),
    ("records_access", r"\brecords?\b|\bretain|\bretention\b|\bkeep (?:a |the )?(?:copy|file|log)|\bhow long .{0,20}keep\b|\bdocumentation\b"),
    ("claim_misbranding", r"\bcan we (?:say|claim|call|print|state|advertise|label it)\b|\bmay we (?:say|claim|call|print|state)\b|"
                          r"\bclaim\b|\bmislead|\bmisbrand|\bimply|\brepresent(?:ation)?\b|\bmarketing\b|\bon the label .{0,30}\?"),
    ("definition", r"\bdefin(?:e|ed|ition)|\bwhat (?:counts|qualifies) as\b|\bwhat is meant by\b|\bclassif(?:y|ied|ication)\b|"
                   r"\bconsidered (?:a|an|to be)\b|\btreat(?:ed|s)? as\b|\bin fda'?s sense\b|\bmeaning of\b"),
    ("exemption", r"\bexempt|\bexcept(?:ion|ed)?\b|\bwaive|\bdo(?:es)? (?:we|it|this|that|they) (?:still )?(?:have|need) to\b|\bnot required\b"),
    ("status_effective", r"\bstill (?:in effect|usable|allowed|permitted|valid|listed|legal|good|apply|applies)\b|\bin effect\b|\bstay(?:ed)?\b|"
                         r"\bterminat|\brevok|\bdelist|\bno longer\b|\bprovisional(?:ly)?\b|\bcurrent status\b|\beffective date\b"),
    ("procedure_submission", r"\bhow (?:do|does|should|can) (?:we|i|a firm|a company|one) (?:file|submit|register|apply|petition|request|list|obtain|get)\b|"
                             r"\bwhat (?:form|information|data)\b|\bform fda\b|\bfd-\d{4}\b|\bsubmi(?:t|ssion)\b|\bpetition\b|\bregist(?:er|ration)\b|\bfile\b|\bfiling\b"),
    ("certification_fees", r"\bcertif(?:y|ied|ication|icate)\b|\bbatch(?:es)?\b|\bfees?\b|\blot\b"),
    ("reporting_safety", r"\badverse\b|\breport(?:able|ing)?\b|\bserious\b|\binjur|\brash\b|\breaction\b|\bsubstantiat|\brecall\b"),
    ("labeling_requirement", r"\blabel(?:ing|led|ed)? (?:must|should|need|require)|\bwhat must (?:the|our) label\b|\bwarning\b|\bcaution\b|"
                             r"\bdeclar(?:e|ation)\b|\bingredient (?:list|statement|declaration)\b|\bnet (?:contents|quantity)\b|\bprincipal display panel\b"),
    ("specification_limits", r"\bspecification|\blimit\b|\blimits\b|\bppm\b|\bparts per million\b|\bpercent\b|%|\bpurity\b|\bmaximum\b|\bhow much\b|"
                             r"\bminimum\b|\bcontent of\b|\bnot (?:more|less) than\b"),
    ("prohibition_adulteration", r"\bprohibit|\bbann?ed\b|\bforbidden\b|\badulterat|\bfilth|\binsanitary\b|\billegal\b|\bnot allowed\b"),
    ("agency_authority", r"\binspect|\bfda (?:can|may|could)\b|\bauthority\b|\bconfidential|\bsuspend|\border\b|\bpublic disclosure\b"),
    ("scope_applicability", r"\bapply to\b|\bapplies to\b|\bcover(?:s|ed)?\b|\bsubject to\b|\bwho must\b|\bdoes (?:this|the rule|part \d+) apply\b"),
    ("permitted_use", r"\b(?:can|may) we use\b|\ballowed\b|\bpermitted\b|\bok to use\b|\bsafe(?:ly)? (?:to )?use\b|\bapproved for\b|\buse (?:it|this|them) in\b"),
))


def question_intents(question: str) -> list[str]:
    """The intents a question's wording signals, in the order of the cue table (most specific first); [] if none."""
    q = question or ""
    return [label for label, rx in _CUES if rx.search(q)]


@lru_cache(maxsize=1)
def section_functions(path: Path = FUNCTIONS_FILE) -> dict[str, tuple[str, ...]]:
    """section -> its functions, main first ({} when the reference file is absent: intent then adds nothing)."""
    if not Path(path).exists():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: tuple(v) for k, v in data["functions"].items()}


def intent_match(question_intent: list[str], section: str) -> float:
    """1.0 when the section's main function is the question's first intent, 0.5 when any of its functions is one of the
    question's intents, else 0.0."""
    fn = section_functions().get(section, ())
    if not fn or not question_intent:
        return 0.0
    if fn[0] == question_intent[0]:
        return 1.0
    return 0.5 if set(fn) & set(question_intent) else 0.0
