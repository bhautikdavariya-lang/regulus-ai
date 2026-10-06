"""Evidence-supply experiment: control vs ES-1 (question-directed evidence admission).

One independent variable: **which of the already-available candidates gets the prompt budget.**
The model, the prompt builder, the prompt text, decoding, validation, repair, the rubric and the
question set are all unchanged, and so is every budget number - the treatment reallocates the same
budget rather than enlarging it. This is deliberately *not* H4: no selected section is expanded to
its full text, and no ceiling is raised.

Arms:

  control    production, exactly as the acceptance run was configured.

  es1        two edits, both inside evidence admission:
             E1  a whole-part request's section listing is ordered by the question's own relevance
                 (the database's `ts_rank_cd` restricted to that part) instead of by section number.
                 Production's `ECFR_EXACT_PART` is `ORDER BY r.section_number` with a LIMIT, so the
                 sections that reach the prompt are the ASCII-first ones and are the same whatever
                 the question asks. Same hard ceiling, different choice.
             E2  an eCFR candidate found by section-number/heading trigram is no longer discarded by
                 the `min_trigram_similarity` cut-off; it competes for the budget on relevance.
                 Measured: on the affected rows the governing section's similarity sits at
                 0.316-0.397 against a 0.400 threshold.

  es1_deep   es1 plus deeper candidate generation, `top_k` 8 -> 48. Retrieval depth costs database
             time, not prompt tokens; the prompt budget is still untouched.

Nothing under `src/regulus` is modified. The arms are installed in-process by wrapping
`regulus.rag.pipeline.select_evidence` (the name the pipeline calls at pipeline.py:341), the same
technique `scripts/d1_experiment.py` uses, and by copying the config dataclass. The wrapper calls the
real `select_evidence`; it never reimplements selection.

Generation budget is pinned to the control arm's own per-question allowance on treatment arms, so a
change in evidence size cannot buy extra tokens and confound the comparison (the rule phase D1
established).

    .venv/bin/python scripts/es_experiment.py --arm control
    .venv/bin/python scripts/es_experiment.py --arm es1      --pin-from artifacts/stage_b/run_control.jsonl
    .venv/bin/python scripts/es_experiment.py --arm es1_deep --pin-from artifacts/stage_b/run_control.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.config.settings import load_settings  # noqa: E402
from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark  # noqa: E402
from regulus.rag import RagPipeline  # noqa: E402
from regulus.rag import pipeline as pipeline_mod  # noqa: E402
from regulus.rag.generation import build_grounded_messages  # noqa: E402
from regulus.rag.remote_generator import load_generator  # noqa: E402
from regulus.rag.selection import is_required  # noqa: E402
from regulus.retrieval import sql  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from regulus.retrieval.models import METHOD_TRIGRAM  # noqa: E402
from regulus.retrieval.query import fallback_terms  # noqa: E402
from regulus.system_identity import configured_generation_config, configured_rag_config  # noqa: E402

WORKBOOK = ROOT / "Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx"
SECTION_RE = re.compile(r"(\d{1,4})\.(\d+)")

# the question currently being answered, so the wrapper can score relevance. Single-threaded
# experiment; set immediately before each pipeline.answer call.
CURRENT: dict[str, object] = {"question": "", "qid": "", "parts": ()}


def section_of(label: str) -> str | None:
    m = SECTION_RE.search(label or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------
# E1 + E2: question-directed admission
# ---------------------------------------------------------------------------------------------
def part_relevance(db: Database, question: str, part: str, cache: dict) -> dict[str, float]:
    """section number -> the question's full-text rank within this part, from the database's own
    ranking function.

    The query text is built the way production builds its own free-text eCFR fallback -
    `fallback_terms` then `" or ".join(...)` - because `websearch_to_tsquery` ANDs its terms, and a
    whole question ANDed together matches nothing. Same ranking function, same term selection, same
    corpus; only the part filter is added.
    """
    key = (part, question)
    if key in cache:
        return cache[key]
    terms = fallback_terms(question, 8)
    if not terms:
        cache[key] = {}
        return {}
    rows = db.query(sql.ECFR_FULL_TEXT, {"query": " or ".join(terms), "part": part, "section": None,
                                         "subchapter": None, "limit": 500})
    best: dict[str, float] = {}
    for r in rows:
        s = r["section_number"]
        best[s] = max(best.get(s, 0.0), float(r["rank"]))
    cache[key] = best
    return best


def install_es1(db: Database) -> str:
    """Wrap `pipeline.select_evidence`. The real function does the selecting; this only decides the
    order the candidates are offered in, and relaxes one filter."""
    real = pipeline_mod.select_evidence
    cache: dict = {}

    def patched(registry, policy=None, *, optional_filter=None, material=None):
        question = str(CURRENT["question"])
        ev = list(registry.evidence)

        # --- E1: order a whole-part listing by the question's relevance -------------------------
        # Only when the plan asked for a whole part: then the required evidence is one row per
        # section with identical exact scores, and production's order is the ASCII section order.
        # A requested *section*'s own paragraphs must keep their document order, so they are
        # untouched.
        part_level = [r.reference.part for r in registry.plan.requirements if r.reference.section is None]
        reordered_required = False
        if part_level:
            rel: dict[str, float] = {}
            for p in part_level:
                rel.update(part_relevance(db, question, p, cache))
            pos = {id(e): i for i, e in enumerate(ev)}
            req = [e for e in ev if is_required(e)]
            rest = [e for e in ev if not is_required(e)]
            # a part listing is one row per distinct section. If the required set is really a single
            # section's own paragraphs, their document order is the meaning and must not be touched.
            if len({section_of(e.result.citation.label) for e in req}) > 1:
                req = sorted(req, key=lambda e: (-rel.get(section_of(e.result.citation.label) or "", 0.0),
                                                 pos[id(e)]))
                reordered_required = True
            ev = req + rest

        # --- E2: let a sub-threshold eCFR trigram hit compete instead of being dropped -----------
        def relaxed(result) -> bool:
            if optional_filter is None:
                return True
            if (result.corpus == "ecfr" and result.retrieval_method == METHOD_TRIGRAM
                    and not result.metadata.get("contextual_only")):
                return True
            return optional_filter(result)

        new_registry = dataclasses.replace(registry, evidence=tuple(ev))
        selection = real(new_registry, policy, optional_filter=relaxed, material=material)
        CURRENT["reordered_required"] = reordered_required
        return selection

    pipeline_mod.select_evidence = patched
    return ("ES-1: pipeline.select_evidence wrapped. E1 whole-part listings ordered by the question's "
            "ts_rank_cd within the part (budgets unchanged); E2 eCFR trigram hits exempt from the "
            "min_trigram_similarity cut-off and ranked on relevance.")


class PinnedGenerator:
    """Forces the control arm's own per-question token allowance, so a change in evidence size
    cannot grant the treatment more generation capacity (the confound phase D1 identified)."""

    def __init__(self, inner, budgets: dict[str, int]) -> None:
        self.inner, self.budgets = inner, budgets

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def generate(self, messages, max_new_tokens=None, on_text=None):
        pinned = self.budgets.get(str(CURRENT["qid"]))
        return self.inner.generate(messages, max_new_tokens=pinned or max_new_tokens, on_text=on_text)


# ---------------------------------------------------------------------------------------------
def record(qid: str, q, out, seconds: float, tok, keys: list[str]) -> dict:
    pkg = out.package
    sources = list(out.context.sources)
    prompt = "\n".join(m["content"] for m in build_grounded_messages(pkg)) if pkg is not None else ""
    ev_text = "\n".join(s.text for s in sources)
    labels = [s.result.citation.label for s in sources]
    secs = [section_of(x) for x in labels]
    paragraphs = [s.result.metadata.get("paragraph_path") or
                  (s.result.citation.label or "").split(" ")[-1] if s.result.corpus == "ecfr" else None
                  for s in sources]
    # did the governing provision reach the prompt, and with how many of its paragraphs
    present = {k: {"in_evidence": k in [x for x in secs if x],
                   "paragraphs_in_evidence": sum(1 for x in secs if x == k),
                   "named_in_prompt": bool(re.search(r"\b" + re.escape(k) + r"\b", prompt))}
               for k in keys}
    # a carve-out/applicability signal: evidence text that states an exception or a scope limit
    carve = [s.result.citation.label for s in sources
             if re.search(r"\b(except|does not apply|do not apply|unless|exempt)\b", s.text, re.I)]
    val = out.metadata.get("validation", {}) if isinstance(out.metadata, dict) else {}
    return {
        "question_id": qid,
        "question": q.question,
        "key_sections": keys,
        # --- evidence supplied -------------------------------------------------------------
        "selected_labels": labels,
        "selected_sections": secs,
        "selected_paragraphs": paragraphs,
        "evidence_order": list(range(1, len(sources) + 1)),
        "n_evidence_blocks": len(sources),
        "evidence_chars": sum(len(s.text) for s in sources),
        "evidence_tokens": (len(tok(ev_text)["input_ids"]) if ev_text else 0),
        "prompt_chars": len(prompt),
        "prompt_tokens": (len(tok(prompt)["input_ids"]) if prompt else 0),
        "prompt_sha16": sha(prompt),
        "evidence_sha16": sha(ev_text),
        "governing_presence": present,
        # The supply metric is the section's TEXT being among the selected evidence. A section
        # number can appear in the prompt because the question or a guidance chunk names it, with
        # none of its text supplied - measured on A-003/A-004 - so `named_in_prompt` is recorded
        # alongside but is never the metric.
        "governing_text_supplied": any(v["in_evidence"] for v in present.values()) if keys else None,
        "governing_named_in_prompt": any(v["named_in_prompt"] for v in present.values()) if keys else None,
        "carve_out_sources": carve,
        "carve_out_present": bool(carve),
        "reordered_required": bool(CURRENT.get("reordered_required")),
        # --- what the system then did ------------------------------------------------------
        "answer": out.answer,
        "raw_model_output": out.metadata.get("raw_model_output"),
        "model_called": out.model_called,
        "no_context": out.no_context,
        "citations": [c.to_dict() for c in out.citations],
        "answerability": (out.metadata.get("answerability") or {}).get("state") if isinstance(out.metadata.get("answerability"), dict) else out.metadata.get("answerability"),
        "fallback_type": out.metadata.get("fallback_type"),
        "validation_initial": out.metadata.get("validation_initial"),
        "validation_initial_codes": out.metadata.get("validation_initial_codes"),
        "validation_final": out.metadata.get("validation_final"),
        "repair": out.metadata.get("repair"),
        "stop_reason": out.metadata.get("stop_reason"),
        "generated_tokens": out.output_tokens,
        "max_new_tokens": getattr(pkg, "max_new_tokens", None),
        "coverage_state": getattr(out.coverage, "state", None),
        "seconds": round(seconds, 2),
        "timings_ms": out.timings_ms,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True, choices=["control", "es1", "es1_deep"])
    ap.add_argument("--subset", type=Path, default=ROOT / "artifacts/stage_b/subset_frozen.json")
    ap.add_argument("--ids", default=None, help="override: comma-separated ids (smoke tests)")
    ap.add_argument("--pin-from", type=Path, default=None, help="control run whose token allowance to pin")
    ap.add_argument("--rows", type=Path, default=ROOT / "artifacts/stage_b/phase1_rows.jsonl")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    out_path = args.out or ROOT / f"artifacts/stage_b/run_{args.arm}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ids = ([i.strip() for i in args.ids.split(",")] if args.ids
           else json.load(args.subset.open())["ids"])
    keys_by_id = {r["id"]: r["key_sections"] for r in
                  (json.loads(l) for l in args.rows.read_text().splitlines() if l.strip())}

    done = set()
    if out_path.exists():
        done = {json.loads(l)["question_id"] for l in out_path.read_text().splitlines() if l.strip()}
    todo = [i for i in ids if i not in done]
    print(f"arm={args.arm}  rows={len(ids)}  already done={len(done)}  to run={len(todo)}")

    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    base_cfg = configured_rag_config(settings)
    cfg = dataclasses.replace(base_cfg, top_k=48) if args.arm == "es1_deep" else base_cfg

    db = Database.from_env()
    db.connect()
    retriever, scope = build_retriever(db, cfg)
    generator = load_generator(settings, local_files_only=True)
    tok = generator.tokenizer

    notes = []
    if args.arm != "control":
        notes.append(install_es1(db))
    if args.arm == "es1_deep":
        notes.append("DEPTH: config.top_k 8 -> 48 (candidate generation only; prompt budget unchanged)")
    budgets: dict[str, int] = {}
    if args.pin_from and args.arm != "control":
        for line in args.pin_from.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("max_new_tokens"):
                    budgets[r["question_id"]] = r["max_new_tokens"]
        generator = PinnedGenerator(generator, budgets)
        notes.append(f"PINNED: generation allowance taken from {args.pin_from.name} for {len(budgets)} rows")
    for n in notes:
        print("  " + n)

    pipeline = RagPipeline(retriever, generator, cfg, scope_policy=scope)
    bench = {q.question_id: q for q in load_acceptance_benchmark(WORKBOOK)}

    meta = {
        "arm": args.arm, "notes": notes, "rows": len(ids),
        "config_fingerprint": cfg.to_dict(),
        "model": generator.describe() if hasattr(generator, "describe") else None,
        "subset": str(args.subset.relative_to(ROOT)) if not args.ids else f"ids={args.ids}",
        "pinned_from": str(args.pin_from) if args.pin_from else None,
    }
    (out_path.parent / f"meta_{args.arm}.json").write_text(json.dumps(meta, indent=2, default=str) + "\n")

    with out_path.open("a") as fh:
        for n, qid in enumerate(todo, 1):
            q = bench[qid]
            CURRENT.update({"question": q.question, "qid": qid, "reordered_required": False})
            t0 = time.perf_counter()
            try:
                out = pipeline.answer(q.question)
                row = record(qid, q, out, time.perf_counter() - t0, tok, keys_by_id.get(qid, []))
                row["error"] = None
            except Exception as exc:
                row = {"question_id": qid, "question": q.question, "error": f"{type(exc).__name__}: {exc}",
                       "seconds": round(time.perf_counter() - t0, 2)}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"  [{n:3}/{len(todo)}] {qid:8} gov_supplied={row.get('governing_text_supplied')!s:5} "
                  f"blocks={row.get('n_evidence_blocks')!s:3} ev_tok={row.get('evidence_tokens')!s:5} "
                  f"{row.get('seconds')}s {row.get('error') or ''}", flush=True)
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
