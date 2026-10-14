"""OFFLINE ONLY: builds patched COPIES of regulus.accuracy under work/variants/<name>/regulus/accuracy.
Production src/ is never modified. Each variant is one candidate refinement (Phase 2E simulation)."""
import shutil, sys
from pathlib import Path
W=Path(sys.argv[1]); SRC=Path("src/regulus/accuracy")
def rep(s,old,new):
    assert s.count(old)==1,(old[:60],s.count(old)); return s.replace(old,new)
def V1(s):  # stemmed overlap (singular/plural, maintain/maintained, submit/submitted)
    s=rep(s,'''    mine = {t for t in content_terms(strip_lead(claim)) if t not in _FRAMING_WORDS}
    if not mine:
        return 0.0
    return len(mine & content_terms(passage.text)) / len(mine)''','''    from regulus.accuracy.intent import same_term, stem
    mine = {stem(t) for t in content_terms(strip_lead(claim)) if t not in _FRAMING_WORDS}
    if not mine:
        return 0.0
    have = _stems(passage.text)
    return sum(1 for t in mine if any(same_term(t, h) for h in have)) / len(mine)


def stemmed_overlap(claim: str, passage: Passage) -> float:
    from regulus.accuracy.intent import same_term, stem
    mine = {stem(t) for t in content_terms(strip_lead(claim))}
    if not mine:
        return 0.0
    have = _stems(passage.text)
    return sum(1 for t in mine if any(same_term(t, h) for h in have)) / len(mine)''')
    s=rep(s,"and best.overlap < MIN_PARAPHRASE_OVERLAP):","and stemmed_overlap(claim, best.passage) < MIN_PARAPHRASE_OVERLAP):")
    return s
def V2(s):  # other sentences of the SELECTED candidate's own source (never another source)
    return rep(s,"    for best, comparison in ordered[:1]:\n","""    _first = ordered[0]
    _sib = [p for p in pool if p.citation == _first[0].passage.citation and p.text != _first[0].passage.text]
    _extra = []
    if _sib:
        from regulus.accuracy.alignment import LexicalAligner as _LA
        for _a in _LA().align(claim, _sib, top_k=len(_sib)):
            _c = OP.compare(claim, _a.passage.text, authority=getattr(_a.passage, "authority", OP.BINDING))
            if not _c.conflicted and _c.support_blocked is None:
                _extra.append((_a, _c))
    for best, comparison in [_first] + _extra:
""")
def V3(s):  # list-item path: generic words exempt from the containment test (kept/maintained)
    return rep(s,"        contained = _contained(item_terms, _stems(p.text))\n",
                 "        contained = _contained({t for t in item_terms if t not in _generic()} or item_terms, _stems(p.text))\n")
VARS={"V1_stemmed_overlap":[V1],"V2_same_source_sentences":[V2],"V3_item_generic_exempt":[V3],"V123_combined":[V1,V2,V3]}
for name,fs in VARS.items():
    d=W/"variants"/name/"regulus"/"accuracy"
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(SRC,d,ignore=shutil.ignore_patterns("__pycache__"))
    s=(d/"verdicts.py").read_text()
    for f in fs: s=f(s)
    (d/"verdicts.py").write_text(s); print("built",name)
