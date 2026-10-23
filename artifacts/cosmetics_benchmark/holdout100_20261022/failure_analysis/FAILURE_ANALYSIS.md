# Holdout 100Q failure analysis (Qwen3-4B-Instruct-2507, 37 PASS)

## Summary

- **63 questions did not pass: 8 partially pass, 26 partially fail and 29 fail.** For 27 of them the prompt never had the right evidence: the picker chose wrongly 18 times, packing or companions left gaps 5 times, and retrieval missed 4 times. The other 36 failed after the evidence stage: the model misread or left things out (20), the validator or repair step blocked or damaged the answer (11), citations were wrong (3), or the composer erred (2). In 34 of those 36 the text that answers the question was in the prompt.
- **When the key section is in the prompt, the 4B model passes about 46% of the time (37 of 80). When it is missing, it never passes (0 of 20).** I use this as the prior for any fix that only gets evidence into the prompt.
- **The cheapest and safest gains come from changes that can be measured offline on recorded drafts, with no regeneration.** These are validator false positives, the composer and post-processing, a correction pass limited to flagged sentences, and checks that drop a wrong sentence. Together they are worth about 8 PASS on paper.
- **If every fix shipped and every diagnosis were right, the gain would be +16.7.** I would plan for **+8 on this set (about 45/100) and +5 to +7 on a fresh, similar set.** The reasons for the discount are in section 2.
- **Withholding helped users overall.** Of the 19 withheld drafts, 10 were misleading and 3 would have passed. But 5 of those 10 were blocked by findings that are themselves false, or that the proposed validator fixes would relax. That is why the regression gates name those rows one by one.

Method note: the stage and fix counts come from single-pass per-question diagnoses (33 high, 29 medium and 1 low confidence). They agree with the measured 18 wrong picks.

---

## 1. Count tables

### Primary root-cause stage

| Primary stage | n | Answer-bearing evidence in prompt (yes / partial / no) |
|---|---|---|
| PICK_WRONG_SECTION | 18 | 0 / 3 / 15 |
| MODEL_MISREAD | 14 | 14 / 0 / 0 |
| VALIDATOR_BLOCKED_GOOD_DRAFT | 9 | 8 / 1 / 0 |
| MODEL_INCOMPLETE | 6 | 6 / 0 / 0 |
| EVIDENCE_INCOMPLETE | 5 | 0 / 5 / 0 |
| RETRIEVAL_MISSING | 4 | 0 / 1 / 3 |
| CITATION_ERROR | 3 | 2 / 1 / 0 |
| VALIDATOR_BLOCKED_BAD_DRAFT | 2 | 2 / 0 / 0 |
| COMPOSER_ERROR | 2 | 2 / 0 / 0 |
| **Total** | **63** | **34 / 11 / 18** |

The measured "key section in prompt" split is 42 / 1 / 20. It is higher than the diagnosis count of 34 because 8 rows had the section in the prompt but not the paragraph that answers the question. For example, 70.3-Q2 had only paragraph (l), and 701.3-Q3 lacked the (g) siblings.

### Fix class (from the diagnoses)

| Fix class | n |
|---|---|
| validator | 23 |
| picker | 16 |
| evidence_packing | 8 |
| composer | 4 |
| prompt_or_answer_format | 4 |
| companions_or_second_provision | 4 |
| candidates | 4 |

### Category by primary stage (where the failures sit)

| Category (PASS) | Non-PASS | Pick | Misread | Incomplete | Validator good/bad | Evidence | Retrieval | Citation | Composer |
|---|---|---|---|---|---|---|---|---|---|
| Colour listings (23/35) | 12 | 2 | 2 | 2 | 4 / 0 | 1 | 0 | 0 | 1 |
| Procedure (7/16) | 9 | 4 | 2 | 1 | 0 / 1 | 0 | 0 | 1 | 0 |
| Statute (4/19) | 15 | 7 | 1 | 1 | 1 / 0 | 0 | 3 | 2 | 0 |
| Labeling 700–740 (3/27) | 24 | 5 | 7 | 2 | 3 / 1 | 4 | 1 | 0 | 1 |
| Specs/definitions 82.3, 82.5, 82.51 (0/3)* | 3 | 0 | 2 | 0 | 1 / 0 | 0 | 0 | 0 | 0 |

