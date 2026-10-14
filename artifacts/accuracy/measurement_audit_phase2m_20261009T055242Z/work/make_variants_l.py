"""OFFLINE ONLY (Phase 2L: Phase 2K code + NUM limit-direction check; Phase 2K: Phase 2J code + JR / JRC fallbacks; Phase 2J, built on the Phase 2I candidate code; adds QPART): patched COPIES of the CURRENT production regulus.accuracy. Production src/ is never edited.
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


# ---------------- Phase 2K fallbacks
_P2K_SKIP = frozenset("""the a an this that these those its their his her our your any each every all some such no
be been being is are was were do does did have has had will would shall should may might must can could to""".split())
_P2K_NEGATORS = frozenset("not no without never non".split())


def _p2k_key_after(body: str, m) -> str | None:
    """The qualifier's content word after the negation: skip auxiliaries, determiners and -ly adverbs
    ('that are not the subject' -> 'subject'; 'that cannot be adequately sanitized' -> 'sanitized')."""
    for w in re.findall(r"[A-Za-z][A-Za-z\-']*", body[m.end():])[:6]:
        lw = w.lower()
        if lw in _P2K_SKIP or lw.endswith("ly"):
            continue
        return _p2j_key(lw)
    return None


def _p2k_rel_qualifiers(text: str) -> list:
    """JR: [(key, negated)] for relative clauses only, determiner/adverb-aware."""
    out = []
    for m in re.finditer(r"\b(?:that|which|who)\b", text or "", re.I):
        before = re.findall(r"[A-Za-z]+", text[: m.start()])
        if before and before[-1].lower() in _P2I_COMPLEMENT:
            continue
        rest = text[m.end():]
        neg = bool(re.match(r"\s+(?:(?:do|does|did|is|are|was|were|will|can|could|may|must|shall|has|have|had|would|should)\s+not\b|cannot\b)", rest, re.I))
        key = None
        for w in re.findall(r"[A-Za-z][A-Za-z\-']*", rest)[:6]:
            lw = w.lower()
            if lw in _P2K_SKIP or lw in ("not", "cannot") or lw.endswith("ly"):
                continue
            key = _p2j_key(lw); break
        if key and not (before and before[-1].lower() in ("to", "so", "such")):
            out.append((key, neg))
    return out


def _p2k_jr_conflict(claim: str, evidence: str):
    qc, qe = _p2k_rel_qualifiers(claim), _p2k_rel_qualifiers(evidence)
    for kc, nc in qc:
        same = [ne for ke, ne in qe if ke == kc or ke + "e" == kc or kc + "e" == ke]
        if same and len(set(same)) == 1 and same[0] != nc:
            return kc, nc, same[0]
    return None


def _p2k_mentioned_unnegated(key: str, other: str) -> bool:
    toks = re.findall(r"[A-Za-z][A-Za-z\-']*", other or "")
    for i, t in enumerate(toks):
        k = _p2j_key(t.lower())
        if k == key or k + "e" == key or key + "e" == k:
            prev = toks[i - 1].lower() if i else ""
            if prev not in _P2K_NEGATORS and not t.lower().startswith("non"):
                return True
    return False


def _p2k_relc_polarity(op, text: str, other: str):
    """JRC: drop a NEGATE that comes ONLY from relative-clause negations, unless the other side mentions
    that qualifier's word un-negated (then keep the production reading - the conservative choice)."""
    if op.polarity != NEGATE:
        return op
    body = main_clause(text or "")
    negs = list(_NEGATE_RE.finditer(body))
    rel = [m for m in negs if _p2i_relative_negation(body, m)]
    if not rel or len(rel) < len(negs):
        return op
    for m in rel:
        key = _p2k_key_after(body, m)
        if key is None or _p2k_mentioned_unnegated(key, other):
            return op
    import dataclasses as _dc
    return _dc.replace(op, polarity=AFFIRM if strength(text) is not None else None)


