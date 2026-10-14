"""Builds the frozen Phase 2F contradiction-control set (investigation only).
Part 1: every conflicting operator comparison the evaluator made on the frozen data, labelled by hand
        review (mechanism + expected operator reading). Part 2: genuine-contradiction controls taken
        verbatim from the repository's existing tests. Nothing here is fed back into production."""
import json, re, sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from regulus.accuracy import operators as OP
D = sys.argv[1]
P = json.load(open(D + "/work/conflict_pairs.json"))

# ---------- hand-review overrides (pid -> label, note)
OVR = {
 "P130": ("FS_MOD_MEANS", "H-003: 'may submit ... through either ABI/ACE/ITDS or FDA PNSI' permits a CHANNEL for the act 1.279(a) mandates; the passage states no channel rule"),
 "P131": ("FS_MOD_MEANS", "H-003: 'may submit prior notice through FDA PNSI' - channel permission, same act mandated"),
 "P005": ("FS_MOD_MEANS", "B-002: 'obligations ... may be met by submission ...' permits a way of meeting an obligation; the claim states the record-keeping duty of one who so elects"),
 "P002": ("FS_MOD_ADJ", "'mode of administration ... recommended' - participle in a definition read as a recommendation (unrelated passage)"),
 "P017": ("UNREL_REAL", "compound claim (mandatory declaration + Commissioner may determine) vs a conditional permission 'such respective term may be used' - no contradiction"),
 "P032": ("UNREL_REAL", "'Deviation ... is permitted if temporary' vs 'deviation shall be justified and documented' - different propositions"),
 "P066": ("UNREL_REAL", "'FDA may withdraw an exemption' vs 'Division Director must approve an order to withdraw' - different acts"),
 "P112": ("UNREL_REAL", "'requires FDA to approve an order' vs 'FDA may withdraw' - different acts"),
 "P006": ("FS_NEG_COND", "negation inside 'provided such shipment ... is not for introduction' (a proviso the boundary list misses); strength difference is between different acts"),
 "P016": ("FS_NEG_COND", "negation inside a 'Whenever the Commissioner determines ... a combination of these does not facilitate ...' condition whose internal commas end the span early"),
 "P018": ("FS_NEG_COND", "as P016"),
 "P003": ("UNREL_REAL", "claim's 'need not be made' is a real negated duty; passage is a definition"),
 "P004": ("UNREL_REAL", "claim's 'must not be sent to this address' is real; passage states another rule"),
 "P007": ("UNREL_REAL", "'the following additional regulations shall not be applicable' is a real negation of another rule"),
 "P008": ("UNREL_REAL", "claim's 'does not apply to ... therapeutic' is real; passage another rule"),
 "P010": ("UNREL_REAL", "'references in part 640 ... are not applicable' is a real negation inside an 'except that' clause; different proposition"),
 "P011": ("UNREL_REAL", "'shall not interact with the product' is a real negated duty in another sentence of the passage"),
 "P014": ("UNREL_REAL", "'the container shall not be used' is a real negated duty in another sentence"),
 "P044": ("UNREL_REAL", "'Identification need not be applied to each individual container' is real; different proposition"),
 "P132": ("UNREL_REAL", "'another investigation is not necessary' is a real negation in a coordinate main clause"),
 "P133": ("UNREL_REAL", "as P132"), "P134": ("UNREL_REAL", "as P132"),
 "P141": ("UNREL_REAL", "'FDA does not regulate the Non-Device-MDDS functions' (real) vs 'FDA may assess the impact' - different acts"),
}
def mech(p):
    if p["pid"] in OVR: return OVR[p["pid"]]
    ops = set(p["operators"]); cs, es = p["claim_side"], p["evidence_side"]
    notes = []
    if ops == {"invented_condition"}: return ("INV", "Priority-2 invented-condition rule (not modality/negation)")
    if "actor" in ops: return ("UNREL_REAL", "different duty-holders of different rules")
    lab = None
    if "polarity" in ops:
        neg_side = es if es["polarity"] == "negate" else cs
        text = (p["evidence"] if neg_side is es else p["claim"])
        mc = neg_side["main"]; m = OP._NEGATE_RE.search(mc); tok = m.group(0).lower()
        before = mc[max(0, m.start() - 40):m.start()].lower()
        after = mc[m.end():m.end() + 15].lower()
        if tok in ("exemption", "exemptions"): lab = ("FS_NEG_NOUN", "the noun 'exemption(s)' read as a negation")
        elif tok == "not required" and not re.search(r"\b(?:is|are|was|were|be|been)\s*$", before): lab = ("FS_NEG_BARE", "reduced relative '<noun> not required to/for ...' read as negating the rule")
        elif after.startswith(" limited") : lab = ("FS_NEG_IDIOM", "'(but) are not limited to' is inclusive, not a negation")
        elif re.search(r"\b(?:that|which|who)\s*$", before): lab = ("FS_NEG_REL", "negation inside a relative clause ('<noun> that " + tok + " ...')")
        elif re.search(r"assurances?\s+that\b", mc[:m.start()].lower()): lab = ("FS_NEG_COMPL", "negation inside the complement of 'provide assurances that ...'")
        elif tok in ("prohibited", "is prohibited", "are prohibited") and es["strength"] == "permissive": lab = ("FS_MOD_EPI", "claim's prohibition vs an epistemic 'may' in a recital read as a permission")
        elif es["polarity"] == "negate" and cs["polarity"] == "negate": lab = ("UNREL_REAL", "")
        else:
            if neg_side is cs and re.match(r"\s*(?:if|when|whenever|where)\b", p["claim"], re.I) and es["polarity"] == "affirm": lab = ("FS_EXC", "claim states a CONDITIONAL exception; the passage states the general rule - not a contradiction")
            else: lab = ("UNREL_REAL", "a real main-clause negation of a different proposition")
    if "strength" in ops and lab is None:
        if es["strength"] == "permissive" and re.search(r"\b(?:to which|which|that)\b[^.]{0,60}\bmay\b", es["main"].lower()): lab = ("FS_MOD_EPI", "epistemic 'may' read as a permission")
        elif "may have become" in p["evidence"] or "might" in p["evidence"]: lab = ("FS_MOD_EPI", "epistemic 'may'")
        else: lab = ("UNREL_REAL", "a real modality difference between different propositions")
    if "strength" in ops and lab[0] == "FS_MOD_EPI": pass
    return lab
