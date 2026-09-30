"""Stage 6 generation experiments: the same model, the same evidence, different representations.

    python scripts/generation_experiments.py --variants base,h1,h1h2,h1h3,h1h2h3 [--ids ...]

Every diagnostic question the Stage 5 gate lets through is packaged under each
variant; the prompt is hashed and generated once per distinct prompt (greedy
decoding is deterministic, so an identical prompt gives an identical output:
outputs recorded by the Stage 5 run are reused when the prompt hash matches).
Each output is validated against the variant's own package and scored against
the keyed expectation of diagnostic_v1 (never edited). Retrieval, the model,
the database and the gate are untouched; only the package/prompt differs.

Variants (general, no question- or provision-specific rule):
  base  Stage 5 prompt
  h1    exact-evidence context: when every requested provision has exact evidence, the
        optional supporting/discovery sources are left out (only the protected evidence)
  h2    enumeration plan line gives the item count, not a copyable list of labels
  h1w   h1 (protected evidence only) applied only when every requested provision's exact text is a complete
        sentence (ends with a full stop) and the question is not a comparison; otherwise the Stage 5 context
  h1f   h1c plus the PARENT of a requested provision whose text is a sentence fragment
  h1c   like h1 (comparisons excepted), but the CHILDREN of a requested provision whose text is a lead-in (ends ":") are kept
  h1p   like h1 (comparisons excepted), but the structural PARENT of a requested provision is kept (its lead-in)
  h1s   like h1, but only SUPPORTING/DISCOVERY sources are left out (structural parents/children kept)
  h3    conditions are stated inside the source they belong to, not in a separate list

Output: artifacts/generation_quality/experiments_<utc>/ (results.jsonl, summary.json) and a
prompt-hash cache shared between runs (artifacts/generation_quality/generation_cache.jsonl).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.config import load_settings  # noqa: E402
from regulus.inference.types import GenerationResult  # noqa: E402
from regulus.observability.trace import sha256  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import RagPipeline, load_qwen_generator  # noqa: E402
from regulus.rag import generation as G  # noqa: E402
from regulus.rag.validation import validate_answer  # noqa: E402
from regulus.retrieval import Database, LexicalRetriever  # noqa: E402
from regulus.stage5.generation_eval import controlled_selection  # noqa: E402
from regulus.system_identity import configured_generation_config, configured_rag_config  # noqa: E402

DATASET = ROOT / "data/evaluation/datasets/diagnostic_v1.jsonl"
OUT = ROOT / "artifacts/generation_quality"
CACHE = OUT / "generation_cache.jsonl"
BASELINE = ROOT / "artifacts/diagnostics/stage5_final_20260929T093254Z/traces.jsonl"
WARNINGS = {"low_overlap_with_cited_source", "qualifier_dropped", "qualifier_misapplied", "applicability_dropped", "scope_expansion",
            "uncited_statement", "repeated_statement", "evidence_by_evidence", "prompt_echo"}

_ORIG_PLAN_LINES = G.plan_lines
_ORIG_RENDER_SOURCE = G.render_source
_CURRENT: dict = {}


def _plan_lines(plan, texts=None, *, h2=False, h3=False):
    lines = _ORIG_PLAN_LINES(plan, texts)
    out = []
    for line in lines:
        if h2 and line.startswith("  items, in order:"):
            n = line.count(";") + 1
            line = f"  items: {n}, one per source, in source order"
        if h3 and line.startswith("  conditions to keep:"):
            continue
        out.append(line)
    return out


def _render_source(source, requirements):
    text = _ORIG_RENDER_SOURCE(source, requirements)
    plan = _CURRENT.get("plan")
    if not _CURRENT.get("h3") or plan is None:
        return text
    ps = plan.source(source.index)
    if ps is None:
        return text
    keep = [f'"{q}"' for q in ps.qualifiers]
    if ps.applicability:
        keep.append(f"applies only to {ps.applicability}")
    if not keep:
        return text
    head, _, body = text.partition("\nText:\n")
    return f"{head}\nCondition of this requirement (keep it with this requirement only): {'; '.join(keep)}\nText:\n{body}"


def render(package, variant: str):
    h2, h3 = "h2" in variant, "h3" in variant
    G.plan_lines = lambda plan, texts=None: _plan_lines(plan, texts, h2=h2, h3=h3)
    G.render_source = _render_source
    _CURRENT.update(plan=package.answer_plan, h3=h3)
    try:
        return G.build_grounded_messages(package)
    finally:
        G.plan_lines, G.render_source = _ORIG_PLAN_LINES, _ORIG_RENDER_SOURCE
        _CURRENT.clear()


def structural_and_exact(selection):
    """h1s: leave out only optional SUPPORTING/DISCOVERY sources; keep the provision's own hierarchy."""
    from regulus.rag.selection import Selection, SelectedEvidence
    kept = [x for x in selection.selected if x.protected or x.evidence.tier in ("exact", "structural")]
    items = tuple(SelectedEvidence(i, x.evidence, x.text, x.truncated, x.protected, x.reason, x.chars) for i, x in enumerate(kept, start=1))
    return Selection(items, (), selection.policy, sum(x.chars for x in items), dict(selection.diagnostics))


