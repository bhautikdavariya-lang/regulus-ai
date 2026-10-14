"""Positive and negative two-sentence cases straight through judge_window (and the full evaluator, lexical aligner),
under whichever `regulus` PYTHONPATH selects. Verbatim 211.192 from tests/fixtures/accuracy_211_192_rows.json."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from regulus.accuracy import verdicts as VD, evaluate
from regulus.accuracy.alignment import Passage, adjacent_windows, LexicalAligner
from tests.test_accuracy_claim_extraction import Src, Pkg, Cov
F = json.load(open("tests/fixtures/accuracy_211_192_rows.json"))
T = F["paragraphs"][0]["text"]
S = [x.strip() for x in re.split(r"(?<=\.)\s+(?=[A-Z])", " ".join(T.split()))]
QUAR = ("21 CFR 211.84(x)", "If a component fails to meet its specifications, it shall be rejected by the quality control unit. "
        "Rejected components shall be identified and controlled under a quarantine system designed to prevent their use in "
        "manufacturing or processing operations.")
CASES = [
 ("P1 211.192 merged paraphrase", "211", "Any unexplained discrepancy or batch failure to meet specifications must be thoroughly investigated, and that investigation must extend to other batches of the same drug product and other associated drug products."),
 ("P2 211.192 merged near-verbatim", "211", "The failure of a batch or any of its components to meet any of its specifications shall be thoroughly investigated, and the investigation shall extend to other batches of the same drug product and other drug products."),
 ("P3 211.192 S3+S4 merged", "211", "The investigation must extend to other batches of the same drug product and other associated drug products, and a written record of it must include the conclusions and followup."),
 ("N1 fabricated period", "211", "Any unexplained discrepancy or batch failure to meet specifications must be thoroughly investigated within 30 days, and that investigation must extend to other batches of the same drug product and other associated drug products."),
 ("N2 fabricated actor", "211", "FDA must thoroughly investigate any unexplained discrepancy or batch failure to meet specifications, and FDA's investigation must extend to other batches of the same drug product and other associated drug products."),
 ("N3 partial: extra unsupported duty", "211", "Any unexplained discrepancy or batch failure to meet specifications must be thoroughly investigated and reported to FDA within 15 days, and that investigation must extend to other batches of the same drug product and other associated drug products."),
 ("N4 negation", "211", "Any unexplained discrepancy or batch failure to meet specifications need not be investigated, and that investigation must extend to other batches of the same drug product and other associated drug products."),
 ("N5 modality weakened", "211", "Any unexplained discrepancy or batch failure to meet specifications may be investigated, and that investigation may extend to other batches of the same drug product and other associated drug products."),
 ("N6 scope narrowed (only undistributed)", "211", "Only an unexplained discrepancy or batch failure in a batch that has not been distributed must be thoroughly investigated, and that investigation must extend to other batches of the same drug product and other associated drug products."),
 ("N7 one sentence carries, other adds terms (F-007 shape)", "211", "The quality control unit must approve every drug product release procedure, and the investigation shall extend to other batches of the same drug product and other drug products that may have been associated."),
 ("N8 omitted condition (quarantine)", "quar", "Components shall be rejected by the quality control unit, and rejected components shall be identified and controlled under a quarantine system designed to prevent their use in manufacturing."),
 ("P4 condition kept (quarantine)", "quar", "A component that fails to meet its specifications shall be rejected by the quality control unit, and rejected components shall be controlled under a quarantine system designed to prevent their use in manufacturing."),
]
out = []
for name, src, claim in CASES:
    texts = S if src == "211" else [x.strip() for x in re.split(r"(?<=\.)\s+(?=[A-Z])", QUAR[1])]
    cit = "21 CFR 211.192" if src == "211" else QUAR[0]
    ps = [Passage(1, cit, "exact", t, "Production record review." if src == "211" else "Quarantine.", "binding_regulation", i) for i, t in enumerate(texts)]
    jw = VD.judge_window(claim, adjacent_windows(ps, ps), evidence=ps)
    q = "What does 21 CFR 211.192 require?" if src == "211" else "What does 21 CFR 211.84 require for rejected components?"
    srcs = (Src(1, cit, " ".join(texts), "Production record review." if src == "211" else "Quarantine."),)
    a = evaluate(q, claim + " [1]", package=Pkg(q, srcs), coverage=Cov(), aligner=LexicalAligner())
    c = a.checked["claims"]
    rec = {"case": name, "judge_window": jw.verdict if jw else None,
           "claims": [(x["final"], x.get("match_path"), x["support_basis"]) for x in c],
           "verdict": a.checked["answer_verdict"]["verdict"], "status": a.status}
    out.append(rec); print(json.dumps(rec))
Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
