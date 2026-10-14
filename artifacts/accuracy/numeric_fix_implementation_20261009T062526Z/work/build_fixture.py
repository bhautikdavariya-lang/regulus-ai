"""Build tests/fixtures/accuracy_numeric_limit_rows.json. Evidence: VERBATIM eCFR body_text from the local read-only snapshot
(captured in Phase 2L/2M and in this phase by scan_temp_age.py; SHA-256 of the whole paragraph). Claims: CONSTRUCTED unless
marked VERBATIM. Expectations are fixed here, before the production change; 'credited_before' records that production
credited a correct claim at the baseline (a non-regression requirement, measured in Phase 2M)."""
import json, sys
R = sys.argv[1]; M = "artifacts/accuracy/measurement_audit_phase2m_20261009T055242Z/work/"
T = {}
for k, v in json.load(open(M + "numeric_cases.json"))["texts"].items(): T[k] = v
for k, v in json.load(open(M + "texts_2m.json")).items(): T[k] = v
for h in [x for xs in json.load(open(R + "/work/scan_temp_age.json")).values() for x in xs]:
    T.setdefault(h["citation"], {"text": h["paragraph"], "snapshot_date": h["snapshot_date"], "content_sha256": h["content_sha256"]})
NC = {c["id"]: c for c in json.load(open(M + "numeric_cases.json"))["cases"]}
MC = {c["id"]: c for c in json.load(open(M + "m_cases.json"))}
def sent(cit, start):
    t = T[cit]["text"]; i = t.index(start); j = t.find(". ", i); return t[i:(j + 1 if j != -1 else len(t))]
E211 = "21 CFR 211.180(a)"
R211 = T[E211]["text"]
def r211(phrase): return R211.replace("shall be retained for at least 1 year", phrase)
rows = []
def add(id_, group, cit, claim, expect, why, start=None, evidence=None, credited_before=False, src=None):
    ev = evidence or (sent(cit, start) if start else T[cit]["text"])
    assert ev in T[cit]["text"], id_
    rows.append({"id": id_, "group": group, "citation": cit, "evidence": ev, "evidence_scope": "sentence" if (start or evidence) else "paragraph",
                 "snapshot_date": T[cit]["snapshot_date"], "content_sha256": T[cit]["content_sha256"], "claim": claim,
                 "claim_provenance": ("VERBATIM text of the evidence" if claim in T[cit]["text"] else "CONSTRUCTED for testing; NOT regulatory text"),
                 "expect": expect, "credited_before": credited_before, "why": why, "source_case": src})
def fromN(id_, n, group, expect, why, **kw): c = NC[n]; add(id_, group, c["citation"], c["claim"], expect, why, evidence=c["evidence"], src="Phase 2L " + n, **kw)
def fromM(id_, m, group, expect, why, **kw): c = MC[m]; add(id_, group, c["citation"], c["claim"], expect, why, evidence=c["evidence"], src="Phase 2M " + m, **kw)
# --- reversed limits: a genuine contradiction
fromN("NL01", "N1", "min_vs_max", "conflict", "'at least 1 year' (minimum) stated as 'less than 1 year'")
fromN("NL02", "N4", "exceed_vs_not", "conflict", "'up to 1 percent' stated as 'above 1 percent'")
fromN("NL03", "N6", "at_most_vs_more", "conflict", "'no more than' stated as 'more than'")
fromN("NL04", "N7", "decimal_percent", "conflict", "'not more than 0.1 percent' stated as 'greater than 0.1 percent'")
fromN("NL05", "N16", "multiple_quantities", "conflict", "'not to exceed 0.3 percent by weight of twine' stated as 'exceeding'; the sentence also bounds glycol at 0.1 percent")
fromM("NL06", "QS3", "multiple_quantities", "conflict", "the glycol limit 'not more than 0.1 percent' stated as 'more than'")
fromN("NL07", "N11", "duration", "conflict", "'within 15 calendar days' stated as 'more than 15 calendar days after'")
fromM("NL08", "MR4", "exceed_vs_not", "conflict", "'may not exceed 30 calendar days' stated as 'may exceed'")
fromN("NL09", "N15", "negated_bound", "conflict", "'shall not be retained for more than 1 year' (a maximum) against 'at least 1 year' (a minimum)")
add("NL10", "multiple_limits_one_claim", "21 CFR 178.3760",
    "Polyethylene glycol (400) monolaurate containing less than 0.1 percent by weight of ethylene and/or diethylene glycol may be used at a level exceeding 0.3 percent by weight of twine as a finish on twine to be used for tying meat.",
    "conflict", "the glycol limit only changes strictness ('less than' vs 'not more than'), but the twine limit is reversed: the reversal must not be masked")
add("NL11", "temperature", "21 CFR 133.182(c)(2)",
    "(2) Milk shall be deemed to have been pasteurized if it has been held at a temperature of less than 143 °F for a period of not less than 30 minutes, or for a time and at a temperature equivalent thereto in phosphatase destruction.",
    "conflict", "'not less than 143 °F' stated as 'less than 143 °F'")
