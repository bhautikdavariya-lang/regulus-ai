"""OFFLINE ONLY (Phase 2I): patched COPIES of the CURRENT production regulus.accuracy. Production src/ is never edited.
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
    _qc, _qe = _p2i_qualifiers(claim), _p2i_qualifiers(evidence)
    for _v in sorted(set(_qc) & set(_qe)):
        if len(_qc[_v]) == 1 and len(_qe[_v]) == 1 and _qc[_v] != _qe[_v]:
            conflicts.append(note("qualifier_polarity", f"the answer and the evidence qualify by '{_v}' with opposite negation",
                                  sorted(_qc[_v]), sorted(_qe[_v])))
            break
    # -- actor: the DUTY-HOLDER, not every party mentioned.''')
    return s
VARIANTS = {"I0_identity": set(), "IA_sent": {"SENT"}, "IB_rel": {"REL"}, "IBQ_rel_qual": {"REL", "QUAL"}, "IABQ_combined": {"SENT", "REL", "QUAL"}}
for name, flags in VARIANTS.items():
    d = W / "variants" / name / "regulus" / "accuracy"
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("__pycache__"))
    (d / "operators.py").write_text(operators((d / "operators.py").read_text(), flags))
    print("built", name, sorted(flags))
