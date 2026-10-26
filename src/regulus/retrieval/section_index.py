"""Section-level ranking of eCFR sections for a question that names no provision.

Why this exists (cosmetics benchmark, 22 Oct): for general questions the lexical legs rank paragraphs, and the
section that answers the question reached the prompt for 28 of 80 keyed questions. Ranking whole SECTIONS instead -
BM25 over each section's live paragraphs, its heading counted three times, plus the share of the question its best
paragraph covers and how much of its specific heading the question names - puts the key section in the top 4 for
39/80 (seen) and 76/143 (unseen bank questions); a product-domain prior (below) raises that to 43/80 and 88/143.

Tokens are PostgreSQL's own ('english' to_tsvector), exactly what the production full-text legs match on. The index
is built once per process from the live rows (removed and reserved rows excluded) and scored with numpy; it holds
lexeme ids only, never text.

Domain prior: a question that names a cosmetic product or a color-additive term (COSMETIC_TERMS, built from the
product categories of 21 CFR 720.4(c)) gets the color-additive parts (70-82) and the cosmetic parts (700-740)
weighted up, and in Parts 73/74 the Cosmetics subpart preferred over the Foods/Drugs/Devices listings of the same
color, which share its heading word for word. A question without such a word is ranked without any prior.
"""
from __future__ import annotations

import contextlib
import contextvars

import math
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

K1, B, HEAD_TF = 1.2, 0.75, 3.0
TF_CAP = 3
# heading words that say nothing about what a section is specifically about
GENERIC_HEAD = frozenset({"gener", "definit", "scope", "purpos", "applic", "requir", "provis", "subpart", "use", "label",
                          "provid", "color", "addit", "cosmet", "exempt", "certif", "list", "specif", "restrict", "limit"})
COSMETIC_PARTS = frozenset({"70", "71", "73", "74", "80", "81", "82", "700", "701", "710", "720", "740"})
# stemmed ('english') product and programme words; product names are the categories of 21 CFR 720.4(c)
COSMETIC_TERMS = frozenset("""lotion cream shampoo lipstick lip balm mascara eyelin eyebrow shadow blush roug nail polish
lacquer enamel cuticl perfum fragranc cologn deodor antiperspir hair dye tint makeup foundat soap bath skin skincar serum
moistur toothpast dentifric mouthwash salon beauti scrub cosmet colorant pigment lake 2511 2512 mocra shave aftershav
sunless tan bronzer gloss condition wave straighten depilatori talc babi cleanser toner facial manicur pedicur glitter
shimmer mica tattoo henna spa butter fd color mask peel primer relax perm eyeshadow kohl kajal wax""".split())
DOMAIN_WEIGHT = 1.6
COSMETIC_SUBPART_WEIGHT, OTHER_SUBPART_WEIGHT = 1.3, 0.8

_ROWS_SQL = """
SELECT r.section_number, r.part_number, r.ordinal,
       COALESCE((SELECT h FROM unnest(r.parent_headings) h WHERE lower(h) LIKE 'subpart%%' LIMIT 1), '') AS subpart,
       r.section_heading,
       tsvector_to_array(to_tsvector('english', COALESCE(r.body_text, ''))) AS body,
       tsvector_to_array(to_tsvector('english', COALESCE(r.section_heading, ''))) AS head
FROM cfr_records r
WHERE r.removed_on IS NULL AND NOT r.is_reserved
ORDER BY r.section_number, r.ordinal
"""
_QUERY_SQL = "SELECT tsvector_to_array(to_tsvector('english', %(q)s)) AS lex"


@dataclass(frozen=True)
class RankedSection:
    section: str
    part: str
    heading: str
    subpart: str
    score: float
    best_ordinal: int       # the section's paragraph that covers most of the question (its snippet)

    def to_dict(self) -> dict[str, Any]:
        return {"section": self.section, "part": self.part, "heading": self.heading, "subpart": self.subpart,
                "score": round(self.score, 4), "best_ordinal": self.best_ordinal}


