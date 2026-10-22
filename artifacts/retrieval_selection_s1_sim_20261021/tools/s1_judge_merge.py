"""Merge the two blind judges per pool; write the adjudication pool (disagreements only, blind) or, once
pools/judgements/<corpus>_adjudicated.json exists, the final labels and the E3 verdict per arm.

    python s1_judge_merge.py <dir>
"""
import json
import sys
from pathlib import Path

D = Path(sys.argv[1]).resolve()
J = D / "pools" / "judgements"
out, adj_needed = {}, {}
for corpus, nb in (("guidance", 4), ("ecfr", 1)):
    key = json.loads((D / "pools" / f"{corpus}_key.json").read_text())
    blind = {b["item"]: b for b in json.loads((D / "pools" / f"{corpus}_blind.json").read_text())}
    A, B = {}, {}
    for i in range(1, nb + 1):
        A.update(json.loads((J / f"{corpus}_{i}_A.json").read_text()))
        B.update(json.loads((J / f"{corpus}_{i}_B.json").read_text()))
    assert set(A) == set(B) == set(key), (corpus, len(A), len(B), len(key))
    adj_path = J / f"{corpus}_adjudicated.json"
    adj = json.loads(adj_path.read_text()) if adj_path.exists() else {}
    dis = [i for i in key if A[i]["label"] != B[i]["label"]]
    adj_needed[corpus] = [blind[i] for i in dis if i not in adj]
    items = {}
    for i, k in key.items():
        final = A[i]["label"] if A[i]["label"] == B[i]["label"] else (adj.get(i, {}).get("label"))
        items[i] = {**k, "judge_A": A[i]["label"], "judge_B": B[i]["label"], "adjudicated": adj.get(i, {}).get("label"), "final": final}
    out[corpus] = {"items": items, "agreement": round(1 - len(dis) / len(key), 4), "disagreements": len(dis)}
for corpus, need in adj_needed.items():
    (D / "pools" / f"{corpus}_adjudication_blind.json").write_text(json.dumps(need, indent=1, ensure_ascii=False))
    print(corpus, "agreement", out[corpus]["agreement"], "disagreements", out[corpus]["disagreements"], "awaiting adjudication", len(need))
(D / "judgements.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
if any(adj_needed.values()):
    raise SystemExit(0)
ev = json.loads((D / "evaluation.json").read_text())
for arm in ("S1", "S1F2"):
    new = [{"corpus": c, "qid": v["qid"], "citation": v["citation"], "label": v["final"]}
           for c in out for v in out[c]["items"].values() if f"removed:{arm}" in v["roles"]]
    reused = [x for x in ev[arm]["E3"]["items"] if x["label"]]
    allr = [{"qid": x["qid"], "citation": x["citation"], "label": x["label"], "source": x["label_source"]} for x in reused] + \
           [{**x, "source": "this pool"} for x in new]
    dist = {l: sum(x["label"] == l for x in allr) for l in ("R2", "R1", "R0")}
    r2 = [x for x in allr if x["label"] == "R2"]
    assert len(allr) == ev[arm]["E3"]["removed"], (arm, len(allr), ev[arm]["E3"]["removed"])
    ev[arm]["E3"].update({"labels": dist, "R2_removed": r2, "pass": not r2})
    print(arm, "E3", dist, "R2 removed:", [(x["qid"], x["citation"][:70], x["source"]) for x in r2])
fill = {c: {l: sum(v["final"] == l for v in out[c]["items"].values() if all(r.startswith("filler") for r in v["roles"])) for l in ("R2", "R1", "R0")} for c in out}
ev["E3_fillers"] = fill
print("fillers", fill)
(D / "evaluation.json").write_text(json.dumps(ev, indent=1, ensure_ascii=False))
