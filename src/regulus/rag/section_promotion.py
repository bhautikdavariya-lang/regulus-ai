"""Section promotion: a question that names no provision is answered as if it had named the section that answers it.

Why (cosmetics benchmark, 22 Oct 2026): a general question reaches the model as "REQUESTED PROVISIONS: none (general
question)" with related passages only, and both Qwen3 models decline it (82 of 88 on 1.7B; 20 of 29 on
Qwen3-4B-Instruct-2507 with an answer-first format). The same questions with their section named are answered, and on
4B-2507 applied to the facts. So the step that was missing is choosing the section, not writing the answer.

How:
  1. rank whole eCFR sections for the question (regulus.retrieval.section_index): top `candidates` sections;
  2. picker: the answering model reads the question and each candidate's heading, part, subpart and best-matching
     sentence, and names the one or two that answer it ("NONE" = no promotion). On 95 bank questions its first choice
     was a key section 80% of the time against 72% for the lexical top 1; the model chooses where to look and never
     supplies regulatory text - the promoted sections are fetched verbatim from the database like any named provision;
  3. companions, mechanical, from the promoted section: a defined term of its family's definitions section (70.3 for
     Parts 70-82, 700.3 for 700-740) that appears in its use or restriction sentences or in the question; 70.5(a) when
     the question names an eye-area product and the section is a color listing; and in Part 82 the "General." section of
     the same subpart. Measured against the bank keys: all needed companions for 52 of 56 questions that need them;
  4. the plan is rebuilt from the question with the citations appended ("... (21 CFR 74.2203, 70.5(a))"), so the
     model sees which provisions were resolved and every later stage treats them as requested provisions.

mode "lexical" promotes the lexical top 1 without a model call (for retrieval-only measurement); "off" does nothing.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any

from regulus.retrieval.section_index import COSMETIC_PARTS, COSMETIC_TERMS, SectionIndex, cosmetic_question, section_index
from regulus.retrieval.statute import BLOCK_HEADER_CHARS, StatuteIndex, statute_index

MODES = ("off", "lexical", "picker")
CANDIDATES = 22
CFR_CANDIDATES_WITH_STATUTE = 20
LEXICAL_CANDIDATES = 16   # cosmetics questions: lexical candidates fused with ...
DENSE_CANDIDATES = 12     # ... the dense top 12 (regulus.retrieval.section_dense)
RRF_K = 10
# a part-only question ("Under Part 710, ...") gets the dense candidates of that part as well (on since 23 Oct, after the
# section-resolution and blind answer gates; REGULUS_PART_DENSE=0 turns it off)
PART_DENSE = os.environ.get("REGULUS_PART_DENSE", "1") == "1"
# a question naming a color additive: other colors' listings vetoed, the named listing offered and, when it ranks
# first, promoted without the picker (regulus.retrieval.entities; on since 23 Oct; REGULUS_ENTITY_CONSTRAINTS=0 turns it off)
ENTITY_CONSTRAINTS = os.environ.get("REGULUS_ENTITY_CONSTRAINTS", "1") == "1"
# the offered FD&C Act sections in order of relevance instead of 201, 601 ... 614 (on since 23 Oct; REGULUS_STATUTE_RANKING=0)
STATUTE_RANKING = os.environ.get("REGULUS_STATUTE_RANKING", "1") == "1"
# a picker reply naming two FD&C Act sections promotes both (the Act budget shared); before, a second pick was kept
# only from the other corpus (on since 23 Oct; REGULUS_PICKER_SECOND_ACT=0 turns it off)
SECOND_ACT = os.environ.get("REGULUS_PICKER_SECOND_ACT", "1") == "1"
# a cross-encoder (regulus.retrieval.rerank) reads each candidate's best paragraphs; a pick it scores below
# RERANK_VETO_BELOW while another candidate scores RERANK_VETO_MARGIN higher is replaced by that one (on since 23 Oct
# with bge-m3, 0.30 / 0.15 fitted on the dev set; REGULUS_RERANKER=off turns it off; without the model files it is off)
RERANKER = (os.environ.get("REGULUS_RERANKER", "bge-m3").strip() or None) if os.environ.get("REGULUS_RERANKER", "bge-m3").strip().lower() not in ("off", "none", "0") else None
RERANK_PARAGRAPHS = 3
RERANK_VETO_BELOW = float(os.environ.get("REGULUS_RERANK_VETO_BELOW", "0.3"))
RERANK_VETO_MARGIN = float(os.environ.get("REGULUS_RERANK_VETO_MARGIN", "0.15"))
STATUTE_BUDGET = 6000   # rendered characters of statute evidence (source headers included)
CO_STATUTE_BUDGET = 2500  # the same when the Act text accompanies a promoted regulation   # fewer CFR candidates when the cosmetics chapter of the Act is offered too
# FD&C Act sections offered to the picker for a cosmetics question: chapter VI (601-614) and the 201 definitions.
# 301 (prohibited acts) and 704 (inspection) are in the store but not offered: they are long, general, and won the
# lexical ranking for questions about everything else (27/56 statute keys in the top 3).
STATUTE_OFFERED = ("201", "601", "602", "603", "604", "605", "606", "607", "608", "609", "610", "611", "612", "613", "614")
_PATH = r"((?:\([a-zA-Z0-9]{1,6}\))*)"
# explicit references to the FD&C Act: accepted as they are
_ACT_REF = re.compile(r"(?:FD&C\s+Act|FDCA|Federal\s+Food,\s+Drug,?\s+and\s+Cosmetic\s+Act)\s*(?:§|section|sec\.)?\s*(\d{3})(?!\d|\.\d)" + _PATH, re.I)
_SIGN_REF = re.compile(r"§\s*(\d{3})(?!\d|\.\d)" + _PATH)
_USC_REF = re.compile(r"21\s+U\.?S\.?C\.?\s*§?\s*(\d{3}[a-z]*)" + _PATH, re.I)
# bare "section 605", "the 610 duties", "under 607": only in a cosmetics question that names no other Act
_SECTION_WORD_REF = re.compile(r"\b(?:section|sec\.)\s*(\d{3})(?!\d|\.\d)" + _PATH, re.I)
_LED_COSMETIC_SECTION = re.compile(r"\b(?:the|under|per)\s+(60[1-9]|61[0-4])(?!\d|\.\d)" + _PATH, re.I)
_OTHER_ACT = re.compile(r"\b(?:Public\s+Health\s+Service|Regulatory\s+Flexibility|Fair\s+Packaging(?:\s+and\s+Labeling)?|"
                        r"Federal\s+Trade\s+Commission|Unfunded\s+Mandates|Paperwork\s+Reduction|Controlled\s+Substances|"
                        r"Federal\s+Meat\s+Inspection|Poultry\s+Products\s+Inspection|Toxic\s+Substances\s+Control)\s+Act\b|"
                        r"\bPHSA?\b|\bFPLA\b|\bTSCA\b|\bCSA\b", re.I)
_SUBPART_REF = re.compile(r"\bsubpart\s+([A-Z])\b")
_BIOLOGIC = re.compile(r"\b(?:biologic(?:al|s)?|blood|plasma|vaccines?|tissues?|HCT/Ps?|allergenic|potency|sterility)\b", re.I)
_SUBSECTION_OF = re.compile(r"\bsubsection\s*\(([a-z0-9]{1,4})\)\s*of\s+(?:FD&C\s+Act\s+)?(?:section|§)\s*(\d{3})", re.I)
_BARE_COSMETIC_SECTION = re.compile(r"(?<![\d.§])\b(60[1-9]|61[0-4])(?!\d|\.\d)" + _PATH)
SNIPPET_CHARS = 200
LEADIN_CHARS = 140   # a sub-paragraph's lead-in shown before it
# 16 tokens cut 33 of 91 holdout replies mid-citation ("21 CFR 740.18, FD&C Act §"), losing every second pick (23 Oct
# failure analysis); greedy decoding keeps the first pick byte-identical under a larger cap. 48 since 23 Oct
# (REGULUS_PICKER_MAX_TOKENS overrides).
PICKER_MAX_TOKENS = int(os.environ.get("REGULUS_PICKER_MAX_TOKENS", "48"))
DEFINITIONS_SECTION = "604"                                    # FD&C Act 604: "In this subchapter:" definitions
# ST1: a regulation citing the Act it implements ("section 403(i) of the act", "sections 501 and 502 of the Federal Food,
# Drug, and Cosmetic Act")
_ACT_CITED = re.compile(r"\bsections?\s+((?:\d{3}[A-Za-z]?(?:\([a-zA-Z0-9]{1,6}\))*(?:\s*,\s*|\s+(?:and|or)\s+)?)+)\s+of\s+the\s+"
                        r"(?:Federal\s+Food,\s+Drug,\s+and\s+Cosmetic\s+)?[Aa]ct\b")
SUBCHAPTER_DEFINED = frozenset(str(n) for n in range(605, 615))  # the sections 604's definitions govern
GENERIC_DEFINED_TERMS = frozenset({"cosmetic product"})        # used in every section; defines nothing a question turns on
DEFINITION_BUDGET = 2400                                      # rendered characters for 604 definitions with a promoted section
PICKER_THINK_BUDGET = 0   # a thinking model picks with its reasoning block closed: the reply is one citation

PICKER_SYSTEM = ("You select which sections of Title 21 of the Code of Federal Regulations or of the FD&C Act answer a "
                 "question. You are given the question and candidate sections, each with its heading and one sentence of its "
                 "text. Judge by what each section is about. Reply with citations only.")
# The reply names the sections ("21 CFR 71.2", "FD&C Act § 607"), not their bracket numbers: with 29 numbered
# candidates Qwen3-4B-Instruct-2507 answered "[27]" (FD&C Act 612) for questions about 607 and 613 (22 Oct).
PICKER_LAST = ("Reply with the citation of the one or two sections whose text most directly answers the question, best "
               "first, separated by a comma, written as shown (for example 21 CFR 71.2 or FD&C Act § 607). Reply NONE if no "
               "candidate answers it.")

_DEF_RE = re.compile(r"^\([a-z]{1,2}\)\s+(?:The terms?\s+)?(.+?)\s+means?\b", re.I)
_USE_RE = re.compile(r"\b(?:safely used|restricted to|uses and restrictions|for use (?:in|only)|may be used)\b", re.I)
_SENT_RE = re.compile(r"(?<=[.;])\s+")
# a listing that speaks to eye-area use: "area of the eye", or names eye products ("eyeliner, brush-on-brow, eye shadow")
_EYE_USE = re.compile(r"area of the eye|eye ?liner|eye ?shadow|mascara|eyebrow|brush-on-brow|eye makeup", re.I)
EYE_TERMS = frozenset({"eye", "eyelin", "eyebrow", "mascara", "shadow"})   # 21 CFR 720.4(c)(3), stemmed
COLOR_LISTING_PARTS = frozenset({"73", "74", "82"})

_XREF_SQL = """
SELECT DISTINCT x.target_citation FROM cfr_cross_references x JOIN cfr_records r ON r.id = x.from_record_id
WHERE r.section_number = %(s)s AND r.removed_on IS NULL AND x.resolvable
"""
_SNIPPET_SQL = """
SELECT section_number, ordinal, paragraph_path, body_text FROM cfr_records
WHERE removed_on IS NULL AND section_number = ANY(%(s)s) AND ordinal = ANY(%(o)s)
"""
_LEADIN_SQL = """
SELECT section_number, paragraph_path, body_text FROM cfr_records
WHERE removed_on IS NULL AND section_number = ANY(%(s)s) AND paragraph_path = ANY(%(p)s)
"""
_SECTION_SQL = """
SELECT paragraph_path, body_text FROM cfr_records
WHERE removed_on IS NULL AND NOT is_reserved AND section_number = %(s)s ORDER BY ordinal
"""


@dataclass(frozen=True)
class Promotion:
    sections: tuple[str, ...]          # the promoted section(s), "74.2203"
    companions: tuple[str, ...]        # "70.3(v)", "70.5(a)", "82.1050"
    method: str
    statute: tuple[str, ...] = ()      # promoted FD&C Act section(s), "605"; their paragraphs become the evidence
    statute_rows: tuple[int, ...] = () # StatuteIndex row indices placed in the prompt
    statute_blocks: tuple[tuple[int, ...], ...] = ()     # the same rows grouped into evidence passages
    statute_left_out: tuple[tuple[int, ...], ...] = ()   # blocks of the promoted section(s) the budget kept out
    candidates: tuple[dict, ...] = ()
    picker_output: str | None = None
    seconds: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def citations(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.sections + self.companions))

    @property
    def suffix(self) -> str:
        return " (21 CFR " + ", ".join(self.citations) + ")" if self.citations else ""

    def to_dict(self) -> dict[str, Any]:
        return {"sections": list(self.sections), "companions": list(self.companions), "method": self.method,
                "statute": list(self.statute), "statute_rows": len(self.statute_rows),
                "statute_blocks_left_out": len(self.statute_left_out),
                "citations": list(self.citations), "picker_output": self.picker_output, "seconds": round(self.seconds, 2),
                "candidates": [c["section"] for c in self.candidates], "notes": list(self.notes)}


def rerank_label(c: dict) -> str:
    """A candidate's citation with where it sits, for the cross-encoder: the same color is listed word for word in the
    Foods, Drugs and Cosmetics subparts, and without the subpart the reranker could not tell 73.85 from 73.2085."""
    if c.get("statute"):
        return f"FD&C Act § {c['section']} (Federal Food, Drug, and Cosmetic Act)"
    where = c.get("part_title") or f"Part {c.get('part', '')}"
    if c.get("subpart"):
        where += f"; {c['subpart'].title()}"
    return f"21 CFR {c['section']} ({where})"


def picker_prompt(question: str, candidates: list[dict]) -> str:
    lines = [f"QUESTION: {question}", "", "CANDIDATE SECTIONS:"]
    for i, c in enumerate(candidates, 1):
        if c.get("statute"):
            lines.append(f"[{i}] FD&C Act § {c['section']} [21 U.S.C. {c['usc']}] {c['heading']} (Federal Food, Drug, and "
                         f"Cosmetic Act, statute) Covers: {c['snippet']}")
            continue
        where = c.get("part_title") or f"Part {c['part']}"
        if c.get("subpart"):
            where += f"; {c['subpart'].title()}"
        lines.append(f"[{i}] 21 CFR {c['section']} {c['heading']} ({where}) Text: \"{c['snippet']}\"")
    lines += ["", PICKER_LAST]
    return "\n".join(lines)


_CFR_NUM = re.compile(r"\b(\d{1,4}\.\d+[a-z]?)\b")
_ACT_NUM = re.compile(r"(?:§|[Ss]ection|Act)\s*(\d{3})(?!\d|\.\d)")
_CITATION_LIKE = re.compile(r"\d\.\d|CFR|§|\bAct\b|[Ss]ection|U\.S\.C", re.I)


def parse_picks(text: str, n: int, sections: list[str] | None = None) -> list[int]:
    """Candidate positions (1-based) the picker's reply names, best first, at most two.

    The reply is asked for citations ("21 CFR 71.2", "FD&C Act § 607"); each is mapped to the candidate carrying it.
    A reply that cites something that is not a candidate gives [] - its digits are never read as positions ("21 CFR
    70.3" would have meant candidates 21 and 3). Bare positions are accepted only as "[n]" or a reply of numbers."""
    if not text or (re.search(r"\bnone\b", text, re.I) and not re.search(r"\d", text)):
        return []
    out: list[int] = []
    if sections:
        cited = _CFR_NUM.findall(text) + _ACT_NUM.findall(_CFR_NUM.sub(" ", text))
        for x in cited:
            if x in sections and sections.index(x) + 1 not in out:
                out.append(sections.index(x) + 1)
        if out or _CITATION_LIKE.search(re.sub(r"\[\d+\]", " ", text)):
            return out[:2]
    numbers = re.findall(r"\[(\d+)\]", text) or (re.findall(r"\d+", text) if re.fullmatch(r"[\d,\s\[\]]+", text.strip()) else [])
    for x in numbers:
        i = int(x)
        if 1 <= i <= n and i not in out:
            out.append(i)
    return out[:2]


COSMETIC_TERMS_GENERIC = frozenset({"cosmet", "label", "product", "compani", "manufactur", "make", "sell", "use"})
_PART_QUESTION_WORDS = frozenset({"part", "cfr", "requir", "cover", "say", "provid", "regul", "apply", "appli", "rule", "contain",
                                  "establish", "address", "set", "govern", "21", "subpart", "general", "overview"})
_SUBPART_OF = (("cosmetic", "cosmetic"), ("drug", "drug"), ("food", "food"), ("device", "device"))
_NON_COSMETIC_TERMS = {"drug": frozenset({"drug", "tablet", "capsul", "oral", "ingest"}),
                       "food": frozenset({"food", "beverag", "candi"}), "device": frozenset({"devic", "sutur", "lens", "implant"})}


# product words that say which subpart of a color listing a question is about (stemmed, PostgreSQL 'english'); used only
# when no reranker reads the listings (SectionPromoter.choose_listing)
_PRODUCT_KIND_TERMS = {
    "food": frozenset("""food beverag drink juic punch soda cola sauc snack confect candi dessert ice cereal bake bread cake
                         gum gelatin feed anim pet fish salmon shrimp trout egg yolk meat sausag poultri chicken dairi chees
                         milk yogurt season spice popcorn margarin oil-bas jam jelli frost soup gravi beer wine spirit""".split()),
    "drug": frozenset("drug tablet capsul oral ingest prescript medic pharmaceut ointment otc".split()),
    "device": frozenset("devic sutur lens implant contact catheter".split()),
}
# cosmetic product words (COSMETIC_TERMS without the color words every color question has), with the eye makeup words of
# 21 CFR 720.4(c)(3) ("eyebrow pencil", "eye shadow") - "green eye pencil" named no product kind (73.2326, 23 Oct)
_COSMETIC_PRODUCT_TERMS = (COSMETIC_TERMS - {"color", "colorant", "pigment", "lake", "fd", "tint", "glitter", "shimmer"}) | {"eye", "pencil"}


def _subpart_kind(subpart: str) -> str | None:
    s = (subpart or "").lower()
    return next((k for key, k in _SUBPART_OF if key in s), None)


class SectionPromoter:
    def __init__(self, db, generator=None, mode: str = "picker", candidates: int = CANDIDATES,
                 index: SectionIndex | None = None) -> None:
        if mode not in MODES:
            raise ValueError(f"section_promotion must be one of {MODES}, got {mode!r}")
        self.db, self.generator, self.mode, self.limit = db, generator, mode, candidates
        self._index = index
        self._defs: dict[str, list[tuple[str, list[str]]]] | None = None
        self._part_titles: dict[str, str] | None = None

    @property
    def statute(self) -> StatuteIndex | None:
        return statute_index(self.db)

    def statute_candidates(self, lexemes, question: str | None = None) -> list[dict]:
        st = self.statute
        if st is None:
            return []
        ranked = {r.fdca: r for r in st.rank(lexemes, limit=len(st.by_sec))}
        order = self.statute_order(question, ranked) if (STATUTE_RANKING and question) else STATUTE_OFFERED
        out = []
        for s in order:
            if s not in st.by_sec:
                continue
            r = ranked.get(s)
            row = st.rows[r.best if r else st.by_sec[s][0]]
            out.append({"statute": True, "section": s, "usc": st.usc(s), "heading": st.heading(s), "part": "FDCA",
                        "subpart": "", "part_title": "", "score": round(r.score, 4) if r else 0.0,
                        # the section's own subsection captions: what it covers (retrieval diagnosis, 22 Oct)
                        "snippet": st.outline(s) or " ".join(row["body_text"].split())[:SNIPPET_CHARS]})
        return out

    def rerank_scores(self, question: str, cands: list[dict]) -> dict[str, tuple[float, str]]:
        """Each candidate section's best cross-encoder score over its RERANK_PARAGRAPHS paragraphs most similar to the
        question by embedding: section -> (score 0..1, that paragraph's path). {} without the models."""
        from regulus.retrieval.paragraph_dense import paragraph_dense
        from regulus.retrieval.rerank import reranker

        pd, rr = paragraph_dense(self.db), reranker(RERANKER) if RERANKER else None
        if pd is None or rr is None:
            return {}
        sims = pd.similarities(question)
        passages, owners = [], []
        for c in cands:
            label = rerank_label(c)
            for para, _ in pd.section_paragraphs(question, c["section"], sims)[:RERANK_PARAGRAPHS]:
                passages.append(f"{label} {pd.text(para)}")
                owners.append((c["section"], para.path))
        best: dict[str, tuple[float, str]] = {}
        for (sec, path), s in zip(owners, rr.score(question, passages) if passages else ()):
            if sec not in best or s > best[sec][0]:
                best[sec] = (float(s), path)
        self.__dict__["last_rerank"] = best   # diagnostics for the caller (the harness records it)
        return best

    def rerank_veto(self, question: str, cands: list[dict], picked: dict) -> dict | None:
        """The candidate that replaces the picker's choice, or None to keep it: the pick scores below RERANK_VETO_BELOW
        and the best-scored candidate at least RERANK_VETO_MARGIN above it."""
        scores = self.rerank_scores(question, cands)
        if not scores:
            return None
        top = max(cands, key=lambda c: (scores.get(c["section"], (0.0, ""))[0], -cands.index(c)))
        ps, ts = scores.get(picked["section"], (0.0, ""))[0], scores.get(top["section"], (0.0, ""))[0]
        if top["section"] != picked["section"] and ps < RERANK_VETO_BELOW and ts - ps >= RERANK_VETO_MARGIN:
            return top
        return None

    def statute_order(self, question: str, ranked: dict) -> list[str]:
        """The offered FD&C Act sections, most relevant first: the lexical ranking (StatuteIndex.rank) fused by
        reciprocal rank with each section's best paragraph by embedding (regulus.retrieval.paragraph_dense). The fixed
        order 201, 601 ... 614 put the key section first for 1 of 40 Act-keyed dev questions; this order for 23."""
        from regulus.retrieval.paragraph_dense import paragraph_dense

        lex_order = sorted(STATUTE_OFFERED, key=lambda s: (-(ranked[s].score if s in ranked else 0.0), STATUTE_OFFERED.index(s)))
        score = {s: 1.0 / (RRF_K + i + 1) for i, s in enumerate(lex_order)}
        pd = paragraph_dense(self.db)
        if pd is not None:
            dense = [s for s, _, _ in pd.rank_sections(question, corpus="fdca") if s in STATUTE_OFFERED]
            for i, s in enumerate(dense):
                score[s] += 1.0 / (RRF_K + i + 1)
        return sorted(STATUTE_OFFERED, key=lambda s: (-score[s], STATUTE_OFFERED.index(s)))

    def named_statute(self, question: str, lexemes) -> list[tuple[str, str]]:
        """FD&C Act sections (with any paragraph path) the question itself cites: (section, path) pairs in order.

        Explicit references ("FD&C Act 605(e)", "§ 607", "21 U.S.C. 364a(b)") are accepted. A bare "section 610",
        "the 610 duties" or "under 607" is read as the FD&C Act only in a cosmetics question that names no other Act:
        "section 610 ... biological products" and "section 301 of the Public Health Service Act" are not (code review)."""
        st = self.statute
        if st is None:
            return []
        usc_to_fdca = {st.usc(s): s for s in st.by_sec}
        other_act = bool(_OTHER_ACT.search(question))
        found: list[tuple[str, str]] = [] if other_act else [(s, f"({p})") for p, s in _SUBSECTION_OF.findall(question) if s in st.by_sec]
        found += [(m, p) for m, p in _ACT_REF.findall(question) if m in st.by_sec]
        found += [(usc_to_fdca[m.lower()], p) for m, p in _USC_REF.findall(question) if m.lower() in usc_to_fdca]
        if not other_act:
            found += [(m, p) for m, p in _SIGN_REF.findall(question) if m in st.by_sec]
            if not found and cosmetic_question(lexemes) and not _BIOLOGIC.search(question):
                found = [(m, p) for m, p in _SECTION_WORD_REF.findall(question) + _LED_COSMETIC_SECTION.findall(question)
                         + _BARE_COSMETIC_SECTION.findall(question) if m in st.by_sec]
        out: list[tuple[str, str]] = []
        for s, p in found:
            if s not in [x for x, _ in out]:
                out.append((s, p))
        return out

    def _statute_promotion(self, sections, lexemes, method: str, t0: float, cands=(), raw=None, budget: int | None = None) -> Promotion:
        """`sections`: (section, named paragraph path or "") pairs."""
        st = self.statute
        kept, left = [], []
        budget = (budget or STATUTE_BUDGET) // max(len(sections), 1)
        for s, path in sections:
            k, lo = st.blocks(s, lexemes, budget=budget, named_path=path or None)
            kept += [tuple(g) for g in k]
            left += [tuple(g) for g in lo]
        if any(s in SUBCHAPTER_DEFINED for s, _ in sections):
            kept += [g for g in self.definition_blocks([i for g in kept for i in g]) if g not in kept]
        return Promotion(sections=(), companions=(), method=method, statute=tuple(s for s, _ in sections),
                         statute_rows=tuple(i for g in kept for i in g), statute_blocks=tuple(kept),
                         statute_left_out=tuple(left), candidates=tuple(cands), picker_output=raw,
                         seconds=time.perf_counter() - t0)

    def practice_silence(self, question: str, lexemes, t0: float) -> Promotion | None:
        """P1 (regulus.rag.practice_silence): a cosmetics question about a manufacturing practice no general cosmetic
        provision and no cosmetics section of the Act mentions (calibration, pest control, cleaning SOPs, equipment
        certification) is answered from FD&C Act 606 and 601 (and 610 for records), pinned paragraph by paragraph;
        the search that establishes the silence runs on the database text, so a provision added later ends it."""
        from regulus.rag import practice_silence as PS
        from regulus.rag.validator_switches import enabled as precision_fix

        if not precision_fix("P1"):
            return None
        practices = PS.asked_practices(question)
        if not practices or self.statute is None or not all(PS.silent(self.db, self.statute, p) for p in practices):
            return None
        pinned = PS.statute_paths(practices, PS.asks_records(question))
        st = self.statute
        kept: list[tuple[int, ...]] = []
        for s, path in pinned:
            rows = tuple(i for i in st.by_sec.get(s, ()) if st.rows[i].get("paragraph_path") == path)
            if not rows:
                return None
            kept.append(rows)
        return Promotion(sections=(), companions=(), method="practice_silence",
                         statute=tuple(dict.fromkeys(s for s, _ in pinned)),
                         statute_rows=tuple(i for g in kept for i in g), statute_blocks=tuple(kept),
                         seconds=time.perf_counter() - t0, notes=PS.notes_for(practices))

    def definition_blocks(self, rows: list[int]) -> list[tuple[int, ...]]:
        """FD&C Act section 604 opens "In this subchapter:" - its definitions govern sections 605-614. The definitions
        of the terms the kept text uses ("serious adverse event", "responsible person", "facility"), most used first,
        within DEFINITION_BUDGET; they follow the section's own blocks, so the hard ceiling drops them first. On the
        dev questions the key elements needed them and they were never supplied (605 reports without 604(5), 22 Oct)."""
        st = self.statute
        if st is None or DEFINITIONS_SECTION not in st.by_sec:
            return []
        text = " ".join(st.rows[i]["body_text"] for i in rows).lower()
        groups: dict[str, list[int]] = {}
        for i in st.by_sec[DEFINITIONS_SECTION]:
            top = st._top(i)
            if top:
                groups.setdefault(top, []).append(i)
        scored = []
        for top, g in groups.items():
            term = (st.rows[g[0]]["paragraph_heading"] or st.rows[g[0]].get("top_caption") or "").strip().lower()
            uses = len(re.findall(rf"\b{re.escape(term)}\b", text)) if term and term not in GENERIC_DEFINED_TERMS else 0
            if uses:
                scored.append((-uses, g[0], tuple(g)))
        out, used = [], 0
        for _, _, g in sorted(scored):
            cost = sum(len(st.rows[i]["body_text"]) + 1 for i in g) + BLOCK_HEADER_CHARS
            if used + cost <= DEFINITION_BUDGET:
                out.append(g)
                used += cost
        return out

    @property
    def index(self) -> SectionIndex:
        if self._index is None:
            self._index = section_index(self.db)
        return self._index

    # -- candidates -----------------------------------------------------------
    def candidates(self, question: str, parts: tuple[str, ...] | None = None) -> tuple[list[str], list[dict]]:
        lex = SectionIndex.question_lexemes(self.db, question)
        if parts:
            ranked = [r for r in self.index.rank(lex, limit=400) if r.part in parts]
            sub = _SUBPART_REF.search(question or "")
            subpart = None
            if sub:   # "subpart C of Part 82": that subpart's sections only (retrieval diagnosis: parser)
                in_sub = [r for r in ranked if (r.subpart or "").lower().startswith(f"subpart {sub.group(1).lower()} ")]
                subpart = f"subpart {sub.group(1).lower()} " if in_sub else None
                ranked = in_sub or ranked
            ranked = ranked[:self.limit]
            if PART_DENSE:
                # the dense ranking inside the named part(s) too: a section sharing no lexeme with the question was never
                # offered ("FDA Registered Facility, Reg. No." -> 710.8: 'registered' and 'registration' stem apart).
                # Appended after the lexical order, not fused into it: fusing reordered the top of the list and lost
                # two rank-1 keys of 17 (23 Oct section-resolution benchmark)
                extra = self._dense_only(question, ranked, parts, subpart)
                ranked = ranked[:max(self.limit - len(extra), 0)] + extra
        elif cosmetic_question(lex):
            # a cosmetics question: candidates from the color-additive and cosmetic parts only. Food, feed and device
            # sections were picked for cosmetics questions (117.251, 111.455, 226.30; 22 Oct); on the 277-question bank
            # the restriction loses no key section and adds 3 to the candidate lists
            ranked = [r for r in self.index.rank(lex, limit=400) if r.part in COSMETIC_PARTS][:LEXICAL_CANDIDATES]
            ranked = self._fuse_dense(question, ranked)
        else:
            ranked = self.index.rank(lex, limit=self.limit)
        if ENTITY_CONSTRAINTS:
            try:
                ranked = self._entity_constrained(question, lex, ranked, parts)
            except Exception:  # noqa: BLE001 - an aid: without it the ranking stands
                pass
        if not ranked:
            return lex, []
        rows = self.db.query(_SNIPPET_SQL, {"s": [r.section for r in ranked], "o": sorted({r.best_ordinal for r in ranked})})
        text = {(r["section_number"], int(r["ordinal"])): (r["paragraph_path"] or "", r["body_text"] or "") for r in rows}
        # a sub-paragraph is shown with its lead-in: "(2) the package is opened" says nothing without "(d) A certificate
        # shall expire ... if:" (retrieval diagnosis: picker context)
        parents = {}
        for r in ranked:
            path = text.get((r.section, r.best_ordinal), ("", ""))[0]
            m = re.match(r"^(\([^)]+\))\(", path or "")
            if m:
                parents[(r.section, m.group(1))] = ""
        if parents:
            for row in self.db.query(_LEADIN_SQL, {"s": sorted({s for s, _ in parents}), "p": sorted({p for _, p in parents})}):
                key = (row["section_number"], row["paragraph_path"])
                if key in parents:
                    parents[key] = " ".join((row["body_text"] or "").split())

        def snippet(r):
            path, body = text.get((r.section, r.best_ordinal), ("", ""))
            body = " ".join(body.split())
            m = re.match(r"^(\([^)]+\))\(", path or "")
            lead = parents.get((r.section, m.group(1)), "") if m else ""
            if lead:
                return (lead[:LEADIN_CHARS].rstrip() + " ... " + body)[:SNIPPET_CHARS + LEADIN_CHARS]
            return body[:SNIPPET_CHARS]

        titles = self._titles()
        return lex, [{"section": r.section, "part": r.part, "heading": r.heading, "subpart": r.subpart,
                      "part_title": titles.get(r.part, ""), "score": round(r.score, 4), "snippet": snippet(r)}
                     for r in ranked]

    def _dense_only(self, question: str, ranked: list, parts: tuple[str, ...], subpart: str | None, limit: int = 4) -> list:
        """Up to `limit` sections of the named part(s) (and subpart) that the dense ranking puts in its top
        DENSE_CANDIDATES there and the lexical list lacks, in dense order."""
        from regulus.retrieval.section_dense import section_dense
        from regulus.retrieval.section_index import RankedSection

        dense_ix = section_dense(self.db)
        if dense_ix is None:
            return []
        ix, where, first = self.index, self._where(), self.__dict__["_first_ordinal"]
        inside = [s for s in dense_ix.rank(question, len(dense_ix.names)) if s in where and ix.parts[where[s]] in parts
                  and (subpart is None or (ix.subparts[where[s]] or "").lower().startswith(subpart))][:DENSE_CANDIDATES]
        have = {r.section for r in ranked}
        return [RankedSection(s, ix.parts[where[s]], ix.headings[where[s]], ix.subparts[where[s]], 0.0, first.get(s, 0))
                for s in inside if s not in have][:limit]

    def _fuse_dense(self, question: str, ranked: list) -> list:
        """Lexical top LEXICAL_CANDIDATES fused with the dense top DENSE_CANDIDATES by reciprocal rank (k = RRF_K); the
        dense ranking finds paraphrased sections the words miss (unseen bank questions: key among the candidates
        129 -> 138 of 143). Without the embedding model the lexical list is returned unchanged."""
        from regulus.retrieval.section_dense import section_dense
        from regulus.retrieval.section_index import RankedSection

        dense_ix = section_dense(self.db)
        if dense_ix is None:
            return ranked
        dense = dense_ix.rank(question, DENSE_CANDIDATES)
        score: dict[str, float] = {}
        for i, r in enumerate(ranked):
            score[r.section] = score.get(r.section, 0.0) + 1.0 / (RRF_K + i + 1)
        for i, s in enumerate(dense):
            score[s] = score.get(s, 0.0) + 1.0 / (RRF_K + i + 1)
        by_section = {r.section: r for r in ranked}
        ix = self.index
        out = []
        for s in sorted(score, key=lambda x: (-score[x], x))[:self.limit]:
            if s in by_section:
                out.append(by_section[s])
            elif s in ix.sections:
                i = ix.sections.index(s)
                out.append(RankedSection(s, ix.parts[i], ix.headings[i], ix.subparts[i], 0.0, 0))
        return out

    # -- named color additives (regulus.retrieval.entities) ---------------------------------------
    def _where(self) -> dict[str, int]:
        cached = self.__dict__.get("_where_ix")
        if cached is None:
            ix = self.index
            cached = self.__dict__["_where_ix"] = {s: i for i, s in enumerate(ix.sections)}
            first: dict[str, int] = {}
            for si, o in zip(ix.row_section.tolist(), ix.row_ordinal.tolist()):
                s = ix.sections[si]
                first[s] = min(first.get(s, o), o)
            self.__dict__["_first_ordinal"] = first
        return cached

    def preferred_listing(self, sections, lex, parts: tuple[str, ...] | None = None, exact=(), order=()) -> list[str]:
        """Of one color's listing sections, the ones a question about it is answered from, best first, when no reranker
        reads them: the listing for the product kind the question names, then the Part 82 certification listing, then a
        listing without a product subpart. A question that names a food, drug or device product and no cosmetic one
        is about that kind ("carmine in our strawberry ice cream": 73.100, not the cosmetics listing 73.2087, 23 Oct
        synthetic set); otherwise the cosmetics subpart, the deployment's own (the same rule as siblings()). Within one
        kind: the exactly named color first ("paprika oleoresin" 73.345 before "paprika" 73.340), then the ranking's
        order (`order`, the candidate list), never the section number."""
        ix, where = self.index, self._where()
        lx = set(lex)
        other = {k for k, terms in _PRODUCT_KIND_TERMS.items() if lx & terms}
        wanted = set(other) if other and not (lx & _COSMETIC_PRODUCT_TERMS) else other | {"cosmetic"}
        ranked = []
        for s in sections:
            i = where.get(s)
            if i is None or (parts and ix.parts[i] not in parts):
                continue
            kind = _subpart_kind(ix.subparts[i])
            ranked.append((0 if kind in wanted else 1 if ix.parts[i] == "82" else 2 if kind is None else 3,
                           0 if (not exact or s in exact) else 1, order.index(s) if s in order else len(order), s))
        return [r[-1] for r in sorted(ranked)]

    def _listing_cands(self, sections) -> list[dict]:
        ix, where, titles = self.index, self._where(), self._titles()
        return [{"section": s, "part": ix.parts[where[s]], "heading": ix.headings[where[s]], "subpart": ix.subparts[where[s]],
                 "part_title": titles.get(ix.parts[where[s]], "")} for s in sections if s in where]

    def choose_listing(self, question: str, sections, lex, parts: tuple[str, ...] | None, exact=(), order=()) -> str | None:
        """The one listing of a named color a question is about. With the reranker it reads them - each with its subpart
        ("Subpart A - Foods", "Subpart C - Cosmetics") and its best paragraphs - and the best-scored one is chosen:
        whether 'salmon feed', 'fruit punch' or 'lip balm' is a food or a cosmetic is read from the text, not from a
        word list. Without the reranker, preferred_listing's product-kind rule."""
        where = self._where()
        pool = [s for s in sections or () if s in where and (not parts or self.index.parts[where[s]] in parts)]
        # a Part 82 listing is a one-line pointer ("shall conform to ... § 74.2331"): the companion of the listing that
        # says where the color may be used, never chosen in its place (5 dev keys lost to it, 23 Oct) - unless the
        # question asks about Part 82 only
        substantive = [s for s in pool if self.index.parts[where[s]] != "82"]
        pool = substantive or pool
        if not pool:
            return None
        lx = set(lex)
        kinds = {k for k, terms in _PRODUCT_KIND_TERMS.items() if lx & terms} | ({"cosmetic"} if lx & _COSMETIC_PRODUCT_TERMS else set())
        # a question that names one kind of product ("mascara", "ice cream") is decided by that word: the reranker reads
        # the Foods and Cosmetics listings of an exempt color as near-identical text and chose the food listing for 5
        # cosmetics questions (23 Oct). It reads the listings when the question names no kind of product, or several.
        if RERANKER and len(pool) > 1 and len(kinds) != 1:
            scores = self.rerank_scores(question, self._listing_cands(pool))
            if scores:
                return max(pool, key=lambda s: (scores.get(s, (0.0, ""))[0], -pool.index(s)))
        return (self.preferred_listing(pool, lex, parts, exact, order) or [None])[0]

    def _entity_constrained(self, question: str, lex, ranked: list, parts: tuple[str, ...] | None) -> list:
        """A question naming a color additive: a question naming a certified color (FD&C Blue No. 1) cannot mean another
        certified color's listing, so those are taken out of the candidates (FD&C Red No. 40 was picked for an FD&C Blue
        No. 1 question); an exempt color's listing is never taken out, because exempt names are loose ("pearlescent mica
        pigment", "krill meal" - vetoing them lost 12 synthetic keys, 23 Oct). Each named color's listing is offered
        when the ranking missed it (third place: offered, not forced)."""
        from regulus.retrieval.entities import entity_index, names_a_color
        from regulus.retrieval.section_index import RankedSection

        E = entity_index(self.index)
        named = [m for m in E.match(question) if names_a_color(question, m)]
        if not named:
            return ranked
        allowed = {s for m in named for s in m.sections}
        certified = any(any(k[0] == "cert" for k in m.keys) for m in named)
        kept = [r for r in ranked if not (certified and E.is_certified_listing(r.section) and r.section not in allowed)]
        have = {r.section for r in kept}
        ix, where, first = self.index, self._where(), self.__dict__["_first_ordinal"]
        for m in named:
            if have & set(m.sections):
                continue
            best = self.preferred_listing(m.sections, lex, parts, m.exact, [r.section for r in kept])
            if best:
                i = where[best[0]]
                kept.insert(min(2, len(kept)), RankedSection(best[0], ix.parts[i], ix.headings[i], ix.subparts[i], 0.0,
                                                             first.get(best[0], 0)))
                have.add(best[0])
        return kept

    def entity_pick(self, question: str, lex, cands: list[dict], parts: tuple[str, ...] | None) -> list[str] | None:
        """The sections promoted without the picker, or None: when the best-ranked regulation left after the color
        constraint is a listing of a color the question names, the listing of that exact name (not a shorter name inside
        it: "paprika oleoresin" is 73.345, not 73.340) for the question's product (choose_listing) is promoted, with the
        Part 82 certification listing of a cosmetics listing (as siblings() does); the same for a second named color.
        The picker still decides every other question."""
        from regulus.retrieval.entities import entity_index, names_a_color, normalize_heading

        E = entity_index(self.index)
        named = [m for m in E.match(question) if names_a_color(question, m)]
        top = next((c for c in cands if not c.get("statute")), None)
        if not named or top is None or not E.is_color_listing(top["section"]):
            return None
        first = next((m for m in named if top["section"] in m.sections), None)
        if first is None:
            return None
        ix, where = self.index, self._where()
        out: list[str] = []
        order = [c["section"] for c in cands if not c.get("statute")]
        for m in [first] + [m for m in named if m is not first][:1]:
            best = self.choose_listing(question, m.sections, lex, parts, m.exact, order)
            if best is None:
                continue
            chosen = [best]
            if ix.parts[where[best]] != "82":
                # the Part 82 certification listing of the same color, when the ranking offered it (as siblings() keeps it)
                head = normalize_heading(ix.headings[where[best]])
                chosen += [s for s in order if s in m.sections and ix.parts[where[s]] == "82"
                           and normalize_heading(ix.headings[where[s]]) == head][:1]
            out += [s for s in chosen if s not in out]
        return out or None

    def _titles(self) -> dict[str, str]:
        if self._part_titles is None:
            self._part_titles = {r["number"]: r["title"] or "" for r in self.db.query("SELECT number, title FROM cfr_parts")}
        return self._part_titles

    # -- companions -------------------------------------------------------------
    def _definitions(self) -> dict[str, list[tuple[str, list[str]]]]:
        if self._defs is None:
            self._defs = {}
            for sec in ("70.3", "700.3"):
                out = []
                for r in self.db.query(_SECTION_SQL, {"s": sec}):
                    m = _DEF_RE.match(r["body_text"] or "")
                    if not (m and r["paragraph_path"]):
                        continue
                    terms = [t.strip(" ,") for t in re.split(r",\s*|\s+and\s+", m.group(1))]
                    terms = [t for t in terms if len(t.split()) >= 2]
                    if terms:
                        out.append((r["paragraph_path"], terms))
                self._defs[sec] = out
        return self._defs

    def _section_text(self, section: str) -> str:
        """A section's live text, fetched once per section and promoter (it is read up to three times per question)."""
        cache = self.__dict__.setdefault("_text_cache", {})
        if section not in cache:
            if len(cache) > 256:
                cache.clear()
            cache[section] = " ".join(r["body_text"] or "" for r in self.db.query(_SECTION_SQL, {"s": section}))
        return cache[section]

    def definition_companions(self, question: str, limit: int = 4) -> list[str]:
        """For a question that asks how FDA defines something ("in FDA's sense", "How do FDA's definitions treat 'area
        of the eye' ..."): the paragraphs of the programme's definitions sections (70.3, 700.3, 82.3) whose defined term
        the question names - kept whatever section is promoted (retrieval diagnosis: promotion switched the
        defined-terms leg off). Single-word terms count only when the question quotes them."""
        from regulus.retrieval.query import _INVOKES_DEFINITION_RE, _QUOTED_TERM_RE

        if not _INVOKES_DEFINITION_RE.search(question or ""):
            return []
        q = " ".join((question or "").lower().split())
        quoted = {m.strip().lower() for m in _QUOTED_TERM_RE.findall(question or "")}
        out: list[str] = []
        for sec in ("70.3", "700.3", "82.3"):
            for path, terms in self._all_definitions(sec):
                for term in terms:
                    tl = term.lower().strip()
                    single = len(tl.split()) == 1
                    hit = (tl in quoted or any(tl in qt or qt in tl for qt in quoted)) if single else \
                          re.search(rf"(?<![a-z]){re.escape(tl)}s?(?![a-z])", q)
                    if hit and sec + path not in out:
                        out.append(sec + path)
                        break
        return out[:limit]

    def _all_definitions(self, sec: str) -> list[tuple[str, list[str]]]:
        cache = self.__dict__.setdefault("_defs_all", {})
        if sec not in cache:
            out = []
            for r in self.db.query(_SECTION_SQL, {"s": sec}):
                m = _DEF_RE.match(r["body_text"] or "") or re.match(r"^\([a-z]{1,2}\)\s+(?:A|An|The)\s+(.+?)\s+is\b", r["body_text"] or "")
                if m and r["paragraph_path"]:
                    out.append((r["paragraph_path"], [x.strip(" ,") for x in re.split(r",\s*|\s+and\s+", m.group(1)) if x.strip(" ,")]))
            cache[sec] = out
        return cache[sec]

    def cross_reference_companions(self, section: str, limit: int = 2) -> list[str]:
        """Provisions the promoted section itself cites, inside the cosmetics programme (cfr_cross_references): a
        paragraph citation as it is ("710.4" -> 700.3(j)); a whole-section citation by the paragraphs of that section
        that cite back the promoted one ("70.55" -> 70.19(n), the fee for the studies 70.55 provides), or whole when it
        is short. Not for color listings, whose citations are identity and labeling boilerplate."""
        out: list[str] = []
        for r in self.db.query(_XREF_SQL, {"s": section}):
            m = re.match(r"^21 CFR (\d+)\.(\d+[a-z]?)((?:\([a-z0-9]+\))*)$", r["target_citation"] or "")
            if not m or m.group(1) not in COSMETIC_PARTS or f"{m.group(1)}.{m.group(2)}" == section:
                continue
            target, path = f"{m.group(1)}.{m.group(2)}", m.group(3)
            if path:
                cand = [target + path]
            else:
                rows = self.db.query(_SECTION_SQL, {"s": target})
                back = [r2["paragraph_path"] for r2 in rows if r2["paragraph_path"]
                        and re.search(rf"§+\s*{re.escape(section)}(?![\d])", r2["body_text"] or "")]
                cand = [target + p for p in back[:1]] or ([target] if len(rows) <= 3 else [])
            out += [c for c in cand if c not in out]
            if len(out) >= limit:
                break
        return out[:limit]

    def companions(self, section: str, question: str, lexemes) -> list[str]:
        ix = self.index
        try:
            i = ix.sections.index(section)
        except ValueError:
            return []
        part, subpart = ix.parts[i], ix.subparts[i]
        out: list[str] = []
        p = int(re.match(r"\d+", part).group(0)) if re.match(r"\d+", part) else 0
        family = "70.3" if 70 <= p <= 82 else ("700.3" if 700 <= p <= 799 else None)
        if family and family != section:
            sents = _SENT_RE.split(self._section_text(section))
            use_text = " ".join(s for s in sents if _USE_RE.search(s)).lower()
            q = (question or "").lower()
            for path, terms in self._definitions().get(family, ()):
                if any(t.lower() in use_text or t.lower() in q for t in terms):
                    out.append(family + path)
        if part in COLOR_LISTING_PARTS and set(lexemes) & EYE_TERMS and "70.3(s)" not in out:
            out.append("70.3(s)")   # the question names an eye product: what "area of the eye" covers
        if part in COLOR_LISTING_PARTS and set(lexemes) & EYE_TERMS and section != "70.5":
            # 70.5(a) (no eye-area use unless the listing provides for it) only when the listing does not itself speak to
            # the area of the eye: added to a listing that permits eye use, it led the model to deny that use (22 Oct)
            if not _EYE_USE.search(self._section_text(section)):
                out.append("70.5(a)")
        if part not in COLOR_LISTING_PARTS:
            out += [c for c in self.cross_reference_companions(section) if c not in out]
        if part == "82":
            for j, (pj, sj, hj) in enumerate(zip(ix.parts, ix.subparts, ix.headings)):
                if pj == part and sj == subpart and (hj or "").lower().startswith("general.") and ix.sections[j] != section:
                    out.append(ix.sections[j])
            # C82 (regulus.rag.validator_switches): a certification question about an FD&C (subpart B) listing also gets
            # 82.5, the general specifications 82.50 makes a condition of certification (lead, arsenic, heavy metals):
            # the 82.705 / 82.706 keys name those limits, and the composed answer can quote them only when supplied
            from regulus.rag.validator_switches import enabled as precision_fix

            if ("82.50" in out and precision_fix("C82") and re.search(r"\bcertif|\bspecification", question or "", re.I)
                    and re.search(r"shall conform in identity and specifications to the requirements of §\s*74\.",
                                  self._section_text(section))):
                out.append("82.5")   # only a conformity listing, which the C82 composer answers from these texts
        return list(dict.fromkeys(out))

    # -- decision ---------------------------------------------------------------
    def named_companions(self, sections: list[str], question: str) -> list[str]:
        """Companions of sections the question names itself ("What does 82.1327 require?" -> 82.1050, the subpart's
        certification rule; "under § 710.4" -> 700.3(j)): the same rules as for a promoted section, no picker."""
        lex = SectionIndex.question_lexemes(self.db, question)
        out: list[str] = []
        for s in sections:
            out += [c for c in self.companions(s, question, lex) if c not in out and c not in sections]
        out += [c for c in self.definition_companions(question) if c not in out and c not in sections]
        if "70.5(a)" in out and any(_EYE_USE.search(self._section_text(s)) for s in sections):
            out.remove("70.5(a)")
        return out

    def siblings(self, picked: dict, cands: list[dict], lexemes) -> list[str]:
        """The same color listed elsewhere under the same heading (74.2254 / 82.1254 / 74.1254 "D&C Orange No. 4."): for
        a cosmetics question the Cosmetics-subpart listing and the Part 82 certification listing are both promoted, the
        Foods/Drugs/Devices listings only when the question names that kind of product."""
        if ENTITY_CONSTRAINTS:   # 74.1101 'FD&C Blue No. 1' and 74.2101 'FD&C Blue No. 1.' are one color
            from regulus.retrieval.entities import normalize_heading as norm
        else:
            norm = lambda h: (h or "").strip().lower()  # noqa: E731
        head = norm(picked["heading"])
        if picked["part"] not in COLOR_LISTING_PARTS or re.fullmatch(r"(?:general|definitions?|scope)\.?", head):
            return [picked["section"]]   # "General." in 82.50 / 82.1050 / 82.2050 names no color (code review)
        same = [c for c in cands if not c.get("statute") and c["part"] in COLOR_LISTING_PARTS
                and norm(c["heading"]) == head
                and not (picked["part"] == "82" and c["part"] == "82")]   # one color is listed once in Part 82
        lx = set(lexemes)
        wanted = {k for k, terms in _NON_COSMETIC_TERMS.items() if lx & terms}
        if cosmetic_question(lexemes) or not wanted:
            wanted.add("cosmetic")

        def keep(c):
            kind = _subpart_kind(c["subpart"])
            return c["part"] == "82" or kind is None or kind in wanted

        ordered = [picked] + [c for c in same if c["section"] != picked["section"]]
        chosen = [c["section"] for c in ordered if keep(c)] or [picked["section"]]
        return chosen[:2]

    def prepare(self, question: str, parts: tuple[str, ...] | None = None, named_only: bool = False,
                t0: float | None = None) -> Promotion | tuple[list[str], list[dict]] | None:
        """Everything resolve() decides before a pick: a Promotion of the FD&C Act section(s) the question names, None
        when nothing may be promoted, or (lexemes, candidates) to pick from. Deterministic (no model call): the
        section-resolution harness measures candidate generation through it."""
        t0 = time.perf_counter() if t0 is None else t0
        lex = SectionIndex.question_lexemes(self.db, question)
        named = self.named_statute(question, lex)
        if named:
            return self._statute_promotion(named[:2], lex, "named_statute", t0)
        if named_only:
            return None   # only a section the question names may be resolved here; nothing is guessed
        if parts and not all(p in COSMETIC_PARTS for p in parts):
            return None   # a part outside the cosmetics programme (or a misread statute number): never promoted into
        if parts and len({x for x in lex if not x.isdigit()} - _PART_QUESTION_WORDS - COSMETIC_TERMS_GENERIC) < 2:
            return None   # "What does Part 720 require?" asks about the whole part: not narrowed to one section
        lex, cands = self.candidates(question, parts)
        offer_statute = self.statute is not None and cosmetic_question(lex) and not parts
        if offer_statute:
            cands = cands[:CFR_CANDIDATES_WITH_STATUTE] + self.statute_candidates(lex, question)
        return (lex, cands) if cands else None

    def anchored(self, question: str, cfr: tuple[str, ...] = (), statute: tuple[str, ...] = ()) -> Promotion | None:
        """A follow-up resolved to the provisions its conversation is about (regulus.rag.conversation): those sections
        are promoted, method "conversation", with the companions this question's own words call for - no ranking, no
        picker. None when the question names an FD&C Act section itself or nothing anchored exists (the caller then
        resolves it as it would on its own); a cosmetic practice the regulations are silent on (P1) is answered as such."""
        if self.mode == "off":
            return None
        t0 = time.perf_counter()
        lex = SectionIndex.question_lexemes(self.db, question)
        if self.named_statute(question, lex):
            return None
        silence = self.practice_silence(question, lex, t0)
        if silence is not None:
            return silence
        known = [s for s in cfr if s in set(self.index.sections)]
        acts = [s for s in statute if self.statute is not None and s in self.statute.by_sec]
        if known:
            pr = self._cfr_promotion(known, question, lex, (), None, None, "conversation", t0)
            if acts:
                st = self._statute_promotion([(s, "") for s in acts[:1]], lex, "conversation", t0, budget=CO_STATUTE_BUDGET)
                pr = replace(pr, statute=st.statute, statute_rows=st.statute_rows, statute_blocks=st.statute_blocks,
                             statute_left_out=st.statute_left_out, seconds=time.perf_counter() - t0)
            return pr
        if acts:
            return self._statute_promotion([(s, "") for s in acts[:2]], lex, "conversation", t0)
        return None

    def statute_references(self, sections: list[str], limit: int = 2) -> list[tuple[str, str]]:
        """ST1: the FD&C Act sections (with the cited subsection) that these 21 CFR sections' own text cites - "section
        403(i) of the act", "sections 501 and 502 of the Federal Food, Drug, and Cosmetic Act" - that the Act store
        holds, in order of first citation, at most `limit`."""
        st = self.statute
        if st is None:
            return []
        out: list[tuple[str, str]] = []
        for sec in sections:
            for m in _ACT_CITED.finditer(self._section_text(sec)):
                for num, path in re.findall(r"(\d{3}[A-Za-z]?)((?:\([a-zA-Z0-9]{1,6}\))*)", m.group(1)):
                    if num in st.by_sec and num not in [x for x, _ in out]:
                        out.append((num, path))
                    if len(out) >= limit:
                        return out
        return out

    def statute_companions(self, question: str, sections: list[str]) -> Promotion | None:
        """ST1: the cited FD&C Act text as a companion of the regulation (method "statute_reference"), or None."""
        refs = self.statute_references(sections)
        if not refs:
            return None
        t0 = time.perf_counter()
        lex = SectionIndex.question_lexemes(self.db, question)
        return self._statute_promotion(refs, lex, "statute_reference", t0, budget=CO_STATUTE_BUDGET)

    def ranks_any(self, question: str, cfr: tuple[str, ...] = (), statute: tuple[str, ...] = (), top: int = 8) -> bool:
        """Whether the question's own words rank one of these sections among their first `top` candidates (no model
        call)."""
        # FD&C Act sections are not checked: the Act's general sections (601 adulteration) lead the ranking of most
        # cosmetics questions, so ranking says nothing about whether a question is about them
        if not cfr:
            return False
        lex, cands = self.candidates(question)
        return any(c["section"] in cfr for c in cands[:top])

    def heading_words(self, cfr: tuple[str, ...]) -> list[str]:
        """The headings of these sections (for the follow-up's shared-subject test)."""
        ix = self.index
        pos = {s: i for i, s in enumerate(ix.sections)}
        return [ix.headings[pos[s]] or "" for s in cfr if s in pos]

    def resolve(self, question: str, parts: tuple[str, ...] | None = None, named_only: bool = False) -> Promotion | None:
        """`parts`: the question names only these parts ("Under Part 82, ..."); the answer is looked for inside them."""
        if self.mode == "off":
            return None
        t0 = time.perf_counter()
        if self.mode == "picker" and not named_only and (self.generator is None or getattr(self.generator, "retrieval_only", False)):
            # no model to pick with (retrieval-only harness): nothing is promoted, nothing is ranked - except an FD&C
            # Act section the question names, which needs no pick
            lex = SectionIndex.question_lexemes(self.db, question)
            named = self.named_statute(question, lex)
            return self._statute_promotion(named[:2], lex, "named_statute", t0) if named else None
        prepared = self.prepare(question, parts, named_only, t0)
        if not isinstance(prepared, tuple):
            return prepared
        lex, cands = prepared
        raw, other, notes, second_act = None, None, (), None
        try:
            entity = self.entity_pick(question, lex, cands, parts) if ENTITY_CONSTRAINTS else None
        except Exception:  # noqa: BLE001 - an aid: without it the picker decides
            entity = None
        if entity is not None:
            return self._cfr_promotion(entity, question, lex, cands, None, None, "entity", t0)
        silence = self.practice_silence(question, lex, t0)
        if silence is not None:
            return silence
        if self.mode == "lexical":
            first = next((c for c in cands if not c.get("statute")), None)
            if first is None:
                return None
            picked_c = first
        else:
            if self.generator is None or getattr(self.generator, "retrieval_only", False):
                return None   # no model to pick with (retrieval-only harness): nothing is promoted
            msgs = [{"role": "system", "content": PICKER_SYSTEM}, {"role": "user", "content": picker_prompt(question, cands)}]
            kw = {"think_budget": PICKER_THINK_BUDGET} if getattr(self.generator, "thinking", False) is True else {}
            result = self.generator.generate(msgs, max_new_tokens=PICKER_MAX_TOKENS, **kw)
            raw = (getattr(result, "response", None) or "").strip()
            picks = parse_picks(raw, len(cands), [c["section"] for c in cands])
            if not picks:
                return None
            picked_c = cands[picks[0] - 1]   # first choice; a second choice is used only from the other corpus
            other = next((cands[i - 1] for i in picks[1:] if bool(cands[i - 1].get("statute")) != bool(picked_c.get("statute"))), None)
            if SECOND_ACT and picked_c.get("statute"):
                # "FD&C Act § 604, FD&C Act § 605": both Act sections, the Act budget shared (605-Q2 lost 605 to 604)
                second_act = next((cands[i - 1] for i in picks[1:] if cands[i - 1].get("statute")
                                   and cands[i - 1]["section"] != picked_c["section"]), None)
            if RERANKER:
                vetoed = self.rerank_veto(question, cands, picked_c)
                if vetoed is not None:
                    notes = (f"rerank veto: {picked_c['section']} -> {vetoed['section']}",)
                    picked_c, other = vetoed, (None if other is not None and other["section"] == vetoed["section"] else other)
        if picked_c.get("statute"):
            acts = [(picked_c["section"], "")] + ([(second_act["section"], "")] if second_act is not None
                                                  and second_act["section"] != picked_c["section"] else [])
            pr = self._statute_promotion(acts, lex, self.mode, t0, cands, raw)
            if other is not None:   # FD&C Act section first, a regulation second: the regulation is promoted with it
                sec = self.siblings(other, cands, lex)
                comps = [c for s in sec for c in self.companions(s, question, lex)]
                pr = replace(pr, sections=tuple(sec), companions=tuple(dict.fromkeys(c for c in comps if c not in sec)))
            return replace(pr, notes=pr.notes + notes)
        pr = self._cfr_promotion(self.siblings(picked_c, cands, lex), question, lex, cands, raw, other, self.mode, t0)
        return replace(pr, notes=pr.notes + notes) if notes else pr

    def _cfr_promotion(self, picked: list[str], question: str, lex, cands, raw, other, method: str, t0: float) -> Promotion:
        """The Promotion of picked regulation(s): their companions, and a second FD&C Act pick as co-statute."""
        comps: list[str] = []
        for s in picked:
            comps += [c for c in self.companions(s, question, lex) if c not in comps]
        comps += [c for c in self.definition_companions(question) if c not in comps and c not in picked]
        if "70.5(a)" in comps and any(_EYE_USE.search(self._section_text(s)) for s in picked):
            comps.remove("70.5(a)")   # one promoted listing provides for eye-area use (code review: Part 82 sibling)
        if other is not None and other.get("statute"):
            # a regulation first and an FD&C Act section second (registration rule 710 with Act 607): both, the Act text
            # as additional evidence with a smaller budget (retrieval diagnosis: 11 unseen questions need both)
            st = self._statute_promotion([(other["section"], "")], lex, method, t0, (), None, budget=CO_STATUTE_BUDGET)
            return Promotion(sections=tuple(picked), companions=tuple(c for c in comps if c not in picked), method=method,
                             statute=st.statute, statute_rows=st.statute_rows, statute_blocks=st.statute_blocks,
                             statute_left_out=st.statute_left_out, candidates=tuple(cands), picker_output=raw,
                             seconds=time.perf_counter() - t0)
        return Promotion(sections=tuple(picked), companions=tuple(c for c in comps if c not in picked), method=method,
                         candidates=tuple(cands), picker_output=raw, seconds=time.perf_counter() - t0)