@dataclass
class SectionIndex:
    sections: list[str]
    parts: list[str]
    headings: list[str]
    subparts: list[str]
    vocab: dict[str, int]
    row_section: np.ndarray                 # row -> section index
    row_ordinal: np.ndarray                 # row -> cfr_records.ordinal
    inv_rows: dict[int, np.ndarray]         # lexeme -> rows whose body contains it
    inv_head: dict[int, np.ndarray]         # lexeme -> sections whose heading contains it
    idf: np.ndarray                         # lexeme -> BM25 idf at section level
    sec_len: np.ndarray                     # distinct body lexemes per section
    head_specific: np.ndarray               # specific (non-generic) heading lexemes per section
    generic_ids: frozenset[int] = field(default_factory=frozenset)

    # -- build -------------------------------------------------------------
    @classmethod
    def from_rows(cls, rows) -> "SectionIndex":
        vocab: dict[str, int] = {}

        def lid(lex: str) -> int:
            return vocab.setdefault(lex, len(vocab))

        sec_ix: dict[str, int] = {}
        sections, parts, headings, subparts = [], [], [], []
        row_section, row_lex, row_ordinal = [], [], []
        head_lex: dict[int, set[int]] = {}
        for r in rows:
            s = r["section_number"]
            if s not in sec_ix:
                sec_ix[s] = len(sections)
                sections.append(s); parts.append(r["part_number"] or ""); headings.append(r["section_heading"] or "")
                subparts.append(r["subpart"] or "")
            i = sec_ix[s]
            head_lex.setdefault(i, set()).update(lid(x) for x in (r["head"] or ()))
            row_section.append(i)
            row_ordinal.append(int(r["ordinal"]))
            row_lex.append({lid(x) for x in (r["body"] or ())})
        n_sec, n_lex = len(sections), len(vocab)
        inv_rows_l: dict[int, list[int]] = {}
        sec_body: list[set[int]] = [set() for _ in range(n_sec)]
        for ri, lexes in enumerate(row_lex):
            si = row_section[ri]
            sec_body[si].update(lexes)
            for x in lexes:
                inv_rows_l.setdefault(x, []).append(ri)
        inv_head_l: dict[int, list[int]] = {}
        for si, lexes in head_lex.items():
            for x in lexes:
                inv_head_l.setdefault(x, []).append(si)
        df = np.zeros(n_lex)
        for si in range(n_sec):
            for x in sec_body[si] | head_lex.get(si, set()):
                df[x] += 1
        idf = np.log(1 + (n_sec - df + 0.5) / (df + 0.5))
        generic = frozenset(vocab[g] for g in GENERIC_HEAD if g in vocab)
        return cls(
            sections=sections, parts=parts, headings=headings, subparts=subparts, vocab=vocab,
            row_section=np.asarray(row_section, dtype=np.int32),
            row_ordinal=np.asarray(row_ordinal, dtype=np.int32),
            inv_rows={k: np.asarray(v, dtype=np.int32) for k, v in inv_rows_l.items()},
            inv_head={k: np.asarray(v, dtype=np.int32) for k, v in inv_head_l.items()},
            idf=idf, sec_len=np.asarray([len(b) for b in sec_body], dtype=np.float64),
            head_specific=np.asarray([len(head_lex.get(i, set()) - generic) for i in range(n_sec)], dtype=np.float64),
            generic_ids=generic,
        )

    @classmethod
    def from_db(cls, db) -> "SectionIndex":
        return cls.from_rows(db.query(_ROWS_SQL))

    # -- query -------------------------------------------------------------
    @staticmethod
    def question_lexemes(db, question: str) -> list[str]:
        return list(db.query(_QUERY_SQL, {"q": question or ""})[0]["lex"] or [])

    def rank(self, lexemes, *, limit: int = 20, domain_prior: bool = True) -> list[RankedSection]:
        q = sorted({self.vocab[x] for x in lexemes if x in self.vocab})
        if not q:
            return []
        n_sec, n_rows = len(self.sections), len(self.row_section)
        avg = float(self.sec_len.mean()) or 1.0
        bm25 = np.zeros(n_sec); head_hits = np.zeros(n_sec); row_cov = np.zeros(n_rows); head_cov = np.zeros(n_sec)
        touched = np.zeros(n_sec, dtype=bool)
        for x in q:
            w = float(self.idf[x])
            rows = self.inv_rows.get(x)
            tf = np.bincount(self.row_section[rows], minlength=n_sec).astype(np.float64) if rows is not None else np.zeros(n_sec)
            tf = np.minimum(tf, TF_CAP)
            heads = self.inv_head.get(x)
            if heads is not None:
                tf[heads] += HEAD_TF
                head_cov[heads] += w
                if x not in self.generic_ids:
                    head_hits[heads] += 1
            if rows is not None:
                row_cov[rows] += w
            nz = tf > 0
            touched |= nz
            bm25[nz] += w * tf[nz] * (K1 + 1) / (tf[nz] + K1 * (1 - B + B * self.sec_len[nz] / avg))
        total = float(self.idf[q].sum()) or 1.0
        full = row_cov + head_cov[self.row_section]
        best = np.zeros(n_sec)
        np.maximum.at(best, self.row_section, full)
        best /= total
        # each section's best row: rows by coverage (descending, document order on ties), first per section
        by_cov = np.lexsort((np.arange(n_rows), -full))
        secs_sorted, first = np.unique(self.row_section[by_cov], return_index=True)
        best_row = np.full(n_sec, -1, dtype=np.int64)
        best_row[secs_sorted] = by_cov[first]
        hm = np.divide(head_hits, self.head_specific, out=np.zeros(n_sec), where=self.head_specific > 0)
        score = bm25 / 10 + best + 1.0 * (hm >= 1.0) + 0.5 * hm
        if domain_prior and cosmetic_question(lexemes):
            score *= self._cosmetic_weights()
        idx = np.flatnonzero(touched)
        order = idx[np.lexsort((np.asarray([self.sections[i] for i in idx]), -score[idx]))][:limit]
        return [RankedSection(self.sections[i], self.parts[i], self.headings[i], self.subparts[i], float(score[i]),
                              int(self.row_ordinal[best_row[i]]) if best_row[i] >= 0 else 0)
                for i in order]

    def _cosmetic_weights(self) -> np.ndarray:
        cached = getattr(self, "_cos_w", None)
        if cached is None:
            w = np.ones(len(self.sections))
            for i, (p, sp) in enumerate(zip(self.parts, self.subparts)):
                if p in COSMETIC_PARTS:
                    w[i] *= DOMAIN_WEIGHT
                if p in ("73", "74") and sp:
                    w[i] *= COSMETIC_SUBPART_WEIGHT if "cosmetic" in sp.lower() else OTHER_SUBPART_WEIGHT
            self._cos_w = cached = w
        return cached