*The four named categories add up to 97, so I placed the remaining three rows here by inference.

What the table says:
- **Colour listings:** a third of the failures are validator false positives. These are cheap to fix.
- **Statute:** most failures are picking or candidate problems.
- **Labeling:** the largest group is model reading with complete evidence. Pipeline work will buy little PASS there.

---

## 2. Fixes ranked by expected PASS gain

**How I estimated.** Each of the 63 rows is assigned to exactly one fix: 59 rows to fixes, and 4 rows to section 3 with no gain counted. The probability next to each row is my estimate that it becomes PASS given that fix. "Also needs" notes a dependency, but the row is still counted once.

For fixes that only get evidence into the prompt, I capped the probability near the 0.46 prior. Statute and labeling rows get less than that, colour listings slightly more.

**Regression gates.** Every fix below names the gates it must pass before shipping.
- **G1 Validator replay (offline, exact).** Re-run the recorded drafts from the 100Q holdout, the 300-row validator set, dev34 and dev_label. To pass:
  - The 37 holdout PASS rows deliver byte-identical text.
  - These rows stay withheld: 74.2101, 70.19, 70.3-Q2, 70.45, 71.22, 740.2, FDCA601-Q1, FDCA601-Q2, UC-002, UC-014, plus SD-007.
  - Every row whose delivered text changes is blind double-scored, and none becomes misleading.
  - Unit tests: 792 pass, with the same 6 known failures.
- **G2 Check calibration.** Any new error-level check fires 0 times on sentences of PASS answers in the holdout and dev sets. Warnings are allowed but must be listed. This is the same standard as the validator audit, where 31 of 33 fires were on FAIL and none on PASS.
- **G3 Evidence replay.** On the 352-question retrieval baseline, the byte-level compare differs only on a trigger list declared in advance. On the 277-question cosmetics replay, no keyed section is lost.
- **G4 Picker replay.** Run the picker on the 100Q and 352 sets. None of the 38 currently right picks may change, and every changed pick is listed and checked by hand.
- **G5 Regeneration A/B.** Regenerate only the rows whose prompt changed (in the 100Q, dev34 and dev_label sets) on Qwen3-4B-Instruct-2507, both arms with the same configuration, blind double-scored. Accept only if PASS gained is at least twice PASS lost, no PASS row becomes misleading, and no must-refuse row is delivered.

### Ranking

| # | Fix | Rows | Expected PASS | How measured | Regression risk |
|---|---|---|---|---|---|
| 1 | A. Validator precision on correct drafts | 10 | **4.65** | offline (G1) | medium, with named traps |
| 2 | B. Picker hardening (name guard, untruncated reply) | 9 | **2.10** | regenerate | medium |
| 3 | G. Composer and post-processing | 4 | **1.70** | 1.15 offline, 0.55 regenerate | low |
| 4 | H. Content-aware picker | 8 | **1.55** | regenerate | **high** |
| 5 | E. Checks that drop a wrong sentence | 6 | **1.40** | offline | medium |
| 6 | F2. Packing that keeps paragraph structure | 6 | **1.40** | regenerate | medium-high |
| 7 | C. Pointer and delegation companions | 3 | **1.05** | regenerate | medium |
| 8 | F1. Evidence-text bugs | 3 | **0.90** | regenerate | low-medium |
| 9 | D. Correction pass limited to flagged sentences | 4 | **0.85** | offline | medium |
| 10 | J. Answer-plan prompt fixes | 3 | **0.80** | regenerate | medium |
| 11 | I. Statute topic-alias candidates | 3 | **0.25** | regenerate | low; not worth it now |
| | **Sum** | **59** | **16.65** | offline 8.05 / regenerate 8.60 | |

**Why I plan for about +8 rather than +16.7.**
- **Diagnoses may be wrong.** 30 of the 63 are medium or low confidence, and 9 picker diagnoses could not see the candidate list.
- **Regenerated changes have netted about zero here before.** The binding_first, heading_relevance and trigram threshold changes, context packing and the general-format switch all came out at +4 or less once losses were counted.
- **The rules were designed on these exact rows.** I apply about 65% to the offline fixes (about +5.2) and about 35% net to the regenerated ones (about +3.0).
- **The holdout is now a dev set.** Once these fixes are designed against these 63 rows, an honest gain estimate needs a fresh, unseen set.

