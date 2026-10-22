"""Join the blind judges' labels to the pool key, after adjudication (no database). Writes judgements.json (both judges,
adjudicator, final label, agreement) and relevance.json (final label + key per item).

    python join_labels.py <dir> <workflow_result.json>
"""
import json
import sys
from collections import Counter
from pathlib import Path

D = Path(sys.argv[1]).resolve()
W = json.loads(Path(sys.argv[2]).read_text())
key = json.loads((D / "pool_key.json").read_text())
blind = {b["item"]: b for b in json.loads((D / "pool_blind.json").read_text())}
A, B, adj = W["A"], W["B"], W["adjudicated"]
assert set(A) == set(B) == set(key), (len(A), len(B), len(key))
final, rows = {}, {}
for item in sorted(key):
    a, b = A[item]["label"], B[item]["label"]
    lab = a if a == b else adj[item]["label"]
    final[item] = lab
    rows[item] = {"A": A[item], "B": B[item], "adjudicated": adj.get(item), "final": lab}
labels = ["R2", "R1", "R0"]
n = len(key)
po = sum(1 for i in key if A[i]["label"] == B[i]["label"]) / n
pa, pb = Counter(A[i]["label"] for i in key), Counter(B[i]["label"] for i in key)
pe = sum((pa[l] / n) * (pb[l] / n) for l in labels)
kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
(D / "judgements.json").write_text(json.dumps({"agreement": round(po, 3), "cohen_kappa": round(kappa, 3),
                                               "disagreements": len(W["disagreements"]), "items": rows}, indent=1, ensure_ascii=False))
rel = {i: {**key[i], "label": final[i], "title": blind[i]["guidance_document"]} for i in key}
(D / "relevance.json").write_text(json.dumps(rel, indent=1, ensure_ascii=False))
print(json.dumps({"items": n, "agreement": round(po, 3), "kappa": round(kappa, 3), "disagreements": len(W["disagreements"]),
                  "final": dict(Counter(final.values()))}, indent=1))
