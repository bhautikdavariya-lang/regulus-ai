"""Priority 2 baseline: the full generation trace, through the PRODUCTION engine.

Uses `serve_ui.Engine.ask` - the answering UI's own path: greedy decoding with thinking off
(`system_identity.configured_generation_config`), the configured adapter, top_k 8, evaluation OFF.
A first version of this script built its generator from raw settings, which configure SAMPLING
(do_sample, temperature 0.7); that is not how answers are produced and its outputs were not
reproducible. It is recorded in the report and not used.

The exact messages sent to the model are recorded by wrapping `QwenGenerator.generate` with the
SAME parameters, because the pipeline inspects that signature to decide whether to pass the
per-question token budget. Read-only; writes only its output file.
"""
from __future__ import annotations
import hashlib, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

QUESTIONS = [
    ("Q-howquickly", "How quickly must IND safety reports be submitted under 21 CFR 312.32?"),
    ("Q-timeframes", "What are the IND safety reporting timeframes under 21 CFR 312.32?"),
    ("Q-sevenday",   "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32?"),
    ("Q-difference", "What is the difference between the 15-calendar-day and 7-calendar-day IND safety reporting deadlines in 21 CFR 312.32?"),
]


def main() -> int:
    out_path = Path(sys.argv[1])
    only = {a for a in sys.argv[2:] if not a.startswith("--")}
    from regulus.config import load_settings
    from regulus.rag import generator as G
    from serve_ui import Engine

    seen: list = []
    real = G.QwenGenerator.generate

    def recording(self, messages, max_new_tokens=None, on_text=None):
        seen.append({"messages": [dict(m) for m in messages], "max_new_tokens": max_new_tokens,
                     "do_sample": self.gen.do_sample})
        return real(self, messages, max_new_tokens=max_new_tokens, on_text=on_text)

    if "--no-record" not in sys.argv:
        G.QwenGenerator.generate = recording

    engine = Engine(load_settings(), offline=True)
    out = {}
    for qid, question in QUESTIONS:
        if only and qid not in only:
            continue
        seen.clear()
        t = time.time()
        r = engine.ask(question, accuracy=False)
        call = seen[-1] if seen else {}
        msgs = call.get("messages") or []
        out[qid] = {
            "question": question,
            "seconds": round(time.time() - t, 1),
            "do_sample": call.get("do_sample"),
            "max_new_tokens": call.get("max_new_tokens"),
            "n_generate_calls": len(seen),
            "system_prompt": next((m["content"] for m in msgs if m["role"] == "system"), None),
            "prompt_sent": msgs[-1]["content"] if msgs else None,
            "raw_model_output": r.get("generation", {}).get("raw") if isinstance(r.get("generation"), dict) else None,
            "answer": r.get("answer"),
            "answer_sha": hashlib.sha256((r.get("answer") or "").encode()).hexdigest()[:16],
            "sources": [(s.get("index"), s.get("citation")) for s in r.get("sources") or []],
            "cited_in_answer": [c.get("label") for c in r.get("citations") or [] if c.get("cited_in_answer")],
            "validation": r.get("validation"),
            "citation_support": r.get("citation_support"),
            "answer_shape": r.get("answer_shape"),
            "normalization": r.get("normalization"),
            "fallback_type": r.get("fallback_type"),
            "output_tokens": r.get("output_tokens"),
            "input_tokens": r.get("input_tokens"),
            "response_keys": sorted(r),
        }
        a = r.get("answer") or ""
        print(f"{qid}: sha={out[qid]['answer_sha']} out={out[qid]['output_tokens']} do_sample={out[qid]['do_sample']} "
              f"budget={out[qid]['max_new_tokens']} 7day={'7 calendar' in a} 15day={'15 calendar' in a}", flush=True)
        json.dump(out, open(out_path, "w"), indent=1, ensure_ascii=False, default=str)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
