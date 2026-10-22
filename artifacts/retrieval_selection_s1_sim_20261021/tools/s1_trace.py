"""Read-only: the S1 value / block-chars of every soft-budget candidate in two regression cases, from the recorded
contexts (eval100.json) - lexemes and weights recomputed exactly as s1_sim.py does. Prints only.

    python s1_trace.py <dir>
"""
import json, sys
from pathlib import Path
sys.argv = [sys.argv[0], sys.argv[1]]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_sim as M
D = Path(sys.argv[1]).resolve()
E = json.loads((D / "eval" / "eval100.json").read_text())["questions"]
db = M.Database.from_env(); db.connect(); M.STATE["db"] = db
try:
    for qid, arm in (("COS-70.3-Q1", "S1"), ("COS-74.2602a-Q1", "S1F2")):
        q = E[qid]["question"]; w = M.weights(q); mass = sum(w.values())
        seen = {}
        for c in ("base", arm):
            for s in E[qid][c]["sources"]:
                seen.setdefault(s["key"], {**s, "in": []})["in"].append(c)
        print("==", qid, arm, "| question mass", round(mass, 2))
        for s in sorted(seen.values(), key=lambda s: -sum(v for l, v in w.items() if l in M.lexemes(f"{s['text']} {s['citation']}")) / max(s["chars"], 1)):
            lex = M.lexemes(f"{s['text']} {s['citation']}")
            v = sum(val for l, val in w.items() if l in lex)
            print(f"   cov {v/mass:.3f}  chars {s['chars']:5}  cov/1k {1000*v/mass/max(s['chars'],1):7.3f}  in={s['in']}  {s['citation'][:70]}")
finally:
    db.close()
