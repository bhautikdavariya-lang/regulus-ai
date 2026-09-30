"""List generated questions whose prompt under the CURRENT code differs from a recorded run (no model).

    python scripts/prompt_diff.py <run dir> [<baseline run dir>]

Greedy decoding is deterministic, so a question whose prompt hash is unchanged reproduces the run's
output; only the listed questions need to be generated again.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from regulus.config import load_settings
from regulus.observability.trace import sha256
from regulus.planning import plan_query
from regulus.rag import RagPipeline
from regulus.rag.generation import build_grounded_messages, build_package
from regulus.retrieval import Database, LexicalRetriever
from run_diagnostics import configured_rag_config


def first(p):
    o = {}
    for l in open(p, encoding="utf-8"):
        if l.strip():
            r = json.loads(l); o.setdefault(r["question_id"], r)
    return o


run = first(Path(sys.argv[1]) / "traces.jsonl")
base = first(Path(sys.argv[2]) / "traces.jsonl") if len(sys.argv) > 2 else {}
db = Database.from_env(); db.connect()
p = RagPipeline(LexicalRetriever(db), None, configured_rag_config(load_settings()))
changed = []
for q, t in run.items():
    if not t["model_called"]:
        continue
    plan = plan_query(t["question"]); sh, an = p.question_view(plan)
    r, reg = p.retrieve(t["question"], plan); b, cov, sel = p.build_bundle(r, reg, sh)
    h = sha256(build_grounded_messages(build_package(plan, cov, sel, notes=b.notes, budget=p.config.generation_budget, answer_shape=sh, question_analysis=an)))
    if h != t["prompt_hash"]:
        changed.append((q, bool(base) and h == base[q]["prompt_hash"]))
print(json.dumps({"changed": [q for q, _ in changed], "equal_to_baseline_prompt": [q for q, same in changed if same]}))