# --- equivalent formulations: no contradiction, and production's credit is kept
fromN("NL20", "N2", "equivalent", "equivalent", "'at least' = 'no less than'", credited_before=True)
fromN("NL21", "N5", "equivalent", "equivalent", "'no more than' = 'at most'", credited_before=True)
fromM("NL22", "QS1", "equivalent", "equivalent", "the twine limit restated", credited_before=True)
fromM("NL23", "QS2", "equivalent", "equivalent", "the glycol limit restated", credited_before=True)
fromM("NL24", "DQ1", "equivalent", "equivalent", "unqualified 'days' against 'calendar days' is not a convention mismatch", credited_before=True)
fromM("NL25", "DQ2", "equivalent", "equivalent", "verbatim", credited_before=True)
fromM("NL26", "NN1", "negated_bound", "equivalent", "'shall not be retained for less than 1 year' = 'at least 1 year'", credited_before=True)
fromM("NL27", "MR3", "equivalent", "equivalent", "'may not exceed' = 'must not exceed'", credited_before=True)
add("NL28", "temperature", "21 CFR 133.182(c)(2)",
    "(2) Milk shall be deemed to have been pasteurized if it has been held at a temperature of at least 143 °F for a period of at least 30 minutes, or for a time and at a temperature equivalent thereto in phosphatase destruction.",
    "equivalent", "'not less than' = 'at least', on both limits")
# --- a different boundary in the same direction: not credited, not contradicted
fromN("NL30", "N3", "boundary", "boundary", "'at least 1 year' (inclusive) stated as 'more than 1 year' (strict)")
fromN("NL31", "N8", "boundary", "boundary", "'not more than 0.1 percent' stated as 'less than 0.1 percent'")
# --- the same number for a different quantity, convention, scale or population: insufficient, never agreement
fromN("NL40", "N9", "different_quantity", "blocked", "0.1 percent bounds the glycol impurity, not the level on twine (which is 0.3 percent)")
fromN("NL41", "N10", "calendar_vs_business", "blocked", "15 business days is not 15 calendar days")
fromM("NL42", "DQ3", "calendar_vs_business", "blocked", "30 business days is not 30 calendar days")
fromM("NL43", "DQ4", "calendar_vs_business", "blocked", "working days are not calendar days")
add("NL44", "temperature", "21 CFR 133.182(c)(2)",
    "(2) Milk shall be deemed to have been pasteurized if it has been held at a temperature of not less than 143 °C for a period of not less than 30 minutes, or for a time and at a temperature equivalent thereto in phosphatase destruction.",
    "blocked", "143 °C is not 143 °F; the scales are not converted")
add("NL45", "age_condition", "21 CFR 201.326(a)(2)(v)", "(v) For products labeled for adults and children over 12 years of age.", "blocked",
    "an age threshold says WHO the provision covers; reversing it changes the population, which the check cannot judge", start="(v) For products")
add("NL46", "age_condition", "21 CFR 101.12(a)(2)",
    "Such reference amounts are to be used only when the food is specially formulated or processed for use by an infant or by a child over 4 years of age.",
    "blocked", "a different population, not a reversed limit", start="Such reference amounts are to be used")
# --- abstain: no numeric finding at all
fromN("NL50", "N13", "insufficient_evidence", "no_finding", "the passage states no comparable limit")
fromN("NL51", "N14", "missing_number", "no_finding", "the claim states no number")
fromM("NL52", "NN2", "ambiguous_negation", "no_finding", "'No record shall be retained for less than' is a quantifier negation: the check abstains")
add("NL53", "different_ranges", E211, r211("shall be retained for no more than 3 years"), "no_finding", "different values are never compared")
add("NL54", "ambiguous_units", E211, r211("shall be retained for less than 12 months"), "no_finding", "12 months is not converted to 1 year")
add("NL55", "ambiguous_units", "21 CFR 131.160(b)(2)", "(2) Sodium citrate in an amount greater than 1000 ppm may be added prior to culturing as a flavor precursor.",
    "no_finding", "ppm is not converted to percent")
add("NL56", "different_event", "21 CFR 1.379(a)", "FDA must hold a hearing more than 20 calendar days after the appeal is filed.", "not_the_same_limit",
    "a different event with the same number: never agreement, never a limit conflict", start="(a) FDA may detain")
add("NL57", "different_event", "21 CFR 1.379(a)", "FDA may detain an article of food for more than 20 calendar days after the appeal is filed.", "not_the_same_limit",
    "the same subject but a different event after the number ('the appeal is filed' vs 'the detention order is issued')", start="(a) FDA may detain")
fromN("NL58", "N12", "equivalent_numeric_only", "no_finding",
      "'a period that may not exceed 20 calendar days' and 'no more than 20 calendar days' are the same limit (the remaining contradiction is the strength operator, outside this change)")
json.dump({"_about": "Numeric-limit regression rows (controlled numeric fix, 2026-10-09). 'evidence' is VERBATIM eCFR body_text from the local "
           "read-only snapshot (table cfr_records; snapshot_date and SHA-256 of the whole paragraph per row); it is NOT exact model-prompt evidence. "
           "'claim' is CONSTRUCTED for testing unless claim_provenance says VERBATIM, and is not regulatory text. 'credited_before': production "
           "credited this correct claim before the change (measured in Phase 2M); the change must keep it credited. Do not edit.",
           "rows": rows}, open("tests/fixtures/accuracy_numeric_limit_rows.json", "w"), indent=1, ensure_ascii=False)
from collections import Counter
print(len(rows), "rows", dict(Counter(r["expect"] for r in rows)), "| verbatim claims:", [r["id"] for r in rows if r["claim_provenance"].startswith("VERBATIM")])
