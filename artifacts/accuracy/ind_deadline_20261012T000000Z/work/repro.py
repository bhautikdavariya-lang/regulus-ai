"""Phase 1 reproduction: IND safety-reporting deadline confusion (21 CFR 312.32(c)(1) 15 days
vs (c)(2) 7 days). Runs the real server engine (serve_ui.Engine.ask) offline against the
read-only database with the page's defaults. Each question is answered with evaluation ON and
again with it OFF to confirm the answer and citations are byte-identical."""
import json, sys, time
sys.path.insert(0, "scripts")
from serve_ui import Engine
from regulus.config import load_settings

OUT = sys.argv[1]
QUESTIONS = [
    ("D1", "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32?"),
    ("D2", "How quickly must a sponsor report an unexpected fatal or life-threatening suspected adverse reaction under an IND?"),
    ("D3", "What are the IND safety reporting timeframes under 21 CFR 312.32?"),
    ("D4", "What is the difference between the 15-calendar-day and 7-calendar-day IND safety reporting deadlines in 21 CFR 312.32?"),
    ("D5", "When must a sponsor submit an IND safety report under 21 CFR 312.32(c)?"),
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
    on["_repro"] = {
        "case": cid, "seconds": round(time.time() - t, 1),
        "answer_identical_when_off": off["answer"] == on["answer"],
        "citations_identical_when_off": off["citations"] == on["citations"],
    }
    out[cid] = on
    rv = (on.get("accuracy") or {}).get("question_review") or {}
    a = on["answer"]
    print(f"{cid} {rv.get('label')} score={rv.get('live_check_score')} "
          f"identical_off={on['_repro']['answer_identical_when_off']}/{on['_repro']['citations_identical_when_off']} "
          f"| 7day={'7 calendar' in a} 15day={'15 calendar' in a} fallback={on.get('fallback_type')}", flush=True)
    json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
print("done")
