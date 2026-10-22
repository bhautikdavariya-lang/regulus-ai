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

import re
import time
from dataclasses import dataclass, field, replace
from typing import Any

from regulus.retrieval.section_index import COSMETIC_PARTS, SectionIndex, cosmetic_question, section_index
from regulus.retrieval.statute import BLOCK_HEADER_CHARS, StatuteIndex, statute_index

MODES = ("off", "lexical", "picker")
CANDIDATES = 22
CFR_CANDIDATES_WITH_STATUTE = 20
LEXICAL_CANDIDATES = 16   # cosmetics questions: lexical candidates fused with ...
DENSE_CANDIDATES = 12     # ... the dense top 12 (regulus.retrieval.section_dense)
RRF_K = 10
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
PICKER_MAX_TOKENS = 16
DEFINITIONS_SECTION = "604"                                    # FD&C Act 604: "In this subchapter:" definitions
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

    def statute_candidates(self, lexemes) -> list[dict]:
        st = self.statute
        if st is None:
            return []
        ranked = {r.fdca: r for r in st.rank(lexemes, limit=len(st.by_sec))}
        out = []
        for s in STATUTE_OFFERED:
            if s not in st.by_sec:
                continue
            r = ranked.get(s)
            row = st.rows[r.best if r else st.by_sec[s][0]]
            out.append({"statute": True, "section": s, "usc": st.usc(s), "heading": st.heading(s), "part": "FDCA",
                        "subpart": "", "part_title": "", "score": round(r.score, 4) if r else 0.0,
                        # the section's own subsection captions: what it covers (retrieval diagnosis, 22 Oct)
                        "snippet": st.outline(s) or " ".join(row["body_text"].split())[:SNIPPET_CHARS]})
        return out

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
            if sub:   # "subpart C of Part 82": that subpart's sections only (retrieval diagnosis: parser)
                in_sub = [r for r in ranked if (r.subpart or "").lower().startswith(f"subpart {sub.group(1).lower()} ")]
                ranked = in_sub or ranked
            ranked = ranked[:self.limit]
        elif cosmetic_question(lex):
            # a cosmetics question: candidates from the color-additive and cosmetic parts only. Food, feed and device
            # sections were picked for cosmetics questions (117.251, 111.455, 226.30; 22 Oct); on the 277-question bank
            # the restriction loses no key section and adds 3 to the candidate lists
            ranked = [r for r in self.index.rank(lex, limit=400) if r.part in COSMETIC_PARTS][:LEXICAL_CANDIDATES]
            ranked = self._fuse_dense(question, ranked)
        else:
            ranked = self.index.rank(lex, limit=self.limit)
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
        head = (picked["heading"] or "").strip().lower()
        if picked["part"] not in COLOR_LISTING_PARTS or re.fullmatch(r"(?:general|definitions?|scope)\.?", head):
            return [picked["section"]]   # "General." in 82.50 / 82.1050 / 82.2050 names no color (code review)
        same = [c for c in cands if not c.get("statute") and c["part"] in COLOR_LISTING_PARTS
                and (c["heading"] or "").strip().lower() == head
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

    def resolve(self, question: str, parts: tuple[str, ...] | None = None, named_only: bool = False) -> Promotion | None:
        """`parts`: the question names only these parts ("Under Part 82, ..."); the answer is looked for inside them."""
        if self.mode == "off":
            return None
        t0 = time.perf_counter()
        lex = SectionIndex.question_lexemes(self.db, question)
        named = self.named_statute(question, lex)
        if named:
            return self._statute_promotion(named[:2], lex, "named_statute", t0)
        if named_only:
            return None   # only a section the question names may be resolved here; nothing is guessed
        if self.mode == "picker" and (self.generator is None or getattr(self.generator, "retrieval_only", False)):
            return None   # no model to pick with (retrieval-only harness): nothing is promoted, nothing is ranked
        if parts and not all(p in COSMETIC_PARTS for p in parts):
            return None   # a part outside the cosmetics programme (or a misread statute number): never promoted into
        if parts and len({x for x in lex if not x.isdigit()} - _PART_QUESTION_WORDS - COSMETIC_TERMS_GENERIC) < 2:
            return None   # "What does Part 720 require?" asks about the whole part: not narrowed to one section
        lex, cands = self.candidates(question, parts)
        offer_statute = self.statute is not None and cosmetic_question(lex) and not parts
        if offer_statute:
            cands = cands[:CFR_CANDIDATES_WITH_STATUTE] + self.statute_candidates(lex)
        if not cands:
            return None
        raw, other = None, None
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
        if picked_c.get("statute"):
            pr = self._statute_promotion([(picked_c["section"], "")], lex, self.mode, t0, cands, raw)
            if other is not None:   # FD&C Act section first, a regulation second: the regulation is promoted with it
                sec = self.siblings(other, cands, lex)
                comps = [c for s in sec for c in self.companions(s, question, lex)]
                pr = replace(pr, sections=tuple(sec), companions=tuple(dict.fromkeys(c for c in comps if c not in sec)))
            return pr
        picked = self.siblings(picked_c, cands, lex)
        comps: list[str] = []
        for s in picked:
            comps += [c for c in self.companions(s, question, lex) if c not in comps]
        comps += [c for c in self.definition_companions(question) if c not in comps and c not in picked]
        if "70.5(a)" in comps and any(_EYE_USE.search(self._section_text(s)) for s in picked):
            comps.remove("70.5(a)")   # one promoted listing provides for eye-area use (code review: Part 82 sibling)
        if other is not None and other.get("statute"):
            # a regulation first and an FD&C Act section second (registration rule 710 with Act 607): both, the Act text
            # as additional evidence with a smaller budget (retrieval diagnosis: 11 unseen questions need both)
            st = self._statute_promotion([(other["section"], "")], lex, self.mode, t0, (), None, budget=CO_STATUTE_BUDGET)
            return Promotion(sections=tuple(picked), companions=tuple(c for c in comps if c not in picked), method=self.mode,
                             statute=st.statute, statute_rows=st.statute_rows, statute_blocks=st.statute_blocks,
                             statute_left_out=st.statute_left_out, candidates=tuple(cands), picker_output=raw,
                             seconds=time.perf_counter() - t0)
        return Promotion(sections=tuple(picked), companions=tuple(c for c in comps if c not in picked), method=self.mode,
                         candidates=tuple(cands), picker_output=raw, seconds=time.perf_counter() - t0)
