"""Stage 6 training generators: multi-provision, range and partial answers.

These are the behaviours Stage 5 measures and the earlier datasets never
contained. Every example is built from live cfr_records rows of one section
(the split group); the answer is one block per requested provision in the
order asked, each quoting that provision's row with its source number.

FAMILY: extractive_grounded
--------------------------
The answers here reproduce the authoritative provision text. That teaches
*grounded extraction*: say what the provision says, attribute it to the
right source, keep provisions separate, and say "not found" when one is
absent. It does NOT teach *faithful paraphrase*: explaining a provision in
new words without introducing an unsupported claim. No example in this
module paraphrases, so this dataset cannot teach or test paraphrase
faithfulness, and nothing here should be read as evidence that it does.
Paraphrase supervision would need targets whose faithfulness is verified
independently of the model that wrote them; that does not exist yet and is
recorded as a Stage 6 limitation rather than approximated with synthetic
paraphrases.

    multi_provision   "What do 21 CFR X(b)(1) and 21 CFR X(b)(2) require?"  (2 or 3 provisions)
    range_provision   "What do 21 CFR X(b)(1) through (b)(3) require?"      (3 or 4 consecutive)
    partial_provision one requested provision is proven absent from the section

Determinism: sections and paragraph groups are visited in sorted order and
every template choice comes from a stable hash of the group.
"""

from __future__ import annotations

import re
from typing import Iterator

from regulus.training.config import TrainingConfig
from regulus.training.generators import ecfr_context
from regulus.training.models import ContextItem, TrainingExample
from regulus.training.sources import Corpus, Record, Section
from regulus.training.text import stable_hash

_NUM_CHILD = re.compile(r"^(\([a-z]\))\((\d+)\)$")
_LETTER_PARENT = re.compile(r"^\([a-z]\)$")
MIN_TEXT_CHARS = 40
MAX_PER_SECTION = 2
MAX_ABSENT_SEARCH = 6  # child numbers past the last present one to test for absence
FAMILY = "extractive_grounded"
ANSWER_STYLE = "verbatim_quote"
NOT_FOUND = "not found in the available eCFR data."


def _clean(rec: Record, cfg: TrainingConfig) -> bool:
    t = rec.text.strip()
    if rec.is_reserved or len(t) < MIN_TEXT_CHARS or len(t) > cfg.quality.max_paragraph_chars:
        return False
    return "[reserved]" not in t.lower() and "http" not in t


def numbered_groups(section: Section, cfg: TrainingConfig) -> Iterator[tuple[str, Record | None, list[Record]]]:
    """(parent path, parent record or None, consecutive numbered children 1..n in order)."""
    by_parent: dict[str, dict[int, Record]] = {}
    parents: dict[str, Record] = {}
    for rec in section.records:
        m = _NUM_CHILD.match(rec.paragraph or "")
        if m and rec.path_ordinal == 0:
            by_parent.setdefault(m.group(1), {})[int(m.group(2))] = rec
        elif rec.path_ordinal == 0 and _LETTER_PARENT.match(rec.paragraph or ""):
            parents[rec.paragraph] = rec
    for parent in sorted(by_parent):
        kids = by_parent[parent]
        run: list[Record] = []
        n = 1
        while n in kids and _clean(kids[n], cfg):
            run.append(kids[n])
            n += 1
        if len(run) >= 2:
            yield parent, parents.get(parent), run


def present_paragraph_paths(section: Section) -> set[str]:
    """Every paragraph path that exists in this section's live records."""
    return {r.paragraph or "" for r in section.records}


def children_of(section: Section, parent: str) -> dict[int, str]:
    """{child number: paragraph path} for the numbered children of `parent`."""
    out: dict[int, str] = {}
    for rec in section.records:
        m = _NUM_CHILD.match(rec.paragraph or "")
        if m and m.group(1) == parent:
            out[int(m.group(2))] = rec.paragraph
    return out


def find_absent_child(section: Section, parent: str) -> tuple[int, str] | None:
    """A child number under `parent` that this section provably does not contain.

    Absence is decided by looking at the section's live records, never by
    arithmetic alone: the candidate path must be missing from the complete set
    of paragraph paths the snapshot holds for this section.
    """
    present = present_paragraph_paths(section)
    kids = children_of(section, parent)
    if not kids:
        return None
    start = max(kids) + 1
    for n in range(start, start + MAX_ABSENT_SEARCH):
        path = f"{parent}({n})"
        if path not in present and n not in kids:
            return n, path
    return None


def _label(rec: Record) -> str:
    return rec.citation


def _short(rec: Record) -> str:
    """Continuation form "(b)(2)" for lists inside one section."""
    return rec.paragraph


def _quote(text: str, index: int) -> str:
    """Provision text with its marker inside the sentence, as the Stage 4 contract expects."""
    body = text.strip()
    if body.endswith((".", "!", "?")):
        return f"{body[:-1]} [{index}]{body[-1]}"
    return f"{body} [{index}]."


def _blocks(records: list[Record], missing: str | None = None) -> str:
    lines = [f"{_label(r)}: {_quote(r.text, i)}" for i, r in enumerate(records, start=1)]
    if missing:
        lines.append(f"{missing}: {NOT_FOUND}")
    return "\n".join(lines)


