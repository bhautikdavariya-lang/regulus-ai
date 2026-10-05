"""H4 section 5 gate: prove the intervention changed evidence completeness, with NO model call.

    .venv/bin/python scripts/h4_verify.py

Runs the production pipeline twice over the same questions - once unpatched, once with
install_h4_complete_sections - using a stub generator, so coverage, select_evidence, the Stage 6
required_only narrowing and Stage 8 consolidate_evidence all execute exactly as in a real run.
The benchmark key is read only afterwards, to count paragraphs of the keyed section.
"""
from __future__ import annotations

import json, sys, importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

IDS = ["M-002", "M-003", "M-004"]


class StubResult:
    response = ""; generated_tokens = 0; prompt_tokens = 0; finished = True
    stop_reason = "stub"; seconds = 0.0; first_token_seconds = 0.0
    tokens_per_second = 0.0; decode_tokens_per_second = None


class StubGenerator:
    def __init__(self, inner):
        self.inner = inner; self.model, self.tokenizer = inner.model, inner.tokenizer
    def generate(self, messages, max_new_tokens=None, on_text=None): return StubResult()
    def describe(self): return self.inner.describe()
    def __getattr__(self, n): return getattr(self.inner, n)


def compose(arm: str, probe, bench, db, base):
    """Fresh pipeline per arm; h4 installed only for the h4 arm."""
    import regulus.rag.pipeline as pipemod
    importlib.reload(pipemod)                      # restore the unpatched select_evidence
    from regulus.rag import RagPipeline
    from regulus.planning import plan_query
    from regulus.system_identity import configured_rag_config
    from regulus.config import load_settings
    patches = []
    if arm == "h4":
        import d1_experiment as D
        patches.append(D.install_h4_complete_sections(db))
    cfg = configured_rag_config(load_settings())
    from regulus.retrieval.factory import build_retriever
    retriever, scope = build_retriever(db, cfg)
    pipe = RagPipeline(retriever, StubGenerator(base), cfg, scope_policy=scope)
    rows = {}
    for item in probe:
        qid = item["id"]; q = bench[qid]
        outp = pipe.answer(q.question)
        srcs = list(outp.context.sources)
        secs = [s.result.metadata.get("section") for s in srcs]
        keyed = item.get("key_sections") or []
        rows[qid] = {
            "sections": secs, "n_sources": len(srcs),
            "evidence_chars": sum(len(s.text) for s in srcs),
            "keyed": keyed,
            "keyed_rank": next((n for n, s in enumerate(secs, 1) if s in keyed), None),
            "supplied_chars": sum(len(s.text) for s in srcs if s.result.metadata.get("section") in keyed),
            "blocks_for_keyed": sum(1 for s in secs if s in keyed),
        }
    return rows, patches


def main() -> int:
    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
    from regulus.rag.remote_generator import load_generator
    from regulus.retrieval import Database
    from regulus.system_identity import configured_generation_config

    probe = [x for x in json.loads((ROOT / "artifacts/diagnostics/model_probe/probe_set.json").read_text())
             if x["id"] in IDS]
    probe.sort(key=lambda x: IDS.index(x["id"]))
    bench = {q.question_id: q for q in load_acceptance_benchmark()}
    settings = load_settings(); settings.generation = configured_generation_config(settings)
    base = load_generator(settings, local_files_only=True)
    db = Database.from_env(); db.connect()

    a0, _ = compose("0", probe, bench, db, base)
    h4, patches = compose("h4", probe, bench, db, base)
    print("patches:", patches, "\n")

    ok = True
    for qid in IDS:
        p, h = a0[qid], h4[qid]
        ks = p["keyed"][0]
        avail = db.query("select count(*) n, sum(length(body_text)) c from cfr_records where section_number=%s", (ks,))[0]
        print(f"=== {qid}   keyed section {ks}")
        rowsfmt = [
            ("Total evidence sections", p["n_sources"], h["n_sources"]),
            ("Exact target section present", "yes" if p["keyed_rank"] else "NO", "yes" if h["keyed_rank"] else "NO"),
            ("Exact target section rank", p["keyed_rank"], h["keyed_rank"]),
            ("Target paragraphs available", avail["n"], avail["n"]),
            ("Target paragraphs supplied", p["blocks_for_keyed"], "1 block, all paras" if h["supplied_chars"] >= avail["c"] * 0.95 else "PARTIAL"),
            ("Target chars supplied", p["supplied_chars"], h["supplied_chars"]),
            ("Target chars available", avail["c"], avail["c"]),
            ("Target section completeness", f"{100*p['supplied_chars']/avail['c']:.1f}%", f"{100*h['supplied_chars']/avail['c']:.1f}%"),
            ("Evidence chars (all sources)", p["evidence_chars"], h["evidence_chars"]),
        ]
        print(f"  {'metric':32}{'Arm 0':>22}{'H4':>22}")
        for lbl, x, y in rowsfmt:
            print(f"  {lbl:32}{str(x):>22}{str(y):>22}")
        same_set = p["sections"] == h["sections"]
        complete = h["supplied_chars"] >= avail["c"] * 0.95
        print(f"  section set identical: {same_set}    target complete: {complete}")
        if not same_set:
            print(f"    arm0 {p['sections']}\n    h4   {h['sections']}")
        ok &= same_set and complete
        print()
    print("GATE:", "PASS - intervention verified, safe to run the model" if ok else "FAIL - do not interpret; fix first")
    db.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
