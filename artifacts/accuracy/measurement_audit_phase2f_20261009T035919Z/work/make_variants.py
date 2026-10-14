"""OFFLINE ONLY: patched COPIES of regulus.accuracy under work/variants/<name>/. Production src/ is never edited.
Each candidate rule is a flag; a variant is a set of flags."""
import shutil, sys
from pathlib import Path
W = Path(sys.argv[1]); SRC = Path("src/regulus/accuracy")
def rep(s, old, new):
    assert s.count(old) == 1, (old[:70], s.count(old)); return s.replace(old, new)
PATCH_HELPERS = '''

# ---------------- Phase 2F OFFLINE candidate rules (flags set per variant copy)
_P2F_FLAGS: frozenset = frozenset(__P2F_FLAGS__)
# words after which "that" opens a COMPLEMENT clause (its negation is part of what is stated), not a relative clause
_P2F_COMPLEMENT = frozenset("""ensure ensures ensured assure assures assured insure require requires required provide provides
state states stated specify specifies specified mean means determine determines determined certify certifies demonstrate
demonstrates show shows so such indicate indicates document documents verify verifies confirm confirms assurance assurances
evidence notify notifies inform informs agree agrees certification statement""".split())


def _p2f_negations(body: str) -> list:
    out = []
    for m in _NEGATE_RE.finditer(body):
        tok = m.group(0).lower()
        if "NOUN" in _P2F_FLAGS and tok in ("exemption", "exemptions"):
            continue                                   # a noun names an exemption; it does not negate the duty
        if "BARE" in _P2F_FLAGS and tok == "not required":
            continue                                   # no copula: "<noun> not required to/for ..." is a modifier
        if "IDIOM" in _P2F_FLAGS and re.match(r"\\s+limited\\s+to\\b", body[m.end():], re.I):
            continue                                   # "(but) are not limited to" is inclusive
        if "REL" in _P2F_FLAGS:
            before = re.findall(r"[A-Za-z]+", body[: m.start()])
            if len(before) >= 2 and before[-1].lower() in ("that", "which", "who") and before[-2].lower() not in _P2F_COMPLEMENT:
                continue                               # negation inside a relative clause modifying a noun
        out.append(m)
    return out


def _p2f_permission_over_means(c_text: str, e_text: str, c_strength, e_strength) -> bool:
    """One side PERMITS a way (channel, means) of doing the act the other side MANDATES, and the mandating
    side states no means of its own: the permission is about HOW, not WHETHER - not a modal conflict."""
    from regulus.accuracy.intent import stem
    if {c_strength, e_strength} != {PERMISSIVE, MANDATORY}:
        return False
    perm, mand = (c_text, e_text) if c_strength == PERMISSIVE else (e_text, c_text)
    perm, mand = main_clause(perm), main_clause(mand)
    m = re.search(r"\\b(?:may|can)\\s+(?:be\\s+)?([a-z]+)\\b", perm, re.I)
    if not m:
        return False
    means = re.compile(r"\\b(?:through|via|using|by\\s+means\\s+of|by\\s+way\\s+of|either)\\b", re.I)
    if not means.search(perm[m.end():]) or means.search(mand):
        return False
    verb = stem(m.group(1).lower())
    return any(stem(w.lower()) == verb for w in re.findall(r"[A-Za-z]+", mand))
'''
def operators(s, flags):
    s = s + PATCH_HELPERS.replace("__P2F_FLAGS__", repr(sorted(flags)))
    s = rep(s, '''    if _NEGATE_RE.search(body):
        return NEGATE
    return AFFIRM if strength(text) is not None else None''', '''    if _p2f_negations(body):
        return NEGATE
    return AFFIRM if strength(text) is not None else None''')
    if "COMPL" in flags:
        s = rep(s, r'''r"|(?:(?:in\s+order\s+)?to\s+)?(?:ensure[sd]?|assure[sd]?|insure[sd]?|make\s+sure|guarantee[sd]?))\b", re.I)''',
                   r'''r"|(?:(?:in\s+order\s+)?to\s+)?(?:ensure[sd]?|assure[sd]?|insure[sd]?|make\s+sure|guarantee[sd]?)"
    r"|(?:in\s+order\s+)?to\s+provide\s+(?:an?\s+)?assurances?)\b", re.I)''')
    if "SPAN" in flags:
        s = rep(s, '''    for m in _CONDITION_BOUNDARY_RE.finditer(body):
        comma = body.find(",", m.end())
        spans.append((m.start(), comma if comma != -1 else len(body)))
    for m in _PURPOSE_BOUNDARY_RE.finditer(body):     # a purpose clause runs to the end of its sentence
        spans.append((m.start(), len(body)))''', '''    for m in _CONDITION_BOUNDARY_RE.finditer(body):
        comma = body.find(",", m.end())
        spans.append((m.start(), comma if comma != -1 else len(body)))
    for m in _PURPOSE_BOUNDARY_RE.finditer(body):     # a purpose clause runs to the end of its sentence
        spans.append((m.start(), len(body)))
    # Phase 2F SPAN: a subordinate clause cannot hold the main modal; end it before one
    trimmed = []
    for start, end in spans:
        inner = _first_modal(body[start + 1:end])
        trimmed.append((start, start + inner) if inner is not None else (start, end))
    spans = trimmed''')
    if "MEANS" in flags:
        s = rep(s, '''    elif (c.strength, e.strength) in _STRENGTH_CONFLICTS:
        conflicts.append(note(CONFLICT_STRENGTH,''', '''    elif _p2f_permission_over_means(claim, evidence, c.strength, e.strength):
        relate(CONFLICT_STRENGTH, "permission_over_means", c.strength, e.strength,
               "one side permits a channel or means for the act the other mandates, and the mandate names no means")
    elif (c.strength, e.strength) in _STRENGTH_CONFLICTS:
        conflicts.append(note(CONFLICT_STRENGTH,''')
    if "EPI" in flags:
        s = rep(s, '''def _deontic_permission(text: str) -> bool:
    if _PASSIVE_PERMISSION_RE.search(text):''', '''def _deontic_permission(text: str) -> bool:
    _m = _PERMISSIVE_MODAL_RE.search(text)
    if _m and re.search(r"\\b(?:which|whom|to\\s+which|in\\s+which)\\s+(?:[\\w-]+\\s+){0,3}$", text[: _m.start()], re.I):
        return False      # Phase 2F EPI: a modal in a relative clause describes, it grants nothing
    if _PASSIVE_PERMISSION_RE.search(text):''')
    return s
VARIANTS = {
    "V0_identity": set(),                       # harness check: must equal production exactly
    "VN_bare": {"BARE"}, "VN_span": {"SPAN"}, "VN_noun": {"NOUN"}, "VN_idiom": {"IDIOM"}, "VN_rel": {"REL"}, "VN_compl": {"COMPL"},
    "VM_means": {"MEANS"}, "VM_epi": {"EPI"},
    "VT_targeted": {"BARE", "MEANS"},
    "VT2_targeted_span": {"BARE", "SPAN", "MEANS"},           # the smallest change aimed only at H-003 and D-009
    "VN_all": {"BARE", "NOUN", "IDIOM", "REL", "COMPL"},
    "VA_all": {"BARE", "NOUN", "IDIOM", "REL", "COMPL", "MEANS", "EPI"},
}
for name, flags in VARIANTS.items():
    d = W / "variants" / name / "regulus" / "accuracy"
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("__pycache__"))
    (d / "operators.py").write_text(operators((d / "operators.py").read_text(), flags))
    print("built", name, sorted(flags))
