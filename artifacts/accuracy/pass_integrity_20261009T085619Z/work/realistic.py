"""Realistic evaluation path for the probes: real plan + lexical retrieval over an in-memory table of VERBATIM
snapshot rows (with section headings), real package, real validator (validate_answer) and coverage, then
evaluate() + question_review(). This is what serve_ui hands the evaluator, minus the model."""
import json, sys
sys.path.insert(0, ".")
from regulus.accuracy import evaluate
from regulus.accuracy.review import question_review
from regulus.inference.generate import GenerationResult
from regulus.planning import plan_query
from regulus.rag.coverage import check_coverage
from regulus.rag.validation import validate_answer
from regulus.retrieval import LexicalRetriever
from tests.test_generation_contract import package_for
from tests.test_retrieval_plan import TableDatabase, row
T = {p["citation"]: p["text"] for p in json.load(open("tests/fixtures/accuracy_definition_citation_rows.json"))["paragraphs"]}
M = json.load(open("artifacts/accuracy/measurement_audit_phase2m_20261009T055242Z/work/texts_2m.json"))
T.update({k: v["text"] for k, v in M.items()})
def r(cit, ordinal, heading):
    sec, para = cit.replace("21 CFR ", "").split("(", 1)[0], ("(" + cit.split("(", 1)[1]) if "(" in cit else ""
    return row(sec, para, ordinal, text=T[cit], section_heading=heading)
TABLE211 = [r(c, i, "Personnel qualifications.") for i, c in enumerate(["21 CFR 211.25(a)", "21 CFR 211.25(b)", "21 CFR 211.25(c)"], 1)]
TABLE180 = [r("21 CFR 211.180(a)", 1, "General requirements.")]
TABLE1379 = [row("1.379", "(a)", 1, text="(a) FDA may detain an article of food for a reasonable period that may not exceed 20 calendar days after the detention order is issued.", section_heading="How long may FDA detain an article of food?"),
             row("1.379", "(b)", 2, text=T["21 CFR 1.379(b)"], section_heading="How long may FDA detain an article of food?")]
def evaluate_answer(question, answer, table):
    db = TableDatabase(table)
    pkg = package_for(question, db=db)
    gen = GenerationResult("p", answer, 500, 60, 1.0, finished=True)
    report = validate_answer(answer, pkg, gen)
    cov = check_coverage(LexicalRetriever(TableDatabase(table)).run_plan(plan_query(question), top_k=8).registry)
    d = evaluate(question, answer, package=pkg, validation=report, coverage=cov).to_dict()
    return question_review(d, question=question), d, pkg, report
if __name__ == "__main__":
    def body(c): t = T[c]; return t.split(") ", 1)[1] if t.startswith("(") else t
    A, B, C = body("21 CFR 211.25(a)"), body("21 CFR 211.25(b)"), body("21 CFR 211.25(c)")
    cases = [
        ("POS all three cited", "What are the personnel qualification requirements in 21 CFR 211.25?", f"{A} [1] {B} [2] {C} [3]", TABLE211, True),
        ("A1 one correct marker, rest verbatim uncited", "What are the personnel qualification requirements in 21 CFR 211.25?", f"{A}\n\n{B}\n\n{C} [3]", TABLE211, True),
        ("D2 asks (a),(b),(c), answers (c) only", "What do 21 CFR 211.25(a), (b), and (c) require?", f"{C} [3]", TABLE211, False),
        ("D2b asks the section, answers (c) only", "What does 21 CFR 211.25 require?", f"{C} [3]", TABLE211, False),
        ("D2c asks the personnel requirements, answers (c) only", "What are the personnel qualification requirements in 21 CFR 211.25?", f"{C} [3]", TABLE211, False),
        ("D1 asks exceptions, omits OTC exception", "How long must batch production records be retained under 21 CFR 211.180(a), and are there exceptions?",
         "Batch production records shall be retained for at least 1 year after the expiration date of the batch [1].", TABLE180, False),
        ("POS 1.379(b)", "What does 21 CFR 1.379(b) say about the entire detention period?", "The entire detention period may not exceed 30 calendar days [1].", TABLE1379, True),
    ]
    for name, q, a, table, ok in cases:
        v, d, pkg, rep = evaluate_answer(q, a, table)
        bad = v["status"] == "pass" and not ok
        print(f"{'!! FALSE PASS' if bad else 'ok' if (v['status']=='pass') == ok or not ok else 'POS NOT PASS':14} {v['label']:14} {str(v['live_check_score']):4} | {name}")
        print(f"      sources={[s.citation for s in pkg.sources]} | val codes={rep.to_dict()['codes']} | unaddressed={getattr(rep,'unaddressed',None)}")
        print(f"      dims={ {x['dimension'][:10]: x['state'] for x in d['dimensions']} } | {v['explanation'][:140]}")
