"""Stage 13 training categories that teach request/context grounding.

Stage 12 showed the failure this module targets. Trained on Stage 11, whose
every positive example pairs a question with context that answers it exactly,
the model learned "context present -> apply the citation template". Asked
about the nonexistent 21 CFR 314.999 with a real passage from another section
in context, it presented that passage as the content of 314.999.

The categories here break that shortcut by keeping the context legitimate and
varying only whether it establishes what was asked:

  context_mismatch   requested identifier does not exist; context is real and
                     from somewhere else
  wrong_context      requested identifier exists; context is real and from a
                     different section
  partial_context    requested paragraph exists; context holds a sibling
                     paragraph of the same section, not the requested one
  guidance_mismatch  question asks for a binding requirement and the context
                     is guidance, or the reverse
  citation_grounding the answer IS supported, but only by one source among
                     distractors, and only that source may be cited

The first four are abstentions; the last answers. Without the last, raising
the abstention share would simply teach the model to refuse more often, which
Stage 13 measures separately as the false-refusal rate.

Every identifier used as "nonexistent" is checked against the verified
database through CorpusIdentifierIndex before it is used.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterator

from regulus.grounding.identifiers import CorpusIdentifierIndex
from regulus.training.config import TrainingConfig
from regulus.training.generators import (
    _first_clean_record,
    _live_sections,
    ecfr_context,
    guidance_context,
    recommendation_sentence,
    scope_sentence,
)
from regulus.training.models import TrainingExample
from regulus.training.negatives import _ordered, fake_dockets, fake_part_numbers, fake_section_numbers
from regulus.training.sources import Corpus, GuidanceDoc, Record, Section
from regulus.training.text import clean, heading_topic, pick, quote, stable_hash, strip_label

# Kept in the register the Stage 11 answers and the Stage 13 gate already use.
CANNOT_ESTABLISH = "does not establish"


def _pair_index(seed: str, i: int, n: int) -> int:
    """Deterministic, well-spread partner choice without a random generator."""
    return int(stable_hash(seed, str(i))[:8], 16) % max(n, 1)


def _distractor_pool(corpus: Corpus, cfg: TrainingConfig) -> list[Record]:
    """Clean, citable eCFR paragraphs usable as legitimate but unrelated context."""
    q = cfg.quality
    pool: list[Record] = []
    for sec in _live_sections(corpus):
        rec = _first_clean_record(sec, q.min_paragraph_chars, q.max_paragraph_chars)
        if rec is not None:
            pool.append(rec)
    return _ordered(pool, "stage13_distractor_pool")


def _cite(rec: Record) -> str:
    return rec.citation


def refusal_opening(citation: str, key: str, varied: bool = True) -> str:
    """Vary the opening of a refusal.

    Stage 13 trained 2,000 refusals that all began "The provided source is
    X [1], which ...". The model learned that frame and applied it to
    answerable questions, describing the retrieved documents instead of
    answering. Varying the opening keeps the judgment and drops the tic.
    """
    if not varied:
        return f"The provided source is {citation} [1], which"
    return pick(
        [
            f"The provided source is {citation} [1], which",
            f"{citation} [1] is the only source provided here, and it",
            f"What the context actually contains is {citation} [1], which",
            f"Only {citation} [1] was supplied, and it",
        ],
        "refusal_opening", key, citation,
    )


# ------------------------------------------------------- context mismatch


def gen_context_mismatch(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """Nonexistent identifier, legitimate context from elsewhere -> abstain.

    This is the direct counter-example to the Stage 12 failure: the model must
    notice that the citation on the provided source is not the citation it was
    asked about, even though the source itself is perfectly real.
    """
    snap = corpus.snapshot_date
    q = cfg.quality
    index = CorpusIdentifierIndex(corpus)
    pool = _distractor_pool(corpus, cfg)
    if not pool:
        return []
    out: list[TrainingExample] = []
    target = max(cfg.category_targets().get("context_mismatch", 0), 60)
    per_kind = target // 3 + 20

    # fake sections
    for i, (part, fake) in enumerate(fake_section_numbers(corpus, per_kind)):
        assert not index.section_status(fake)[1], fake
        rec = pool[_pair_index("cm_section", i, len(pool))]
        if rec.part == part:
            rec = pool[_pair_index("cm_section_alt", i, len(pool))]
        question = pick(
            [f"What does 21 CFR {fake} require?", f"What are the requirements of 21 CFR {fake}?", f"Summarize 21 CFR {fake}."],
            "cm_sec_q", fake,
        )
        answer = (
            f"{refusal_opening(_cite(rec), fake, q.varied_refusal_openings)} {CANNOT_ESTABLISH} the content of 21 CFR {fake}. "
            f"I could not verify 21 CFR {fake} in the available eCFR data"
            f"{f' (Title 21 snapshot dated {snap})' if snap else ''}, so I cannot state its requirements."
        )
        out.append(TrainingExample(
            "abstention", "context_mismatch", question, [ecfr_context(corpus, rec)], answer, [], False,
            "context_mismatch/fake_section/v1", f"neg:section:{fake}", snap,
            {"subtype": "fake_section", "negative": {"kind": "section", "identifier": fake}, "provided_source": rec.key},
        ))

    # fake parts
    for i, number in enumerate(fake_part_numbers(corpus, per_kind)):
        assert not index.part_status(number)[1], number
        rec = pool[_pair_index("cm_part", i, len(pool))]
        question = pick(
            [f"What does 21 CFR Part {number} cover?", f"What requirements does 21 CFR Part {number} impose?", f"Summarize 21 CFR Part {number}."],
            "cm_part_q", number,
        )
        answer = (
            f"The provided source is {_cite(rec)} [1], which is in 21 CFR Part {rec.part}, not Part {number}. "
            f"I could not verify 21 CFR Part {number} in the available eCFR data"
            f"{f' (Title 21 snapshot dated {snap})' if snap else ''}, so I cannot describe its contents."
        )
        out.append(TrainingExample(
            "abstention", "context_mismatch", question, [ecfr_context(corpus, rec)], answer, [], False,
            "context_mismatch/fake_part/v1", f"neg:part:{number}", snap,
            {"subtype": "fake_part", "negative": {"kind": "part", "identifier": number}, "provided_source": rec.key},
        ))

    # fake parts whose retrieved context is GUIDANCE rather than eCFR.
    # Stage 13 answered "What does 21 CFR Part 1400 say?" by asserting that the
    # eCFR data contained Part 1400 and attaching retrieved guidance titles to
    # it. Every v2 fake-part example had supplied eCFR context, so the case
    # where only guidance comes back was never demonstrated.
    guidance_pool = _ordered(
        [d for d in corpus.guidance if any(scope_sentence(c) for c in d.intro_chunks)],
        "cm_part_guidance",
    )
    if guidance_pool and cfg.quality.guidance_context_negatives:
        for i, number in enumerate(fake_part_numbers(corpus, per_kind)[: per_kind // 2]):
            assert not index.part_status(number)[1], number
            doc = guidance_pool[_pair_index("cm_part_guid", i, len(guidance_pool))]
            chunk = next(c for c in doc.intro_chunks if scope_sentence(c))
            question = pick(
                [
                    f"What does 21 CFR Part {number} say about this subject?",
                    f"What does 21 CFR Part {number} require?",
                    f"Summarize the provisions of 21 CFR Part {number}.",
                ],
                "cm_partg_q", number,
            )
            answer = (
                f"The provided source is the FDA guidance {quote(doc.title)} [1], not eCFR text, and it "
                f"{CANNOT_ESTABLISH} the contents of any part of Title 21. I could not verify 21 CFR Part "
                f"{number} in the available eCFR data"
                f"{f' (Title 21 snapshot dated {snap})' if snap else ''}, so I cannot describe it."
            )
            out.append(TrainingExample(
                "abstention", "context_mismatch", question, [guidance_context(doc, chunk)], answer, [], False,
                "context_mismatch/fake_part_guidance_context/v1", f"neg:part:{number}", snap,
                {"subtype": "fake_part_guidance_context", "negative": {"kind": "part", "identifier": number}, "provided_source": doc.chunk_key(chunk)},
            ))

    # fake dockets against a real guidance document
    docs = [d for d in corpus.guidance if d.docket and (any(recommendation_sentence(c) for c in d.recommendation_chunks) or any(scope_sentence(c) for c in d.intro_chunks))]
    docs = _ordered(docs, "cm_docket_docs")
    if docs:
        for i, docket in enumerate(fake_dockets(corpus, per_kind)):
            assert not index.docket_exists(docket), docket
            doc = docs[_pair_index("cm_docket", i, len(docs))]
            chunk = next((c for c in doc.recommendation_chunks if recommendation_sentence(c)), None) or next(c for c in doc.intro_chunks if scope_sentence(c))
            question = pick(
                [f"What does FDA guidance {docket} recommend?", f"Summarize the FDA guidance with docket number {docket}.", f"What is FDA guidance docket {docket} about?"],
                "cm_docket_q", docket,
            )
            answer = (
                f"The provided source is the FDA guidance {quote(doc.title)} (Docket {doc.docket}) [1], a different "
                f"document, so it {CANNOT_ESTABLISH} what {docket} recommends. I could not find an FDA guidance "
                f"document with docket number {docket} in the available guidance data."
            )
            out.append(TrainingExample(
                "abstention", "context_mismatch", question, [guidance_context(doc, chunk)], answer, [], False,
                "context_mismatch/fake_docket/v1", f"neg:docket:{docket}", snap,
                {"subtype": "fake_docket", "negative": {"kind": "docket", "identifier": docket}, "provided_source": doc.chunk_key(chunk)},
            ))
    return out


# ---------------------------------------------------------- wrong context


def gen_wrong_context(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """Real identifier, real context from a different section -> abstain.

    Without this category the model can satisfy every abstention example with
    the rule "the identifier looks made up, so refuse". Here the requested
    section genuinely exists and the refusal has to come from comparing it
    against what was supplied.
    """
    snap = corpus.snapshot_date
    q = cfg.quality
    sections = [s for s in _live_sections(corpus) if _first_clean_record(s, q.min_paragraph_chars, q.max_paragraph_chars)]
    sections = _ordered(sections, "wrong_context_sections")
    if len(sections) < 2:
        return []
    out: list[TrainingExample] = []
    cap = max(cfg.category_targets().get("wrong_context", 0), 60) + 40
    for i, requested in enumerate(sections):
        if len(out) >= cap:
            break
        provided_sec = sections[_pair_index("wrong_ctx", i, len(sections))]
        if provided_sec.part == requested.part or provided_sec.number == requested.number:
            continue
        rec = _first_clean_record(provided_sec, q.min_paragraph_chars, q.max_paragraph_chars)
        if rec is None:
            continue
        topic = heading_topic(requested.heading)
        options = [
            f"What does {requested.citation} require?",
            f"What does {requested.citation} provide?",
            f"Summarize {requested.citation}.",
        ]
        if topic:
            options.append(f"What does 21 CFR {requested.number} say about {topic}?")
        question = pick(options, "wrong_ctx_q", requested.number)
        answer = (
            (
                f"{refusal_opening(_cite(rec), requested.number, True)} is in 21 CFR Part {rec.part} and "
                if q.varied_refusal_openings
                else f"The provided source is {_cite(rec)} [1], in 21 CFR Part {rec.part}. It "
            )
            + f"{CANNOT_ESTABLISH} what {requested.citation} provides, so I cannot answer this question from the available context."
        )
        out.append(TrainingExample(
            "abstention", "wrong_context", question, [ecfr_context(corpus, rec)], answer, [], False,
            "wrong_context/section/v1", f"ecfr:{requested.number}", snap,
            {"subtype": "different_section", "requested_identifier": requested.citation, "provided_source": rec.key},
        ))
    return out


# -------------------------------------------------------- partial context


def _sibling_paragraphs(section: Section) -> Iterator[tuple[Record, Record]]:
    """(provided, requested) sibling pairs: same parent, different child."""
    by_parent: dict[str, list[Record]] = {}
    for rec in section.records:
        p = rec.paragraph
        if not p or p.count("(") < 2:
            continue
        parent = p[: p.rindex("(")]
        by_parent.setdefault(parent, []).append(rec)
    for parent, kids in sorted(by_parent.items()):
        if len(kids) >= 2:
            yield kids[0], kids[1]


def gen_partial_context(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """Requested paragraph exists but is not the one supplied -> abstain.

    The retrieved paragraph is a sibling from the same section, so the citation
    is almost right. The model must not read across from (b)(1) to (b)(2).
    """
    snap = corpus.snapshot_date
    q = cfg.quality
    out: list[TrainingExample] = []
    cap = max(cfg.category_targets().get("partial_context", 0), 40) + 30
    for sec in _ordered(_live_sections(corpus), "partial_context"):
        if len(out) >= cap:
            break
        for provided, requested in _sibling_paragraphs(sec):
            if not (q.min_paragraph_chars <= len(clean(provided.text)) <= q.max_paragraph_chars):
                continue
            question = pick(
                [
                    f"What does {requested.citation} require?",
                    f"What does paragraph {requested.paragraph} of 21 CFR {sec.number} provide?",
                    f"Under {sec.citation}, what does paragraph {requested.paragraph} state?",
                ],
                "partial_q", requested.key,
            )
            answer = (
                f"{refusal_opening(_cite(provided), requested.key, q.varied_refusal_openings)}"
                f"{' is' if q.varied_refusal_openings else ' is'} paragraph {provided.paragraph} of "
                f"21 CFR {sec.number}. It {CANNOT_ESTABLISH} the text of paragraph {requested.paragraph}, so I "
                f"cannot state what {requested.citation} requires from this context."
            )
            out.append(TrainingExample(
                "abstention", "partial_context", question, [ecfr_context(corpus, provided)], answer, [], False,
                "partial_context/sibling_paragraph/v1", f"ecfr:{sec.number}", snap,
                {"subtype": "sibling_paragraph", "requested_identifier": requested.citation, "provided_source": provided.key},
            ))
            break
    return out


# ------------------------------------------------------- guidance mismatch


def gen_guidance_mismatch(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """Binding/non-binding mismatches in both directions.

    Stage 12 produced answers that labelled an eCFR regulation as non-binding
    guidance. These examples make the distinction a thing the model must check
    against the supplied source rather than a phrase it appends.
    """
    snap = corpus.snapshot_date
    q = cfg.quality
    out: list[TrainingExample] = []
    cap = max(cfg.category_targets().get("guidance_mismatch", 0), 40) + 30

    # asked for a regulation, given guidance
    docs = _ordered([d for d in corpus.guidance if any(recommendation_sentence(c) for c in d.recommendation_chunks)], "gm_docs")
    for doc in docs[: cap // 2]:
        chunk = next(c for c in doc.recommendation_chunks if recommendation_sentence(c))
        anchor = doc.anchor_section or (f"Part {doc.anchor_part}" if doc.anchor_part else None)
        topic = clean(doc.title).rstrip(".")
        question = pick(
            [
                f"What does the regulation require regarding {quote(topic)}?",
                f"Which binding requirement applies to {quote(topic)}?",
                f"What does the eCFR require about the subject of {quote(topic)}?",
            ],
            "gm_reg_q", doc.url,
        )
        where = f"It relates to 21 CFR {anchor} but does not reproduce that regulation's text, so it" if anchor else "It"
        answer = (
            f"The provided source is FDA guidance, {quote(doc.title)} [1], which represents the agency's current "
            f"thinking and is not binding. {where} {CANNOT_ESTABLISH} a regulatory requirement, and I cannot state "
            "what the regulation requires from this source."
        )
        out.append(TrainingExample(
            "abstention", "guidance_mismatch", question, [guidance_context(doc, chunk)], answer, [], False,
            "guidance_mismatch/regulation_asked_guidance_given/v1", f"guidance:{doc.url}", snap,
            {"subtype": "regulation_asked_guidance_given", "provided_source": doc.chunk_key(chunk)},
        ))

    # asked for a recommendation, given a regulation
    for sec in _ordered(_live_sections(corpus), "gm_secs")[: cap // 2]:
        rec = _first_clean_record(sec, q.min_paragraph_chars, q.max_paragraph_chars)
        topic = heading_topic(sec.heading)
        if rec is None or not topic:
            continue
        question = pick(
            [
                f"What does FDA recommend regarding {topic}?",
                f"What is FDA's non-binding recommendation about {topic}?",
                f"Which FDA guidance recommendation covers {topic}?",
            ],
            "gm_guid_q", sec.number,
        )
        answer = (
            f"The provided source is {_cite(rec)} [1], a binding eCFR regulation rather than FDA guidance. It states "
            f"a legal requirement, not a recommendation, so it {CANNOT_ESTABLISH} what FDA recommends about {topic}."
        )
        out.append(TrainingExample(
            "abstention", "guidance_mismatch", question, [ecfr_context(corpus, rec)], answer, [], False,
            "guidance_mismatch/guidance_asked_regulation_given/v1", f"ecfr:{sec.number}", snap,
            {"subtype": "guidance_asked_regulation_given", "provided_source": rec.key},
        ))
    return out


# ------------------------------------------------------ citation grounding


def gen_citation_grounding(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """The answer is supported, but only by one source among distractors.

    This is the counterweight to the abstention categories. The question is
    answerable and must be answered, citing only the source that supports it
    and leaving the legitimate but irrelevant neighbours uncited.
    """
    snap = corpus.snapshot_date
    q = cfg.quality
    pool = _distractor_pool(corpus, cfg)
    if len(pool) < 3:
        return []
    out: list[TrainingExample] = []
    cap = max(cfg.category_targets().get("citation_grounding", 0), 60) + 40
    per_section: Counter[str] = Counter()
    for i, sec in enumerate(_ordered(_live_sections(corpus), "cite_ground")):
        if len(out) >= cap:
            break
        target = _first_clean_record(sec, q.min_paragraph_chars, q.max_paragraph_chars)
        if target is None or per_section[sec.number]:
            continue
        d1 = pool[_pair_index("cg_a", i, len(pool))]
        d2 = pool[_pair_index("cg_b", i, len(pool))]
        # three genuinely distinct passages, spanning at least two parts so the
        # distractors are not simply neighbouring paragraphs of the target
        if len({d1.key, d2.key, target.key}) < 3 or len({d1.part, d2.part, sec.part}) < 2:
            continue
        total = sum(len(clean(r.text)) for r in (d1, target, d2))
        if total > q.max_context_chars:
            continue
        per_section[sec.number] += 1
        # the supporting source is placed second so position cannot be the cue
        context = [ecfr_context(corpus, d1), ecfr_context(corpus, target), ecfr_context(corpus, d2)]
        topic = heading_topic(sec.heading)
        options = [f"What does {target.citation} provide?", f"What does {sec.citation} state?"]
        if topic:
            options.append(f"Which of the provided sources addresses {topic}, and what does it say?")
        question = pick(options, "cg_q", target.key)
        answer = (
            f"{target.citation} [2], {quote(sec.heading)}, provides: {strip_label(target.text)} "
            f"The other provided sources, {_cite(d1)} and {_cite(d2)}, do not address this and are not cited."
        )
        out.append(TrainingExample(
            "regulatory_qa", "citation_grounding", question, context, answer, [target.citation], True,
            "citation_grounding/one_of_three/v1", f"ecfr:{sec.number}", snap,
            {"subtype": "one_of_three", "supporting_source": target.key, "distractors": [d1.key, d2.key]},
        ))
    return out


STAGE13_GENERATORS = {
    "context_mismatch": gen_context_mismatch,
    "wrong_context": gen_wrong_context,
    "partial_context": gen_partial_context,
    "guidance_mismatch": gen_guidance_mismatch,
    "citation_grounding": gen_citation_grounding,
}
