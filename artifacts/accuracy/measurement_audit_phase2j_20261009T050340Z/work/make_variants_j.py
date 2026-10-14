"""OFFLINE ONLY (Phase 2J, built on the Phase 2I candidate code; adds QPART): patched COPIES of the CURRENT production regulus.accuracy. Production src/ is never edited.
Flags:  SENT = approach A (sentence-local polarity)   REL = approach B (relative-clause scope, the Phase 2F rule)
        QUAL = qualifier check that keeps a negated relative clause MATERIAL when both sides share it (used with REL)."""
import shutil, sys
from pathlib import Path
W = Path(sys.argv[1]); SRC = Path("src/regulus/accuracy")
def rep(s, old, new):
    assert s.count(old) == 1, (old[:70], s.count(old)); return s.replace(old, new)
HELPERS = r'''

# ---------------- Phase 2I OFFLINE candidates (flags set per copy)
_P2I_FLAGS: frozenset = frozenset(__FLAGS__)
_P2I_COMPLEMENT = frozenset("""ensure ensures ensured assure assures assured insure require requires required provide provides
state states stated specify specifies specified mean means determine determines determined certify certifies demonstrate
demonstrates show shows so such indicate indicates document documents verify verifies confirm confirms assurance assurances
evidence notify notifies inform informs agree agrees certification statement""".split())
_P2I_REL_NEG = re.compile(r"\b(that|which|who)\s+(?:(?:do|does|did|is|are|was|were|will|can|could|may|must|shall|has|have|had|would|should)\s+not|cannot)\b", re.I)


def _p2i_relative_negation(body: str, m: "re.Match") -> bool:
    """B: the negation directly follows a relative pronoun that does not open a complement clause."""
    before = re.findall(r"[A-Za-z]+", body[: m.start()])
    return (len(before) >= 2 and before[-1].lower() in ("that", "which", "who")
            and before[-2].lower() not in _P2I_COMPLEMENT)


def _p2i_negations(body: str) -> list:
    out = []
    for m in _NEGATE_RE.finditer(body):
        if "REL" in _P2I_FLAGS and _p2i_relative_negation(body, m):
            continue
        out.append(m)
    return out


_P2I_UNIT_SPLIT = re.compile(r"(?<=[.;:])\s+(?=\(?[A-Za-z0-9]{1,4}\)|[A-Z])|\n+(?=\s*\(?[A-Za-z0-9]{1,4}\))")


def _p2i_units(text: str) -> list:
    return [u.strip() for u in _P2I_UNIT_SPLIT.split(text or "") if u and u.strip()]


def _p2i_best_unit(text: str, other: str) -> str:
    """A: the sentence / enumerated unit of `text` that best matches `other` (stemmed content overlap)."""
    from regulus.accuracy.intent import stem
    units = _p2i_units(text)
    if len(units) < 2:
        return text
    want = {stem(w.lower()) for w in re.findall(r"[A-Za-z]{3,}", other or "")}
    def score(u):
        have = {stem(w.lower()) for w in re.findall(r"[A-Za-z]{3,}", u)}
        return len(want & have) / (len(have) or 1) + len(want & have)
    return max(units, key=score)


_P2I_REL_Q = re.compile(r"\b(?:that|which|who)\s+(?:(?:do|does|did|is|are|was|were|will|can|could|may|must|shall|has|have|had|would|should)\s+)?(not\s+|cannot\s+)?(?:be\s+|been\s+)?([a-z]{3,})\b", re.I)
_P2I_AUX = frozenset("do does did is are was were will can could may must shall has have had would should be been not".split())


def _p2i_qualifiers(text: str) -> dict:
    """QUAL: {verb stem: negated?} for each relative clause ('batches that do not conform' -> conform: True)."""
    from regulus.accuracy.intent import stem
    out = {}
    for m in _P2I_REL_Q.finditer(text or ""):
        verb = m.group(2).lower()
        if verb in _P2I_AUX:
            continue
        neg = bool(m.group(1)) or bool(re.search(r"cannot\s*$", text[m.start():m.start(2)], re.I))
        out.setdefault(stem(verb), set()).add(neg)
    return out


_P2J_NOT_NOUN = frozenset("""a an the and or but of to for in on at by with from into onto upon as than that which who whom whose this these those
is are was were be been being am do does did has have had will would shall should may might must can could not no nor any each every all
some such its their his her our your it they he she we you if when where while whether""".split())
_P2J_PREP_PARTICIPLE = frozenset("""including following regarding concerning according excluding pending during notwithstanding using
involving considering beginning ending""".split())
_P2J_PART = re.compile(r"\b([a-z][a-z'\-]*)\s+(not\s+)?([a-z]{3,}ing)\b", re.I)
_P2J_WITHOUT = re.compile(r"\bwithout\s+([a-z]{3,}ing)\b", re.I)


def _p2j_key(word: str) -> str:
    w = word.lower()
    for suf in ("ing", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _p2j_same(a: str, b: str) -> bool:
    if "QEXACT" in _P2I_FLAGS:      # morphological identity only ("requir" ~ "require"), never prefix similarity
        return a == b or a + "e" == b or b + "e" == a
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long.startswith(short) and len(long) - len(short) <= 2


def _p2j_qualifiers(text: str) -> list:
    """[(verb key, negated)] for relative clauses AND participle / 'without' qualifiers."""
    out = []
    for m in _P2I_REL_Q.finditer(text or ""):
        verb = m.group(2).lower()
        if "QEXACT" in _P2I_FLAGS and verb.endswith("ly"):      # skip an adverb to reach the verb
            nxt = re.match(r"\s+([a-z]{3,})\b", text[m.end():], re.I)
            verb = nxt.group(1).lower() if nxt else verb
        if verb in _P2I_AUX:
            continue
        neg = bool(m.group(1)) or bool(re.search(r"cannot\s*$", text[m.start():m.start(2)], re.I))
        out.append((_p2j_key(verb), neg))
    if "QPART" in _P2I_FLAGS:
        for m in _P2J_PART.finditer(text or ""):
            head, neg, part = m.group(1).lower(), bool(m.group(2)), m.group(3).lower()
            if head in _P2J_NOT_NOUN or part in _P2J_PREP_PARTICIPLE or head.endswith("ing"):
                continue
            out.append((_p2j_key(part), neg))
        for m in _P2J_WITHOUT.finditer(text or ""):
            if m.group(1).lower() not in _P2J_PREP_PARTICIPLE:
                out.append((_p2j_key(m.group(1)), True))
    return out


def _p2j_qualifier_conflict(claim: str, evidence: str):
    qc, qe = _p2j_qualifiers(claim), _p2j_qualifiers(evidence)
    for kc, nc in qc:
        same = [ne for ke, ne in qe if _p2j_same(kc, ke)]
        if same and len(set(same)) == 1 and same[0] != nc and len({n for k, n in qc if _p2j_same(k, kc)}) == 1:
            return kc, nc, same[0]
    return None
'''
def operators(s, flags):
    s = s + HELPERS.replace("__FLAGS__", repr(sorted(flags)))
    s = rep(s, '''    if _NEGATE_RE.search(body):
        return NEGATE
    return AFFIRM if strength(text) is not None else None''', '''    if _p2i_negations(body):
        return NEGATE
    return AFFIRM if strength(text) is not None else None''')
    if "SENT" in flags:
        s = rep(s, "    c, e = extract(claim), extract(evidence)\n", '''    c, e = extract(claim), extract(evidence)
    import dataclasses as _dc
    _cu, _eu = _p2i_best_unit(claim, evidence), _p2i_best_unit(evidence, claim)
    if _cu != claim:
        c = _dc.replace(c, polarity=polarity(_cu))
    if _eu != evidence:
        e = _dc.replace(e, polarity=polarity(_eu))
''')
    if "QUAL" in flags:
        s = rep(s, "    # -- actor: the DUTY-HOLDER, not every party mentioned.", '''    # -- Phase 2I QUAL: a relative-clause qualifier both sides state, with opposite negation, is a conflict
    if "QPART" in _P2I_FLAGS:
        _qx = _p2j_qualifier_conflict(claim, evidence)
        if _qx:
            conflicts.append(note("qualifier_polarity", f"the answer and the evidence qualify by '{_qx[0]}' with opposite negation",
                                  _qx[1], _qx[2]))
    else:
        _qc, _qe = _p2i_qualifiers(claim), _p2i_qualifiers(evidence)
        for _v in sorted(set(_qc) & set(_qe)):
            if len(_qc[_v]) == 1 and len(_qe[_v]) == 1 and _qc[_v] != _qe[_v]:
                conflicts.append(note("qualifier_polarity", f"the answer and the evidence qualify by '{_v}' with opposite negation",
                                      sorted(_qc[_v]), sorted(_qe[_v])))
                break
    # -- actor: the DUTY-HOLDER, not every party mentioned.''')
    return s
VARIANTS = {"J0_identity": set(), "JBQ": {"REL", "QUAL"}, "JBQP": {"REL", "QUAL", "QPART"}, "JBQP2": {"REL", "QUAL", "QPART", "QEXACT"}}
for name, flags in VARIANTS.items():
    d = W / "variants" / name / "regulus" / "accuracy"
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("__pycache__"))
    (d / "operators.py").write_text(operators((d / "operators.py").read_text(), flags))
    print("built", name, sorted(flags))
