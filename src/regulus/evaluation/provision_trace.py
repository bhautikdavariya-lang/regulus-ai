"""Per-required-provision stage attribution from a measurement record (regulus.traceability.measurement).

For each provision a question requires, the first stage it fails to pass:

    corpus_gap       the section is not in the corpus (only when the caller passes the corpus's sections)
    not_retrieved    no candidate is the provision or one of its subparagraphs
    dropped          a candidate was, but selection left it out; `drop_reasons` are the selector's own
                     (soft_budget, max_results, filtered, hard_ceiling_*)
    in_prompt        it reached the prompt but the delivered answer does not cite it
    cited            the delivered answer cites it

A candidate counts for a provision when it IS the provision or one of its subparagraphs: "21 CFR 70.3" is met by
any paragraph of 70.3, "21 CFR 70.3(f)" by (f) and (f)(1)..., never by (g) or by the section's lead-in. The record's
selection (selected + dropped) lists every candidate the selector saw, so it is the candidate list used here; the
record's retrieval_ranking holds only the top-k passed on.

Which provisions a question requires comes from the caller. The benchmark's draft citations are NOT expert-verified:
pass `key_status` so every trace says what its key is."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

STAGE_CORPUS_GAP = "corpus_gap"
STAGE_NOT_RETRIEVED = "not_retrieved"
STAGE_DROPPED = "dropped"
STAGE_IN_PROMPT = "in_prompt"
STAGE_CITED = "cited"
STAGES = (STAGE_CORPUS_GAP, STAGE_NOT_RETRIEVED, STAGE_DROPPED, STAGE_IN_PROMPT, STAGE_CITED)

KEY_DRAFT = "draft_unverified"
KEY_VERIFIED = "expert_verified"

_LABEL_RE = re.compile(r"(?:21\s+CFR\s+)?(\d{1,4}\.\d{1,4}[a-z]?)((?:\([^()\s]+\))*)", re.I)


def parse_provision(label: str | None) -> tuple[str, str] | None:
    """("70.3", "(f)") from "21 CFR 70.3(f)" or "70.3(f)"; None for anything that is not a CFR section label
    (a guidance document, a part)."""
    m = _LABEL_RE.fullmatch((label or "").strip())
    return (m.group(1), m.group(2) or "") if m else None


def covers(candidate: tuple[str, str] | None, provision: tuple[str, str]) -> bool:
    """The candidate row is the provision or one of its subparagraphs."""
    return candidate is not None and candidate[0] == provision[0] and candidate[1].startswith(provision[1]) \
        and bool(candidate[1] or not provision[1])


@dataclass(frozen=True)
class ProvisionTrace:
    question_id: str
    provision: str
    stage: str
    key_status: str
    candidate_rank: int | None = None        # first candidate covering it, 1-based, in the selector's order
    drop_reasons: tuple[str, ...] = ()
    prompt_indices: tuple[int, ...] = ()     # SOURCE numbers covering it
    cited_indices: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _candidates(record: dict[str, Any]) -> list[tuple[str, str | None]]:
    """(citation, drop reason or None) for every candidate the selector saw, selected ones first in prompt order,
    then dropped ones in the order the selector recorded them."""
    sel = ((record.get("evidence") or {}).get("selection")) or {}
    return [(s.get("citation"), None) for s in sel.get("selected") or ()] + \
           [(d.get("citation"), d.get("reason")) for d in sel.get("dropped") or ()]


def trace_record(record: dict[str, Any], provisions: Iterable[str], *, key_status: str = KEY_DRAFT,
                 corpus_sections: set[str] | None = None) -> list[ProvisionTrace]:
    qid = str(record.get("question_id"))
    items = (((record.get("evidence") or {}).get("snapshot")) or {}).get("items") or ()
    prompt = [(int(i["index"]), parse_provision(i.get("citation"))) for i in items]
    cited = {int(n) for c in record.get("citations") or () if c.get("cited_in_answer")
             for n in (c.get("indices") or [c.get("index")]) if n is not None}
    candidates = [(parse_provision(c), reason) for c, reason in _candidates(record)]
    out = []
    for label in dict.fromkeys(provisions):
        want = parse_provision(label)
        if want is None:
            continue
        in_prompt = tuple(n for n, p in prompt if covers(p, want))
        ranks = [n for n, (p, _) in enumerate(candidates, start=1) if covers(p, want)]
        reasons = tuple(dict.fromkeys(r for p, r in candidates if covers(p, want) and r))
        if corpus_sections is not None and want[0] not in corpus_sections:
            stage = STAGE_CORPUS_GAP
        elif in_prompt:
            stage = STAGE_CITED if cited & set(in_prompt) else STAGE_IN_PROMPT
        elif ranks:
            stage = STAGE_DROPPED
        else:
            stage = STAGE_NOT_RETRIEVED
        out.append(ProvisionTrace(qid, label, stage, key_status, ranks[0] if ranks else None, reasons,
                                  in_prompt, tuple(sorted(cited & set(in_prompt)))))
    return out


def summarise(traces: Iterable[ProvisionTrace]) -> dict[str, Any]:
    """Stage counts, drop-reason counts and the key status mix; one provision is one count."""
    traces = list(traces)
    return {
        "provisions": len(traces),
        "questions": len({t.question_id for t in traces}),
        "stages": {s: sum(1 for t in traces if t.stage == s) for s in STAGES},
        "drop_reasons": dict(Counter(r for t in traces if t.stage == STAGE_DROPPED for r in t.drop_reasons)),
        "key_status": dict(Counter(t.key_status for t in traces)),
    }
