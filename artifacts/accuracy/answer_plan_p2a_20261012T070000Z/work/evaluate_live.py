"""Live answers WITH evaluation, through the production engine: what the evaluator says now."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(Path(__file__).parent))
from prompts import PROBES  # noqa: E402


def main():
    from regulus.config import load_settings
    from serve_ui import Engine
    want = set(sys.argv[2:])
    engine = Engine(load_settings(), offline=True)
    out = {}
    for qid, q in PROBES:
        if want and qid not in want:
            continue
        r = engine.ask(q, accuracy=True)
        acc = r.get("accuracy") or {}
        rv = acc.get("question_review") or {}
        out[qid] = {"question": q, "answer": r["answer"], "label": rv.get("label"), "score": rv.get("live_check_score"),
                    "explanation": rv.get("explanation"), "verdict": (acc.get("answer_verdict") or {}),
                    "dimensions": {d["dimension"]: (d["state"], d.get("detail")) for d in acc.get("dimensions") or []},
                    "claims": acc.get("checked", {}).get("claims") if isinstance(acc.get("checked"), dict) else None}
        print(f"{qid:<14} {rv.get('label')} {rv.get('live_check_score')} :: {str(rv.get('explanation'))[:150]}", flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
