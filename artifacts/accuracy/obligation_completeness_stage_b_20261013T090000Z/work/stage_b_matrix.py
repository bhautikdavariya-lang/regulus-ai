"""Stage B matrix (design evidence only): 21 CFR 211.192 through the production pipeline over the verbatim fixture
(tests.test_accuracy_pass_integrity.production: configured pipeline, validation, repair, evidence snapshot,
lexical aligner), under whichever `regulus` PYTHONPATH selects. Prints label, score, completeness state/detail."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from tests.test_accuracy_pass_integrity import production
from tests.test_retrieval_plan import row
F = json.load(open("tests/fixtures/accuracy_211_192_rows.json")); T = F["paragraphs"][0]["text"]
S1, S2, S3, S4 = [s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z])", " ".join(T.split()))]
TABLE = [row("211.192", "", 1, text=T, section_heading=F["section_heading"])]
P1 = ("The quality control unit must review and approve all drug product production and control records, including "
      "packaging and labeling records, before a batch is released or distributed.")
P2 = ("Any unexplained discrepancy or any failure of a batch or its components to meet specifications must be thoroughly "
      "investigated, even if the batch was already distributed.")
P3 = ("The investigation must extend to other batches of the same drug product and to other drug products that may have "
      "been associated with the failure or discrepancy.")
P4 = "A written record of the investigation must be made and must include the conclusions and followup."
BROAD = "What does 21 CFR 211.192 require?"
BROAD2 = "What are the production record review requirements in 21 CFR 211.192?"
FOCUS = "Under 21 CFR 211.192, what must a manufacturer do when a batch fails to meet specifications?"
INV = "What are the investigation requirements under 21 CFR 211.192?"
V = {"S": (S1, S2, S3, S4), "P": (P1, P2, P3, P4)}
CASES = []
for q in (BROAD, BROAD2):
    CASES += [(q, "complete verbatim", " ".join(V["S"])), (q, "complete paraphrase", " ".join(V["P"]))]
    for k in range(4):
        CASES.append((q, f"verbatim omits S{k+1}", " ".join(s for j, s in enumerate(V["S"]) if j != k)))
        CASES.append((q, f"paraphrase omits S{k+1}", " ".join(s for j, s in enumerate(V["P"]) if j != k)))
    CASES += [(q, "complete + unsupported claim", " ".join(V["S"]) + " The manufacturer must also notify FDA of every investigation."),
              (q, "S2-S4 + bare heading 'Production record review.'", "Production record review. " + " ".join(V["S"][1:])),
              (q, "S1 only", S1)]
for q in (FOCUS, INV):
    CASES += [(q, "S2-S4 verbatim", " ".join(V["S"][1:])), (q, "S2 only", S2), (q, "complete verbatim", " ".join(V["S"]))]
out = []
for q, name, a in CASES:
    v, d, o = production(q, a + " [1]", TABLE)
    comp = next(x for x in d["dimensions"] if x["dimension"] == "completeness") if d.get("dimensions") else {}
    rec = {"question": q, "case": name, "label": v["label"], "score": v["live_check_score"],
           "shape": (o.metadata.get("answer_shape") or {}).get("mode"), "completeness": comp.get("state"),
           "detail": comp.get("detail"), "delivered_as_given": o.answer.strip().startswith(a[:50]),
           "claims": [(c["final"], c["relevance"]["verdict"]) for c in d.get("checked", {}).get("claims", [])]}
    out.append(rec)
    print(f"{q[:44]:<45} {name:<48} {rec['shape']:<9} {rec['label']:<20} {str(rec['score']):<4} compl={rec['completeness']}"
          f"{'' if rec['delivered_as_given'] else '  [REPAIRED/WITHHELD]'}  {(rec['detail'] or '')[:150] if rec['completeness'] != 'pass' else ''}")
Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