### Fix details

**1. A. Validator precision on correct drafts (expected 4.65, offline)**
- **Rows:** 82.1328 (.8), 73.2120 (.65), 71.30 (.6), 82.1602 (.45), 82.1330 (.4), 700.27-Q3 (.4), 70.10 (.4), 700.3-Q2 (.35), FDCA610-Q1 (.3), 710.9 (.3, only after B ships).
- **Rules:**
  - **A1. Citation numbers in the figure check.** Reduce '§ 74.1328 (a)(1)', '§74.1328(a)(1)' and '74.1328' to the same citation before comparing. Numbers in Citation and Heading labels count as supplied text.
  - **A2. Scoped absence statements.** Check "this/these provision(s) impose/set/specify no X" by confirming the cited source has no limiting term for X, instead of using word overlap. Unscoped denials ("there is no X", "no regulation anywhere") stay errors; unscoped denials caused the earlier false-denial regression.
  - **A3. Drop filler sentences.** Remove whole sentences that carry no citation, fail support, are not the first sentence, or repeat a supported sentence. Then re-validate and re-check completeness. Never remove a clause inside a sentence, because that is the invented_conditions_removed false-PASS route.
  - **A4. Re-point citations.** Fix the bracket number when the sentence explicitly names a provision held by exactly one other supplied source (71.30), when a source number was mistaken for a paragraph label (700.27-Q3), or when the sentence's distinctive words come from another source (FDCA610-Q1).
  - **A5.** Count headings as supplied text, match word forms (exempt, exemption), and take 'exemption' out of the list of condition words (710.9).
  - **A6.** Derive "every item must be covered" obligations only from listing wording in the user's question, never from citations that section promotion inserted (700.3-Q2).
- **Traps:** each item below is a protection that a naive version of A would remove. Each must be designed out and checked in G1.
  1. Currency normalisation ($75 = $75.00) removes the only error on **70.19**, a misleading draft. Leave currency out of A1.
  2. Letting provision_citation_mismatch accept a section named as a cross-reference inside the cited source would release **FDCA601-Q1** (misleading). Defer until B ships.
  3. A2 can release **FDCA601-Q2** and **UC-002**. Both are wrong-pick drafts made only of scope negatives ("700.27 does not cover rodent filth"). Guard: A2 does not apply when every sentence that answers the question is a scope negative. If the guard cannot hold both rows in G1, ship A2 after B.
  4. A5 removes the only errors on **UC-014** (misleading: it applies beauty-shop, physician and research exemptions to a third-party logistics warehouse). A5 waits for B.
- **Rows that change without a PASS gain:** 73.2329, 82.705, UC-008 and possibly 701.13-Q2 move from withheld or fallback to the delivered draft. They must be scored, not assumed safe.
- **Gates:** G1 and G2.

**2. B. Picker hardening (expected 2.10, regenerate)**
- **Rows:** 74.2101 (.5), FDCA601-Q1 (.3), FDCA601-Q2 (.25), UC-002 (.25), 82.706 (.25, also needs C to add 82.5), UC-018 (.2), 71.22 (.15), UC-012 (.1), UC-014 (.1).
- **Rules:**
  - **B1. Exact-name pre-pick.** If a colour or substance name in the question equals a candidate's heading, pick that section deterministically.
  - **B2. Name-mismatch veto.** Reject a pick whose heading names a different substance, or a substance that does not appear in the question.
  - **B3. Picker reply truncation.** This is the strongest single bug in the set. Eight replies stop at 22–26 characters, which suggests a cap of about 16 tokens: FDCA601-Q1/Q2, UC-002/012/014/018, 720.2 and 70.45. Raise the cap or switch to choosing an index from a list. Keep the first pick byte-identical, and add a parsed second (statute) ID only as a companion within budget.
  - **B4 (optional, separate G5).** Stop appending picked IDs to the QUESTION line. That habit locks the model onto wrong picks (73.2087, FDCA601-Q1/Q2, UC-002).
