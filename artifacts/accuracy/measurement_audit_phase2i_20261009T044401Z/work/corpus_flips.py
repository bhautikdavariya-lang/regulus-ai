"""READ-ONLY: how approach B would read each corpus sentence (variant loaded as a separate module)."""
import json, sys, importlib.util, re
from collections import Counter
W = sys.argv[1] + "/work/"
def load(name):
    p = W + f"variants/{name}/regulus/accuracy/operators.py"
    spec = importlib.util.spec_from_file_location("ops_" + name, p); m = importlib.util.module_from_spec(spec)
    sys.modules["ops_" + name] = m; spec.loader.exec_module(m); return m
B = load("IB_rel")
H = json.load(open(W + "corpus_rel_negations.json"))
seen = {}
for h in H:
    seen.setdefault((h["citation"], h["sentence"]), h)
flips, keep = [], []
for (cit, s), h in seen.items():
    pb = B.polarity(s)
    rec = {**h, "polarity_B": pb}
    (flips if (h["polarity"] == "negate" and pb != "negate") else keep).append(rec)
MATERIAL = re.compile(r"\b(?:which|that|who)\s+(?:\w+\s+)?not\s+(?:\w+\s+)?(?:exceed|contaminat|result|reveal|contain|present|interact|increase|adulterat)|\bof\s+which\s+(?:\w+\s+)?not\b", re.I)
mat = [f for f in flips if MATERIAL.search(f["sentence"])]
json.dump({"flips": flips, "material_flips": mat}, open(W + "corpus_flips_B.json", "w"), indent=1, ensure_ascii=False)
print("unique sentences:", len(seen), "| production NEGATE:", sum(1 for h in seen.values() if h["polarity"] == "negate"),
      "| B flips NEGATE->not negate:", len(flips), "(with a modal:", sum(1 for f in flips if f["strength"]), ")",
      "| flips whose negated relative clause carries a limit/contamination/result qualifier:", len(mat))
for f in mat[:12]: print("  MATERIAL", f["citation"], "|", f["sentence"][:200].replace("\n", " "))
