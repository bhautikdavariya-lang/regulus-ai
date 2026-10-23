"""Offline validator replay: rebuild each recorded answer's evidence (recorded section promotion, same pipeline),
feed the recorded FIRST draft back as the model's output, and record the delivery decision. No model is loaded.

    python replay_validate.py <out.jsonl> <answers.jsonl> [...]  [--patch V1[,V2]]

Patches are applied in memory only (the repository is not modified):
  V1  condition_not_in_cited_source: a cited source's parent/child paragraphs (same section, path prefix) count as
      cited - a numbered item inherits the condition of its lead-in ("(a) ... is exempt ... if: (1) ... (2) ...")."""
import json, sys, time
from pathlib import Path

ROOT = Path("/Users/sensussoftsoftware/Desktop/Prachi Patel/Regulus AI.nosync")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/q17_fix_20261022/tools"))
import guarded  # noqa: E402  SELECT-only DB, semantic loader refused
from guarded import Database  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--") and a not in ("V1",)]
patches = set(sys.argv[sys.argv.index("--patch") + 1].split(",")) if "--patch" in sys.argv else set()
out_path, inputs = Path(args[0]), args[1:]

import regulus.rag.claim_validation as CV  # noqa: E402
if "V1" in patches:
    src = Path(CV.__file__).read_text(encoding="utf-8")
    old = "        cited_texts = [by_index[i].text for i in marks]\n"
    new = ("        cited_ids = [identities.get(i) for i in marks]\n"
           "        cited_texts = [by_index[i].text for i in marks] + [s.text for j, s in by_index.items() if j not in marks\n"
           "                       and identities.get(j) and related and any(c and related(c, identities[j]) for c in cited_ids)]\n")
    assert src.count(old) == 1
    code = compile(src.replace(old, new), CV.__file__, "exec")
    exec(code, CV.__dict__)
    import regulus.rag.validation as V
    V.check_claims = CV.check_claims

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.inference.types import GenerationResult  # noqa: E402
from run_cosmetics_eval import _replay, read_bank  # noqa: E402


class Scripted:
    retrieval_only = False

    def __init__(self):
        self.text, self.calls, self.first_prompt = "", 0, None

    def generate(self, messages, max_new_tokens=None, on_text=None, **kw):
        self.calls += 1
        if self.calls == 1:
            self.first_prompt = messages[-1]["content"]
        return GenerationResult(prompt=messages[-1]["content"], response=self.text, prompt_tokens=0, generated_tokens=max(1, len(self.text) // 4),
                                seconds=0.0, finished=True)

    def describe(self):
        return {"model_id": "scripted replay"}


db = Database.from_env(); db.connect()
pipe, _ = RB.production_pipeline(db)
gen = Scripted(); pipe.generator = gen
t0 = time.perf_counter()
with out_path.open("w", encoding="utf-8") as f:
    for path in inputs:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line) if line.strip() else None
            if not r or r.get("error"):
                continue
            gen.text, gen.calls, gen.first_prompt = r.get("raw") or "", 0, None
            _replay(pipe, r["asked"], r.get("promotion"))
            o = pipe.answer(r["asked"])
            md = o.metadata
            errs = sorted({p["code"] for p in ((md.get("validation") or {}).get("initial") or {}).get("problems", []) if p.get("severity") == "error"})
            f.write(json.dumps({"file": path.split("/")[-2] + "/" + path.split("/")[-1], "id": r["id"],
                                "recorded_fallback": r.get("fallback_type"), "replay_fallback": md.get("fallback_type"),
                                "recorded_correction": ((r.get("generation") or {}).get("correction_pass") or {}).get("accepted"),
                                "replay_errors": errs, "answer": o.answer, "calls": gen.calls, "prompt": gen.first_prompt,
                                "sources": [s.result.citation.label for s in o.context.sources],
                                "problems": [(p["code"], p.get("severity"), (p.get("detail") or "")[:200], (p.get("sentence") or "")[:200]) for p in ((md.get("validation") or {}).get("initial") or {}).get("problems", [])]}, ensure_ascii=False) + "\n")
db.close()
print("done", round(time.perf_counter() - t0), "s; patches", sorted(patches) or "none")
