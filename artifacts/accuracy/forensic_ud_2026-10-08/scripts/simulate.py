"""OFFLINE SIMULATION ONLY. Monkeypatches live in this process; no repository file changes.
Scenarios: base, excl (drop unverifiable claims), gate (no verb-list gate), guid_q / guid_a
(lost guidance restored, chunks ranked against question / answer terms), gate+guid_q."""
import json, re, sys, importlib.util
from collections import Counter
from dataclasses import replace
from pathlib import Path
ROOT = Path.cwd()
spec = importlib.util.spec_from_file_location("av", ROOT / "scripts/accuracy_validate.py")
av = importlib.util.module_from_spec(spec); sys.modules["av"] = av; spec.loader.exec_module(av)
from regulus.accuracy import claims as CL, answer as AN, evaluator as EV
from regulus.accuracy.intent import terms
from regulus.accuracy.alignment import SemanticAligner
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings

OUT = Path(sys.argv[1])
rows = [json.loads(l) for l in av.DATASET.read_text().splitlines() if l.strip()]
subset = av.select(rows, 60)
emb = TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True)
aligner = SemanticAligner(emb)
db = Database.from_env(); db.connect(); index = DatabaseIdentifierIndex(db); cache = {}

_DOCKET = re.compile(r"Docket\s+([A-Z]{3}-\d{4}-[A-Z]-\d{3,5})")
def guidance_chunks(label, query_text, k):
    m = _DOCKET.search(label)
    title = label.split(": ", 1)[1].split(" (")[0] if ": " in label else label
    if not m: return []
    toks = sorted(set(re.findall(r"[a-z]{4,}", query_text.lower())))
    q = " | ".join(toks) or "x"
    rs = db.query("""SELECT c.body_text, c.ordinal, g.title, ts_rank_cd(c.search_vector, to_tsquery('english', %(q)s), 1) r
                     FROM fda_guidance_chunks c JOIN fda_guidance g ON g.id=c.guidance_id
                     WHERE g.docket_number=%(d)s AND left(g.title, 40)=left(%(t)s, 40)
                     ORDER BY r DESC, c.ordinal LIMIT %(k)s""", {"q": q, "d": m.group(1), "t": title, "k": k})
    return [r["body_text"] for r in rs]

def build_full(row, mode):
    """Every evidence entry in its live position; lost guidance restored when mode is set."""
    pkg, cov, _ = av.build(row, db, cache)
    if mode is None: return pkg, cov
    qtext = row["question"] if mode == "q" else (row["answer"] or "")
    srcs, seen = [], Counter()
    for label in row["evidence"]:
        text, heading = av.fetch_text(db, label, cache)
        if text is None:
            seen[label] += 1
            chunks = guidance_chunks(label, qtext, seen[label])
            if len(chunks) < seen[label]: continue
            text, heading = chunks[seen[label] - 1], None
            srcs.append(av.Src(index=len(srcs) + 1, citation=label, text=text, heading=heading,
                               citation_fields={}, corpus="guidance", is_docket=True))
        else:
            srcs.append(av.Src(index=len(srcs) + 1, citation=label, text=text, heading=heading,
                               citation_fields=av._fields(label)))
    return replace(pkg, sources=tuple(srcs)), cov

orig_verdict = AN.verdict
def excl_verdict(intent, claims, **kw):
    kept = [c for c in claims if c.final != AN.UNVERIFIABLE]
    return orig_verdict(intent, kept if kept else claims, **kw)
orig_assert = CL._ASSERTS_RE

def run(row, gate, mode, excl):
    CL._ASSERTS_RE = re.compile(r"") if not gate else orig_assert
    AN.verdict = excl_verdict if excl else orig_verdict
    try:
        pkg, cov = build_full(row, mode)
        a = EV.evaluate(row["question"], row["answer"] or "", package=pkg, coverage=cov, validation=None,
                        model_called=bool(row.get("model_called")), fallback_type=row.get("fallback_type"),
                        scope_status=row.get("scope"),
                        answerability={"state": row.get("answerability")} if row.get("answerability") else None,
                        identifier_index=index, aligner=aligner)
    finally:
        CL._ASSERTS_RE = orig_assert; AN.verdict = orig_verdict
    v = a.checked.get("answer_verdict") or {}
    cl = a.checked.get("claims") or []
    return {"verdict": v.get("verdict"), "acc": a.accuracy, "reason": a.reason[:240],
            "claims": len(cl), "status": dict(Counter(c["final"] for c in cl)),
            "sources": len(pkg.sources) if pkg else 0,
            "detail": [{"final": c["final"], "support": c["support"], "basis": c.get("support_basis"),
                        "rel": (c.get("relevance") or {}).get("verdict"), "claim": c["claim"][:160],
                        "why": str(c.get("support_reason"))[:160],
                        "ev": [e.get("citation") for e in (c.get("evidence") or [])][:2]} for c in cl]}

SCEN = {"base": (True, None, False), "excl": (True, None, True), "gate": (False, None, False),
        "guid_q": (True, "q", False), "guid_a": (True, "a", False), "gate_guid_q": (False, "q", False),
        "gate_guid_q_excl": (False, "q", True)}
out = {}
for row in subset:
    out[row["id"]] = {"N": row["N"], "M": row.get("M"), **{k: run(row, *v) for k, v in SCEN.items()}}
db.close()
OUT.write_text(json.dumps(out, indent=1, default=str))
print("done", len(out))
