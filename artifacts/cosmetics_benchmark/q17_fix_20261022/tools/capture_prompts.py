"""Render the exact user prompt each question gets (retrieval + package + rendering), no model. Read-only DB.

    python capture_prompts.py <out.jsonl>        # 100 cosmetics + 352 frozen retrieval-baseline questions

Guards from guarded.py are installed on import (semantic loader refused, SELECT-only). The generator records the
messages it is handed and returns no text, so everything up to the model call is the production path.
"""
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guarded  # noqa: F401,E402  (installs the guards)
from guarded import ROOT, Database  # noqa: E402
from regulus.evaluation import retrieval_baseline as RB  # noqa: E402


class Capture(RB.NoGenerator):
    def __init__(self):
        super().__init__(); self.last = None

    def generate(self, messages, max_new_tokens=None, on_text=None):
        self.last = {"system_sha": hashlib.sha256(messages[0]["content"].encode()).hexdigest(), "user": messages[-1]["content"],
                     "max_new_tokens": max_new_tokens}
        return super().generate(messages, max_new_tokens, on_text)


def main():
    cos = json.loads((ROOT / "artifacts/cosmetics_benchmark/cosmetics100_q17_20261022T035901Z/selection.json").read_text())["questions"]
    base = [json.loads(l) for l in (ROOT / "data/evaluation/datasets/retrieval_baseline_v1.jsonl").read_text().splitlines() if l.strip()]
    qs = [(q["ID"], q["Question (ask verbatim)"]) for q in cos] + [(b["id"], b["question"]) for b in base]
    db = Database.from_env(); db.connect()
    try:
        pipe, _ = RB.production_pipeline(db)
        cap = Capture(); pipe.generator = cap
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            for qid, text in qs:
                cap.last = None
                out = pipe.answer(text)
                rec = {"id": qid, "model_called": cap.last is not None, "fallback_type": out.metadata.get("fallback_type")}
                if cap.last:
                    rec.update(cap.last, user_sha=hashlib.sha256(cap.last["user"].encode()).hexdigest())
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    finally:
        db.close()
    print("captured", len(qs))


if __name__ == "__main__":
    main()
