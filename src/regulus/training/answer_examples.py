"""Stage 14 training categories that counter the Stage 13 over-correction.

Stage 13 fixed grounding and broke answering. Of its 20 scored failures, 14
shared one shape: the model described which documents had been retrieved and
what their legal status was, then stopped, instead of answering the question.
Asked "What is the purpose of the FDA?" it replied that the sources do not
establish what the FDA is.

The cause is visible in the v2 data. Every one of its 2,000 refusal examples
opens the same way, "The provided source is X [1], which ...", so that opening
was reinforced 2,000 times while no example ever demonstrated extracting a
usable answer from thin or partly relevant context. The model learned the
frame rather than the judgment.

These categories supply the missing half:

  grounded_definition   a defining passage among distractors; answer from it,
                        leading with the substance rather than with source
                        commentary
  grounded_topic        a topical question whose answer is in one retrieved
                        passage among distractors
  guidance_answer       a guidance question answered from guidance, labelled
                        non-binding, without refusing

All three answer. They exist to keep the refusal categories from becoming the
only pattern the model knows.
"""

from __future__ import annotations

from collections import Counter

from regulus.training.config import TrainingConfig
from regulus.training.generators import (
    _first_clean_record,
    _live_sections,
    definition_answer,
    ecfr_context,
    guidance_context,
    recommendation_sentence,
    scope_sentence,
)
from regulus.training.grounding_examples import _distractor_pool, _pair_index
from regulus.training.models import TrainingExample
from regulus.training.negatives import _ordered
from regulus.training.sources import Corpus
from regulus.training.text import clean, heading_topic, pick, quote, strip_label

# Openings that lead with the answer. Deliberately none of them begin with
# "The provided source is", which is the v2 refusal frame the model overused.
NONBINDING_TAIL = "This is FDA guidance, which is non-binding, rather than a codified requirement."


def _plain_term(term: str) -> str:
    return clean(term).strip('"“”‘’\'')