- **Do first:** dump the candidate lists for the 9 rows whose diagnoses cannot tell a pick error from a candidate miss: 74.2101, 82.706, 70.45, 71.22, 81.10, 701.13-Q2, 701.20, 720.2, FDCA612-Q2.
- **Caution:** we do not know which statute section the truncated replies were naming. UC-012, UC-014 and UC-018 need two or three sections each, so they are capped at partial pass.
- **Risks:** budget displacement from the companion, and the veto wrongly rejecting a right pick (synonyms, 'Ext. D&C').
- **Gates:** G4, then G3, then G5 on the changed rows.

**3. G. Composer and post-processing (expected 1.70)**
- **Rows:** 740.17 (.65), 74.2260 (.5), 82.2051 (.3), 82.51 (.25).
- **Rules:**
  - Duplicate removal must treat a quotation, or any span matching source text, as one unit. Check afterwards that each quote is still intact, and roll back if not. 740.17 delivered a cut-down mandatory caution.
  - The listing composer writes one direct line per facet the question asks about (use, limit, certification, labeling).
  - When a quoted paragraph names a different substance than its section heading, add "as printed" (the 74.2260(d) "Orange No. 11" misprint).
  - Exhaustive item lists are rendered verbatim from the source, keeping (i)/(ii) branches and full series; the model writes only the lead (82.2051, 82.51).
- **Risk:** low for the first three rules. Verbatim rendering changes every exhaustive-shape answer.
- **Gates:**
  - G1 on all composed_from_listing rows and every row the duplicate removal touches; the byte diff may change only trigger rows.
  - G5 on the listing-shape rows for verbatim rendering. The 82.5/82.51 shapes and verdicts must hold.

**4. H. Content-aware picker (expected 1.55, high risk)**
- **Rows:** 720.2 (.25), 720.4-Q2 (.25), 710.8 (.2), 701.13-Q2 (.2), 70.3-Q2 (.2), 70.45 (.15, the only low-confidence diagnosis), 701.20 (.15), FDCA612-Q2 (.15).
- **Rules:**
  - Build each candidate's preview from its best-matching paragraph, not just its heading.
  - Add intent cues: definitional wording points to 70.3; "by when" points to time sections; "can we say" points to misbranding sections.
  - Rank statute sections that only grant rulemaking authority below CFR sections.
  - When the draft declines, retry with the next-ranked section.
- **Risk:** this changes the picker's input for every question that names no section, so all 38 right picks are exposed.
- **Gates:** the candidate dump first, then G4 with zero tolerance, then G5.

**5. E. Checks that drop a wrong sentence (expected 1.40, offline; the main value is safety)**
- **Rows:** 80.22 (.5), 700.25-Q3 (.3), 73.2087 (.2), 720.1 (.2), 700.25-Q1 (.1), 701.1 (.1).
- **Checks:**
  - A condition the cited source lacks has been added ("applies only if...").
  - A date or amount is attached to the wrong requirement.
  - An exception has been moved from one paragraph to another.
  - Obligation strength is raised ('requested/should/may' becomes 'must/required/prohibited').
  - A condition is asserted as a fact about the user's product.
- **Reach beyond PASS:** the same checks would also reduce misstatements in 82.51, 710.3, 720.4-Q2 and 720.6. None of these checks may drop the first, verdict sentence; if one would, withhold instead.
- **Gates:** G2 (zero error-level fires on PASS sentences), then G1.

**6. F2. Packing that keeps paragraph structure (expected 1.40)**
- **Rows:** 701.3-Q3 (.35, list closure), 80.34 (.25, trailing main clause), 73.2329 (.25, a "Context:" line for children of a colon-ended lead-in), UC-024 (.25, pack the matching subtree first and strip incorporation-by-reference boilerplate), FDCA608 (.15, split statute subsections into paragraphs), 701.9-Q2 (.15, scope tags).
- **Risk:** the grouped-subparagraph packing of 20 Oct gained 0 and lost 3 (X-001, G-010), and every budget lever has been zero-sum.
- **Gates:** ship each sub-rule separately; G3 with a trigger list declared in advance; then G5.

