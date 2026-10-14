"""Reproduce the six reported UI cases through the real server engine (serve_ui.Engine.ask): local model
(--offline, no download), read-only database, the page's defaults (configured adapter, gate off, top_k 8).
Each question is answered with evaluation ON, and once more with it OFF to confirm the answer is identical.
Writes the full responses to OUT. Questions other than M-020 are RECONSTRUCTED from the case descriptions."""
import json, sys, time
sys.path.insert(0, "scripts")
from serve_ui import Engine
from regulus.config import load_settings
OUT = sys.argv[1]
QUESTIONS_ORIG = [
    ("C1", "What are the personnel qualification requirements in 21 CFR 211.25?"),
    ("C2", "What are the IND safety reporting requirements under 21 CFR 312.32?"),
    ("C3", "What must an NDA contain under 21 CFR 314.50?"),
    ("C4", "What does 21 CFR 801.15 require regarding the prominence of required label statements?"),
    ("C5a", "What does 21 CFR 820.35 add to the record control requirements of the incorporated standard?"),
    ("C5b", "What must complaint records include under 21 CFR 820.35?"),
    ("C6", "What does FDA stand for?"),
]
QUESTIONS = [
    ("C2v1", "Summarize 21 CFR 312.32."),
    ("C2v2", "What does 21 CFR 312.32 require?"),
    ("C2v3", "What are the IND safety reporting requirements in 21 CFR 312.32?"),
    ("C4v1", "What does 21 CFR 801.15 require?"),
    ("C4v2", "What are the label prominence requirements in 21 CFR 801.15?"),
]
only = set(sys.argv[2:])
engine = Engine(load_settings(), offline=True)
out = {}
for cid, q in QUESTIONS:
    if only and cid not in only:
        continue
    t = time.time()
    on = engine.ask(q, accuracy=True)
    off = engine.ask(q, accuracy=False)
    on["_repro"] = {"case": cid, "seconds": round(time.time() - t, 1), "answer_identical_when_off": off["answer"] == on["answer"],
                    "citations_identical_when_off": off["citations"] == on["citations"]}
    out[cid] = on
    rv = (on.get("accuracy") or {}).get("question_review") or {}
    print(f"{cid} {rv.get('label')} score={rv.get('live_check_score')} identical_off={on['_repro']['answer_identical_when_off']} "
          f"| fallback={on.get('fallback_type')} codes={(on.get('validation') or {}).get('codes') if isinstance(on.get('validation'), dict) else None}", flush=True)
    json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