def protected_and_referenced(selection):
    """h1r (experiment only, not adopted): protected evidence plus structural sources the protected
    text points to by paragraph ("devices listed in paragraph (c)(1)")."""
    import re
    from regulus.rag.selection import Selection, SelectedEvidence
    refs = {m.group(1).lower() for x in selection.selected if x.protected
            for m in re.finditer(r"paragraphs?\s+((?:\([a-z0-9]{1,4}\))+)", x.text or "", re.I)}
    kept = [x for x in selection.selected if x.protected or (x.evidence.tier == "structural" and refs
                                                             and any((x.evidence.citation or "").lower().endswith(r) for r in refs))]
    items = tuple(SelectedEvidence(i, x.evidence, x.text, x.truncated, x.protected, x.reason, x.chars) for i, x in enumerate(kept, start=1))
    return Selection(items, (), selection.policy, sum(x.chars for x in items), dict(selection.diagnostics))


def protected_and_parents(selection):
    """h1p: protected evidence plus the structural PARENT of a requested provision (its lead-in); unrequested
    children and related supporting/discovery sources are still left out."""
    from regulus.rag.selection import Selection, SelectedEvidence
    from regulus.retrieval.evidence import REL_PARENT
    kept = [x for x in selection.selected if x.protected or (x.evidence.tier == "structural" and REL_PARENT in x.evidence.relations.values())]
    items = tuple(SelectedEvidence(i, x.evidence, x.text, x.truncated, x.protected, x.reason, x.chars) for i, x in enumerate(kept, start=1))
    return Selection(items, (), selection.policy, sum(x.chars for x in items), dict(selection.diagnostics))


def protected_and_leadin_children(selection):
    """h1c: protected evidence plus the structural CHILDREN of a requested provision whose own text is a
    lead-in (ends with a colon): its content is in those subparagraphs."""
    from regulus.rag.selection import Selection, SelectedEvidence
    from regulus.retrieval.evidence import REL_CHILD
    leadin = {rid for x in selection.selected if x.protected and x.evidence.tier == "exact" and (x.text or "").rstrip().endswith(":")
              for rid, rel in x.evidence.relations.items() if rel == "exact"}
    kept = [x for x in selection.selected if x.protected or (x.evidence.tier == "structural"
            and any(rel == REL_CHILD and rid in leadin for rid, rel in x.evidence.relations.items()))]
    items = tuple(SelectedEvidence(i, x.evidence, x.text, x.truncated, x.protected, x.reason, x.chars) for i, x in enumerate(kept, start=1))
    return Selection(items, (), selection.policy, sum(x.chars for x in items), dict(selection.diagnostics))


