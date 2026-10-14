"""Final per-case classification of the 78 remaining false conflicts (hand review recorded here, with the
measured counterfactual impact). Output: cases_classified.json + table_cases.md."""
import json, re, sys
from collections import Counter
sys.path.insert(0, "src")
from regulus.accuracy import operators as OP
W = sys.argv[1] + "/work/"
C = json.load(open(W + "cases_78.json"))
CAT = {
 "FS_NEG_REL": ("NEG-REL", "negation scope: negation inside a relative clause that modifies a noun"),
 "FS_NEG_COMPL": ("NEG-PURPOSE", "obligation vs purpose: negation inside the complement of 'to provide assurances that ...'"),
 "FS_NEG_NOUN": ("NEG-NOUN", "lexical negation trigger: the noun 'exemption(s)'"),
 "FS_NEG_COND": ("NEG-COND", "condition span: negation inside a condition whose span is cut short (internal commas, 'provided such')"),
 "FS_NEG_IDIOM": ("NEG-IDIOM", "lexical negation trigger: '(but) are not limited to'"),
 "FS_MOD_EPI": ("MOD-EPISTEMIC", "modality: an epistemic 'may' (possibility) read as a deontic permission"),
 "FS_MOD_ADJ": ("MOD-PARTICIPLE", "modality: the participle 'recommended' in a definition read as a recommendation"),
 "FS_MOD_MEANS": ("MOD-MEANS", "modality: a permission over the means ('may be met by submission') vs the duty"),
}
# hand review: how the conflicting passage relates to the claim's proposition
STATING = {"P058": "117.135(a)(1) states s5 ('requires preventive controls to minimize or prevent hazards')",
           "P059": "117.139 states s8 ('You must establish a written recall plan')",
           "P060": "117.139 states s8 ('You must establish a written recall plan')",
           "P016": "701.13(a) states both halves of s3 across sentences", "P018": "701.13(a) states both halves of s3 across sentences"}
RELATED = {"P005": "same paragraph, 600.80(c)(1)(iii); the claim is supported verbatim by another passage",
           "P012": "606.65; the claim is supported by another 606.65 passage",
           "P019": "the ingredient's own section; recital only", "P020": "own section; recital only", "P021": "own section; recital only",
           "P022": "own section; recital only", "P023": "own section; recital only", "P024": "own section; recital only",
           "P025": "own section; recital only", "P026": "own section; recital only", "P027": "own section; recital ('deleterious substance')",
           "P028": "own section; 'deemed to be adulterated' (prohibition only by legal inference, Phase 2E ambiguous)",
           "P029": "own section; recital only", "P030": "own section; recital only",
           "P088": "117.135, the provision the definition points to", "P089": "117.135, the provision the definition points to",
           "P091": "117.135, the provision the definition points to", "P101": "117.135(a)(1) states 'implement', not 'verified'",
           "P120": "recall-plan passage for a multi-part anaphoric claim", "P121": "117.135(a)(1) 'provide assurances' for a multi-part claim",
           "P122": "recall-plan passage for a multi-part anaphoric claim", "P126": "117.135(a)(1) 'implement preventive controls' for a list item",
           "P064": "117.251 withdrawal vs 117.201 modified requirements (same subpart)"}
CONF = {"MOD-EPISTEMIC": "medium", "MOD-MEANS": "medium", "NEG-COND": "medium"}
G2 = {"MOD-MEANS": "same family as the Phase 2G MEANS rule, not covered: 'by' is not a means marker and the clause is passive",
      "NEG-REL": "none (Phase 2G removed only the bare 'not required')"}
def other_sentence(text, tok_start):
    head = text[:tok_start]
    return bool(re.search(r"[.;:]\s+(?:\(\w+\)\s*)?[A-Z(]", head))
out = []
for c in C:
    cat, catdesc = CAT[c["label_2F"]]
    neg_side = None; trig = None
    if "polarity" in c["conflicts_now"]:
        neg_side = "evidence" if c["evidence_ops"]["polarity"] == "negate" else "claim"
        t = c["evidence"] if neg_side == "evidence" else c["claim"]
        mc = OP.main_clause(t); m = OP._NEGATE_RE.search(mc)
        trig = {"side": neg_side, "token": m.group(0), "context": mc[max(0, m.start() - 100): m.end() + 40].replace("\n", " "),
                "in_another_sentence_of_the_passage": other_sentence(mc, m.start())}
    rel = "STATING" if c["case"] in STATING else "RELATED" if c["case"] in RELATED else "UNRELATED"
    occ = c["occurrences"]
    if c["case"] in ("P088", "P123"):
        sent = "F-009 s0 (split into s0.1, s0.2)" if c["case"] == "P088" else "F-022 s4 (split into s4.1-s4.3)"
        occ_ids = [f"{d}:{sent}" for d in ("F60", "REAL17")] if c["case"] == "P088" else [f"F60:{sent}"]
    else:
        occ_ids = sorted({f"{o['dataset']}:{o['row']}:{o['claim_id']}" for o in occ})
    impact = "citation dimension: F-003 citation 'pass' currently rests on this false conflict (marker counted as 'contradicted' = decided); without it 'not_established' - no answer verdict or score change" if c["case"] == "P058" else "none measured (0 claim, 0 answer, 0 dimension changes when removed)"
    sev = "S2-dimension" if c["case"] == "P058" else ("S1-latent" if rel != "UNRELATED" else "S0-noise")
    out.append({**{k: c[k] for k in ("case", "authority", "provenance", "claim", "evidence", "conflicts_now")},
                "category": cat, "category_description": catdesc, "trigger": trig,
                "claim_operators": c["claim_ops"], "evidence_operators": c["evidence_ops"],
                "evidence_relation": rel, "relation_note": STATING.get(c["case"]) or RELATED.get(c["case"]) or "a different provision / proposition",
                "claims": occ_ids, "rows": sorted({x.split(":")[1] for x in occ_ids}),
                "final_verdicts_now": sorted({f"{o['final']}/{o['basis']}" for o in occ}),
                "verdict_impact": impact, "severity": sev, "confidence": CONF.get(cat, "high"),
                "overlap_with_phase2G": G2.get(cat, "none")})
json.dump(out, open(W + "cases_classified.json", "w"), indent=1, ensure_ascii=False)
print(Counter(o["category"] for o in out))
print(Counter((o["category"], o["evidence_relation"]) for o in out))
print(Counter(o["severity"] for o in out))
print("NEG-REL trigger in another sentence of the passage:", sum(1 for o in out if o["category"] == "NEG-REL" and o["trigger"]["in_another_sentence_of_the_passage"]), "| claim-side:", sum(1 for o in out if o["category"] == "NEG-REL" and o["trigger"]["side"] == "claim"))
print("claims:", len({x for o in out for x in o["claims"]}), "rows:", len({r for o in out for r in o["rows"]}))