def gen_grounded_definition(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """Define a term from the one passage that defines it, among distractors.

    The answer starts with the term and its definition, not with a description
    of the retrieved documents.
    """
    q = cfg.quality
    snap = corpus.snapshot_date
    pool = _distractor_pool(corpus, cfg)
    if len(pool) < 3:
        return []
    out: list[TrainingExample] = []
    cap = max(cfg.category_targets().get("grounded_definition", 0), 60) + 60
    per_section: Counter[str] = Counter()
    for i, d in enumerate(_ordered(corpus.definitions, "grounded_def")):
        if len(out) >= cap:
            break
        rec, term = d.record, _plain_term(d.term)
        if not term or len(term) > 80 or per_section[rec.section] >= 3:
            continue
        body = _plain_term(strip_label(rec.text))
        core = definition_answer(rec.citation, term, body)
        if core is None:
            continue
        d1 = pool[_pair_index("gd_a", i, len(pool))]
        d2 = pool[_pair_index("gd_b", i, len(pool))]
        if len({d1.key, d2.key, rec.key}) < 3 or len({d1.part, d2.part, rec.part}) < 2:
            continue
        if sum(len(clean(r.text)) for r in (d1, rec, d2)) > q.max_context_chars:
            continue
        per_section[rec.section] += 1
        context = [ecfr_context(corpus, d1), ecfr_context(corpus, rec), ecfr_context(corpus, d2)]
        question = pick(
            [
                f"What does {quote(term)} mean in 21 CFR {rec.section}?",
                f"Define {quote(term)} as used in 21 CFR Part {rec.part}.",
                f"Using the provided sources, what is the definition of {quote(term)}?",
            ],
            "gd_q", rec.key, term,
        )
        # core already reads "Under <citation> [1], ..." so renumber to [2]
        answer = core.replace("[1]", "[2]", 1) + f" The other provided sources, {d1.citation} and {d2.citation}, do not define this term."
        out.append(TrainingExample(
            "regulatory_qa", "grounded_definition", question, context, answer, [rec.citation], True,
            "grounded_definition/one_of_three/v1", f"ecfr:{rec.section}", snap,
            {"subtype": "definition_among_distractors", "supporting_source": rec.key, "distractors": [d1.key, d2.key]},
        ))
    return out


def gen_grounded_topic(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """Answer a topical question from the single passage that addresses it.

    Unlike citation_grounding in v2, the answer opens with the regulatory
    substance and only afterwards names the citation, so the model practises
    committing to an answer.
    """
    q = cfg.quality
    snap = corpus.snapshot_date
    pool = _distractor_pool(corpus, cfg)
    if len(pool) < 3:
        return []
    out: list[TrainingExample] = []
    cap = max(cfg.category_targets().get("grounded_topic", 0), 60) + 60
    for i, sec in enumerate(_ordered(_live_sections(corpus), "grounded_topic")):
        if len(out) >= cap:
            break
        topic = heading_topic(sec.heading)
        rec = _first_clean_record(sec, q.min_paragraph_chars, q.max_paragraph_chars)
        if rec is None or not topic or len(topic.split()) < 2:
            continue
        d1 = pool[_pair_index("gt_a", i, len(pool))]
        d2 = pool[_pair_index("gt_b", i, len(pool))]
        if len({d1.key, d2.key, rec.key}) < 3 or len({d1.part, d2.part, sec.part}) < 2:
            continue
        if sum(len(clean(r.text)) for r in (d1, rec, d2)) > q.max_context_chars:
            continue
        context = [ecfr_context(corpus, d1), ecfr_context(corpus, d2), ecfr_context(corpus, rec)]
        question = pick(
            [
                f"What do the provided sources establish about {topic}?",
                f"Which of the provided sources addresses {topic}, and what does it require?",
                f"Using the provided sources, what applies to {topic}?",
            ],
            "gt_q", rec.key,
        )
        answer = (
            f"{strip_label(rec.text)} That is {rec.citation} [3], {quote(sec.heading)}. "
            f"The other provided sources, {d1.citation} and {d2.citation}, do not address {topic}."
        )
        out.append(TrainingExample(
            "regulatory_qa", "grounded_topic", question, context, answer, [rec.citation], True,
            "grounded_topic/answer_first/v1", f"ecfr:{sec.number}", snap,
            {"subtype": "answer_first", "supporting_source": rec.key, "distractors": [d1.key, d2.key]},
        ))
    return out


def gen_guidance_answer(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """Answer a guidance question from guidance, labelled non-binding.

    v2 taught the model to refuse when a question asked for a regulation and
    the context was guidance. Without this counterpart it generalised to
    refusing whenever the context was guidance at all, which is most of the
    general-knowledge benchmark.
    """
    snap = corpus.snapshot_date
    out: list[TrainingExample] = []
    cap = max(cfg.category_targets().get("guidance_answer", 0), 60) + 60
    for doc in _ordered(corpus.guidance, "guidance_answer"):
        if len(out) >= cap:
            break
        chunk = next((c for c in doc.recommendation_chunks if recommendation_sentence(c)), None)
        sentence = recommendation_sentence(chunk) if chunk else None
        kind = "recommendation"
        if sentence is None:
            chunk = next((c for c in doc.intro_chunks if scope_sentence(c)), None)
            sentence = scope_sentence(chunk) if chunk else None
            kind = "scope"
        if sentence is None:
            continue
        topic = clean(doc.title).rstrip(".")
        question = pick(
            [
                f"According to FDA guidance, what applies to {quote(topic)}?",
                f"What does FDA say about the subject of {quote(topic)}?",
                f"Using the provided guidance, what does FDA advise regarding {quote(topic)}?",
            ],
            "ga_q", doc.url,
        )
        answer = f"{sentence} That is from the FDA guidance {quote(doc.title)} [1]. {NONBINDING_TAIL}"
        out.append(TrainingExample(
            "regulatory_qa", "guidance_answer", question, [guidance_context(doc, chunk)], answer, [doc.citation], True,
            f"guidance_answer/{kind}/v1", f"guidance:{doc.url}", snap,
            {"subtype": kind, "supporting_source": doc.chunk_key(chunk)},
        ))
    return out


STAGE14_GENERATORS = {
    "grounded_definition": gen_grounded_definition,
    "grounded_topic": gen_grounded_topic,
    "guidance_answer": gen_guidance_answer,
}
