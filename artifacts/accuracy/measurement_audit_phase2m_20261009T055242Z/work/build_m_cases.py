"""Phase 2M labelled diagnostics. Evidence: VERBATIM eCFR text (texts_2m.json, read-only snapshot, SHA-256 of the whole
paragraph recorded; where a single sentence is used it is an exact substring). Claims: CONSTRUCTED (one modal, negation,
bound, unit or qualifier changed, or a verbatim clause) - NOT regulatory text. Expectations fixed BEFORE any candidate ran.
expect: conflict = a conflict and not credited | equivalent = not contradicted | not_credited = not credited (block or
unverifiable; a contradiction is also acceptable) | no_polarity_conflict = operator level, as T3c/DX4."""
import json, sys
W = sys.argv[1]
T = json.load(open(W + "/texts_2m.json"))
def sent(cit, start):
    t = T[cit]["text"]; i = t.index(start); j = t.index(". ", i) + 1 if ". " in t[i:] else len(t); return t[i:j]
N15C = "(a) Any production, control, or distribution record that is required to be maintained in compliance with this part and is specifically associated with a batch of a drug product shall not be retained for {} 1 year after the expiration date of the batch or, in the case of certain OTC drug products lacking expiration dating because they meet the criteria for exemption under § 211.137, 3 years after distribution of the batch."
C = [
 # family PROP - polarity of a multi-proposition passage (T3c / DX4)
 ("PR1", "PROP", "21 CFR 701.13(d)", None, "A common fraction shall not be reduced to its lowest terms.", "conflict", "negates the affirmative common-fraction duty"),
 ("PR2", "PROP", "21 CFR 701.13(d)", None, "A decimal fraction shall be carried out to more than two places.", "conflict", "affirms what the decimal clause prohibits"),
 ("PR3", "PROP", "21 CFR 113.40(a)(6)", None, "A bottom crate support shall not be used in vertical still retorts.", "conflict", "negates the affirmative crate-support duty"),
 ("PR4", "PROP", "21 CFR 113.40(a)(6)", None, "Baffle plates shall be used in the bottom of still retorts.", "conflict", "affirms the prohibited baffle plates"),
 ("PR5", "PROP", "21 CFR 113.40(a)(6)", None, "Baffle plates shall not be used in the bottom of still retorts.", "equivalent", "verbatim negated sentence"),
 ("PR6", "PROP", "21 CFR 701.13(d)", None, "A decimal fraction shall not be carried out to more than two places.", "equivalent", "verbatim negated clause"),
 ("PR7", "PROP", "21 CFR 800.55(c)", None, "An authorized FDA representative may terminate a detention before the expiration of the detention period.", "equivalent", "permission in sentence 4; 'may not exceed' sits in sentences 1 and 3 (cross-sentence STRENGTH)"),
 # family MODREL - modal strength (N12)
 ("MR1", "MODREL", "21 CFR 1.379(a)", "(a) FDA may detain", "FDA must detain an article of food for a reasonable period that may not exceed 20 calendar days after the detention order is issued.", "conflict", "discretion ('may detain') stated as a duty"),
 ("MR2", "MODREL", "21 CFR 1.379(a)", "(a) FDA may detain", "FDA may detain an article of food for a reasonable period that may exceed 20 calendar days after the detention order is issued.", "conflict", "maximum removed"),
 ("MR3", "MODREL", "21 CFR 1.379(b)", None, "The entire detention period must not exceed 30 calendar days.", "equivalent", "'may not exceed' = 'must not exceed' (both prohibitions)"),
 ("MR4", "MODREL", "21 CFR 1.379(b)", None, "The entire detention period may exceed 30 calendar days.", "conflict", "prohibition stated as permission"),
 ("MR5", "MODREL", "21 CFR 1150.1", "The total amount", "The total amount of user fees may exceed the amount specified for that fiscal year in section 919(b) of the Federal Food, Drug, and Cosmetic Act.", "conflict", "cap without a number, reversed"),
 ("MR6", "MODREL", "21 CFR 1.379(a)", "(a) FDA may detain", "FDA may detain an article of food for a reasonable period that may not exceed 20 calendar days after the detention order is issued.", "equivalent", "verbatim"),
 ("MR7", "MODREL", "21 CFR 1.379(a)", "(a) FDA may detain", "FDA may detain an article of food for up to 20 calendar days after the detention order is issued.", "equivalent", "'up to' = 'may not exceed'"),
 # family QSCOPE - which quantity a number belongs to (N9)
 ("QS1", "QSCOPE", "21 CFR 178.3760", None, "Polyethylene glycol (400) monolaurate may be used at a level not to exceed 0.3 percent by weight of twine as a finish on twine to be used for tying meat.", "equivalent", "correct twine limit"),
 ("QS2", "QSCOPE", "21 CFR 178.3760", None, "Polyethylene glycol (400) monolaurate containing not more than 0.1 percent by weight of ethylene and/or diethylene glycol may be used as a finish on twine to be used for tying meat.", "equivalent", "correct glycol limit"),
 ("QS3", "QSCOPE", "21 CFR 178.3760", None, "Polyethylene glycol (400) monolaurate containing more than 0.1 percent by weight of ethylene and/or diethylene glycol may be used as a finish on twine to be used for tying meat.", "conflict", "glycol limit reversed"),
 # family DAYQ - day-count convention (N10)
 ("DQ1", "DAYQ", "21 CFR 112.203(d)(2)", None, "(2) Appeal the order within 15 days of the date of receipt of the order in accordance with the requirements of § 112.206.", "equivalent", "unqualified 'days' vs 'calendar days'"),
 ("DQ2", "DAYQ", "21 CFR 112.203(d)(2)", None, "(2) Appeal the order within 15 calendar days of the date of receipt of the order in accordance with the requirements of § 112.206.", "equivalent", "verbatim"),
 ("DQ3", "DAYQ", "21 CFR 1.379(b)", None, "The entire detention period may not exceed 30 business days.", "not_credited", "calendar -> business days"),
 ("DQ4", "DAYQ", "21 CFR 1.379(b)", None, "The entire detention period may not exceed 30 working days.", "not_credited", "calendar -> working days"),
 # family NNEG / EXN - N15 ('shall not ... more than' with 'exemption' in the evidence)
 ("NN1", "NNEG", "21 CFR 211.180(a)", None, N15C.format("less than"), "equivalent", "'shall not be retained for less than 1 year' = 'at least 1 year'"),
 ("NN2", "NNEG", "21 CFR 211.180(a)", None, "No production, control, or distribution record associated with a batch of a drug product shall be retained for less than 1 year after the expiration date of the batch.", "equivalent", "quantifier negation, equivalent (the check should abstain, not contradict)"),
 ("EX1", "EXN", "21 CFR 1.24(a)(4)", "(4) Individually", "(4) Individually wrapped pieces of penny candy and other confectionery of less than one-half ounce net weight per individual piece shall be subject to the labeling requirements of this part when the container in which such confectionery is shipped is in conformance with the labeling requirements of this part.", "conflict", "'shall be exempt' (predicate) reversed"),
 ("EX2", "EXN", "21 CFR 1.24(a)(4)", "(4) Individually", "(4) Individually wrapped pieces of penny candy and other confectionery of less than one-half ounce net weight per individual piece shall be exempt from the labeling requirements of this part when the container in which such confectionery is shipped is in conformance with the labeling requirements of this part.", "equivalent", "verbatim predicate exemption"),
 ("EX3", "EXN", "21 CFR 211.180(a)", None, N15C.format("at least").replace("shall not be retained for at least", "shall be retained for at least"), "equivalent", "verbatim 211.180(a) (noun 'exemption' on both sides)"),
 # family APPL - applicability (DX2)
 ("AP1", "APPL", "21 CFR 1141.1(b)", None, "The requirements of this part do not apply to manufacturers or distributors of cigarettes that do not manufacture, package, or import cigarettes for sale or distribution within the United States.", "equivalent", "verbatim"),
 ("AP2", "APPL", "21 CFR 1141.1(b)", None, "The requirements of this part do not apply to manufacturers of cigarettes that do not manufacture cigarettes for sale within the United States.", "equivalent", "narrowed, same polarity"),
 ("AP3", "APPL", "21 CFR 1141.1(b)", None, "The requirements of this part apply to manufacturers of cigarettes that manufacture cigarettes for sale within the United States.", "not_contradicted", "the complementary scope: consistent with (b), which says nothing against it"),
]
out = []
for cid, fam, cit, start, claim, expect, why in C:
    ev = sent(cit, start) if start else T[cit]["text"]
    assert ev in T[cit]["text"]
    out.append({"id": cid, "family": fam, "citation": cit, "evidence": ev, "evidence_scope": "sentence" if start else "paragraph",
                "evidence_provenance": "REAL verbatim eCFR", "snapshot_date": T[cit]["snapshot_date"], "content_sha256": T[cit]["content_sha256"],
                "claim": claim, "claim_provenance": "CONSTRUCTED (not regulatory text)" if claim not in T[cit]["text"] else "VERBATIM clause/sentence of the evidence",
                "expect": expect, "why": why})
json.dump(out, open(W + "/m_cases.json", "w"), indent=1, ensure_ascii=False)
print(len(out), "cases;", sum(o["claim_provenance"].startswith("VERBATIM") for o in out), "verbatim claims")
