"""Operator-level control evaluation of whatever regulus.accuracy is loaded (run via use_variant.py)."""
import json, sys
from collections import Counter
sys.path.insert(0, ".")
from regulus.accuracy import operators as OP
D, NAME = sys.argv[1], sys.argv[2]
W = D + "/work/"
FR = json.load(open(W + "controls_frozen.json")); GT = json.load(open(W + "controls_tests.json")); RD = json.load(open(W + "controls_readings.json"))
TARGET = {"FS_NEG_NOUN": {"polarity"}, "FS_NEG_BARE": {"polarity"}, "FS_NEG_IDIOM": {"polarity"}, "FS_NEG_REL": {"polarity"},
          "FS_NEG_COMPL": {"polarity"}, "FS_NEG_COND": {"polarity"}, "FS_MOD_MEANS": {"strength"}, "FS_MOD_ADJ": {"strength"},
          "FS_MOD_EPI": {"strength", "polarity"}}
res = {"variant": NAME, "frozen": [], "tests": [], "readings": []}
for c in FR:
    now = sorted({x["operator"] for x in OP.compare(c["claim"], c["evidence"], authority=c["authority"]).conflicts})
    lab = c["label"]
    if lab in TARGET: ok = not (set(now) & TARGET[lab]); kind = "false_conflict"
    elif lab == "UNREL_REAL": ok = set(c["base_conflicts"]) <= set(now); kind = "real_operator_preserved"
    elif lab == "INV": ok = set(now) == set(c["base_conflicts"]); kind = "out_of_scope_unchanged"
    else: ok = None; kind = "report_only"
    res["frozen"].append({"id": c["control_id"], "label": lab, "kind": kind, "base": c["base_conflicts"], "now": now, "ok": ok})
for g in GT:
    now = sorted({x["operator"] for x in OP.compare(g["claim"], g["evidence"], authority=g["authority"]).conflicts})
    res["tests"].append({"id": g["control_id"], "kind": g["kind"], "expect": g["expect"], "now": now, "ok": set(g["expect"]) <= set(now)})
for r in RD:
    p = OP.polarity(r["text"]); ok = (p != "negate") if r["expect"] == "not negate" else (p == r["expect"])
    res["readings"].append({"id": r["control_id"], "expect": r["expect"], "now": p, "ok": ok})
# replay every recorded comparison: new conflicts anywhere?
B = json.load(open(W + "h_current.json"))["calls"]
seen, new, gone = set(), [], []
for c in B:
    k = (c["claim"], c["evidence"], c["authority"])
    if k in seen: continue
    seen.add(k)
    now = {x["operator"] for x in OP.compare(*k[:2], authority=k[2]).conflicts}; base = {x["operator"] for x in c["conflicts"]}
    if now - base: new.append({"claim": k[0][:160], "evidence": k[1][:160], "added": sorted(now - base), "row": c["row"]})
    if base - now: gone.append(1)
res["replay"] = {"unique_pairs": len(seen), "pairs_with_new_conflicts": len(new), "pairs_with_removed_conflicts": len(gone), "new": new}
json.dump(res, open(W + f"controls_result_{NAME}.json", "w"), indent=1, ensure_ascii=False)
fr = Counter((x["kind"], x["ok"]) for x in res["frozen"])
lab_ok = Counter((x["label"], x["ok"]) for x in res["frozen"] if x["kind"] == "false_conflict")
print(f"{NAME:14} false-conflict fixed {fr[('false_conflict',True)]}/{fr[('false_conflict',True)]+fr[('false_conflict',False)]} | "
      f"real-operator kept {fr[('real_operator_preserved',True)]}/{fr[('real_operator_preserved',True)]+fr[('real_operator_preserved',False)]} | "
      f"INV unchanged {fr[('out_of_scope_unchanged',True)]}/18 | genuine kept {sum(x['ok'] for x in res['tests'])}/{len(res['tests'])} | "
      f"readings {sum(x['ok'] for x in res['readings'])}/{len(res['readings'])} | replay new {len(new)} removed {len(gone)}")