# other product domains (stemmed): a question naming one of these is not treated as a cosmetics question by scope alone
OTHER_DOMAIN_TERMS = frozenset("""food beverag infant formula dietari supplement drug tablet capsul prescript devic implant
sutur tobacco cigarett vape nicotin biolog vaccin blood plasma tissu feed anim pet veterinari pesticid medic""".split())


# the focus one request asked for (the page's "Focus" control: "cosmetics" or "general"), over the deployment's own
FOCUSES = ("cosmetics", "general")
_FOCUS: contextvars.ContextVar[str | None] = contextvars.ContextVar("regulus_focus", default=None)


@contextlib.contextmanager
def focus(value: str | None):
    """Answer inside this block with `value` as the deployment scope ("general": no cosmetics prior); None leaves the
    deployment's own (REGULUS_DEPLOYMENT_SCOPE). Per thread and per context, so concurrent requests never mix."""
    if value is not None and value not in FOCUSES:
        raise ValueError(f"focus must be one of {', '.join(FOCUSES)}")
    token = _FOCUS.set(value)
    try:
        yield
    finally:
        _FOCUS.reset(token)


def deployment_scope() -> str | None:
    """REGULUS_DEPLOYMENT_SCOPE: "cosmetics" for a deployment that answers cosmetics questions (the cosmetics
    benchmark, a cosmetics-compliance UI); unset for general FDA use. A request's own focus (see `focus`) wins."""
    import os

    asked = _FOCUS.get()
    if asked is not None:
        return None if asked == "general" else asked
    value = (os.environ.get("REGULUS_DEPLOYMENT_SCOPE") or "").strip().lower()
    return value or None


def cosmetic_question(lexemes) -> bool:
    """A question about cosmetics: it names a cosmetic product or programme word, or - in a cosmetics deployment
    (REGULUS_DEPLOYMENT_SCOPE=cosmetics) - it names no other product domain ("What must our registration include?").
    On the bank, 35 of 277 questions name no product word; in a general deployment they are ranked without the prior."""
    lx = set(lexemes)
    if lx & COSMETIC_TERMS:
        return True
    return deployment_scope() == "cosmetics" and not (lx & OTHER_DOMAIN_TERMS)


_LOCK = threading.Lock()
_CACHE: dict[int, SectionIndex] = {}


def section_index(db) -> SectionIndex:
    """One index per Database object (built on first use, ~1 query over the live eCFR rows)."""
    key = id(db)
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = SectionIndex.from_db(db)
        return _CACHE[key]
