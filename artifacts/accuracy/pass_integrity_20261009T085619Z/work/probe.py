"""Adversarial PASS-integrity probes through the REAL evaluator + review, on VERBATIM snapshot text.
Answers are CONSTRUCTED. Each probe states whether PASS is allowed."""
import json, sys
sys.path.insert(0, ".")
from tests.test_accuracy_claim_extraction import judge
from regulus.accuracy.review import question_review
T = {p["citation"]: p["text"] for p in json.load(open("tests/fixtures/accuracy_definition_citation_rows.json"))["paragraphs"]}
M = json.load(open("artifacts/accuracy/measurement_audit_phase2m_20261009T055242Z/work/texts_2m.json"))
T.update({k: v["text"] for k, v in M.items()})
def body(c): t = T[c]; return t.split(") ", 1)[1] if t.startswith("(") else t
A, B, C = body("21 CFR 211.25(a)"), body("21 CFR 211.25(b)"), body("21 CFR 211.25(c)")
S211 = [("21 CFR 211.25(a)", T["21 CFR 211.25(a)"]), ("21 CFR 211.25(b)", T["21 CFR 211.25(b)"]), ("21 CFR 211.25(c)", T["21 CFR 211.25(c)"])]
Q211 = "What are the personnel qualification requirements in 21 CFR 211.25?"
S1379 = [("21 CFR 1.379(a)", "(a) FDA may detain an article of food for a reasonable period that may not exceed 20 calendar days after the detention order is issued."),
         ("21 CFR 1.379(b)", T["21 CFR 1.379(b)"])]
Q1379 = "How long may FDA detain an article of food under 21 CFR 1.379?"
S180 = [("21 CFR 211.180(a)", T["21 CFR 211.180(a)"])]
Q180 = "How long must batch production records be retained under 21 CFR 211.180(a), and are there exceptions?"
S820 = [(c, T[c]) for c in ["21 CFR 820.35(a)", "21 CFR 820.35(a)(1)", "21 CFR 820.35(a)(2)", "21 CFR 820.35(a)(5)", "21 CFR 820.35(b)", "21 CFR 820.35(b)(3)", "21 CFR 820.35(b)(5)"]]
Q820 = "What must complaint records include under 21 CFR 820.35?"
P = [
 # positive controls: must stay eligible for PASS
 ("POS 211.25 all cited", Q211, f"{A} [1] {B} [2] {C} [3]", S211, True),
 ("POS 1.379(b)", Q1379, "The entire detention period may not exceed 30 calendar days [2].", S1379, True),
 # A. citations
 ("A1 one correct marker, rest uncited (all verbatim)", Q211, f"{A}\n\n{B}\n\n{C} [3]", S211, True),
 ("A2 one correct marker + uncited FABRICATED claim", Q211, f"Each person shall pass an annual written CGMP examination.\n\n{C} [3]", S211, False),
 ("A3 marker supports neighbour, not its own sentence", Q211, f"{C} Personnel records shall be retained for ten years [3].", S211, False),
 ("A4 no citation at all", Q211, f"{A} {B} {C}", S211, False),
 # B. mixtures
 ("B1 four supported + one fabricated requirement", Q211, f"{A} [1] {B} [2] {C} [3] Each person shall also complete an annual CGMP proficiency test [1].", S211, False),
 ("B2 correct rule, wrong exception (5 years for OTC)", Q180, "Batch production records shall be retained for at least 1 year after the expiration date of the batch, or, for certain OTC drug products lacking expiration dating, 5 years after distribution of the batch [1].", S180, False),
 ("B3 correct number on the wrong requirement", Q1379, "The entire detention period may not exceed 20 calendar days [2].", S1379, False),
 ("B3b ... cited to the paragraph the number comes from", Q1379, "The entire detention period may not exceed 20 calendar days [1].", S1379, False),
 ("B4 invented exception", Q180, "Batch production records shall be retained for at least 1 year after the expiration date of the batch, except records for OTC drug products, which need not be retained [1].", S180, False),
 ("B5 servicing items as complaint-record contents", Q820, "Complaint records must include the date of service and the service performed [6].", S820, False),
 ("B5b ... one item, cited to (b)(3)", Q820, "Complaint records must include the date of service [6].", S820, False),
 ("B6 correct + reversed limit", Q1379, "FDA may detain an article of food for a reasonable period that may not exceed 20 calendar days after the detention order is issued [1]. The entire detention period may exceed 30 calendar days [2].", S1379, False),
 # D. completeness / scope
 ("D1 asks for exceptions, omits the OTC exception", Q180, "Batch production records shall be retained for at least 1 year after the expiration date of the batch [1].", S180, False),
 ("D2 asks several requirements, gives one", "What do 21 CFR 211.25(a), (b), and (c) require?", f"{C} [3]", S211, False),
 ("D3 definition + unsupported extra claim", "What does FDA stand for?", "The FDA stands for the Food and Drug Administration [1]. It approves every food label before sale [1].", [("21 CFR 10.3(a)", T["21 CFR 10.3(a)"])], False),
 ("D4 correct definition", "What does FDA stand for?", "The FDA stands for the Food and Drug Administration [1].", [("21 CFR 10.3(a)", T["21 CFR 10.3(a)"])], True),
]
out = []
for name, q, a, src, pass_ok in P:
    d = judge(q, a, src).to_dict(); v = question_review(d, question=q)
    bad = (v["status"] == "pass") and not pass_ok
    out.append({"probe": name, "status": v["label"], "score": v["live_check_score"], "pass_allowed": pass_ok, "FALSE_PASS": bad,
                "dims": {x["dimension"]: x["state"] for x in d["dimensions"]}, "why": v["explanation"][:180],
                "claims": [(c["final"], c["support_basis"], c.get("citation")) for c in d["checked"]["claims"]]})
    print(f"{'!! FALSE PASS' if bad else ('ok' if (v['status']=='pass')==pass_ok or not pass_ok else 'POSITIVE NOT PASS'):18} {v['label']:20} {str(v['live_check_score']):4} | {name} | {v['explanation'][:120]}")
json.dump(out, open(sys.argv[1], "w"), indent=1)
