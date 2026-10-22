"""Per-question failure classification of the 22 Oct 1.7B run (categories 1-8 of the brief); read-only."""
import json, re, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
RUN = ROOT / "artifacts/cosmetics_benchmark/cosmetics100_q17_20261022T035901Z"
sys.path.insert(0, str(RUN / "tools"))
from common import evidence_check, load_run  # noqa: E402
from build_workbook import category  # noqa: E402

labels = json.loads((ROOT / "artifacts/retrieval_rootcause_20261021/refined_classes.json").read_text())["labels"]
first_loss = {}
for k, cls in labels.items():
    qid = k.split(" ")[0]
    first_loss.setdefault(qid, Counter())[cls["class"]] += 1
verd = json.loads((RUN / "scoring/verdicts.json").read_text())
statute = {r["id"]: r for r in json.loads((ROOT / "artifacts/cosmetics_benchmark/answerstage_extraction_diag_20261022/statute_coverage.json").read_text())}
MISINTERP = {"COS-82.50-Q1": "names 82.1050/82.2050 for a subpart B color", "COS-82.304-Q1": "inverts 82.5 ('shall be certified ... unless')",
             "COS-710.2-Q1": "'should register' stated as 'must register'", "COS-74.2602a-Q1": "says the provision specifies no requirement",
             "COS-FDCA605-Q3": "uncited 15-business-day remark"}
out, cnt = [], Counter()
for it in load_run(RUN):
    q, r, resp = it["q"], it["r"], it["resp"]
    v = verd[q["ID"]]
    cat = category(v, r["execution_status"])
    ev = evidence_check(q, resp)
    a = (r["answer"] or "")
    decline = a.startswith("The available regulatory sources do not provide enough information")
    withheld = r.get("fallback_type") == "unvalidated_answer_withheld"
    cats = []
    if ev["expected"] and not ev["in_evidence"]:
        cats += ["1 missing evidence", "2 retrieval/ranking (section is in the database)"]
    elif ev["expected"] and set(ev["in_evidence"]) != set(ev["expected"]):
        cats += ["2 retrieval/ranking (companion section missing)"]
    if ev["in_evidence"] and decline and r.get("fallback_type") is None:
        cats.append("3 evidence-to-answer (declined with key section present)")
    if ev["in_evidence"] and cat in ("PARTIALLY PASS", "PARTIALLY FAIL") and q["ID"] not in MISINTERP:
        cats.append("4 incomplete (restated or partial, not applied)")
    if q["ID"] in MISINTERP:
        cats.append("5 incorrect interpretation: " + MISINTERP[q["ID"]])
    if q["ID"] == "COS-70.19-Q2":
        cats.append("6 validator false negative (prompt-label echo 'None (general question)' delivered)")
    if q["ID"] in statute:
        cats.append("7 knowledge-source gap (FD&C Act not in corpus)" + ("" if not statute[q["ID"]]["missing_locally"] else "; local govinfo copy also lacks " + ",".join(statute[q["ID"]]["missing_locally"])))
    if re.search(r"(?m)^\s*r\d+\s*:", a) or re.search(r"(?m)^\s*\d{1,2}\.\s*$", a):
        cats.append("8 other: plan-id echo or empty list items in delivered text")
    if withheld:
        cats.append("withheld by validator (justified: see DIAGNOSIS)")
    if not cats:
        cats.append("8 other")
    for c in cats:
        cnt[c.split(" (")[0].split(":")[0]] += 1
    out.append({"id": q["ID"], "category": cat, "classes": cats, "expected": ev["expected"], "in_evidence": ev["in_evidence"],
                "first_loss_21oct": dict(first_loss.get(q["ID"], {})), "delivered": "decline" if decline else ("withheld" if withheld else (r.get("fallback_type") or "answer"))})
(ROOT / "artifacts/cosmetics_benchmark/q17_fix_20261022/classification.json").write_text(json.dumps(out, indent=1))
for k, n in sorted(cnt.items()):
    print(f"{n:3}  {k}")
fl = Counter(c for o in out for c in o["first_loss_21oct"] if c != "OK" and not o["in_evidence"])
print("first-loss classes among missing-evidence questions:", dict(fl))
