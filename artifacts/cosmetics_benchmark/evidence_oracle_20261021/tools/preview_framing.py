"""Render, without any model, the prompts both framings would send, and diff them (Step 3B, before inference).

    python preview_framing.py <experiment_dir> <framing_dir>

The pipeline is built exactly as recovered_step3/oracle_run.py builds it. OracleRetriever is exec'd from that file's own
source, so it is not re-implemented. A stub generator records the messages and returns empty text. Checks:
  1. the original-framing preview equals the prompt recorded by the restored oracle run (run/answers.jsonl), byte for byte;
  2. per question, the system prompt and the evidence blocks (citation + text) are identical across framings;
  3. lists every other user-prompt line that differs, and the token allowance each framing gets.
Read-only database; writes only <framing_dir>/preview.json.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

E, F = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.dont_write_bytecode = True
HOME = os.path.expanduser("~")
SNAP = HOME + "/regulus_eval_runs/q17_feasibility/hf_cache_mlx/models--Qwen--Qwen3-1.7B-MLX-4bit/snapshots/21457c6f51ed54a7c16e988c0844db973815c137"
os.environ.update({"REGULUS_MODEL_BACKEND": "mlx", "REGULUS_MODEL_ID": "Qwen/Qwen3-1.7B",
                   "REGULUS_MODEL_CACHE_DIR": HOME + "/regulus_eval_runs/q17_feasibility/hf_cache",
                   "REGULUS_MLX_PYTHON": HOME + "/regulus_eval_runs/q17_feasibility/mlx_venv/bin/python",
                   "REGULUS_MLX_MODEL_PATH": SNAP, "REGULUS_MLX_REVISION": "21457c6f51ed54a7c16e988c0844db973815c137",
                   "REGULUS_MLX_MIN_AVAILABLE_MB": "2000", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})

from regulus.config import load_settings  # noqa: E402
from regulus.inference.generate import GenerationResult  # noqa: E402
from regulus.rag.pipeline import RagPipeline  # noqa: E402
from regulus.retrieval import sql as SQLM  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.domain import DomainVocabulary, ScopePolicy  # noqa: E402
from regulus.retrieval.lexical import METHOD_FULL_TEXT, LexicalRetriever  # noqa: E402
from regulus.system_identity import configured_generation_config, configured_rag_config  # noqa: E402

src = (E / "recovered_step3/oracle_run.py").read_text(encoding="utf-8")
cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "OracleRetriever")
ns = {"LexicalRetriever": LexicalRetriever, "METHOD_FULL_TEXT": METHOD_FULL_TEXT}
exec(compile(ast.Module([cls], []), "oracle_run.OracleRetriever", "exec"), ns)
OracleRetriever = ns["OracleRetriever"]


class Stub:
    def __init__(self):
        self.calls = []

    def generate(self, messages, max_new_tokens=None, on_text=None):
        self.calls.append({"messages": messages, "max_new_tokens": max_new_tokens})
        return GenerationResult("", "", 0, 0, 0.0, finished=True)

    def describe(self):
        return {"model_id": "none (prompt preview)"}


settings = load_settings()
settings.generation = configured_generation_config(settings)
db = Database.from_env()
_q = db.query
db.query = lambda s, p=None: _q(s, p) if re.match(r"(?is)^\s*(select|with)\b", re.sub(r"--[^\n]*", " ", s)) else (_ for _ in ()).throw(RuntimeError("non-SELECT refused"))
config = configured_rag_config(settings)
cfg = replace(config, top_k=8, context=replace(config.context, max_results=24, max_chars_per_result=4000, max_total_chars=9000))
scope = ScopePolicy(DomainVocabulary.from_database(db)) if config.scope_policy == "general_knowledge" else None
retriever, stub = OracleRetriever(db), Stub()
pipe = RagPipeline(retriever, stub, cfg, grounding=None, scope_policy=scope)

P = json.loads((E / "packets/packets.json").read_text(encoding="utf-8"))["questions"]
pairs = json.loads((F / "paired_wording.json").read_text(encoding="utf-8"))
recorded = {r["qid"]: r for r in (json.loads(l) for l in (E / "run/answers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}


def render(question, qid):
    rows = []
    for pr in P[qid]["rows"]:
        r = db.query(f"SELECT {SQLM._ECFR_COLUMNS} FROM cfr_records r LEFT JOIN cfr_parts p ON p.number = r.part_number "
                     "WHERE r.section_number = %(s)s AND COALESCE(r.paragraph_path, '') = %(p)s AND r.removed_on IS NULL AND NOT r.is_reserved",
                     {"s": pr["section"], "p": pr["path"]})
        rows.append(r[0])
    retriever.set_packet(rows)
    stub.calls.clear()
    out = pipe.answer(question)
    call = stub.calls[0] if stub.calls else None
    return call, out


def evidence(user):
    body = user.split("<<<SOURCES\n", 1)[1].split("\n>>>END SOURCES", 1)[0] if "<<<SOURCES\n" in user else ""
    blocks = re.split(r"\n\n(?=SOURCE \d+\n)", body)
    ev = []
    for b in blocks:
        cit = re.search(r"\nCitation: ([^\n]+)", b)
        txt = b.split("\nText:\n", 1)[1] if "\nText:\n" in b else ""
        ev.append((cit.group(1) if cit else None, " ".join(txt.split())))
    return sorted(ev)


result, all_ok = {}, True
for qid, w in pairs.items():
    ca, out_a = render(w["original"], qid)
    cb, out_b = render(w["framed"], qid)
    if ca is None or cb is None:
        result[qid] = {"error": "the pipeline did not call the generator", "a_called": ca is not None, "b_called": cb is not None,
                       "b_fallback": out_b.metadata.get("fallback_type")}
        all_ok = False
        continue
    ua, ub = ca["messages"][-1]["content"], cb["messages"][-1]["content"]
    la, lb = set(ua.split("\n")), set(ub.split("\n"))
    ev_same = evidence(ua) == evidence(ub)
    rec = {"original_matches_recorded_step3_prompt": ua == recorded[qid]["prompt_user"],
           "system_prompt_identical": ca["messages"][0]["content"] == cb["messages"][0]["content"],
           "evidence_identical": ev_same, "evidence_items": len(evidence(ua)),
           "max_new_tokens": {"original": ca["max_new_tokens"], "framed": cb["max_new_tokens"]},
           "lines_only_in_original": sorted(la - lb), "lines_only_in_framed": sorted(lb - la),
           "framed_prompt": ub}
    all_ok &= rec["original_matches_recorded_step3_prompt"] and rec["system_prompt_identical"] and ev_same
    result[qid] = rec
(F / "preview.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
db.close()
print("ALL CHECKS PASS:", all_ok)
for qid, r in result.items():
    if "error" in r:
        print(qid, r)
        continue
    print(f"\n== {qid}: original==recorded {r['original_matches_recorded_step3_prompt']} | system same {r['system_prompt_identical']} | "
          f"evidence same {r['evidence_identical']} ({r['evidence_items']} items) | tokens {r['max_new_tokens']}")
    for l in r["lines_only_in_original"]:
        print("   - " + l[:230])
    for l in r["lines_only_in_framed"]:
        print("   + " + l[:230])
