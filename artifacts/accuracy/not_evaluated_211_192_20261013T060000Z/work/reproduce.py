"""REPRODUCTION ATTEMPT, not the original case (which was not persisted): natural wordings of a 21 CFR 211.192
question through the production engine (serve_ui.Engine.ask: greedy, configured adapter, top_k 8, evaluation
ON). Records the answer, the evidence, every claim, every dimension, and the review label and reason."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))

QS = ["What does 21 CFR 211.192 require?",
      "What are the production record review requirements in 21 CFR 211.192?",
      "Under 21 CFR 211.192, what must a manufacturer do when a batch fails to meet specifications?"]


def main():
    from regulus.config import load_settings
    from serve_ui import Engine
    e = Engine(load_settings(), offline=True)
    out = {}
    for q in QS:
        r = e.ask(q, accuracy=True)
        acc = r["accuracy"]; rv = acc["question_review"]
        rec = {"question": q, "answer": r["answer"], "review": rv,
               "status": acc.get("status"), "reason": acc.get("reason"), "verdict": acc.get("answer_verdict"),
               "dimensions": acc.get("dimensions"),
               "claims": (acc.get("checked") or {}).get("claims"),
               "sources": [(s["index"], s["citation"], s.get("tier")) for s in r["sources"]],
               "citations": [(c["index"], c["label"], c.get("cited_in_answer")) for c in r["citations"]],
               "fallback_type": r.get("fallback_type"), "validation": r.get("validation"),
               "answer_shape": r.get("answer_shape"), "output_tokens": r.get("output_tokens")}
        out[q] = rec
        a = r["answer"].lower()
        topics = {"S1 QCU review": "quality control unit" in a, "S2 investigate": "investigat" in a,
                  "S3 other batches": "other batch" in a, "S4 written record": "written record" in a}
        print(f"{rv['label']:<14} score={rv['live_check_score']} topics={topics}\n   Q: {q}\n   why: {rv['explanation'][:200]}", flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
