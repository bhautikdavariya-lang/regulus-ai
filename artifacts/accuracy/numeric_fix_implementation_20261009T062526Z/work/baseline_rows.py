"""Decisions of the PRE-CHANGE evaluator (snapshot_before/, loaded in place of the package) on the new fixture rows."""
import json, os, sys
import regulus
regulus.__path__.insert(0, os.path.abspath(sys.argv[1]))
import regulus.accuracy.operators as OP
assert OP.__file__.startswith(os.path.abspath(sys.argv[1])), OP.__file__
sys.path.insert(0, ".")
from tests.test_accuracy_claim_extraction import judge
rows = json.load(open("tests/fixtures/accuracy_numeric_limit_rows.json"))["rows"]
out = {}
for r in rows:
    cmp = OP.compare(r["claim"], r["evidence"])
    c = judge(f"What does {r['citation']} require?", r["claim"] + " [1]", [(r["citation"], r["evidence"])]).checked["claims"][0]
    out[r["id"]] = {"expect": r["expect"], "conflicts": sorted({x["operator"] for x in cmp.conflicts}), "blocked": cmp.support_blocked,
                    "basis": c["support_basis"], "final": c["final"]}
json.dump(out, open(sys.argv[2], "w"), indent=1)
for i in sys.argv[3:]: print(i, out[i])