def leadin_children_and_fragment_parents(selection):
    """h1f: h1c (production required_only) plus the structural PARENT of a requested provision whose own text
    is a sentence fragment (does not end a sentence: "... or, in the absence thereof,")."""
    from regulus.rag.selection import Selection, SelectedEvidence, required_only
    from regulus.retrieval.evidence import REL_PARENT
    base = required_only(selection)
    frag = {rid for x in selection.selected if x.protected and x.evidence.tier == "exact" and not (x.text or "").rstrip().endswith((".", "?", "!", ".)", '."'))
            for rid, rel in x.evidence.relations.items() if rel == "exact"}
    keep_ids = {x.evidence.evidence_id for x in base.selected}
    kept = [x for x in selection.selected if x.evidence.evidence_id in keep_ids or (x.evidence.tier == "structural"
            and any(rel == REL_PARENT and rid in frag for rid, rel in x.evidence.relations.items()))]
    items = tuple(SelectedEvidence(i, x.evidence, x.text, x.truncated, x.protected, x.reason, x.chars) for i, x in enumerate(kept, start=1))
    return Selection(items, (), selection.policy, sum(x.chars for x in items), dict(selection.diagnostics))


def retrieve_once(pipe: RagPipeline, question: str):
    plan = plan_query(question)
    shape, analysis = pipe.question_view(plan)
    response, registry = pipe.retrieve(question, plan)
    bundle, coverage, selection = pipe.build_bundle(response, registry, shape)
    return plan, shape, analysis, bundle, coverage, selection


def package_for(pipe: RagPipeline, retrieved, variant: str):
    plan, shape, analysis, bundle, coverage, selection = retrieved
    if coverage is None or selection is None:
        return None, None
    if variant.startswith("h1w"):
        if coverage.explicit and coverage.complete and not (shape is not None and shape.mode == "comparison") \
                and all((x.text or "").rstrip().endswith((".", '."', ".)")) for x in selection.selected if x.protected and x.evidence.tier == "exact"):
            selection = controlled_selection(selection)
    elif variant.startswith("h1f") and coverage.explicit and coverage.complete and not (shape is not None and shape.mode == "comparison"):
        selection = leadin_children_and_fragment_parents(selection)
    elif variant.startswith("h1c") and coverage.explicit and coverage.complete and not (shape is not None and shape.mode == "comparison"):
        selection = protected_and_leadin_children(selection)
    elif variant.startswith("h1p") and coverage.explicit and coverage.complete and not (shape is not None and shape.mode == "comparison"):
        selection = protected_and_parents(selection)
    elif variant.startswith("h1r") and coverage.explicit and coverage.complete:
        selection = protected_and_referenced(selection)
    elif variant.startswith("h1s") and coverage.explicit and coverage.complete:
        selection = structural_and_exact(selection)
    elif "h1" in variant and coverage.explicit and coverage.complete:
        selection = controlled_selection(selection)
    pkg = G.build_package(plan, coverage, selection, notes=bundle.notes, budget=pipe.config.generation_budget,
                          answer_shape=shape, question_analysis=analysis)
    return pkg, plan


def keyed(exp, text):
    t = (text or "").lower()
    terms = [x for x in exp.get("expected_terms") or [] if x.lower() not in t]
    points = [p[0] for p in exp.get("expected_points") or [] if not any(a.lower() in t for a in p)]
    return terms + points


