"""Which sentences of a delivered answer are claims the MODEL made.

A delivered answer is not all model output. The pipeline appends text of its
own after generation, and its repair layer replaces or completes the answer with
verbatim provision text. Scoring any of that as a model claim is unsafe in both
directions:

* **false high** - the measured failure mode. Acceptance row S-002 scores N=0
  with a fabricated citation, yet six of its seventeen sentences attribute to
  the evidence at 0.83-0.96 coverage, because the repair appended
  `21 CFR 111.103 (eCFR, binding, verbatim): You must establish and follow ...`
  blocks. An answer made entirely of such blocks would attribute perfectly while
  answering nothing. The quotation is grounded by construction
  (`regulus.rag.generation.extractive_answer` built it from the source), so
  "it matches the evidence" says nothing about the model.
* **false low** - the pipeline's own refusal and limitation sentences are not
  claims about the evidence either, and counting them as unattributable
  paraphrase penalises an answer for text the model never wrote.

So each sentence is given an origin, and only `MODEL` origins become claims:

    MODEL        the model's own statement about the evidence
    QUOTATION    verbatim provision text the repair or fallback inserted
    PIPELINE     a fixed or templated sentence written by the pipeline
    LABEL        a bare citation label used as a heading
    ECHO         a restatement of the question
    TRIVIAL      too short to carry a regulatory claim

Nothing here parses regulation or decides correctness; it only separates
authorship. The origins are reported in the assessment so a reader can see what
was and was not judged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from regulus.accuracy.attribution import MARK_RE, normalise, strip_lead
from regulus.evaluation.grounding_eval import split_sentences
from regulus.rag.validation import attach_trailing_markers

MODEL = "model_claim"
QUOTATION = "inserted_quotation"
PIPELINE = "pipeline_sentence"
LABEL = "citation_label"
ECHO = "question_echo"
TRIVIAL = "too_short"
# Found by the Phase 1 forensic review: sentences the model wrote that assert no
# regulatory proposition, and that blocked otherwise-decided answers because
# every claim had to be decided (acceptance rows B-001, B-002, D-013, F-004).
HEADING = "heading_fragment"      # "Postmarketing reporting of adverse experiences [10]."; "As used in this subchapter:"
POINTER = "pointer_sentence"      # "... requirements are specified in [1]."; "... are described in subparts B and G."
RESTATEMENT = "question_restatement"  # says nothing the question did not already say
META = "meta_statement"           # about the sources or the answer itself: "The sources that support this are [1][2]."
UNCERTAIN = "uncertain"           # propositional status unresolved: commentary, placeholders; traced, never judged

# Three outcomes for every sentence (Priority 3). A sentence is a CLAIM unless it
# is one of the recognised non-claims; UNCERTAIN is recorded with its reason and
# is neither judged nor silently dropped.
CLAIM_STATUS_CLAIM = "claim"
CLAIM_STATUS_NON_CLAIM = "non_claim"
CLAIM_STATUS_UNCERTAIN = "uncertain"

ORIGINS = (MODEL, QUOTATION, PIPELINE, LABEL, ECHO, TRIVIAL, HEADING, POINTER, RESTATEMENT, META, UNCERTAIN)

# `<label> (eCFR, binding, verbatim): <text>` and `<label> (FDA guidance,
# non-binding, verbatim): <text>` - the one format every inserted quotation
# carries (regulus.rag.generation.extractive_answer / extractive_items), plus
# the lead-ins the fallback builder uses before quoting.
_QUOTATION_RE = re.compile(
    r",\s*verbatim\)\s*:"
    r"|\bwhat (?:it says|the requested provision says), verbatim\s*:"
    r"|\bthe verified text of the requested provision\(s\) follows",
    re.I)

# Sentences the pipeline writes itself: fixed strings and templates from
# regulus.rag.prompt, .fallback, .generation and .answer_quality. Matching the
# wording rather than the module keeps this readable, and the test suite pins
# every one of them against the functions that produce them.
_PIPELINE_RE = re.compile(
    r"the available regulatory sources do not (?:provide enough information|cover)"
    r"|the generated answer could not be validated"
    r"|the available ecfr data does not contain"
    r"|not found in the available ecfr data"
    r"|the answer above covers only the provisions that were retrieved"
    r"|^\s*evidence limit\s*:"
    r"|the answer above does not cover that text"
    r"|the available ecfr data \(snapshot [^)]*\) has no subpart"
    r"|^\s*21 cfr part \d+ has these subparts\s*:"
    r"|no provision of 21 cfr part \d+ in the available ecfr data"
    r"|this question is outside what regulus ai can answer"
    r"|regulus ai (?:answers|cannot)"
    r"|the retrieved evidence does not establish"
    r"|the retrieved text of the requested provision does not state"
    r"|sources? consulted\s*:"
    r"|this does not appear to be a regulatory question"
    r"|the question (?:refers to a provision without identifying|names)"
    r"|^\s*not answered\s*:"
    r"|no exact text for the requested"
    r"|no sufficiently relevant ecfr or fda guidance passage was retrieved"
    r"|the retrieved sources were not verified to answer the question"
    r"|i will not infer its contents"
    r"|^\s*\(?no regulatory sources were retrieved",
    re.I)

_LABEL_ONLY_RE = re.compile(
    r"^\s*[-*•]?\s*(?:21\s*CFR\s*)?(?:§\s*)?(?:part\s+)?"
    r"\d{1,4}(?:\.\d{1,4}[a-z]?)?(?:\([A-Za-z0-9]{1,4}\))*\s*:?\s*$", re.I)

# A claim needs enough words to assert something about a requirement.
MIN_CLAIM_WORDS = 5

# What is NOT a claim, recognised by what it is about rather than by its verb.
# (A verb allow-list was the former final gate. It silently dropped 43 of 377
# answer sentences in the 60-row validation - "The requirements for reanalysis
# include conducting a reanalysis ... every 3 years", "These provisions ensure
# the authenticity ... of electronic records" - because include / ensure /
# contain / affect were not on it. A substantive proposition is a claim whatever
# its main verb.)
#
# META: the answer talking about its sources or itself.
_META_RE = re.compile(
    r"\bsources?\s+(?:that\s+)?(?:support|supporting|cited|listed|above|provided)\b"
    r"|\b(?:supported|established|shown)\s+by\s+the\s+(?:evidence|sources?)\b"
    r"|\bretrieved\s+sources\s+were\s+not\s+verified\b|\bsee\s+the\s+sources?\b", re.I)
# UNCERTAIN: commentary about importance, or a template placeholder the model
# left unfilled. Either may be a proposition; neither is safely judgeable.
_COMMENTARY_RE = re.compile(
    r"\b(?:is|are)\s+(?:very\s+|particularly\s+)?(?:important|crucial|essential|critical|vital|key|helpful|beneficial)"
    r"\b(?!\s+(?:that|to\s+(?:establish|maintain|submit|keep|document|report)))|\bfor\s+public\s+health\s+reasons\b",
    re.I)
_PLACEHOLDER_RE = re.compile(r"\b(?:YY|XX+|TBD|TBA)\b|\[insert[^\]]*\]|<[^>]{1,20}>")
_OBLIGATION_SIGNAL_RE = re.compile(r"\b(?:must|shall|required?|prohibit\w*|may\s+not)\b", re.I)
_NAMES_PROVISION_RE = re.compile(
    r"\d{1,4}\.\d{1,4}[a-z]?(?:\([A-Za-z0-9]{1,4}\))*|\bpart\s+\d{1,4}\b|\bclause\s+\d+(?:\.\d+)*", re.I)


@dataclass(frozen=True)
class Sentence:
    text: str
    origin: str
    reason: str = ""
    paragraph: int = 0   # which line-block of the answer the sentence belongs to

    @property
    def is_claim(self) -> bool:
        return self.origin == MODEL

    @property
    def claim_status(self) -> str:
        if self.origin == MODEL:
            return CLAIM_STATUS_CLAIM
        return CLAIM_STATUS_UNCERTAIN if self.origin == UNCERTAIN else CLAIM_STATUS_NON_CLAIM

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text.strip()[:300], "origin": self.origin, "reason": self.reason,
                "claim_status": self.claim_status, "paragraph": self.paragraph}


def _norm_words(text: str) -> list[str]:
    return normalise(text).split()


# A finite verb or modal. A sentence with none of these is a heading or a noun
# phrase, not a proposition. Deliberately broad; a miss leaves the sentence a claim.
_VERB_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|do|does|did|shall|must|may|might|should|can|could|will|"
    r"would|need|needs|means|mean|include|includes|require|requires|required|apply|applies|establish|establishes|"
    r"maintain|maintains|ensure|ensures|provide|provides|contain|contains|describe|describes|state|states|specify|"
    r"specifies|prohibit|prohibits|permit|permits|submit|submits|report|reports|keep|keeps|record|records|review|"
    r"reviews|approve|approves|define|defines|cover|covers|govern|governs|list|lists|set|sets|limit|limits|"
    r"identify|identifies|consist|consists|allow|allows|exempt|exempts|mandate|mandates|direct|directs|"
    r"stand|stands|refer|refers|regulate|regulates)\b", re.I)
# A sentence whose subject is a pronoun ("It regulates all food ...", "They
# must ...") is a proposition, never a heading, whatever its verb: headings
# do not open with "it" or "they".
_PRONOUN_SUBJECT_RE = re.compile(r"^\s*(?:it|they|he|she|we|you|this|these|those)\s+[a-z]", re.I)
# A heading is SHORT and verbless. Both conditions, because no closed verb list
# is complete: "obliges ... to check" uses neither listed verb and is a full
# proposition, and classifying it a heading made a real answer look like a
# refusal. An infinitive ("to check") is taken as a verb too.
HEADING_MAX_WORDS = 8


def _looks_like_heading(plain: str) -> bool:
    body = re.sub(r"\d+(?:\.\d+)?(?:\([^)]{1,4}\))*|\b21\s*CFR\b|[§]", " ", plain)
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", body)
    if len(words) > HEADING_MAX_WORDS:
        return False
    if _VERB_RE.search(body) or re.search(r"\bto\s+[a-z]{3,}\b", body) or _PRONOUN_SUBJECT_RE.match(body):
        return False
    return True


_POINTER_RE = re.compile(
    r"\b(?:are|is)\s+(?:specified|described|set\s+(?:out|forth)|found|listed|contained|detailed|provided|outlined|"
    r"addressed|covered)\s+(?:in|at|under|by)\b|\bas\s+(?:outlined|described|specified|set\s+out)\s+in\b"
    r"|\bsee\s+(?:\[|§|21\s*CFR|section|part|subpart)", re.I)
_POINTER_WORDS = frozenset("specified described set out forth found listed contained detailed provided outlined "
                           "addressed covered see ecfr guidance eCFR".lower().split())


def _novel_terms(text: str, question: str | None) -> list[str]:
    """Content stems the sentence adds beyond the question and pointer wording."""
    from regulus.accuracy.intent import matched, terms

    mine = [t for t in terms(MARK_RE.sub(" ", text)) if t not in {w[:6] for w in _POINTER_WORDS}]
    mine = [t for t in mine if not any(t.startswith(w[:5]) for w in _POINTER_WORDS)]
    if not question:
        return mine
    asked = terms(question)
    return [t for t in mine if t not in matched(mine, asked) or not matched((t,), asked)]


def classify(sentence: str, *, question: str | None = None) -> Sentence:
    text = sentence.strip()
    if _QUOTATION_RE.search(text):
        return Sentence(text, QUOTATION, "inserted verbatim by the pipeline's repair or fallback, grounded by construction")
    if _PIPELINE_RE.search(text):
        return Sentence(text, PIPELINE, "a fixed or templated sentence the pipeline wrote, not a claim about the evidence")
    if _LABEL_ONLY_RE.match(text):
        return Sentence(text, LABEL, "a citation label used as a heading")
    plain_text = MARK_RE.sub(" ", text).strip()
    if plain_text.rstrip().endswith(":"):
        return Sentence(text, HEADING, "a lead-in ending in a colon; it introduces content but asserts none")
    # "... shall include the following sub-requirements: [1][2] ... [18]." - a list
    # lead-in whose list is only citation markers asserts nothing (row D-004)
    if re.sub(r"[\s.;,]+$", "", plain_text).endswith(":"):
        return Sentence(text, HEADING, "a lead-in to a list that is not there; it asserts nothing")
    if _looks_like_heading(plain_text):
        return Sentence(text, HEADING, "no verb: a heading or noun phrase, not a proposition")
    body = strip_lead(text)
    if len(_norm_words(body)) < MIN_CLAIM_WORDS:
        return Sentence(text, TRIVIAL, f"fewer than {MIN_CLAIM_WORDS} assertable words")
    if question and _norm_words(MARK_RE.sub(" ", text)) == _norm_words(question):
        return Sentence(text, ECHO, "a restatement of the question")
    if _POINTER_RE.search(plain_text) and len(_novel_terms(plain_text, question)) <= 1:
        return Sentence(text, POINTER, "says where the requirements are, not what they are")
    if question and not _novel_terms(plain_text, question):
        return Sentence(text, RESTATEMENT, "adds nothing to what the question already says")
    plain = MARK_RE.sub(" ", text)
    if _META_RE.search(plain):
        return Sentence(text, META, "a statement about the sources or the answer, not about the regulation")
    if _PLACEHOLDER_RE.search(plain):
        return Sentence(text, UNCERTAIN, "contains an unfilled placeholder; its proposition cannot be resolved")
    if _COMMENTARY_RE.search(plain) and not _OBLIGATION_SIGNAL_RE.search(plain) and not _NAMES_PROVISION_RE.search(plain):
        return Sentence(text, UNCERTAIN, "commentary on importance with no regulatory proposition resolved")
    return Sentence(text, MODEL, "")


_QUOTE_BOUNDARY_RE = re.compile(r'(?<=[.!?]["\u201d\u2019])\s+(?=[A-Z])')


def segment(answer: str, *, question: str | None = None) -> tuple[Sentence, ...]:
    """Every sentence of the delivered answer, with its authorship and paragraph."""
    out: list[Sentence] = []
    blocks = [b for b in re.split(r"\n\s*\n|\n(?=\s*(?:[-*\u2022]|\d+[.)])\s)", answer or "") if b.strip()]
    for number, block in enumerate(blocks):
        for whole in split_sentences(attach_trailing_markers(block)):
            # the shared splitter (also used by the answering pipeline, so not
            # changed) does not break after a closing quote: 'for "Drug" and
            # "Facts." The headings ...' is two sentences (acceptance row G-004)
            for sentence in _QUOTE_BOUNDARY_RE.split(whole):
                if not sentence.strip():
                    continue
                classified = classify(sentence, question=question)
                out.append(Sentence(classified.text, classified.origin, classified.reason, number))
    return tuple(out)


# Verbs that open an independent regulatory obligation inside a coordinated
# list: "must establish a QMS, maintain UDI procedures, and ensure ...".
_OBLIGATION_VERBS = frozenset("""establish maintain document ensure review keep submit notify retain record validate
verify investigate report provide include identify control implement train conduct perform follow approve reject use
label test sample examine evaluate monitor calibrate inspect assess analyze analyse prepare develop designate register
renew list update declare describe disclose determine define store hold handle segregate quarantine reconcile verify
""".split())
_MODAL_SPLIT_RE = re.compile(r"\b(must|shall|is required to|are required to|should|may not|must not|shall not)\s+", re.I)


def propositions(sentence: str) -> list[str]:
    """Independent regulatory propositions inside one sentence, or [sentence].

    Splits only the unambiguous shape: ONE modal followed by a list of at least
    two items that each open with an obligation verb, e.g.

        "The manufacturer must establish a QMS, maintain UDI procedures, and
         ensure all personnel receive annual training [1]."
        -> "The manufacturer must establish a QMS [1]."
           "The manufacturer must maintain UDI procedures [1]."
           "The manufacturer must ensure all personnel receive annual training [1]."

    Anything else is returned whole: splitting a sentence that is not a list of
    obligations would manufacture fragments that no passage can match. Each
    proposition keeps the sentence's citation markers.
    """
    marks = " ".join(MARK_RE.findall(sentence) and [f"[{m}]" for m in MARK_RE.findall(sentence)])
    plain = MARK_RE.sub(" ", sentence).strip().rstrip(".")
    modals = list(_MODAL_SPLIT_RE.finditer(plain))
    if len(modals) != 1:
        return [sentence]
    m = modals[0]
    head, tail = plain[: m.end()], plain[m.end():]
    items = [i.strip(" ,;") for i in re.split(r",\s*(?:and\s+|or\s+)?|;\s*|\s+and\s+(?=\w+\s)", tail) if i.strip(" ,;")]
    # Every item must be a verb WITH its own object. "establish and maintain
    # procedures" is one obligation with a compound verb, and splitting it would
    # leave a bare "establish" that asserts nothing.
    if (len(items) < 2 or not all(len(i.split()) >= 2 and i.split()[0].lower() in _OBLIGATION_VERBS for i in items)):
        return [sentence]
    return [f"{head}{item}{(' ' + marks) if marks else ''}." for item in items]


# "<head> include / add / contain / comprise / consist of <items>": the head is
# what the items belong to and the items are the content. Descriptive verbs only:
# a modal sentence is split by `propositions` above, with its modality inherited.
_ENUMERATION_RE = re.compile(
    r"^(?P<head>.{2,200}?\b(?:includes?|including|contains?|comprises?|consists?\s+of|adds?|such\s+as|"
    r"(?:is|are)\s+as\s+follows:?))\s+(?P<tail>\S.*)$", re.I)
_INNER_LIST_RE = re.compile(r"\b(?:includes?|including|contains?|comprises?|consists?\s+of|such\s+as)\b", re.I)
_HARD_ITEM_BOUNDARY_RE = re.compile(r"\s*(?:,\s*with\s+|;\s*)", re.I)
_MARKED_ITEM_RE = re.compile(r"(.+?)((?:\s*\[\d{1,2}\])+)\s*(?:,\s*(?:and\s+|or\s+)?|;\s*|\s+and\s+|$)")


@dataclass(frozen=True)
class Enumeration:
    """A sentence of the shape "<head> include <item>, <item> and <item>"."""

    head: str
    items: tuple[str, ...]          # each with its own citation markers, when it had any
    marked: bool                    # items were delimited by citation markers

    def units(self) -> list[str]:
        return [f"{self.head} {item.rstrip('.')}." for item in self.items]


def enumeration(sentence: str) -> Enumeration | None:
    """The head and items of an include-type sentence, or None.

    Items are split at citation markers when every item carries one ("adds the
    name of the device [3], the date the complaint was received [4], ..."),
    otherwise at commas / and / ", with". A one-word piece ("address" in "the
    name, address, and phone number") is not an item and is joined back to the
    one before it, so a list of attributes is never shredded into words.
    """
    text = sentence.strip()
    m = _ENUMERATION_RE.match(text)
    if not m:
        return None
    head, tail = m.group("head").strip(), m.group("tail").strip().rstrip(".")
    if _MODAL_SPLIT_RE.search(head):
        return None                                   # a modal sentence: `propositions` handles it
    # marker-delimited: consecutive "<item> [n]," matches that cover the whole tail
    marked, at = [], 0
    for mm in _MARKED_ITEM_RE.finditer(tail):
        if mm.start() != at:
            break
        marked.append(f"{mm.group(1).strip(' ,;')} {mm.group(2).strip()}")
        at = mm.end()
    if len(marked) >= 2 and at >= len(tail.rstrip(" .")):
        return Enumeration(head, tuple(marked), True)
    # ", with" and ";" join separate facts; inside each segment, commas separate
    # items only when the segment is shaped like a list - three or more pieces,
    # or a final ", and X" / ", or X". A bare "and"/"or" is never a boundary: it
    # joins words inside one phrase ("headings and subheadings", "minimize or
    # prevent"), and ", as appropriate" / ", taking into account ..." modify the
    # item before them rather than starting a new one (acceptance row F-007).
    items: list[str] = []
    for segment in _HARD_ITEM_BOUNDARY_RE.split(tail):
        segment = segment.strip(" ,;")
        if not segment:
            continue
        pieces = [p.strip(" ,;") for p in re.split(r",\s*", segment) if p.strip(" ,;")]
        listy = len(pieces) >= 3 or (len(pieces) == 2 and re.match(r"(?:and|or)\b", pieces[1], re.I))
        # "conducting activities THAT INCLUDE verification, reanalysis, and
        # validation": the commas belong to the inner list, not to this head's
        if listy and _INNER_LIST_RE.search(pieces[0]):
            listy = False
        for piece in (pieces if listy else [segment]):
            piece = re.sub(r"^(?:and|or)\s+", "", piece, flags=re.I)
            items.append(piece)     # a one-word member of a list ("chloroform") is still a member
    return Enumeration(head, tuple(items), False) if items else None


_DEMONSTRATIVE_RE = re.compile(r"^\s*(?:-\s*)?(?P<pron>these|those|they|this|it|such)\b(?P<noun>\s+(?!include|includes|are|is|"
                               r"must|shall|may|should|will|can|ensure|ensures|require|requires|apply|applies)[a-z]+)?", re.I)


def antecedent(previous: str) -> str | None:
    """The noun phrase a following "These ..." refers to, from the previous claim
    sentence only: the object of its modal verb ("must maintain RECORDS"), or its
    subject when it has no modal. Local and deterministic; None when unclear."""
    plain = MARK_RE.sub(" ", previous or "").strip().rstrip(".")
    m = _MODAL_SPLIT_RE.search(plain)
    if m:
        rest = plain[m.end():].split(None, 1)
        phrase = re.split(r"\s*(?:,|;|\bto\b|\bthat\b|\bwhich\b)\s*", rest[1])[0] if len(rest) > 1 else ""
    else:
        v = re.search(r"\b(?:is|are|include|includes|contain|contains|ensure|ensures|apply|applies|cover|covers)\b", plain, re.I)
        phrase = plain[: v.start()] if v else ""
    phrase = strip_lead(phrase).strip(" ,")
    return phrase if 1 <= len(phrase.split()) <= 8 else None


def resolve(sentence: str, previous: str | None) -> tuple[str, str | None]:
    """(text with a leading demonstrative resolved, the antecedent used)."""
    if not previous:
        return sentence, None
    m = _DEMONSTRATIVE_RE.match(sentence)
    if not m:
        return sentence, None
    noun = (m.group("noun") or "").strip().lower()
    if noun:
        # "These provisions ..." refers to the provisions the previous sentence
        # named; any other explicit noun already says what it is about
        if not re.match(r"(?:provision|section|paragraph|regulation|requirement|rule|part)s?$", noun):
            return sentence, None
        from regulus.retrieval.references import parse_cfr_references

        named = [r.canonical for r in parse_cfr_references(MARK_RE.sub(" ", previous))]
        if not named:
            return sentence, None
        ante = " and ".join(dict.fromkeys(named))
        return ante + sentence[m.end():], ante
    ante = antecedent(previous)
    if not ante:
        return sentence, None
    return ante + sentence[m.end():], ante


def cited(sentence: Sentence, sentences, *, provisions: frozenset = frozenset()) -> bool:
    """Whether a statement carries a citation, as a reader of the answer sees it.

    Three forms count, all of which the rubric's own scorer accepted:
    a `[n]` marker on the sentence; a marker on a LATER sentence of the same
    paragraph (one trailing `[1]` citing the paragraph it closes, as acceptance
    row P-010 does and was scored L=1 for); or the sentence naming, in its own
    text, a provision that is one of the evidence sources. Which source is cited
    is still checked elsewhere: this only says whether one is.
    """
    if MARK_RE.search(sentence.text):
        return True
    later = [s for s in sentences if s.paragraph == sentence.paragraph]
    if any(MARK_RE.search(s.text) for s in later[later.index(sentence) + 1:] if sentence in later):
        return True
    if provisions:
        from regulus.retrieval.references import parse_cfr_references

        return any(ref.canonical in provisions for ref in parse_cfr_references(MARK_RE.sub(" ", sentence.text)))
    return False


def claims(sentences) -> tuple[Sentence, ...]:
    return tuple(s for s in sentences if s.is_claim)


def counts(sentences) -> dict[str, int]:
    out = {origin: 0 for origin in ORIGINS}
    for s in sentences:
        out[s.origin] += 1
    return out
