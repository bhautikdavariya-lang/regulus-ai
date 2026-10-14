"""Verdict-level false support / false contradiction over the labelled sets (numeric 16, Phase 2M 29 + 7 targets, Phase 2I 15, decisions 11)."""
import json, sys
W = sys.argv[1]; V = sys.argv[2:]
CRED = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}
WRONG_NUM = {"N1", "N3", "N4", "N6", "N7", "N8", "N9", "N16", "N10", "N11", "N14", "N15"}   # claims that misstate the rule
rows = {}
for v in V:
    fs, fc, det = [], [], []
    for r in json.load(open(f"{W}/numeric_{v}.json")):
        if r["id"] in WRONG_NUM and r["basis"] in CRED: fs.append(r["id"])
        if r["id"] not in WRONG_NUM and r["id"] != "N13" and r["final"] == "contradicted": fc.append(r["id"])
    seen = set()
    for r in json.load(open(f"{W}/m_cases_{v}.json")):
        if r["family"] == "TARGET": continue
        if r["expect"] in ("conflict", "not_credited") and r["credited"]: fs.append(r["id"])
        if r["expect"] in ("equivalent", "not_contradicted") and r["final"] == "contradicted": fc.append(r["id"])
    for r in json.load(open(f"{W}/real_controls_{v}.json")):
        if r["expect"] == "conflict" and r["basis"] in CRED: fs.append(r["id"])
        if r["expect"] != "conflict" and r["claim_final"] == "contradicted": fc.append(r["id"])
    for r in json.load(open(f"{W}/diagnostics_{v}.json")):
        if r.get("kind") != "decision": continue
        if r["expect"] == "conflict" and r["basis"] in CRED: fs.append(r["id"])
        if r["expect"] != "conflict" and r["final"] == "contradicted": fc.append(r["id"])
    rows[v] = {"false_support": fs, "false_contradiction": fc}
    print(f"{v:13} false support {len(fs):2} {fs}\n{'':13} false contra  {len(fc):2} {fc}")
json.dump(rows, open(W + "/error_counts.json", "w"), indent=1)
