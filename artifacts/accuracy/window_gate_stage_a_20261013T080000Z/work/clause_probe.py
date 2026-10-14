"""Variant check: split a merged claim at ', and' and judge EACH clause with the ordinary single-sentence judge
(all its safeguards) against the source's sentences. A window would then support the claim only if every clause
is borne out by one of the window's two sentences."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from regulus.accuracy import verdicts as VD
from regulus.accuracy.alignment import Passage, LexicalAligner
exec(open(Path(__file__).with_name("window_cases.py")).read().split("out = []")[0].split("from tests.test_accuracy_claim_extraction")[1].split("\n", 1)[1])
for name, src, claim in CASES:
    texts = S if src == "211" else [x.strip() for x in re.split(r"(?<=\.)\s+(?=[A-Z])", QUAR[1])]
    ps = [Passage(1, "21 CFR 211.192", "exact", t, "Production record review.", "binding_regulation", i) for i, t in enumerate(texts)]
    parts = [p.strip(" .") for p in re.split(r",\s+and\s+", claim)]
    res = []
    for p in parts:
        v = VD.judge(p, LexicalAligner().align(p, ps), evidence=ps)
        res.append((v.verdict, v.alignment.passage.seq if v.alignment else None, v.reason[:110]))
    ok = len(parts) == 2 and all(r[0] in VD.BORNE_OUT for r in res) and len({r[1] for r in res}) == 2
    print(f"{name:<55} clause-variant={'SUPPORT' if ok else 'reject'}")
    for p, r in zip(parts, res): print(f"     {r[0]:<22} seq={r[1]} | {p[:70]} | {r[2]}")