def load_cache():
    cache = {}
    if CACHE.exists():
        for l in CACHE.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                cache[r["prompt_hash"]] = r
    return cache


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="base,h1,h1h2,h1h3,h1h2h3")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--dry-run", action="store_true", help="count prompts to generate, generate nothing")
    args = ap.parse_args()
    variants = args.variants.split(",")
    items = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]
    base_traces = {}
    for l in BASELINE.read_text(encoding="utf-8").splitlines():
        t = json.loads(l)
        base_traces.setdefault(t["question_id"], t)
    generated = [i for i in items if base_traces[i["id"]]["model_called"] and (not args.ids or i["id"] in args.ids)]
    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    db = Database.from_env()
    db.connect()
    # the Stage 5 context is the base every variant starts from (variants add their own change)
    pipe = RagPipeline(LexicalRetriever(db), None, dataclasses.replace(configured_rag_config(settings), optional_context="always"))
    cache = load_cache()
    # the Stage 5 run's own outputs, keyed by the prompt it recorded
    for t in base_traces.values():
        if t.get("prompt_hash") and t.get("raw_model_output") is not None and t["prompt_hash"] not in cache:
            cache[t["prompt_hash"]] = {"prompt_hash": t["prompt_hash"], "response": t["raw_model_output"], "generated_tokens": t["output_token_count"],
                                       "prompt_tokens": t["prompt_token_count"], "finished": t["finished"], "seconds": None, "from": "stage5_final"}
    plans = []
    for ex in generated:
        retrieved = retrieve_once(pipe, ex["question"])
        for v in variants:
            pkg, _ = package_for(pipe, retrieved, v)
            if pkg is None:
                continue
            msgs = render(pkg, v)
            plans.append((ex, v, pkg, msgs, sha256(msgs)))
    todo = {h: m for _, _, _, m, h in plans if h not in cache}
    pkgs = {h: p for _, _, p, _, h in plans}
    print(f"{len(plans)} (question, variant) prompts; {len(set(h for *_, h in plans))} distinct; to generate: {len(todo)}", flush=True)
    if args.dry_run:
        per = {v: sum(1 for _, vv, _, _, h in plans if vv == v and h in todo) for v in variants}
        print("to generate per variant (first occurrence counted once overall):", per)
        return 0
    if todo:
        generator = load_qwen_generator(settings, local_files_only=True)
        pipe.generator = generator
        with CACHE.open("a", encoding="utf-8") as f:
            for n, (h, msgs) in enumerate(todo.items(), 1):
                t0 = time.perf_counter()
                gen = pipe._generate(msgs, pkgs[h].max_new_tokens)
                rec = {"prompt_hash": h, "response": gen.response, "generated_tokens": gen.generated_tokens, "prompt_tokens": gen.prompt_tokens,
                       "finished": gen.finished, "seconds": round(time.perf_counter() - t0, 2),
                       "first_token_seconds": getattr(gen, "first_token_seconds", None), "from": "stage6_experiment"}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                cache[h] = rec
                print(f"  {n}/{len(todo)} {rec['seconds']}s {rec['generated_tokens']} tok", flush=True)
    out_dir = OUT / f"experiments_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for ex, v, pkg, msgs, h in plans:
        c = cache[h]
        text = c["response"].strip()
        gen = GenerationResult("", text, c.get("prompt_tokens") or 0, c.get("generated_tokens") or 0, 0.0, finished=c.get("finished"))
        rep = validate_answer(text, pkg, gen)
        codes = sorted(set(rep.codes()))
        rows.append({"id": ex["id"], "variant": v, "prompt_hash": h, "prompt_chars": len(msgs[1]["content"]), "sources": len(pkg.sources),
                     "prompt_tokens": c.get("prompt_tokens"), "generated_tokens": c.get("generated_tokens"), "seconds": c.get("seconds"),
                     "valid": rep.ok, "status": rep.status, "errors": [x for x in codes if x not in WARNINGS],
                     "warnings": [x for x in codes if x in WARNINGS], "keyed_missing": keyed(ex, text) if ex.get("expected_behavior") else None,
                     "answer": text})
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {}
    for v in variants:
        rs = [r for r in rows if r["variant"] == v]
        keyedrs = [r for r in rs if r["keyed_missing"] is not None]
        summary[v] = {
            "questions": len(rs), "valid": sum(r["valid"] for r in rs),
            "keyed_complete": sum(not r["keyed_missing"] for r in keyedrs), "keyed_questions": len(keyedrs),
            "qualifier_warnings": sum(bool(set(r["warnings"]) & {"qualifier_dropped", "qualifier_misapplied", "applicability_dropped"}) for r in rs),
            "citation_errors": sum(bool(set(r["errors"]) & {"citation_mismatch", "provision_citation_mismatch", "invalid_citation", "synthesis_citation_gap"}) for r in rs),
            "enumeration_errors": sum(bool(set(r["errors"]) & {"enumeration_incomplete", "requirement_not_addressed", "material_group_uncovered"}) for r in rs),
            "unsupported": sum(bool(set(r["errors"]) & {"unsupported_figure", "asserted_missing_provision"}) for r in rs),
            "degenerate": sum("degenerate_output" in r["errors"] for r in rs),
            "median_prompt_chars": statistics.median(r["prompt_chars"] for r in rs) if rs else None,
            "median_generated_tokens": statistics.median(r["generated_tokens"] or 0 for r in rs) if rs else None,
        }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print("wrote", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