def _clean_parent(parent: Record) -> bool:
    t = parent.text.strip()
    return 10 <= len(t) <= 1500 and "http" not in t


def _context(corpus: Corpus, records: list[Record], parent: Record | None) -> list[ContextItem]:
    items = [ecfr_context(corpus, r) for r in records]
    if parent is not None and _clean_parent(parent):
        items.append(ecfr_context(corpus, parent))
    return items


def _example(category: str, generator: str, corpus: Corpus, section: Section, question: str,
             records: list[Record], parent: Record | None, missing_meta: dict | None = None) -> TrainingExample:
    missing_label = missing_meta["requested_identifier"] if missing_meta else None
    extra = {
        "family": FAMILY,
        "answer_style": ANSWER_STYLE,
        "provisions": [_label(r) for r in records],
        "snapshot_date": corpus.snapshot_date,
        "prompt_format": "grounded",
    }
    if missing_meta:
        extra["missing_provision"] = missing_meta
    return TrainingExample(
        type="regulatory_qa", category=category, question=question, context=_context(corpus, records, parent),
        answer=_blocks(records, missing_label), citations=[_label(r) for r in records], grounded=True,
        generator=generator, group=section.number, snapshot_date=corpus.snapshot_date, extra=extra,
    )


def _sections(corpus: Corpus) -> list[Section]:
    return [s for _, s in sorted(corpus.sections.items()) if s.records and not s.is_reserved]


def gen_multi_provision(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    out: list[TrainingExample] = []
    for section in _sections(corpus):
        made = 0
        for parent, prec, run in numbered_groups(section, cfg):
            if made >= MAX_PER_SECTION:
                break
            h = int(stable_hash(section.number, parent, "multi")[:8], 16)
            if len(run) >= 3 and h % 3 == 0:
                picked = run[:3]
                a, b, c = picked
                question = [f"What do {_label(a)}, {_short(b)} and {_short(c)} require?",
                            f"What are the requirements of {_label(a)}, {_short(b)}, and {_short(c)}?",
                            f"Explain {_label(a)}, {_label(b)} and {_label(c)}."][h % 3]
            else:
                picked = [run[0], run[1]] if h % 2 == 0 or len(run) < 3 else [run[0], run[2]]
                a, b = picked
                question = [f"What do {_label(a)} and {_label(b)} require?",
                            f"What are the requirements of {_label(a)} and {_short(b)}?",
                            f"Compare the requirements of {_label(a)} and {_label(b)}.",
                            f"Explain {_label(a)} and {_short(b)}."][h % 4]
            out.append(_example("multi_provision", "gen_multi_provision", corpus, section, question, picked, prec))
            made += 1
    return out


def gen_range_provision(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    out: list[TrainingExample] = []
    for section in _sections(corpus):
        made = 0
        for parent, prec, run in numbered_groups(section, cfg):
            if len(run) < 3 or made >= MAX_PER_SECTION:
                continue
            h = int(stable_hash(section.number, parent, "range")[:8], 16)
            picked = run[:4] if len(run) >= 4 and h % 2 == 0 else run[:3]
            a, z = picked[0], picked[-1]
            question = [f"What do {_label(a)} through {_short(z)} require?",
                        f"List the requirements in {_label(a)}-{_short(z)}.",
                        f"Explain {_label(a)} through {_label(z)} one by one.",
                        f"What are the requirements of {_label(a)} to {_short(z)}?"][h % 4]
            out.append(_example("range_provision", "gen_range_provision", corpus, section, question, picked, prec))
            made += 1
    return out


def gen_partial_provision(corpus: Corpus, cfg: TrainingConfig) -> list[TrainingExample]:
    """One provision that exists plus one proven absent from the same section.

    The absent identifier is not inferred from arithmetic: `find_absent_child`
    checks the candidate paragraph path against every live paragraph path the
    snapshot holds for that section, and the example records that check.
    """
    out: list[TrainingExample] = []
    for section in _sections(corpus):
        made = 0
        for parent, prec, run in numbered_groups(section, cfg):
            if made >= 1:
                break
            found = find_absent_child(section, parent)
            if found is None:
                continue
            number, path = found
            kids = children_of(section, parent)
            missing_meta = {
                "requested_identifier": f"21 CFR {section.number}{path}",
                "section": section.number,
                "parent_paragraph": parent,
                "requested_child_number": number,
                "absent_verified": True,
                "absent_check": "candidate paragraph_path compared against every live paragraph path of this section in the snapshot",
                "section_live_paragraph_count": len(present_paragraph_paths(section)),
                "parent_children_present": [kids[n] for n in sorted(kids)],
                "snapshot_date": corpus.snapshot_date,
            }
            h = int(stable_hash(section.number, parent, "partial")[:8], 16)
            a = run[0] if h % 2 == 0 else run[-1]
            label = missing_meta["requested_identifier"]
            question = [f"What do {_label(a)} and {parent}({number}) require?",
                        f"What are the requirements of {_label(a)} and {label}?",
                        f"Explain {_label(a)} and {label}."][h % 3]
            out.append(_example("partial_provision", "gen_partial_provision", corpus, section, question, [a], prec, missing_meta=missing_meta))
            made += 1
    return out


STAGE6_GENERATORS = {
    "multi_provision": gen_multi_provision,
    "range_provision": gen_range_provision,
    "partial_provision": gen_partial_provision,
}
