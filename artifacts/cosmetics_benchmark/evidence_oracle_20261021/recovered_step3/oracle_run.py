"""Step 3 evidence-oracle run: production pipeline, Qwen3-1.7B MLX 4-bit, retrieval replaced by fixed verified packets.
Writes only under argv[1]. One model, one pass, greedy decoding. No fallback model: a load failure stops the run."""
import os, sys, json, time, re, hashlib, subprocess
from dataclasses import replace
sys.dont_write_bytecode = True
OUT, PACKETS = sys.argv[1], sys.argv[2]
HOME = os.path.expanduser("~")
SNAP = HOME + "/regulus_eval_runs/q17_feasibility/hf_cache_mlx/models--Qwen--Qwen3-1.7B-MLX-4bit/snapshots/21457c6f51ed54a7c16e988c0844db973815c137"
REV = "21457c6f51ed54a7c16e988c0844db973815c137"
os.environ.update({
    "REGULUS_MODEL_BACKEND": "mlx", "REGULUS_MODEL_ID": "Qwen/Qwen3-1.7B",
    "REGULUS_MODEL_CACHE_DIR": HOME + "/regulus_eval_runs/q17_feasibility/hf_cache",
    "REGULUS_MLX_PYTHON": HOME + "/regulus_eval_runs/q17_feasibility/mlx_venv/bin/python",
    "REGULUS_MLX_MODEL_PATH": SNAP, "REGULUS_MLX_REVISION": REV, "REGULUS_MLX_MIN_AVAILABLE_MB": "2000",
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"})

def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)

from regulus.config import load_settings
from regulus.system_identity import configured_generation_config, configured_rag_config
from regulus.rag.mlx_generator import available_memory_mb
settings = load_settings(); settings.generation = configured_generation_config(settings)
m = settings.model
assert m.backend == "mlx" and m.id == "Qwen/Qwen3-1.7B" and str(m.mlx_model_path) == SNAP and m.adapter is None, "model config"
meta = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "memory_before": available_memory_mb(),
        "tokenizer_cache": str(m.cache_dir), "decoding": {k: str(v) for k, v in vars(settings.generation).items()}}
from regulus.rag.remote_generator import load_generator
t0 = time.perf_counter()
generator = load_generator(settings, local_files_only=True)        # raises on failure; no fallback
meta["model_load_seconds"] = round(time.perf_counter() - t0, 2)
desc = generator.describe(); meta["generator"] = desc
assert desc["model_id"] == "Qwen/Qwen3-1.7B" and desc["model_revision"] == REV and desc["backend"] == "mlx", desc
assert desc["quantization"] == {"group_size": 128, "bits": 4}, desc["quantization"]
log(f"model loaded in {meta['model_load_seconds']} s: {desc['dtype']} {desc['runtime_versions']}")

# ---------------- read-only DB, SELECT-only guard
from regulus.retrieval.db import Database
from regulus.retrieval import sql as SQLM
db = Database.from_env(); _orig = db.query
def guarded(s, p=None):
    if not re.match(r"(?is)^\s*(select|with)\b", re.sub(r"--[^\n]*", " ", s)):
        raise RuntimeError("non-SELECT refused")
    return _orig(s, p)
db.query = guarded
st = {k: v for k, v in db.status().items() if k != "url"}
assert st["transaction_read_only"] == "on" and st["default_transaction_read_only"] == "on"
meta["db_session"] = st
TABLES = ["cfr_records", "cfr_sections", "cfr_parts"]
def counters():
    return {r["relname"]: [int(r["n_tup_ins"]), int(r["n_tup_upd"]), int(r["n_tup_del"])] for r in
            db.query("SELECT relname, n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables WHERE relname = ANY(%(t)s)", {"t": TABLES})}
meta["write_counters_before"] = counters()

# ---------------- oracle retriever: production LexicalRetriever, legs replaced by the fixed packet
from regulus.retrieval.lexical import LexicalRetriever, METHOD_FULL_TEXT
from regulus.retrieval.domain import DomainVocabulary, ScopePolicy
from regulus.rag.pipeline import RagPipeline

class OracleRetriever(LexicalRetriever):
    packet, keys = [], set()
    def set_packet(self, rows):
        self.packet = rows
        self.keys = {self._ecfr_result(r, METHOD_FULL_TEXT, 1.0, {}).key for r in rows}
    def full_text_ecfr(self, query, filters, limit):
        return [self._ecfr_result(r, METHOD_FULL_TEXT, 10.0 - 0.01 * i, {"ts_rank_cd": 10.0 - 0.01 * i, "oracle": True})
                for i, r in enumerate(self.packet)]
    def exact_cfr(self, ref, filters, limit, question=None):
        return [r for r in super().exact_cfr(ref, filters, limit, question) if r.key in self.keys]
    def exact_row(self, section, paragraph_path, filters):
        return [r for r in super().exact_row(section, paragraph_path, filters) if r.key in self.keys]
    def full_text_guidance(self, *a, **k): return []
    def full_text_or_ecfr(self, *a, **k): return []
    def full_text_or_guidance(self, *a, **k): return []
    def section_coverage_ecfr(self, *a, **k): return []
    def trigram_ecfr(self, *a, **k): return []
    def definition_ecfr(self, *a, **k): return []
    def defined_terms_ecfr(self, *a, **k): return []
    def exact_docket(self, *a, **k): return []

class Capture:
    def __init__(self, inner): self.inner, self.messages, self.results = inner, [], []
    def generate(self, messages, *a, **k):
        self.messages.append(messages); r = self.inner.generate(messages, *a, **k); self.results.append(r); return r
    def describe(self): return self.inner.describe()
    def __getattr__(self, n): return getattr(self.inner, n)