# ---------------- Phase 2L NUM: limit direction on the SAME quantity (independent of the clause logic)
_P2L_NUMW = "one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|sixty|ninety"
_P2L_NUM = rf"(\d+(?:,\d{{3}})*(?:\.\d+)?|{_P2L_NUMW})"
_P2L_UNIT = (r"(percent|%|(?:calendar\s+|business\s+|working\s+)?days?|weeks?|months?|years?|hours?|minutes?|"
             r"milligrams?|mg|grams?|g|kilograms?|kg|milliliters?|ml|liters?|ppm|ppb|degrees?)\b")
_P2L_PATTERNS = (   # longest / negation-bearing forms first; a span is claimed by the first pattern that matches it
    ("<=", r"\b(?:(?:do|does|did|shall|must|may|will|can|should)\s+not\s+exceed|not\s+to\s+exceed|not\s+exceeding|no\s+more\s+than|"
           r"not\s+more\s+than|at\s+most|up\s+to|no\s+longer\s+than|not\s+longer\s+than|maximum\s+of|within)"),
    (">=", r"\b(?:at\s+least|not\s+less\s+than|no\s+less\s+than|no\s+fewer\s+than|not\s+fewer\s+than|minimum\s+of)"),
    ("<",  r"\b(?:less\s+than|fewer\s+than|below|under|shorter\s+than)"),
    (">",  r"\b(?:exceed(?:s|ed|ing)?|more\s+than|greater\s+than|above|over|longer\s+than|in\s+excess\s+of)"),
)
_P2L_TIME = ("day", "calendar day", "business day", "working day", "week", "month", "year", "hour", "minute")
_P2L_NEGATORS = re.compile(r"\b(?:not|no|never|cannot|neither|nor)\b", re.I)
_P2L_STOP = frozenset("""a an the of to for in on at by with from and or that which who is are be been may must shall can will
used use any each such its their this these those than as""".split())


def _p2l_unit(u: str) -> str:
    u = re.sub(r"\s+", " ", u.lower()).strip()
    if u in ("%", "percent"): return "percent"
    for a, b in (("milligram", "mg"), ("gram", "g"), ("kilogram", "kg"), ("milliliter", "ml"), ("liter", "l")):
        if u.rstrip("s") == a: return b
    return u[:-1] if u.endswith("s") and u not in ("ppms",) else u


def _p2l_bounds(text: str) -> list:
    """[(relation, value, unit, context stems)] for each unambiguous bound; ambiguous ones are dropped."""
    from regulus.accuracy.intent import stem
    t = text or ""
    taken, out = [], []
    _all = []                                             # NUM2: every bound span, to discount their own negations
    for rel, phrase in _P2L_PATTERNS:
        for m in re.finditer(phrase + r"\s+(?:a\s+(?:period|total|level)\s+of\s+)?" + _P2L_NUM + r"\s*" + _P2L_UNIT, t, re.I):
            _all.append((m.start(), m.end()))
    for rel, phrase in _P2L_PATTERNS:
        for m in re.finditer(phrase + r"\s+(?:a\s+(?:period|total|level)\s+of\s+)?" + _P2L_NUM + r"\s*" + _P2L_UNIT, t, re.I):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            unit = _p2l_unit(m.group(m.lastindex))
            if rel == "<=" and re.match(r"\s*within", t[m.start():], re.I) and unit not in _P2L_TIME:
                continue                                  # 'within' bounds only durations
            clause = re.split(r"[.;:]\s", t[: m.start()])[-1]
            cstart = m.start() - len(clause)
            scan = clause
            if "NUM2" in _P2I_FLAGS:                       # discount negations inside OTHER bound phrases
                for s0, e0 in _all:
                    if e0 <= m.start() and s0 >= cstart:
                        scan = scan[: s0 - cstart] + " " * (e0 - s0) + scan[e0 - cstart:]
            if _P2L_NEGATORS.search(scan):                # a negation outside the bound phrase: scope ambiguous
                out.append(("ambiguous", None, None, None, None)); continue
            ctx = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", clause) if w.lower() not in _P2L_STOP][-4:]
            tail = frozenset()
            if "NUM2" in _P2I_FLAGS:                       # what the quantity is OF ('by weight of twine')
                after = re.split(r"[.;:]\s", t[m.end():])[0]
                tail = frozenset(stem(w.lower()) for w in [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", after)
                                 if w.lower() not in _P2L_STOP and w.lower() not in ("weight", "after", "before", "per")][:4])
            out.append((rel, _normalise_number(_NUM_WORDS.get(m.group(m.lastindex - 1).lower(), m.group(m.lastindex - 1))), unit,
                        frozenset(stem(w.lower()) for w in ctx), tail))
    return out


