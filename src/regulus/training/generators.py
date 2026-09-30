"""Deterministic question -> context -> answer generators.

Every answer is assembled from verbatim database text plus fixed templates;
no language model is involved. Each generator returns *candidates* for one
category; the pipeline de-duplicates, excludes benchmark look-alikes and
applies the per-category caps.

Citation markers: answers refer to context items as [1], [2] ... in the order
they appear in `context`, matching the Stage 6 RAG prompt's convention, so a
fine-tuned model produces the same markers the RAG pipeline expects.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from regulus.training.config import TrainingConfig
from regulus.training.models import ContextItem, TrainingExample
from regulus.training.sources import Corpus, GuidanceChunk, GuidanceDoc, Record, Section
from regulus.training.text import (
    clean,
    find_sentence_with,
    has_footnote_artifact,
    heading_topic,
    is_clean_paragraph,
    is_list_intro,
    leadin,
    pick,
    quote,
    sentences,
    stable_hash,
    strip_label,
    word_set,
)

SCOPE_HEADING_RE = re.compile(r"^(scope|purpose|applicability|scope and (purpose|applicability|application)|purpose and scope|general|applicability and scope)\b", re.IGNORECASE)
DEFINITIONS_HEADING_RE = re.compile(r"^definitions?\b", re.IGNORECASE)
SCOPE_SENTENCE_RE = re.compile(
    r"This (?:draft )?guidance(?: document)? (?:is intended to|provides|describes|addresses|explains|outlines|discusses|clarifies|assists|establishes|announces|applies to|covers)\b"
)
RECOMMENDS_RE = re.compile(r"\bFDA recommends\b")
REQUIRES_RE = re.compile(r"\b(shall|must|required|require|requires)\b", re.IGNORECASE)

NONBINDING = (
    "This is FDA guidance: it represents the agency's current thinking and contains non-binding recommendations; "
    "it is not a legally binding regulation."
)
NONBINDING_SHORT = "This is a non-binding FDA guidance recommendation, not a requirement of the eCFR."
MAX_EXCERPT_CHARS = 1200
MAX_SCOPE_EXCERPT_CHARS = 1500


def marks(n: int, start: int = 1) -> str:
    if n <= 3:
        return ", ".join(f"[{i}]" for i in range(start, start + n))
    return f"[{start}]-[{start + n - 1}]"


# ------------------------------------------------------------- context items


def ecfr_context(corpus: Corpus, rec: Record) -> ContextItem:
    sec = corpus.sections.get(rec.section)
    sp = corpus.subpart_of(sec) if sec else None
    return ContextItem(
        source_type="ecfr",
        citation=rec.citation,
        text=clean(rec.text),
        url=rec.url,
        part=rec.part,
        part_title=corpus.part_title(rec.part),
        subpart=sp.designation if sp else None,
        section=rec.section,
        paragraph=rec.paragraph or None,
        heading=rec.heading,
        source_key=rec.key,
    )


def guidance_context(doc: GuidanceDoc, chunk: GuidanceChunk) -> ContextItem:
    return ContextItem(
        source_type="fda_guidance",
        citation=doc.citation,
        text=clean(chunk.text),
        url=doc.url,
        document_title=doc.title,
        docket_number=doc.docket,
        status=doc.status,
        issued_on=doc.issued_on,
        center=doc.center,
        source_key=doc.chunk_key(chunk),
    )


def hierarchy_context(corpus: Corpus, *, citation: str, text: str, key: str, part: str, subpart: str | None = None, section: str | None = None, heading: str | None = None) -> ContextItem:
    p = corpus.parts.get(part)
    return ContextItem(
        source_type="ecfr_hierarchy",
        citation=citation,
        text=text,
        url=p.url if p else None,
        part=part,
        part_title=p.title if p else None,
        subpart=subpart,
        section=section,
        heading=heading,
        source_key=key,
    )


# --------------------------------------------------------------- selection


def section_excerpt(section: Section, max_chars: int, min_chars: int) -> tuple[list[Record], bool]:
    """Leading records of a section that fit in max_chars, ending on a whole
    record and never on a list introduction. Returns (records, complete)."""
    chosen: list[Record] = []
    used = 0
    for rec in section.records:
        t = clean(rec.text)
        if rec.is_reserved or not t or "[reserved]" in t.lower():
            if not chosen:
                return [], False
            break
        if used + len(t) + (1 if chosen else 0) > max_chars:
            break
        chosen.append(rec)
        used += len(t) + (1 if len(chosen) > 1 else 0)
    while chosen and is_list_intro(chosen[-1].text):
        chosen.pop()
    if not chosen or used < min_chars:
        return [], False
    complete = len(chosen) == len(section.records)
    text = " ".join(clean(r.text) for r in chosen)
    if not is_clean_paragraph(text, min_chars, max_chars):
        return [], False
    return chosen, complete


def excerpt_text(records: list[Record]) -> str:
    return " ".join(clean(r.text) for r in records)


def part_scope_section(corpus: Corpus, part: str) -> Section | None:
    p = corpus.parts.get(part)
    if not p:
        return None
    for num in p.sections:
        sec = corpus.sections.get(num)
        if sec and not sec.is_reserved and sec.heading and SCOPE_HEADING_RE.match(sec.heading.strip()) and sec.records:
            return sec
    return None


def _part_intro(corpus: Corpus, part: str) -> str:
    p = corpus.parts[part]
    sub = corpus.subchapter_of_part(part)
    where = f" and is part of Subchapter {sub.code} ({sub.title}) of Title 21" if sub and sub.title else ""
    return f'21 CFR Part {part} is titled {quote(p.title)}{where}' if p.title else f"21 CFR Part {part} is in Title 21{where}"


def _live_sections(corpus: Corpus) -> list[Section]:
    return [s for _, s in sorted(corpus.sections.items()) if not s.is_reserved and s.records and s.heading]


# ------------------------------------------------------------ A. direct CFR


def gen_direct_cfr(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    out: list[TrainingExample] = []
    # Part-level: the part's own scope section is the evidence.
    for number, part in sorted(corpus.parts.items()):
        if part.is_reserved or not part.title:
            continue
        scope = part_scope_section(corpus, number)
        if scope is None:
            continue
        recs, complete = section_excerpt(scope, MAX_SCOPE_EXCERPT_CHARS, q.min_paragraph_chars)
        if not recs:
            continue
        ctx = [ecfr_context(corpus, r) for r in recs]
        verb = "provides" if complete else "begins"
        question = pick(
            [
                f"What does 21 CFR Part {number} cover?",
                f"What is the scope of 21 CFR Part {number}?",
                f"What is 21 CFR Part {number} about?",
                f"Which subject does 21 CFR Part {number}, {quote(part.title)}, regulate?",
                f"What is the purpose of 21 CFR Part {number}?",
            ],
            "direct_part", number,
        )
        answer = f"{_part_intro(corpus, number)}. Its scope is set out in {scope.citation} {marks(len(recs))}, which {verb}: {excerpt_text(recs)}"
        out.append(TrainingExample("regulatory_qa", "direct_cfr", question, ctx, answer, [c.citation for c in ctx], True, "direct_cfr/part/v1", f"ecfr:{scope.number}", corpus.snapshot_date, {"subtype": "part"}))
    # Section-level.
    for sec in _live_sections(corpus):
        if DEFINITIONS_HEADING_RE.match(sec.heading.strip()):
            continue  # definitions are covered by their own category
        recs, complete = section_excerpt(sec, MAX_EXCERPT_CHARS, q.min_paragraph_chars)
        if not recs:
            continue
        ctx = [ecfr_context(corpus, r) for r in recs]
        topic = heading_topic(sec.heading)
        part_title = corpus.part_title(sec.part)
        where = f" in 21 CFR Part {sec.part} ({part_title})" if part_title else f" in 21 CFR Part {sec.part}"
        verb = "provides" if complete else "begins"
        options = [
            f"What does {sec.citation} cover?",
            f"What is the purpose of {sec.citation}?",
            f"What does {sec.citation}, {quote(sec.heading)}, provide?",
            f"Summarize {sec.citation}.",
        ]
        if topic:
            options.append(f"What does 21 CFR {sec.number} say about {topic}?")
        question = pick(options, "direct_section", sec.number)
        answer = f"{sec.citation} {marks(len(recs))}, {quote(sec.heading)}, is{where}. It {verb}: {excerpt_text(recs)}"
        out.append(TrainingExample("regulatory_qa", "direct_cfr", question, ctx, answer, [c.citation for c in ctx], True, "direct_cfr/section/v1", f"ecfr:{sec.number}", corpus.snapshot_date, {"subtype": "section"}))
    return out


# ---------------------------------------------------- B. section / paragraph


def gen_section_paragraph(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    out: list[TrainingExample] = []
    for sec in _live_sections(corpus):
        cands = [r for r in sec.records if r.paragraph and is_clean_paragraph(r.text, q.min_paragraph_chars, q.max_paragraph_chars)]
        cands = sorted(cands, key=lambda r: _order_key("para", r.key))[: q.max_paragraph_examples_per_section]
        topic = heading_topic(sec.heading)
        for rec in cands:
            lead, rest = leadin(rec.text)
            para = rec.paragraph
            ctx = [ecfr_context(corpus, rec)]
            requires = bool(REQUIRES_RE.search(rest))
            verb_q = "require" if requires else "provide"
            if lead and len(lead.split()) >= 2:
                lead_low = lead[0].lower() + lead[1:]
                question = pick(
                    [
                        f"What does {sec.citation} say about {lead_low}?",
                        f"What does {rec.citation}, {quote(lead)}, {verb_q}?",
                        f"Under {sec.citation}, what does paragraph {para} {verb_q} regarding {lead_low}?",
                    ],
                    "para_lead", rec.key,
                )
                answer = f"{rec.citation} [1] ({quote(lead)}) provides: {rest}"
            else:
                body = strip_label(rec.text)
                options = [f"Under {sec.citation}, {quote(sec.heading)}, what does paragraph {para} {verb_q}?", f"What does paragraph {para} of 21 CFR {sec.number} state?"]
                if topic:
                    options.append(f"What does {rec.citation} {verb_q} regarding {topic}?")
                question = pick(options, "para_plain", rec.key)
                answer = f"{rec.citation} [1], in the section on {topic}, provides: {body}" if topic else f"{rec.citation} [1] provides: {body}"
            out.append(TrainingExample("regulatory_qa", "section_paragraph", question, ctx, answer, [rec.citation], True, "section_paragraph/v1", f"ecfr:{sec.number}", corpus.snapshot_date, {"subtype": "leadin" if lead else "plain"}))
    return out


_QUOTE_CHARS = "\"“”‘’'"
_DEF_LEAD_RE = re.compile(r"^(?:the terms? )?(?P<term>.+?),?\s+(?P<verb>means?|has the (?:same )?meaning|have the meaning|includes?|is|are|refers? to)\b(?P<rest>.*)$", re.IGNORECASE | re.DOTALL)


def _strip_quotes(text: str) -> str:
    return clean("".join(ch for ch in text if ch not in _QUOTE_CHARS))


def _plain_term(term: str) -> str:
    return _strip_quotes(term)


def definition_answer(citation: str, term: str, body: str) -> str | None:
    """Answer text when `body` (label and quotes removed) is a definition of `term`; else None."""
    m = _DEF_LEAD_RE.match(body)
    if not m or m.group("term").strip().lower() != term.lower():
        return None
    verb, rest = m.group("verb").lower(), m.group("rest").rstrip()
    if not any(ch.isalpha() for ch in rest):
        return None  # "Act means:" is a list introduction, not a definition
    if verb.startswith("mean"):
        return f"Under {citation} [1], {quote(term)} means{rest}"
    if "meaning" in verb:
        return f"Under {citation} [1], {quote(term)} {verb}{rest}"
    return f"{citation} [1] defines {quote(term)} as follows: {body}"


def _order_key(*parts: str) -> str:
    return stable_hash(*parts)


# ------------------------------------------------------------ C. definitions


def gen_definitions(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    out: list[TrainingExample] = []
    per_section: Counter[str] = Counter()
    for d in sorted(corpus.definitions, key=lambda d: (_order_key("def", d.record.key, d.term))):
        rec = d.record
        term = _plain_term(d.term)
        if not term or len(term) > 80 or not is_clean_paragraph(rec.text, 30, q.max_paragraph_chars):
            continue
        body = _strip_quotes(strip_label(rec.text))
        answer = definition_answer(rec.citation, term, body)
        if answer is None:
            continue
        if per_section[rec.section] >= q.max_definition_examples_per_section:
            continue
        per_section[rec.section] += 1
        question = pick(
            [
                f"What does {quote(term)} mean under 21 CFR {rec.section}?",
                f"How does 21 CFR Part {rec.part} define {quote(term)}?",
                f"Define {quote(term)} as used in 21 CFR {rec.section}.",
                f"Under 21 CFR {rec.section}, what is the definition of {quote(term)}?",
            ],
            "definition", rec.key, term,
        )
        out.append(TrainingExample("regulatory_qa", "definition", question, [ecfr_context(corpus, rec)], answer, [rec.citation], True, "definition/v1", f"ecfr:{rec.section}", corpus.snapshot_date, {"subtype": "definition", "term": term}))
    return out


# ---------------------------------------------------------- D. relationships


def _section_list(corpus: Corpus, numbers: list[str]) -> list[Section]:
    return [corpus.sections[n] for n in numbers if n in corpus.sections and not corpus.sections[n].is_reserved]


def gen_relationships(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    out: list[TrainingExample] = []
    snap = corpus.snapshot_date

    # 1. subpart -> sections
    for sp_id, sp in sorted(corpus.subparts.items(), key=lambda kv: (kv[1].part, kv[1].sort_order, kv[1].designation)):
        secs = _section_list(corpus, sp.sections)
        part = corpus.parts.get(sp.part)
        if not part or not part.title or not sp.title or "reserved" in sp.title.lower() or not (2 <= len(secs) <= 40):
            continue
        listing = "; ".join(f"§ {s.number} {s.heading or ''}".strip() for s in secs)
        sub = corpus.subchapter_of_part(sp.part)
        sub_txt = f"Subchapter {sub.code} ({sub.title}); " if sub and sub.title else ""
        text = f"Title 21, Chapter I; {sub_txt}Part {sp.part} ({part.title}); Subpart {sp.designation} ({sp.title}). Sections: {listing}."
        citation = f"21 CFR Part {sp.part}, Subpart {sp.designation}"
        ctx = [hierarchy_context(corpus, citation=citation, text=text, key=f"ecfr_hierarchy:part:{sp.part}:subpart:{sp.designation}", part=sp.part, subpart=sp.designation, heading=sp.title)]
        shown = secs if len(secs) <= 12 else secs[:10]
        items = ", ".join(f"§ {s.number} ({strip_period(s.heading)})" for s in shown)
        tail = "" if len(secs) <= 12 else f", and {len(secs) - 10} further sections"
        question = pick([f"Which sections are in Subpart {sp.designation} of 21 CFR Part {sp.part}?", f"What does Subpart {sp.designation} of 21 CFR Part {sp.part} contain?", f"List the sections of 21 CFR Part {sp.part}, Subpart {sp.designation}."], "rel_subpart", sp.part, sp.designation)
        answer = f"Subpart {sp.designation} of 21 CFR Part {sp.part} ({part.title}) is titled {quote(sp.title)} and contains {len(secs)} sections [1]: {items}{tail}."
        out.append(TrainingExample("regulatory_qa", "relationship", question, ctx, answer, [citation], True, "relationship/subpart_sections/v1", f"ecfr_part:{sp.part}", snap, {"subtype": "subpart_sections"}))

    # 2. section -> part / subpart / subchapter
    for sec in _live_sections(corpus):
        sp = corpus.subpart_of(sec)
        part = corpus.parts.get(sec.part)
        sub = corpus.subchapter_of_part(sec.part)
        if not (sp and sp.title and part and part.title and sub and sub.title) or "reserved" in sp.title.lower():
            continue
        text = f"21 CFR {sec.number} — {sec.heading} Located in: Title 21, Chapter I; Subchapter {sub.code} ({sub.title}); Part {sec.part} ({part.title}); Subpart {sp.designation} ({sp.title})."
        ctx = [hierarchy_context(corpus, citation=sec.citation, text=text, key=f"ecfr_hierarchy:section:{sec.number}", part=sec.part, subpart=sp.designation, section=sec.number, heading=sec.heading)]
        question = pick([f"Which part and subpart of 21 CFR contain § {sec.number}?", f"Where is 21 CFR {sec.number} located within Title 21?", f"To which part, subpart and subchapter does 21 CFR {sec.number} belong?"], "rel_location", sec.number)
        answer = f"{sec.citation}, {quote(sec.heading)}, is in Subpart {sp.designation} ({sp.title}) of Part {sec.part} ({part.title}), within Subchapter {sub.code} ({sub.title}) of Title 21, Chapter I [1]."
        out.append(TrainingExample("regulatory_qa", "relationship", question, ctx, answer, [sec.citation], True, "relationship/section_location/v1", f"ecfr:{sec.number}", snap, {"subtype": "section_location"}))

    # 3. section -> paragraphs (only when every top-level paragraph has a caption)
    for sec in _live_sections(corpus):
        tops = [r for r in sec.records if r.top_level]
        if not (2 <= len(tops) <= 8):
            continue
        leads = [leadin(r.text)[0] for r in tops]
        if any(l is None for l in leads):
            continue
        if sum(len(clean(r.text)) for r in tops) > q.max_context_chars:
            continue
        ctx = [ecfr_context(corpus, r) for r in tops]
        parts_txt = "; ".join(f"{r.paragraph} {l} [{i}]" for i, (r, l) in enumerate(zip(tops, leads), start=1))
        question = pick([f"What paragraphs does 21 CFR {sec.number} contain, and what does each address?", f"How is 21 CFR {sec.number} organised?", f"What are the main paragraphs of {sec.citation}?"], "rel_paragraphs", sec.number)
        answer = f"{sec.citation}, {quote(sec.heading)}, contains {len(tops)} paragraphs: {parts_txt}."
        out.append(TrainingExample("regulatory_qa", "relationship", question, ctx, answer, [c.citation for c in ctx], True, "relationship/section_paragraphs/v1", f"ecfr:{sec.number}", snap, {"subtype": "section_paragraphs"}))

    # 4. cross-references (from paragraph + the target's first record)
    per_section: Counter[str] = Counter()
    seen_from: set[str] = set()
    for x in sorted(corpus.cross_refs, key=lambda x: _order_key("xref", x.from_record.key, x.to_record.key)):
        a, b = x.from_record, x.to_record
        if a.key in seen_from or per_section[a.section] >= 2:
            continue
        if not is_clean_paragraph(a.text, q.min_paragraph_chars, q.max_paragraph_chars) or x.raw_text not in clean(a.text):
            continue
        target_sec = corpus.sections.get(b.section)
        if not target_sec or not target_sec.heading:
            continue
        target = b if is_clean_paragraph(b.text, 30, q.max_paragraph_chars) else next((r for r in target_sec.records if is_clean_paragraph(r.text, 30, q.max_paragraph_chars)), None)
        if target is None:
            continue
        seen_from.add(a.key)
        per_section[a.section] += 1
        ctx = [ecfr_context(corpus, a), ecfr_context(corpus, target)]
        label = xref_label(x.raw_text, b)
        question = pick([f"Which provision does {a.citation} refer to as {quote(x.raw_text)}?", f"What does the reference {quote(x.raw_text)} in {a.citation} point to?", f"When {a.citation} mentions {quote(x.raw_text)}, which section is meant?"], "rel_xref", a.key, b.key)
        answer = f"In {a.citation} [1], the reference {quote(x.raw_text)} points to {label}, in the section {quote(target_sec.heading)} [2]."
        out.append(TrainingExample("regulatory_qa", "relationship", question, ctx, answer, [a.citation, target.citation], True, "relationship/cross_reference/v1", f"ecfr:{a.section}", snap, {"subtype": "cross_reference"}))
    return out


def xref_label(raw_text: str, target: Record) -> str:
    """'§ 820.7' names a section; '§ 101.9(c)(6)' names a paragraph."""
    return target.citation if "(" in raw_text else f"21 CFR {target.section}"


def strip_period(text: str | None) -> str:
    return clean(text).rstrip(".")


# ------------------------------------------------------------ E. guidance


def _doc_intro(doc: GuidanceDoc) -> str:
    quals = [x for x in (doc.status, doc.center, f"issued {doc.issued_on}" if doc.issued_on and not doc.issued_on.startswith("1900") else None, f"Docket {doc.docket}" if doc.docket else None) if x]
    return f"The FDA guidance {quote(doc.title)}" + (f" ({', '.join(quals)})" if quals else "")


def scope_sentence(chunk: GuidanceChunk) -> str | None:
    text = clean(chunk.text)
    m = SCOPE_SENTENCE_RE.search(text)
    if not m:
        return None
    for s in sentences(text[m.start():]):
        if 40 <= len(s) <= 500 and _whole_sentence(s) and "http" not in s and not re.search(r"\.{4,}", s) and not has_footnote_artifact(s):
            return s
        return None
    return None


def _whole_sentence(s: str) -> bool:
    return s.rstrip('"”)').endswith((".", "!", "?", ";"))


def recommendation_sentence(chunk: GuidanceChunk) -> str | None:
    text = clean(chunk.text)
    for s in sentences(text):
        s = s.lstrip("•·o*- ").strip()
        if not RECOMMENDS_RE.search(s) or not s[:1].isupper():
            continue
        if 60 <= len(s) <= 450 and _whole_sentence(s) and "http" not in s and not re.search(r"\.{4,}", s) and not has_footnote_artifact(s):
            return s
    return None


def gen_guidance(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    out: list[TrainingExample] = []
    for doc in corpus.guidance:
        n = 0
        group = f"guidance:{doc.url}"
        for chunk in doc.intro_chunks:
            s = scope_sentence(chunk)
            if not s:
                continue
            question = pick([f"What is the FDA guidance {quote(doc.title)} about?", f"What does the FDA guidance {quote(doc.title)} address?", f"What is the purpose of the FDA guidance document {quote(doc.title)}?"], "guid_scope", doc.url)
            answer = f"{_doc_intro(doc)} [1] states: {quote(s)} {NONBINDING}"
            out.append(TrainingExample("regulatory_qa", "fda_guidance", question, [guidance_context(doc, chunk)], answer, [doc.citation], True, "fda_guidance/scope/v1", group, corpus.snapshot_date, {"subtype": "scope"}))
            n += 1
            break
        for chunk in doc.recommendation_chunks:
            if n >= q.max_guidance_examples_per_document:
                break
            s = recommendation_sentence(chunk)
            if not s:
                continue
            question = pick([f"What does FDA recommend in the guidance {quote(doc.title)}?", f"According to the FDA guidance {quote(doc.title)}, what does FDA recommend?", f"What recommendation does the FDA guidance {quote(doc.title)} make?"], "guid_rec", doc.url, str(chunk.ordinal))
            answer = f"The FDA guidance {quote(doc.title)} [1] states: {quote(s)} {NONBINDING_SHORT}"
            out.append(TrainingExample("regulatory_qa", "fda_guidance", question, [guidance_context(doc, chunk)], answer, [doc.citation], True, "fda_guidance/recommendation/v1", group, corpus.snapshot_date, {"subtype": "recommendation"}))
            n += 1
    return out


# --------------------------------------------------- F. CFR vs guidance


def _first_clean_record(sec: Section, min_chars: int, max_chars: int) -> Record | None:
    for r in sec.records:
        if is_clean_paragraph(r.text, min_chars, max_chars):
            return r
    return None


def gen_cfr_vs_guidance(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    out: list[TrainingExample] = []
    snap = corpus.snapshot_date
    # eCFR-only
    for sec in _live_sections(corpus):
        rec = _first_clean_record(sec, q.min_paragraph_chars, q.max_paragraph_chars)
        if rec is None:
            continue
        first = sentences(strip_label(rec.text))[0]
        if len(first) > 300:
            continue
        part_title = corpus.part_title(rec.part)
        question = pick([f"Is the following from the eCFR or from FDA guidance? {quote(first)}", "Does the provided source state a binding regulation or non-binding FDA guidance?", "Is the provided passage a codified regulation or an FDA guidance recommendation?"], "vs_ecfr", rec.key)
        where = f", in 21 CFR Part {rec.part} ({part_title})" if part_title else ""
        answer = f"The passage is from the eCFR: {rec.citation} [1]{where}. It is a codified regulation and therefore legally binding; it is not FDA guidance."
        out.append(TrainingExample("regulatory_qa", "cfr_vs_guidance", question, [ecfr_context(corpus, rec)], answer, [rec.citation], True, "cfr_vs_guidance/ecfr/v1", f"ecfr:{sec.number}", snap, {"subtype": "ecfr_only"}))
    # guidance-only
    for doc in corpus.guidance:
        chunk = next((c for c in doc.recommendation_chunks if recommendation_sentence(c)), None) or next((c for c in doc.intro_chunks if scope_sentence(c)), None)
        if chunk is None:
            continue
        s = recommendation_sentence(chunk) or scope_sentence(chunk)
        question = pick([f"Is the following from the eCFR or from FDA guidance? {quote(s)}", "Does the provided source state a binding regulation or non-binding FDA guidance?", "Is the provided passage a codified regulation or an FDA guidance recommendation?"], "vs_guid", doc.url)
        docket = f", Docket {doc.docket}" if doc.docket else ""
        answer = f"The passage is from FDA guidance: {quote(doc.title)} ({doc.status or 'guidance'}{docket}) [1]. FDA guidance describes the agency's current thinking and is not legally binding; it is not part of the eCFR."
        out.append(TrainingExample("regulatory_qa", "cfr_vs_guidance", question, [guidance_context(doc, chunk)], answer, [doc.citation], True, "cfr_vs_guidance/guidance/v1", f"guidance:{doc.url}", snap, {"subtype": "guidance_only"}))
    # pair: regulation + guidance that explicitly cites it
    for doc, chunk, sec, rec, _ in _guidance_section_pairs(corpus, cfg):
        question = pick(["Of the provided sources, which is a binding regulation and which is FDA guidance?", f"Which of these sources is legally binding: {rec.citation} or the FDA guidance {quote(doc.title)}?", f"How do {rec.citation} and the FDA guidance {quote(doc.title)} differ in legal status?"], "vs_pair", doc.url, rec.key)
        answer = f"{rec.citation} [1] is a binding eCFR regulation. The FDA guidance {quote(doc.title)} [2] is non-binding guidance that refers to 21 CFR {sec.number}; it represents FDA's current thinking and does not itself impose legal requirements."
        out.append(TrainingExample("regulatory_qa", "cfr_vs_guidance", question, [ecfr_context(corpus, rec), guidance_context(doc, chunk)], answer, [rec.citation, doc.citation], True, "cfr_vs_guidance/pair/v1", f"guidance:{doc.url}", snap, {"subtype": "pair"}))
    return out


def _guidance_section_pairs(corpus: Corpus, cfg: TrainingConfig):
    """(doc, chunk, section, record, sentence) where the chunk cites the doc's anchor section verbatim."""
    q = cfg.quality
    for doc in corpus.guidance:
        if not doc.anchor_section or doc.anchor_section not in corpus.sections:
            continue
        sec = corpus.sections[doc.anchor_section]
        if sec.is_reserved or not sec.heading:
            continue
        rec = _first_clean_record(sec, q.min_paragraph_chars, q.max_paragraph_chars)
        if rec is None:
            continue
        for chunk in doc.anchor_chunks:
            s = find_sentence_with(chunk.text, doc.anchor_section, 40, 450)
            if s and len(clean(chunk.text)) + len(clean(rec.text)) <= q.max_context_chars:
                yield doc, chunk, sec, rec, s
                break


