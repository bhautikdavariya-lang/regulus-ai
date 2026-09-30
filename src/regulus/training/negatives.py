"""Abstention and negative examples.

Every identifier used here is checked against the loaded corpus (all part
numbers including reserved ranges, all section numbers including reserved
ones, every docket on any guidance row) so a "fake" identifier can never be a
real one. No regulatory text is invented: the only text in these examples is
real database text used as a *distractor* context, and the answer refuses.
"""

from __future__ import annotations

from collections import Counter

from regulus.training.config import TrainingConfig
from regulus.training.generators import _first_clean_record, _live_sections, ecfr_context, guidance_context, part_scope_section, recommendation_sentence, scope_sentence, topic_words
from regulus.training.models import TrainingExample
from regulus.training.sources import Corpus, Section
from regulus.training.text import clean, heading_topic, pick, quote, stable_hash, word_set

REFUSAL_MARKERS = (
    "could not verify", "could not find", "does not record", "no information", "insufficient",
    "does not address", "cannot", "no paragraph",
    # Stage 13 grounding wording
    "does not establish", "do not establish", "is reserved", "not cited",
)
FAKE_SECTION_SUFFIXES = ("999", "998", "997", "9999", "777")
FAKE_PARAGRAPH_LABELS = ("(z)", "(y)", "(x)")
FUTURE_YEARS = ("2030", "2031", "2032", "2033", "2034", "2035")


def _ordered(items, *key_parts):
    return sorted(items, key=lambda x: stable_hash("neg", *key_parts, str(x)))


def fake_section_numbers(corpus: Corpus, limit: int) -> list[tuple[str, str]]:
    """(part, fake_section) for real parts with live sections; the section number is absent from cfr_sections."""
    out = []
    for part in _ordered([p for p, v in corpus.parts.items() if not v.is_reserved and v.sections], "fake_section"):
        for suffix in FAKE_SECTION_SUFFIXES:
            cand = f"{part}.{suffix}"
            if cand not in corpus.all_section_numbers:
                out.append((part, cand))
                break
        if len(out) >= limit:
            break
    return out


def fake_part_numbers(corpus: Corpus, limit: int) -> list[str]:
    reserved = corpus.reserved_part_numbers()
    existing = {int(n) for n in corpus.all_part_numbers if n.isdigit()}
    cands = [str(n) for n in range(1, 1500) if n not in existing and n not in reserved]
    return _ordered(cands, "fake_part")[:limit]


def fake_dockets(corpus: Corpus, limit: int) -> list[str]:
    out = []
    i = 0
    while len(out) < limit and i < limit * 10:
        h = stable_hash("fake_docket", str(i))
        year = 2008 + int(h[:4], 16) % 18
        num = 90000 + int(h[4:10], 16) % 9999
        cand = f"FDA-{year}-D-{num:05d}"
        i += 1
        if cand not in corpus.all_dockets and cand not in out:
            out.append(cand)
    return out


def _refusal_section(fake: str, date: str | None) -> str:
    snap = f" (Title 21 snapshot dated {date})" if date else ""
    return f"I could not verify 21 CFR {fake} in the available eCFR data{snap}, so I cannot provide a reliable statement of its requirements. The section may not exist, may be reserved, or may lie outside the available data."