**7. C. Pointer and delegation companions (expected 1.05)**
- **Rows:** 82.705 (.4, add 82.5), 700.23 (.4, add 2.125), 81.10 (.25, a Part 81 status companion). C also completes 82.706, which is counted under B.
- **Rule:** fire only when the promoted text is a short pointer clause ("conform to § X", "as provided in § X") and the prompt is well under budget. General cross-reference expansion was switched off earlier because it was zero-sum.
- **Gates:** G3 (only trigger rows differ, no keyed section lost), then G5.

**8. F1. Evidence-text bugs (expected 0.90)**
- **Rows:** 740.18 (.4), 73.2110 (.25), 82.3 (.25; also needs A2).
- **Rules:**
  - Ingest the eCFR section notes (stays, effective dates) and show them as a "Status:" line.
  - The sub-requirement splitter must not cut at decimals or '§ N.N' references, and must drop empty items. This bug touches every prompt that prints the line.
  - The paragraph parser must treat a reserved range '(a)-(f) [Reserved]' as a sibling paragraph, not a parent.
- **Gates:**
  - Reserved-range relabelling: G3 label diff confined to sections with reserved ranges.
  - Splitter: G5 on the full 100Q.

**9. D. Correction pass limited to flagged sentences (expected 0.85, offline)**
- **Rows:** FDCA610-Q2 (.3), FDCA611 (.25), 701.11 (.15), 720.6 (.15).
- **Rules:** repair may change only sentences named by an error finding, and must re-validate the whole result. Reject a repair that re-introduces a removed claim (720.6) or deletes the only sentence answering part of the question (82.1602, FDCA610-Q2).
- **Risk:** the LLM rewrite sometimes fixes errors nobody flagged; this rule keeps them.
- **Gate:** G1 on every row that went through repair.

**10. J. Answer-plan prompt fixes (expected 0.80)**
- **Rows:** 740.10-Q2 (.3, saving clauses into "limits to keep" and _focus_gap), 82.5 (.3, parenthetical "(except Pb and As)" listed as an exclusion, not a condition), 701.2 (.2, an applicability step for each item in a list of alternatives).
- **Caution:** prompt variants have failed repeatedly (rule-9, the general-format switch).
- **Gates:** the plan text must stay byte-identical on rows without the pattern; G5 on the rest.

**11. I. Statute topic aliases (expected 0.25)**
- **Rows:** UC-005 (.1), UC-010 (.1), UC-004 (.05).
- **Why it is low:** these keys need the "606 GMP rule not issued" fact, which is not in the corpus, so they are capped at partial pass.

**Recommended order:**
1. A (without A5 and without the cross-reference rule)
2. The offline part of G (duplicate removal and facet lines)
3. D
4. E
5. B
6. A5 and the cross-reference rule
7. F1
8. C
9. F2
10. J
11. H, after the candidate dump
12. Skip I.

Offline fixes come first because they replay exactly and roll back cheaply. B comes before A5 and the cross-reference rule because it removes the wrong-pick drafts that those relaxations would otherwise release.

---

## 3. Not worth fixing, or not fixable now

