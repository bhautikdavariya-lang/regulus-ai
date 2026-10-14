"""Current code, single-sentence answers (no window involved): do fabricated period / actor / narrowed scope pass?
Evaluated (a) evaluator-only with the lexical aligner and (b) through the production pipeline (validation, repair)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from regulus.accuracy import evaluate
from regulus.accuracy.alignment import LexicalAligner
from tests.test_accuracy_claim_extraction import Src, Pkg, Cov
from tests.test_accuracy_pass_integrity import production
from tests.test_retrieval_plan import row
F = json.load(open("tests/fixtures/accuracy_211_192_rows.json")); T = F["paragraphs"][0]["text"]
TABLE = [row("211.192", "", 1, text=T, section_heading=F["section_heading"])]
Q = "Under 21 CFR 211.192, what must a manufacturer do when a batch fails to meet specifications?"
A = {"control: faithful": "Any unexplained discrepancy or failure of a batch to meet its specifications must be thoroughly investigated.",
     "N1 fabricated period": "Any unexplained discrepancy or failure of a batch to meet its specifications must be thoroughly investigated within 30 days.",
     "N2 fabricated actor": "FDA must thoroughly investigate any unexplained discrepancy or failure of a batch to meet its specifications.",
     "N6 narrowed scope": "Only a failure of a batch that has not been distributed to meet its specifications must be thoroughly investigated."}
for k, a in A.items():
    e = evaluate(Q, a + " [1]", package=Pkg(Q, (Src(1, "21 CFR 211.192", T, F["section_heading"]),)), coverage=Cov(), aligner=LexicalAligner())
    v, d, out = production(Q, a + " [1]", TABLE)
    dims = {x["dimension"]: x["state"] for x in d["dimensions"]}
    print(f"{k:<22} evaluator-only: claim={e.checked['claims'][0]['final']:<12} verdict={e.checked['answer_verdict']['verdict']:<12}"
          f" | pipeline: delivered_as_given={out.answer.strip().startswith(a[:40])} label={v['label']} {v['live_check_score']} "
          f"fabrication={dims.get('fabrication_free')} claims={[c['final'] for c in d['checked'].get('claims', [])]}")