def _p2l_compare(claim: str, evidence: str):
    """('conflict' | 'boundary', detail) for the same value+unit+context, or None (no finding / ambiguous)."""
    bc, be = _p2l_bounds(claim), _p2l_bounds(evidence)
    if any(b[0] == "ambiguous" for b in bc):
        return None
    upper, lower = {"<=", "<"}, {">=", ">"}
    for rc, vc, uc, cc, tc in bc:
        same = [(re_, ce) for re_, ve, ue, ce, te in be if re_ != "ambiguous" and ve == vc and ue == uc and cc & ce
                and not ("NUM2" in _P2I_FLAGS and tc and te and not (tc & te))]
        rels = {r for r, _ in same}
        if not same or len(rels) != 1:
            continue                                      # nothing comparable, or the evidence reads two ways
        re_ = rels.pop()
        if re_ == rc:
            continue
        if (rc in upper) != (re_ in upper):
            return ("conflict", f"the answer bounds {vc} {uc} as '{rc}' where the evidence bounds it as '{re_}'")
        return ("boundary", f"the answer's boundary '{rc}' {vc} {uc} differs from the evidence's '{re_}'")
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
    if "RELC" in flags:
        s = rep(s, "    c, e = extract(claim), extract(evidence)\n", """    c, e = extract(claim), extract(evidence)
    if "RELC" in _P2I_FLAGS:
        c, e = _p2k_relc_polarity(c, claim, evidence), _p2k_relc_polarity(e, evidence, claim)
""")
    if "NUM" in flags or "NUM2" in flags:
        s = rep(s, """    if not claim_kinds:
        undetermined.append(CONFLICT_QUANTITY)
""", """    if not claim_kinds:
        undetermined.append(CONFLICT_QUANTITY)
    if "NUM" in _P2I_FLAGS or "NUM2" in _P2I_FLAGS:          # Phase 2L limit direction
        _lx = _p2l_compare(claim, evidence)
        if _lx and _lx[0] == "conflict":
            conflicts.append(note("limit_direction", _lx[1], None, None))
        elif _lx and support_blocked is None:
            support_blocked = _lx[1]
""")
    if "QUAL" in flags:
        s = rep(s, "    # -- actor: the DUTY-HOLDER, not every party mentioned.", '''    # -- Phase 2I QUAL: a relative-clause qualifier both sides state, with opposite negation, is a conflict
    if "JRQ" in _P2I_FLAGS:
        _qx = _p2k_jr_conflict(claim, evidence)
        if _qx:
            conflicts.append(note("qualifier_polarity", f"the answer and the evidence qualify by '{_qx[0]}' with opposite negation",
                                  _qx[1], _qx[2]))
    elif "QPART" in _P2I_FLAGS:
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
VARIANTS = {"L0_identity": set(), "JR": {"REL", "QUAL", "JRQ"}, "NUM": {"NUM"}, "JRN": {"REL", "QUAL", "JRQ", "NUM"}, "NUM2": {"NUM2"}, "JRN2": {"REL", "QUAL", "JRQ", "NUM2"}}
for name, flags in VARIANTS.items():
    d = W / "variants" / name / "regulus" / "accuracy"
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("__pycache__"))
    (d / "operators.py").write_text(operators((d / "operators.py").read_text(), flags))
    print("built", name, sorted(flags))
