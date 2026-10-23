"""Section-resolution benchmark: does the system put the section(s) that answer a question into the evidence?

Why this exists (23 Oct 2026): on the frozen cosmetics holdout, 18 of 63 non-PASS answers came from a wrong section
pick, and in 15 of those the right section was among the picker's candidates. Picks were only measured after a full
answer run. This module measures section resolution on its own, over every section of the cosmetics programme
(21 CFR Parts 70-82 and 700-740) and of the FD&C Act store, in minutes and without generating any answer.

Two kinds of rows (data/evaluation/datasets/section_resolution_v1.jsonl):
  * bank: the 277 cosmetics bank questions, their gold parsed from the verified key. Split "dev" (the 200 questions
    already run: seen-100 and holdout-100) or "sealed" (the 77 never run; scored only with --unseal, once, at the end).
  * synthetic: questions written for every section and checked by a separate adversarial reviewer (kept or relabelled
    only); "acceptable" holds the other sections the reviewer confirmed answer it as well.

Metrics per row, over the sections a resolution promotes (sections, their siblings and the FD&C Act sections) or that
the question names itself:
  hit       - a gold (or acceptable) section is promoted. The holdout's "pick right".
  primary   - the primary gold section is promoted.
  cover     - every in-scope section the answer needs is promoted or a companion.
  cand_rank - the primary gold's rank among the candidates offered (None: not offered).
Questions the pipeline never promotes for (named sections, out of scope) are recorded with their method.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

KEY_FIELD = "Expected Citation — VERIFIED KEY"
QUESTION_FIELD = "Question (ask verbatim)"
STATUTE_SECTIONS = frozenset({"201", "301", "704"} | {str(n) for n in range(601, 615)})
_CFR = re.compile(r"(?<![\d.])(\d{1,4}\.\d+[a-z]?)(?![\d])")
_USC = re.compile(r"21\s*U\.?S\.?C\.?\s*§*\s*(\d{3}[a-z]{0,2})(?:\([^)]*\))*", re.I)
_ACT_NUM = re.compile(r"(?<![\d.])(201|301|704|60[1-9]|61[0-4])(?![\d.])")


def section_of(citation: str) -> str:
    """'70.3(v)' -> '70.3'; '605(e)' -> '605'; '21 CFR 74.2101' -> '74.2101'."""
    c = re.sub(r"^(?:21\s+CFR|FD&C\s+Act\s*§?)\s*", "", (citation or "").strip(), flags=re.I)
    return re.sub(r"\(.*$", "", c).strip()


def parse_key(key: str, usc_to_fdca: dict[str, str]) -> list[str]:
    """The sections a verified key cites, in order: CFR sections ("21 CFR 74.2101(c)(1)") and FD&C Act sections
    ("FD&C Act 605(e)", "606", "21 U.S.C. 364a" -> 605). U.S.C. numbers are never read as Act numbers."""
    text = key or ""
    out: list[str] = []
    found: list[tuple[int, str]] = []
    for m in _USC.finditer(text):
        fd = usc_to_fdca.get(m.group(1).lower())
        if fd:
            found.append((m.start(), fd))
    rest = _USC.sub(lambda m: " " * len(m.group(0)), text)
    if re.search(r"CFR|\bPart", rest):
        found += [(m.start(), m.group(1)) for m in _CFR.finditer(rest)]
    rest = _CFR.sub(lambda m: " " * len(m.group(0)), rest)
    if re.search(r"FD&C|FDCA|\bAct\b|U\.S\.C", text):
        found += [(m.start(), m.group(1)) for m in _ACT_NUM.finditer(rest)]
    for _, s in sorted(found):
        if s not in out:
            out.append(s)
    return out


def bank_rows(bank: list[dict], dev_ids: Iterable[str], sealed_ids: Iterable[str],
              usc_to_fdca: dict[str, str], in_scope: Callable[[str], bool]) -> list[dict]:
    dev, sealed = set(dev_ids), set(sealed_ids)
    rows = []
    for q in bank:
        gold = parse_key(q.get(KEY_FIELD) or "", usc_to_fdca)
        sec = str(q.get("Section") or "")
        primary = sec if _CFR.fullmatch(sec) else (sec.split("-", 1)[1] if sec.startswith("FDCA-") else None)
        if primary not in gold:
            primary = next((g for g in gold if in_scope(g)), gold[0] if gold else None)
        rows.append({"id": q["ID"], "source": "bank", "split": "dev" if q["ID"] in dev else ("sealed" if q["ID"] in sealed else "other"),
                     "question": q[QUESTION_FIELD], "primary": primary, "gold": gold, "acceptable": [],
                     "needs": [g for g in gold if in_scope(g)], "out_of_scope_gold": [g for g in gold if not in_scope(g)],
                     "intent": None, "style": q.get("Question Type"), "names_part": bool(re.search(r"\bPart\s+\d", q[QUESTION_FIELD])),
                     "part": "FDCA" if primary in STATUTE_SECTIONS else (primary.split(".")[0] if primary else None)})
    return rows


def synthetic_rows(gen_dir: Path, verify_dir: Path, in_scope: Callable[[str], bool],
                   reinstate: Iterable[str] = ()) -> tuple[list[dict], dict]:
    """Writer questions joined with the reviewer's checks: kept and relabelled rows only; leaking, unrealistic or
    unanswered ones are dropped (the counts are returned). `reinstate`: qids a reviewer dropped as leaks only for naming
    the substance or product its heading names, with the gold confirmed (an explicit, recorded override)."""
    rows, stats = [], Counter()
    reinstate = set(reinstate)
    for gf in sorted(Path(gen_dir).glob("batch_*.json")):
        gen = json.loads(gf.read_text())
        vf = Path(verify_dir) / gf.name
        checks = {c["qid"]: c for c in json.loads(vf.read_text())["checks"]} if vf.exists() else {}
        for q in gen["questions"]:
            c = checks.get(q["qid"])
            stats["written"] += 1
            if c is None:
                stats["unchecked"] += 1
                continue
            verdict = c.get("verdict")
            if q["qid"] in reinstate and c.get("gold") in ("yes", "partial"):
                c = {**c, "verdict": "keep", "leak": False}
                verdict = "keep"
                stats["reinstated"] += 1
            if verdict == "drop" or c.get("leak") or c.get("realistic") == "no" or (verdict == "keep" and c.get("gold") == "no"):
                stats["dropped"] += 1
                continue
            primary = section_of(q["section"])
            if verdict == "relabel":
                if not c.get("relabel_to"):
                    stats["dropped"] += 1
                    continue
                primary = section_of(c["relabel_to"])
                stats["relabelled"] += 1
            else:
                stats["kept"] += 1
            acceptable = [section_of(a["section"]) for a in c.get("alternatives") or () if a.get("relation") in ("equal", "better")]
            acceptable += [section_of(a) for a in q.get("also_answered_by") or ()]
            if verdict == "relabel":
                acceptable.append(section_of(q["section"]))
            acceptable = [a for a in dict.fromkeys(acceptable) if a != primary]
            needs = [primary] + [section_of(n) for n in q.get("needs_also") or ()]
            rows.append({"id": q["qid"], "source": "synthetic", "split": "synthetic", "question": q["question"],
                         "primary": primary, "gold": [primary], "acceptable": acceptable,
                         "needs": [n for n in dict.fromkeys(needs) if in_scope(n)],
                         "out_of_scope_gold": [n for n in needs if not in_scope(n)],
                         "intent": q.get("intent"), "style": q.get("style"), "names_part": bool(q.get("names_part")),
                         "part": "FDCA" if primary in STATUTE_SECTIONS else primary.split(".")[0],
                         "gold_paragraphs": q.get("gold_paragraphs") or [], "review": {"gold": c.get("gold"), "note": c.get("note")}})
    return rows, dict(stats)


# ---------------------------------------------------------------------------------------------- resolution of one row


@dataclass
class Resolved:
    method: str                      # named | named_statute | picker | lexical | resolver | none | not_allowed | error
    candidates: list[str]
    promoted: list[str]              # sections + statute (+ the sections the question names itself)
    companions: list[str]            # companion sections (paragraph citations reduced to their section)
    raw: str | None = None
    detail: dict[str, Any] | None = None


def resolve_row(pipe, question: str, mode: str = "production") -> Resolved:
    """How the pipeline resolves this question's sections, gated exactly as RagPipeline.answer() gates promotion
    (RagPipeline.promotion_request). mode "production": SectionPromoter.resolve (the configured method; the picker
    needs a real generator). mode "candidates": the candidate list only (SectionPromoter.prepare), nothing picked."""
    from regulus.planning import plan_query

    plan = plan_query(question)
    named = [r.reference.section for r in plan.requirements if r.reference.section is not None]
    promoter, allowed, parts, error = pipe.promotion_request(question, plan, require_model=(mode == "production"))
    if named and not allowed:
        return Resolved("named", [], named, [])
    if promoter is None:
        return Resolved("not_allowed" if not allowed else "none", [], [], [], detail={"error": error})
    named_only = allowed == "named_statute"
    try:
        if mode == "candidates":
            prepared = promoter.prepare(question, parts, named_only)
            if prepared is None:
                return Resolved("none", [], [], [])
            if not isinstance(prepared, tuple):   # an FD&C Act section the question names
                return Resolved(prepared.method, [], list(prepared.statute), [])
            return Resolved("candidates", [c["section"] for c in prepared[1]], [], [])
        pr = promoter.resolve(question, parts=parts, named_only=named_only)
    except Exception as exc:  # noqa: BLE001 - recorded, never hidden
        return Resolved("error", [], [], [], detail={"error": f"{type(exc).__name__}: {exc}"[:300]})
    if pr is None:
        return Resolved("none", [], [], [])
    return Resolved(pr.method, [c["section"] if isinstance(c, dict) else str(c) for c in (pr.candidates or ())],
                    list(pr.sections) + list(pr.statute), [section_of(c) for c in pr.companions], pr.picker_output,
                    detail={"notes": list(pr.notes), "rerank": {s: list(v) for s, v in
                                                                (getattr(promoter, "last_rerank", None) or {}).items()}} if pr.notes else None)


def score_row(row: dict, res: Resolved) -> dict:
    good = {row["primary"], *row["gold"], *row["acceptable"]} - {None}
    promoted = set(res.promoted)
    have = promoted | set(res.companions)
    primary = row["primary"]
    rank = res.candidates.index(primary) + 1 if primary in res.candidates else None
    best = min((res.candidates.index(g) + 1 for g in good if g in res.candidates), default=None)
    acts = [c for c in res.candidates if c in STATUTE_SECTIONS]
    act_rank = min((acts.index(g) + 1 for g in good if g in acts), default=None)
    return {"id": row["id"], "source": row["source"], "split": row["split"], "method": res.method,
            "hit": bool(promoted & good), "primary": primary in promoted, "cover": all(n in have for n in row["needs"]),
            "cand_rank": rank, "best_cand_rank": best, "act_rank": act_rank, "n_candidates": len(res.candidates), "n_promoted": len(promoted),
            "promoted": sorted(promoted), "companions": res.companions, "raw": res.raw, "detail": res.detail}


# ---------------------------------------------------------------------------------------------- summaries


def _rate(xs: list[bool]) -> str:
    return f"{sum(xs)}/{len(xs)}" if xs else "0/0"


def summarize(rows: list[dict], scored: list[dict]) -> dict[str, Any]:
    by_id = {r["id"]: r for r in rows}
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in scored:
        r = by_id[s["id"]]
        corpus = "fdca" if r["primary"] in STATUTE_SECTIONS else "cfr"
        keys = [f"all:{r['split']}", f"corpus:{r['split']}:{corpus}", f"names_part:{r['split']}:{r['names_part']}"]
        if r["source"] == "synthetic":
            keys += [f"style:{r['style']}", f"intent:{r['intent']}", f"part:{r['part']}"]
        for k in keys:
            groups[k].append(s)
    out = {}
    for k in sorted(groups):
        g = groups[k]
        ranks = [s["best_cand_rank"] for s in g]
        out[k] = {"n": len(g), "hit": _rate([s["hit"] for s in g]), "primary": _rate([s["primary"] for s in g]),
                  "cover": _rate([s["cover"] for s in g]),
                  "cand@1": _rate([r == 1 for r in ranks]), "cand@3": _rate([r is not None and r <= 3 for r in ranks]),
                  "cand@10": _rate([r is not None and r <= 10 for r in ranks]), "cand@any": _rate([r is not None for r in ranks]),
                  "act@1": _rate([s.get("act_rank") == 1 for s in g]), "act@3": _rate([(s.get("act_rank") or 99) <= 3 for s in g]),
                  "methods": dict(Counter(s["method"] for s in g)),
                  "mean_promoted": round(sum(s["n_promoted"] for s in g) / len(g), 2)}
    return out


def compare(a: list[dict], b: list[dict], metric: str = "hit") -> dict[str, Any]:
    """Rows whose metric changed from run a to run b (gained / lost), by id."""
    A, B = {s["id"]: s for s in a}, {s["id"]: s for s in b}
    gained = sorted(i for i in A.keys() & B.keys() if not A[i][metric] and B[i][metric])
    lost = sorted(i for i in A.keys() & B.keys() if A[i][metric] and not B[i][metric])
    changed = sorted(i for i in A.keys() & B.keys() if A[i]["promoted"] != B[i]["promoted"])
    return {"metric": metric, "gained": gained, "lost": lost, "n_promoted_changed": len(changed), "promoted_changed": changed}