# ------------------------------------------------------------ G. citation


def gen_citation(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    out: list[TrainingExample] = []
    snap = corpus.snapshot_date
    heading_counts = Counter(strip_period(s.heading).lower() for s in corpus.sections.values() if s.heading)
    part_heading_counts = Counter((s.part, strip_period(s.heading).lower()) for s in corpus.sections.values() if s.heading)
    for sec in _live_sections(corpus):
        topic = heading_topic(sec.heading)
        if not topic or len(topic.split()) < 3 or len(topic) > 120:
            continue
        recs, _ = section_excerpt(sec, 800, q.min_paragraph_chars)
        if not recs:
            continue
        key = strip_period(sec.heading).lower()
        if heading_counts[key] == 1:
            question = pick([f"Which regulation addresses {topic}?", f"Which section of 21 CFR covers {topic}?", f"Where in 21 CFR is {topic} addressed?"], "cite_heading", sec.number)
        elif part_heading_counts[(sec.part, key)] == 1:
            question = pick([f"Which section of 21 CFR Part {sec.part} addresses {topic}?", f"Where in 21 CFR Part {sec.part} is {topic} covered?"], "cite_heading_part", sec.number)
        else:
            continue
        ctx = [ecfr_context(corpus, r) for r in recs]
        answer = f"{sec.citation}, {quote(sec.heading)}, addresses this {marks(len(recs))}. It provides: {excerpt_text(recs)}"
        out.append(TrainingExample("regulatory_qa", "citation", question, ctx, answer, [c.citation for c in ctx], True, "citation/heading/v1", f"ecfr:{sec.number}", snap, {"subtype": "heading"}))
    term_counts = Counter((d.record.part, clean(d.term).lower()) for d in corpus.definitions)
    per_section: Counter[str] = Counter()
    for d in sorted(corpus.definitions, key=lambda d: _order_key("cite_def", d.record.key, d.term)):
        rec, term = d.record, clean(d.term)
        if not term or term_counts[(rec.part, term.lower())] != 1 or not is_clean_paragraph(rec.text, 30, q.max_paragraph_chars):
            continue
        if not strip_label(rec.text).lower().startswith(term.lower() + " "):
            continue
        if per_section[rec.section] >= 4:
            continue
        per_section[rec.section] += 1
        question = pick([f"Which section of 21 CFR Part {rec.part} defines {quote(term)}?", f"Where is {quote(term)} defined in 21 CFR Part {rec.part}?", f"Which provision of 21 CFR Part {rec.part} gives the definition of {quote(term)}?"], "cite_def", rec.key, term)
        answer = f"{quote(term)} is defined in {rec.citation} [1]: {strip_label(rec.text)}"
        out.append(TrainingExample("regulatory_qa", "citation", question, [ecfr_context(corpus, rec)], answer, [rec.citation], True, "citation/definition/v1", f"ecfr:{rec.section}", snap, {"subtype": "definition"}))
    return out


# --------------------------------------------------------- H. multi-context


def gen_multi_context(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    out: list[TrainingExample] = []
    snap = corpus.snapshot_date
    per_section: Counter[str] = Counter()
    for x in sorted(corpus.cross_refs, key=lambda x: _order_key("multi", x.from_record.key, x.to_record.key)):
        a, b = x.from_record, x.to_record
        if per_section[a.section] >= 1:
            continue
        if not (is_clean_paragraph(a.text, q.min_paragraph_chars, q.max_paragraph_chars) and is_clean_paragraph(b.text, q.min_paragraph_chars, q.max_paragraph_chars)):
            continue
        if x.raw_text not in clean(a.text) or len(clean(a.text)) + len(clean(b.text)) > q.max_context_chars:
            continue
        bsec = corpus.sections.get(b.section)
        if not bsec or not bsec.heading:
            continue
        per_section[a.section] += 1
        ctx = [ecfr_context(corpus, a), ecfr_context(corpus, b)]
        question = pick([f"How do {a.citation} and {b.citation} relate to each other?", f"What does {a.citation} provide, and what does the provision it references, {b.citation}, say?", f"Read {a.citation} together with {b.citation}: what do they establish?"], "multi_xref", a.key, b.key)
        answer = f"{a.citation} [1] refers to {xref_label(x.raw_text, b)} as {quote(x.raw_text)}. {a.citation} provides: {strip_label(a.text)} {b.citation} [2], in the section {quote(bsec.heading)}, provides: {strip_label(b.text)}"
        out.append(TrainingExample("regulatory_qa", "multi_context", question, ctx, answer, [a.citation, b.citation], True, "multi_context/cross_reference/v1", f"ecfr:{a.section}", snap, {"subtype": "cross_reference"}))
    for doc, chunk, sec, rec, s in _guidance_section_pairs(corpus, cfg):
        ctx = [ecfr_context(corpus, rec), guidance_context(doc, chunk)]
        question = pick([f"What does {rec.citation} provide, and what does the FDA guidance {quote(doc.title)} say about it?", f"How does the FDA guidance {quote(doc.title)} relate to 21 CFR {sec.number}?", f"Using both sources, what does 21 CFR {sec.number} require and how does FDA's guidance discuss it?"], "multi_guid", doc.url, rec.key)
        answer = (
            f"{rec.citation} [1], {quote(sec.heading)}, provides: {strip_label(rec.text)} "
            f"The FDA guidance {quote(doc.title)} [2] refers to 21 CFR {sec.number}, stating: {quote(s)} "
            "The regulation is binding; the guidance is non-binding and reflects FDA's current thinking."
        )
        out.append(TrainingExample("regulatory_qa", "multi_context", question, ctx, answer, [rec.citation, doc.citation], True, "multi_context/guidance_section/v1", f"guidance:{doc.url}", snap, {"subtype": "guidance_section"}))
    return out


GENERATORS = {
    "direct_cfr": gen_direct_cfr,
    "section_paragraph": gen_section_paragraph,
    "definition": gen_definitions,
    "relationship": gen_relationships,
    "fda_guidance": gen_guidance,
    "cfr_vs_guidance": gen_cfr_vs_guidance,
    "citation": gen_citation,
    "multi_context": gen_multi_context,
}


def topic_words(text: str) -> frozenset[str]:
    stop = {"the", "of", "and", "or", "for", "to", "in", "a", "an", "by", "on", "with", "general", "requirements", "provisions", "other", "as", "under"}
    return frozenset(w for w in word_set(text) if w not in stop and len(w) > 2)