| Rows | Why | What to do |
|---|---|---|
| 70.19 | The evidence was complete, but the model read "less $1,600" as a $1,600 refund and miscited (f) for (g). It is withheld, which is the right outcome even though the reason (a false '75' figure) is wrong. | Keep it withheld. Exclude currency normalisation from A1. Passing it needs better model reading. |
| 740.2 | The draft looped and was cut off. The P2 experiment rejected salvaging loop prefixes: 15 wrong answers and SD-007 delivered. | Nothing until a stop on repeated output at generation time is tested. |
| 710.3 | The key needs "the voluntary registration program stopped accepting submissions in March 2023", which is not in the eCFR text. | This is the owner's decision: a curated, dated and sourced status-note layer is a content decision, not an engineering one. |
| UC-008 | A releases a correct partial-pass draft, which helps users. A full pass needs 601(c) and the 606 rule status, which are not in the corpus. | No PASS gain counted. |
| UC-004, UC-005, UC-010, UC-012, UC-014, UC-018 | The keys need the 606 status fact and/or two or three statute sections at once (606+610+601(c), 604+607, 605(e)+609). The design promotes one section. | Counted at 0.2 or less each above. Revisit only with status notes and promotion of several sections. |
| 701.1, 701.2, 701.9-Q2, 701.11 (and 70.19) | Evidence was complete; the misreads are semantic: contradicting the stated facts, choosing the wrong branch, or not linking "jar bottom" to "panel displayed under customary conditions". Prompt variants and thinking mode have already failed, and thinking was worse on labeling. Labeling is 3/27, and 9 of its 24 failures are model reading. | E makes these less wrong. A full pass needs a stronger model. |
| Key or rubric issues | 73.2110: the key's (d)(1) is arguably supplier-side labeling. 81.10: the conclusions are right and the rubric weights a historical termination heavily. FDCA610-Q1: the skeptic scorer's reason is wrong, since the exclusion text is in 610(a), not 610(b). 74.2260: the source itself prints "Orange No. 11". UC-004: the key states a status fact found in no text. | Flag to the owner; do not edit the benchmark. |
| Measurement noise | 82.706 is counted as "pick right" although 82.50 is the secondary provision. UC-008 is counted as "key not in prompt" although 606 is keyed. | The 38 right / 18 wrong pick split and the 42 / 1 / 20 key-in-prompt split each carry about ±2 rows of noise. |

---

## 4. Did withholding protect users?

**Yes, on balance.** Here is how the 19 withheld drafts score if they had been shown:

| If shown | n | Rows |
|---|---|---|
| Would pass (citations right, substance 2, completeness 2, not misleading) | 3 | 73.2120, 82.1328, 71.30 |
| Near pass, only a citation defect | 1 | 700.27-Q3 |
| Right direction but incomplete or on the wrong basis; not misleading | 5 | 70.10, 701.13-Q2, UC-008, UC-010, 82.3 |
| **Misleading** (5 of them also fabricate) | **10** | 74.2101†, 70.45†, 740.2†, FDCA601-Q1†, UC-002†, 70.19, 70.3-Q2, 71.22, FDCA601-Q2, UC-014 |

† also fabricates.

- **Withholding blocked 10 misleading answers at a cost of 3–4 passes.** 53% of the withheld drafts were misleading, against 65% (20 of 31) on the dev questions earlier today. The conclusion is the same: do not loosen thresholds across the board.
- **The validator mainly backstops the picker.** 8 of the 10 misleading drafts come from a wrong pick. The validator withheld 9 of the 18 wrong-pick drafts, and 8 of those were misleading. B therefore reduces how much users depend on withholding.
- **Half of the protection is accidental.**
  - 70.19 was blocked by a false '75' figure.
  - FDCA601-Q1 was blocked by a citation mismatch that is itself probably false.
  - FDCA601-Q2 and UC-002 were blocked by low overlap on scope negatives, the very mechanism A2 relaxes.
  - UC-014 was blocked by a shaky 'exempt' invented-condition finding that A5 removes.
  - In 740.2 the errors landed on the correct sentences.

  This is why G1 lists these rows by name and why A has a fixed order.
- **There is a hidden cost beyond the 19.** Four more correct drafts were replaced by the verbatim fallback (82.1330, 82.705, 700.3-Q2, 710.9). Six more were damaged by the correction pass: 82.1602, 701.11, FDCA611, FDCA610-Q2 and 720.6 were damaged, and UC-018 lost its scope caveat.
- **The protection covers only one kind of error.** About 20 of the 44 delivered non-PASS answers contain a substantive misstatement, judged by the diagnoses rather than blind-scored. Examples:
  - a condition turned into a premise (73.2087, 73.2329);
  - 'should', 'requested' or 'may' turned into 'must' or 'prohibited' (720.1, 701.1, 710.3, 82.51);
  - an exception moved to another paragraph (700.25-Q1);
  - a wrong date (700.25-Q3);
  - a shortened mandatory caution (740.17);
  - an invented condition (80.22, 82.5);
  - "no other action required" (720.6).

  These sentences share many words with the source, so the overlap-based validator passes them. E is aimed at about 9 of them, which is why I would ship it even though its PASS gain is small.