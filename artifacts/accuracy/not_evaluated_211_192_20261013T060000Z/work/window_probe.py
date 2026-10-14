"""Which gate of verdicts.judge_window rejects the merged S2+S3 claim (and a control), on the verbatim 211.192 text."""
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT / "src"))
from regulus.accuracy import verdicts as VD
from regulus.accuracy.alignment import LexicalAligner, Passage, adjacent_windows
from regulus.accuracy.attribution import longest_run, normalise
from regulus.accuracy.attribution import strip_lead
from regulus.evaluation.grounding_eval import split_sentences
row = json.loads(sys.argv[1])
S = [x.strip() for x in re.split(r"(?<=\.)\s+(?=[A-Z])", " ".join(row.split()))]
ps = [Passage(1, "21 CFR 211.192", "regulation", s, "Production record review.", "binding_regulation", i) for i, s in enumerate(S)]
CLAIMS = {
 "merged paraphrase (matrix case 5)": "Any unexplained discrepancy or batch failure to meet specifications must be thoroughly investigated, and that investigation must extend to other batches of the same drug product and other associated drug products.",
 "merged near-verbatim": "The failure of a batch or any of its components to meet any of its specifications shall be thoroughly investigated, and the investigation shall extend to other batches of the same drug product and other drug products.",
}
for name, c in CLAIMS.items():
    single = VD.judge(c, LexicalAligner().align(c, ps), evidence=ps)
    wins = adjacent_windows([ps[1], ps[2]], ps)
    v = VD.judge(c, LexicalAligner().align(c, wins), evidence=ps)
    words = normalise(strip_lead(c)).split()
    halves = split_sentences(v.alignment.passage.text) if v.alignment else []
    runs = [longest_run(words, normalise(h))[0] for h in halves[:2]]
    print(json.dumps({"claim": name, "single_sentence_verdict": single.verdict, "single_reason": single.reason[:160],
                      "window_verdict": v.verdict, "window_reason": v.reason[:200],
                      "window_overlap": round(v.alignment.overlap, 3) if v.alignment else None,
                      "window_first_seq": v.alignment.passage.seq if v.alignment else None,
                      "runs_into_each_half": runs, "gates": {"borne_out": v.verdict in VD.BORNE_OUT,
                      "overlap>=0.85": bool(v.alignment and v.alignment.overlap >= VD.WINDOW_MIN_OVERLAP),
                      "run>=5 each": all(r >= VD.WINDOW_MIN_RUN_EACH for r in runs)},
                      "judge_window": (lambda f: f.verdict if f else None)(VD.judge_window(c, wins, evidence=ps))}, indent=1))
