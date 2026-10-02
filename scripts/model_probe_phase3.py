"""Phase 3 + Phase 4: capture the real production prompt, and the raw output beside the final answer.

    python scripts/model_probe_phase3.py --ids S-003 S-006 ... [--out artifacts/diagnostics/model_probe]

The pipeline is run unchanged; the generator is wrapped in a recorder that captures the exact message list
it is handed, renders it through the model's own chat template, hashes it and counts its tokens, then
delegates to the real generator. So the prompt recorded here IS the production prompt - the gap the
300-question run left open - and the same call yields the raw model output, the repaired answer and the
final answer, which is what Phase 4 needs to locate a failure before, during or after generation.

Nothing in the pipeline is modified. Output: <out>/phase3_prompts.json plus one .txt per question.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


class RecordingGenerator:
    """Transparent proxy: records the exact messages, then delegates to the real generator."""

    def __init__(self, inner, tokenizer, enable_thinking: bool) -> None:
        self.inner, self.tok, self.enable_thinking = inner, tokenizer, enable_thinking
        self.model, self.tokenizer = inner.model, inner.tokenizer
        self.calls: list[dict] = []

    def generate(self, messages, max_new_tokens=None, on_text=None):
        rendered = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                enable_thinking=self.enable_thinking)
        ids = self.tok(rendered)["input_ids"]
        t0 = time.perf_counter()
        res = self.inner.generate(messages, max_new_tokens=max_new_tokens, on_text=on_text)
        self.calls.append({
            "system": next((m["content"] for m in messages if m["role"] == "system"), None),
            "user": next((m["content"] for m in messages if m["role"] == "user"), None),
            "rendered_prompt": rendered,
            "prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            "prompt_tokens_counted": len(ids),
            "prompt_tokens_reported": res.prompt_tokens,
            "generation_budget_passed": max_new_tokens,
            "generated_tokens": res.generated_tokens,
            "finished_with_eos": res.finished,
            "stop_reason": res.stop_reason,
            "seconds": round(time.perf_counter() - t0, 1),
            "raw_response": res.response,
        })
        return res

    def describe(self):
        return self.inner.describe()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--out", default=str(ROOT / "artifacts/diagnostics/model_probe"))
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / "prompts").mkdir(exist_ok=True)

    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
    from regulus.rag import RagPipeline
    from regulus.rag.remote_generator import load_generator
    from regulus.retrieval import Database
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_generation_config, configured_rag_config

    bench = {q.question_id: q for q in load_acceptance_benchmark()}
    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    base = load_generator(settings, local_files_only=True)
    rec = RecordingGenerator(base, base.tokenizer, settings.generation.enable_thinking)
    db = Database.from_env(); db.connect()
    cfg = configured_rag_config(settings)
    retriever, scope = build_retriever(db, cfg)
    pipe = RagPipeline(retriever, rec, cfg, scope_policy=scope)

    rows = []
    for qid in args.ids:
        q = bench[qid]
        before = len(rec.calls)
        t0 = time.perf_counter()
        out_ans = pipe.answer(q.question)
        m = out_ans.metadata
        calls = rec.calls[before:]
        ctx = getattr(rec.model.config, "max_position_embeddings", None)
        row = {
            "id": qid, "type": q.question_type, "question": q.question,
            "key_citation": q.expected_citation_draft, "key_elements": q.key_answer_elements,
            "model_called": out_ans.model_called, "generation_calls": len(calls),
            "seconds_total": round(time.perf_counter() - t0, 1),
            "evidence": [s.result.citation.label for s in out_ans.context.sources],
            "evidence_sha256": hashlib.sha256("||".join(s.text for s in out_ans.context.sources).encode()).hexdigest(),
            "answerability": (m.get("answerability") or {}).get("state"),
            "coverage": (m.get("coverage") or {}).get("state"),
            "raw_model_output": m.get("raw_model_output"),
            "validation_initial": (m.get("validation") or {}).get("initial", {}).get("status"),
            "validation_initial_codes": (m.get("validation") or {}).get("initial", {}).get("codes"),
            "validation_final": (m.get("validation") or {}).get("final", {}).get("status"),
            "repair": (m.get("validation") or {}).get("repair"),
            "final_answer": out_ans.answer,
            "citations": [c.label for c in out_ans.citations],
            "context_window": ctx,
            "prompts": calls,
        }
        if calls:
            c = calls[0]
            row["prompt_tokens"] = c["prompt_tokens_counted"]
            row["context_tokens_available"] = (ctx - c["prompt_tokens_counted"]) if ctx else None
            row["prompt_sha256"] = c["prompt_sha256"]
            (out / "prompts" / f"{qid}.txt").write_text(c["rendered_prompt"], encoding="utf-8")
        rows.append(row)
        print(f"{qid:8} {q.question_type:16} calls={len(calls)} prompt_tokens={row.get('prompt_tokens')} "
              f"gen={calls[0]['generated_tokens'] if calls else '-'} budget={calls[0]['generation_budget_passed'] if calls else '-'} "
              f"eos={calls[0]['finished_with_eos'] if calls else '-'} repair={row['repair']} {row['seconds_total']}s", flush=True)
    db.close()
    (out / "phase3_prompts.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    print("wrote", out / "phase3_prompts.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