def gen_abstention(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    q = cfg.quality
    snap = corpus.snapshot_date
    out: list[TrainingExample] = []
    target = max(cfg.category_targets().get("abstention", 0), 50)
    per_kind = max(target // 7 + 10, 20)

    # 1. nonexistent sections (half with no context, half with a real distractor from the same part)
    for i, (part, fake) in enumerate(fake_section_numbers(corpus, per_kind)):
        question = pick([f"What does 21 CFR {fake} require?", f"Summarize 21 CFR {fake}.", f"What is the purpose of 21 CFR {fake}?", f"What does 21 CFR {fake} cover?"], "neg_sec_q", fake)
        scope = part_scope_section(corpus, part) or next((corpus.sections[n] for n in corpus.parts[part].sections if n in corpus.sections and corpus.sections[n].records), None)
        rec = _first_clean_record(scope, q.min_paragraph_chars, q.max_paragraph_chars) if scope else None
        if i % 2 == 0 or rec is None:
            answer = _refusal_section(fake, snap)
            ctx = []
        else:
            part_title = corpus.part_title(part)
            pt = f" ({part_title})" if part_title else ""
            answer = f"I could not verify 21 CFR {fake} in the available eCFR data. The provided source is {rec.citation} [1], a different section of 21 CFR Part {part}{pt}; it does not establish what 21 CFR {fake} says, so I cannot answer reliably."
            ctx = [ecfr_context(corpus, rec)]
        out.append(TrainingExample("abstention", "abstention", question, ctx, answer, [], False, "abstention/fake_section/v1", f"neg:section:{fake}", snap, {"subtype": "fake_section", "negative": {"kind": "section", "identifier": fake}}))

    # 2. nonexistent parts
    for n in fake_part_numbers(corpus, per_kind):
        question = pick([f"What does 21 CFR Part {n} cover?", f"What are the requirements of 21 CFR Part {n}?", f"Summarize 21 CFR Part {n}."], "neg_part_q", n)
        answer = f"I could not verify 21 CFR Part {n} in the available eCFR data (Title 21, Chapter I{', snapshot dated ' + snap if snap else ''}), so I cannot describe its contents or requirements."
        out.append(TrainingExample("abstention", "abstention", question, [], answer, [], False, "abstention/fake_part/v1", f"neg:part:{n}", snap, {"subtype": "fake_part", "negative": {"kind": "part", "identifier": n}}))

    # 3. nonexistent guidance dockets (half with a real, different guidance as distractor)
    docs = [d for d in corpus.guidance if d.docket and (any(recommendation_sentence(c) for c in d.recommendation_chunks) or any(scope_sentence(c) for c in d.intro_chunks))]
    docs = _ordered(docs, "neg_docket_distractor") if docs else []
    for i, docket in enumerate(fake_dockets(corpus, per_kind)):
        question = pick([f"What does FDA guidance docket {docket} recommend?", f"Summarize the FDA guidance with docket number {docket}.", f"What is FDA guidance {docket} about?"], "neg_docket_q", docket)
        if i % 2 == 1 and docs:
            doc = docs[i % len(docs)]
            chunk = next((c for c in doc.recommendation_chunks if recommendation_sentence(c)), None) or next(c for c in doc.intro_chunks if scope_sentence(c))
            answer = f"I could not find an FDA guidance document with docket number {docket} in the available guidance data. The provided source is the guidance {quote(doc.title)} (Docket {doc.docket}) [1], a different document, so it does not tell us what {docket} recommends."
            ctx = [guidance_context(doc, chunk)]
        else:
            answer = f"I could not find an FDA guidance document with docket number {docket} in the available guidance data, so I cannot summarize it or state what it recommends."
            ctx = []
        out.append(TrainingExample("abstention", "abstention", question, ctx, answer, [], False, "abstention/fake_docket/v1", f"neg:docket:{docket}", snap, {"subtype": "fake_docket", "negative": {"kind": "docket", "identifier": docket}}))

    # 4. invalid paragraph of a real section (context = the section's top-level paragraphs)
    count = 0
    for sec in _ordered(_live_sections(corpus), "neg_para"):
        tops = [r for r in sec.records if r.top_level]
        if not (2 <= len(tops) <= 6) or sum(len(clean(r.text)) for r in tops) > q.max_context_chars:
            continue
        labels = {r.paragraph for r in sec.records}
        label = next((l for l in FAKE_PARAGRAPH_LABELS if l not in labels and not any(p.startswith(l) for p in labels)), None)
        if label is None:
            continue
        fake = f"{sec.number}{label}"
        ctx = [ecfr_context(corpus, r) for r in tops]
        listing = ", ".join(r.paragraph for r in tops)
        question = pick([f"What does 21 CFR {fake} require?", f"Explain 21 CFR {fake}.", f"What does paragraph {label} of 21 CFR {sec.number} provide?"], "neg_para_q", fake)
        answer = f"The available eCFR data contains 21 CFR {sec.number}, {quote(sec.heading)}, but no paragraph {label}: its top-level paragraphs are {listing} [1]-[{len(tops)}]. I cannot provide a requirement for 21 CFR {fake}."
        out.append(TrainingExample("abstention", "abstention", question, ctx, answer, [], False, "abstention/invalid_paragraph/v1", f"neg:paragraph:{fake}", snap, {"subtype": "invalid_paragraph", "negative": {"kind": "paragraph", "identifier": fake, "section": sec.number, "paragraph": label}}))
        count += 1
        if count >= per_kind:
            break

    # 5. amendment date not recorded in the data
    count = 0
    for sec in _ordered(_live_sections(corpus), "neg_amended"):
        rec = _first_clean_record(sec, q.min_paragraph_chars, q.max_paragraph_chars)
        if rec is None:
            continue
        question = pick([f"When was 21 CFR {sec.number} last amended?", f"On what date was {sec.citation} most recently revised?"], "neg_amended_q", sec.number)
        answer = f"The provided source, {rec.citation} [1], gives text from the section, but the available eCFR data does not record when 21 CFR {sec.number} was last amended, so I cannot state an amendment date."
        out.append(TrainingExample("abstention", "abstention", question, [ecfr_context(corpus, rec)], answer, [], False, "abstention/unrecorded_date/v1", f"neg:amended:{sec.number}", snap, {"subtype": "unrecorded_date", "negative": {"kind": "attribute", "identifier": sec.number}}))
        count += 1
        if count >= per_kind:
            break

    # 6. future / unknowable revisions
    count = 0
    for number in _ordered([p for p, v in corpus.parts.items() if not v.is_reserved and v.title], "neg_future"):
        scope = part_scope_section(corpus, number)
        rec = _first_clean_record(scope, q.min_paragraph_chars, q.max_paragraph_chars) if scope else None
        if rec is None:
            continue
        year = pick(FUTURE_YEARS, "neg_future_year", number)
        question = pick([f"What will 21 CFR Part {number} require after its {year} revision?", f"How does the {year} amendment change 21 CFR Part {number}?"], "neg_future_q", number)
        answer = f"The available eCFR data is a snapshot{' dated ' + snap if snap else ''} and contains no information about a {year} revision of 21 CFR Part {number}. The provided source, {rec.citation} [1], reflects the current text only, so I cannot describe future requirements."
        out.append(TrainingExample("abstention", "abstention", question, [ecfr_context(corpus, rec)], answer, [], False, "abstention/future_revision/v1", f"neg:future:{number}", snap, {"subtype": "future_revision", "negative": {"kind": "attribute", "identifier": number}}))
        count += 1
        if count >= per_kind:
            break

    # 7. insufficient evidence: the context is about something else
    secs = [s for s in _live_sections(corpus) if s.heading and len((heading_topic(s.heading) or "").split()) >= 3]
    ordered = _ordered(secs, "neg_offtopic")
    count = 0
    used: Counter[str] = Counter()
    for i, a in enumerate(ordered):
        b = ordered[(i * 7 + 13) % len(ordered)]
        if a.part == b.part or a.number == b.number:
            continue
        rec = _first_clean_record(b, q.min_paragraph_chars, q.max_paragraph_chars)
        if rec is None or used[b.number]:
            continue
        ta = topic_words(a.heading)
        if not ta or ta & word_set(rec.text) or ta & word_set(b.heading or ""):
            continue
        used[b.number] += 1
        topic_a, topic_b = heading_topic(a.heading), heading_topic(b.heading)
        question = pick([f"What does 21 CFR require regarding {topic_a}?", f"Which requirements apply to {topic_a} under 21 CFR?"], "neg_offtopic_q", a.number)
        answer = f"The provided source, {rec.citation} [1], concerns {topic_b} and does not address {topic_a}. The available evidence is insufficient to answer this question."
        out.append(TrainingExample("abstention", "abstention", question, [ecfr_context(corpus, rec)], answer, [], False, "abstention/insufficient_evidence/v1", f"neg:offtopic:{a.number}", snap, {"subtype": "insufficient_evidence", "negative": {"kind": "topic", "identifier": a.number}}))
        count += 1
        if count >= per_kind:
            break
    return out


def is_refusal(answer: str) -> bool:
    low = answer.lower()
    return any(m in low for m in REFUSAL_MARKERS)