EXPECT = {  # what a correct operator reading must do with the pair
 "FS_MOD_MEANS": "no strength conflict", "FS_MOD_ADJ": "no strength conflict", "FS_MOD_EPI": "no strength/polarity conflict (recital states no rule)",
 "FS_NEG_NOUN": "no polarity conflict", "FS_NEG_BARE": "no polarity conflict", "FS_NEG_IDIOM": "no polarity conflict",
 "FS_NEG_REL": "no polarity conflict", "FS_NEG_COMPL": "no polarity conflict", "FS_NEG_COND": "no polarity conflict",
 "FS_EXC": "no contradiction (claimed exception vs general rule); NOT a modality/negation-scope case - out of narrow scope",
 "UNREL_REAL": "the real operator reading must be preserved (negation / modality still detected); the pair has no verdict role",
 "INV": "unchanged (Priority-2 invented-condition rule, out of scope)"}
out = []
for p in P:
    lab, note = mech(p)
    out.append({"control_id": p["pid"], "tier": "FROZEN", "provenance": ", ".join(f"{d}:{r}" for d, r in p["rows"]) +
                (" (LEGACY_RECONSTRUCTED evidence)" if any(d == "F60" for d, _ in p["rows"]) else " (test fixture evidence)"),
                "aligners": p["aligners"], "authority": p["authority"], "claim": p["claim"], "evidence": p["evidence"],
                "base_conflicts": p["operators"], "label": lab, "expected": EXPECT[lab], "note": note,
                "claim_finals": p["claim_finals"]})
json.dump(out, open(D + "/work/controls_frozen.json", "w"), indent=1, ensure_ascii=False)
from collections import Counter
print(Counter(o["label"] for o in out))
for o in out:
    if o["label"] in ("FS_EXC", "FS_MOD_EPI", "FS_NEG_COMPL", "FS_NEG_IDIOM"): print(" ", o["control_id"], o["label"], o["base_conflicts"], "|", o["claim"][:70], "||", o["evidence"][:70].replace("\n"," "))