config = configured_rag_config(settings)
ctx = replace(config.context, max_results=24, max_chars_per_result=4000, max_total_chars=9000)   # deliver the whole packet
cfg = replace(config, top_k=8, context=ctx)
meta["context_override"] = {"production": {k: getattr(config.context, k) for k in ("max_results", "max_chars_per_result", "max_total_chars")},
                            "oracle_run": {k: getattr(ctx, k) for k in ("max_results", "max_chars_per_result", "max_total_chars")}}
scope = ScopePolicy(DomainVocabulary.from_database(db)) if config.scope_policy == "general_knowledge" else None
retriever = OracleRetriever(db)
cap = Capture(generator)
pipe = RagPipeline(retriever, cap, cfg, grounding=None, scope_policy=scope)
json.dump(meta, open(os.path.join(OUT, "run_meta.json"), "w"), indent=1, default=str)

P = json.load(open(PACKETS))["questions"]
QUESTIONS = json.load(open(os.path.join(os.path.dirname(PACKETS), "questions.json")))
norm = lambda t: " ".join((t or "").split())
fh = open(os.path.join(OUT, "answers.jsonl"), "w")
for qid, question in QUESTIONS.items():
    rows = []
    for pr in P[qid]["rows"]:
        r = db.query(f"SELECT {SQLM._ECFR_COLUMNS} FROM cfr_records r LEFT JOIN cfr_parts p ON p.number = r.part_number "
                     "WHERE r.section_number = %(s)s AND COALESCE(r.paragraph_path, '') = %(p)s AND r.removed_on IS NULL AND NOT r.is_reserved",
                     {"s": pr["section"], "p": pr["path"]})
        assert len(r) == 1 and hashlib.sha256(r[0]["body_text"].encode()).hexdigest() == pr["sha256"], (qid, pr["citation"])
        rows.append(r[0])
    retriever.set_packet(rows)
    cap.messages.clear(); cap.results.clear()
    mem0 = available_memory_mb()
    t0 = time.perf_counter()
    out = pipe.answer(question)
    wall = round(time.perf_counter() - t0, 3)
    md = out.metadata
    msgs = cap.messages[-1] if cap.messages else None
    user = msgs[-1]["content"] if msgs else ""
    g = cap.results[-1] if cap.results else None
    sel = md.get("selection") or {}
    delivered_rows = {pr["citation"]: norm(pr["text"]) in norm(user) for pr in P[qid]["rows"]}
    val = md.get("validation") or {}
    def vrep(v):
        if not v: return None
        return {"status": v.get("status"), "codes": v.get("codes"),
                "problems": [{k: p.get(k) for k in ("code", "severity", "detail", "sentence", "citation")} for p in (v.get("problems") or [])]}
    rec = {"qid": qid, "question": question, "packet": [(pr["citation"], pr["sha256"][:12]) for pr in P[qid]["rows"]],
           "model_called": out.model_called, "raw_model_output": md.get("raw_model_output"), "delivered_answer": out.answer,
           "validation_initial": vrep(val.get("initial")), "validation_final": vrep(val.get("final")),
           "repair": val.get("repair") if not isinstance(val.get("repair"), dict) else {k: v for k, v in val["repair"].items() if k not in ("repair_input", "repair_output")},
           "fallback_type": md.get("fallback_type"), "fallback_reason": md.get("fallback_reason"),
           "generation": {k: (md.get("generation") or {}).get(k) for k in ("prompt_tokens", "generated_tokens", "max_new_tokens", "finished", "stop_reason", "tokens_per_second", "decode_tokens_per_second")},
           "worker_timing": {k: getattr(g, k, None) for k in ("prompt_tokens", "generated_tokens", "seconds", "first_token_seconds", "finished")} if g else None,
           "timings_ms": {k: v for k, v in (md.get("timings_ms") or {}).items() if k in ("retrieval_ms", "context_ms", "generation_ms", "validation_ms", "total_ms")},
           "wall_seconds": wall, "memory_available_mb_before": mem0[0],
           "selection": {"selected": len(sel.get("selected") or []), "dropped": [(d.get("citation"), d.get("reason")) for d in sel.get("dropped") or []],
                         "truncated": [s.get("citation") for s in sel.get("selected") or [] if s.get("truncated")], "total_chars": sel.get("total_chars")},
           "packet_rows_in_prompt": delivered_rows, "packet_fully_delivered": all(delivered_rows.values()),
           "query_type": (md.get("plan") or {}).get("query_type"), "answerability": (md.get("answerability") or {}).get("state"),
           "prompt_system_sha256": hashlib.sha256(msgs[0]["content"].encode()).hexdigest() if msgs else None,
           "prompt_user": user}
    fh.write(json.dumps(rec, default=str) + "\n"); fh.flush()
    log(f"{qid}: model_called={out.model_called} tokens in={rec['generation']['prompt_tokens']} out={rec['generation']['generated_tokens']} "
        f"gen={rec['timings_ms'].get('generation_ms')} ms wall={wall}s packet_delivered={rec['packet_fully_delivered']} "
        f"val={rec['validation_initial'] and rec['validation_initial']['status']}->{rec['validation_final'] and rec['validation_final']['status']} fallback={rec['fallback_type']}")
fh.close()
meta["write_counters_after"] = counters()
meta["write_counters_unchanged"] = meta["write_counters_before"] == meta["write_counters_after"]
meta["memory_after"] = available_memory_mb()
meta["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
generator.close(); db.close()
json.dump(meta, open(os.path.join(OUT, "run_meta.json"), "w"), indent=1, default=str)
log(f"done; write counters unchanged: {meta['write_counters_unchanged']}")
