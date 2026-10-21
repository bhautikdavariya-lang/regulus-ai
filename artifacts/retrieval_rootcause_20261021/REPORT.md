# Regulus: root cause of regulatory retrieval failures (2026-10-21)

**Scope:** retrieval only: what is searched, matched, ranked, capped, selected and passed on. No model was run, and no
answer was used as evidence.

**State traced:**
- **Code:** production code byte-identical to the start of the task. The changes to files tracked at 6f94938 hash
  3a246702… throughout. The git user's commits made during the task (HEAD 6f94938 → fd82d78, 13:48–13:52) changed no
  code content.
- **Switches:** no `REGULUS_*` variable set, so `REGULUS_ECFR_LITERAL_OR` is off.
- **Semantic loader:** refused, and 0 attempts were made.
- **Database:** session read-only, and the corpus fingerprint and write counters were identical before and after every
  run.

**Question set:** the 100 cosmetics questions with verified answer keys (step6 `selection.json`).
- 88 questions name no provision. These general questions are where retrieval fails.
- 12 name a provision, and none names a docket.
- Required evidence is the paragraphs the key cites.

## A. The pipeline that actually runs

```
question ─ plan_query ─┬─ names a provision (12) → exact_cfr + parent row → EXACT/STRUCTURAL → required in selection
                       │      the named provision reaches the context in 12/12
                       └─ general question (88): lexical.py run_plan
   3a  definition_term → definition_ecfr                 "what does X mean" only; skips step 3 when it finds one
   3   full_text_ecfr(question), full_text_guidance(question)    websearch_to_tsquery: every word ANDed, but a
                                                        standalone "or" becomes OR · limit 16 each · → SUPPORTING
   5   trigram_ecfr                                     short/identifier query, or eCFR AND rows < top_k
   5b  section_coverage_ecfr(content_terms(question))   GATE: eCFR AND rows < 3
         idf-weighted lexeme coverage per section → top 4 sections, ≤ 2 rows per section, ≤ 4 rows → DISCOVERY
   5   OR fallback over the 8 longest words             eCFR only if 5b found nothing; guidance always → DISCOVERY
   5c  defined_terms_ecfr                               definition questions only
   6   merge → classify → order_evidence                EXACT, STRUCTURAL, SUPPORTING by score, DISCOVERY by score
       5b rows moved behind ALL other evidence          (lexical.py:605)
       heading promotion → SUPPORTING, first            heading in the question + another row from the same part
   selection.py select_evidence (general question)
       eCFR reserve 1,200 chars: eCFR rows only, STRUCTURAL → SUPPORTING → DISCOVERY, registry order
       soft budget 3,600 chars, max 8 sources: tier by tier, registry order → guidance DISCOVERY precedes 5b rows
```

**Code references:**
- [lexical.py:411](../../src/regulus/retrieval/lexical.py#L411) `run_plan`, with steps 3a/3/5/5b/5c/6 at
  :505/:518/:557/:564/:588/:596.
- RC1 gate at :566, and the rows moved last at :605.
- `SECTION_COVERAGE_ROWS_PER_SECTION = 2` at [lexical.py:147](../../src/regulus/retrieval/lexical.py#L147).
  `coverage_slots = top_k // 2` = 4 serves as both the section limit and the row limit (:565, :1007).
- RC1 SQL at [sql.py:153](../../src/regulus/retrieval/sql.py#L153).
- `content_terms` at [query.py:141](../../src/regulus/retrieval/query.py#L141) drops tokens under 3 characters and any
  token containing a digit.
- Selection: [selection.py:399–452](../../src/regulus/rag/selection.py#L399), with `_optional_order` at :483. Policy
  values are in [context.py:56–81](../../src/regulus/rag/context.py#L56).
- **Not running:**
  - the semantic fallback: `general_questions=False` ([fallback.py:75](../../src/regulus/retrieval/fallback.py#L75));
  - cross-references (off);
  - the literal-OR switch (off).

**Trace fidelity** ([tools/trace_retrieval.py](tools/trace_retrieval.py), [traces_all/](traces_all/)):
- Every leg was wrapped to record its input, the tsquery PostgreSQL built from it, and its rows.
- The selection replay equals the real selection in 87 of 88 general questions. The exception, COS-74.2304-Q1, is an
  unmodelled duplicate-consolidation step that involves no required paragraph.
- The section-coverage SQL, recomputed with every section and row exposed, reproduces the leg's returned rows
  wherever it ran ({{FID}}).

## B. Root causes

Base: the 68 general questions whose key cites eCFR text, with 174 required paragraphs. One key, "(b)(2)(i)-(iv)", was
mis-parsed into a non-existent 740.11(i); it is excluded.
- **17 of 174** required paragraphs reach the context today.
- All required paragraphs arrive in 5 questions; none arrive in 54.

Each missing paragraph is assigned to the first stage where it was lost ([prevalence.json](prevalence.json),
[rank_check.json](rank_check.json), [causal/causal_checks.json](causal/causal_checks.json)).

| # | Lost at | Mechanism (demonstrated) | Prevalence | Causal chain of a traced example |
|---|---|---|---|---|
| **A** | Coverage gate (lexical.py:566) | A standalone "or" turns the AND query into an OR of two conjunctions. The short tail branch alone matches ≥ 3 off-topic rows, so the eCFR AND "succeeds", the coverage leg never runs, and the off-topic rows become SUPPORTING. | **10 questions, 39 paragraphs.** All 39 sit in a section the coverage weighting ranks 1–4. | **COS-73.2725-Q1**, "…what restrictions, certification **or** labeling apply?"<br>• tsquery `…'restrict' & 'certif' \| 'label' & 'appli'`.<br>• Branch 1 matches 0 eCFR rows; `'label' & 'appli'` matches 415 rows in 196 sections.<br>• Returned: 16 rows of 1271.90 (HCT/P donors) and 16 HCT/P and food guidance chunks.<br>• 16 ≥ 3, so coverage is skipped.<br>• **Final context: 8 rows of 1271.90**, 0 of 73.2725(a)–(e). |
| **B** | Coverage row caps (sql.py:153: ≤ 2 rows per section, ≤ 4 rows) | The right section ranks in the top 4, but the required paragraph is not among the rows taken. Some required paragraphs share no word with the question and can never be taken. | **17 questions, 23 paragraphs.** 3 match no question lexeme (700.15(b), (c); 70.3(v) in COS-82.1206-Q1). Under A, the caps also hold back 27 of the 39 A paragraphs. | **COS-700.25-Q2:** 700.25 is section rank 1. (d), "Requests for exemptions", is its 6th row, so the 2-row cap cuts it.<br>**COS-700.15-Q1:** rank 1. (b) "These halogenated salicylanilides … deemed to be adulterated" and (c) match none of the question's 8 lexemes. |
| **C** | Section ranking (sql.py:153, top 4 sections) | No leg reaches the required section. | **40 questions, 91 paragraphs.** Best rank of a required section: {{CBEST}}. | **COS-74.2317-Q1** (D&C Red No. 17):<br>• `content_terms` drops "17", "D&C" and "No.".<br>• 74.2317 ranks **103rd** of 6,294 matching sections; with "17 D&C" restored it ranks 10th.<br>• **Final context:** 2 animal-food guidance chunks and 170.3(o)(14), (n)(12). |
| **D** | Selection order (selection.py:424, `_optional_order`) | Coverage rows are DISCOVERY and are moved behind everything. Guidance OR-fallback chunks (DISCOVERY, ~1,500 chars each) therefore spend the 3,600-char budget first, and eCFR rows enter mainly through the 1,200-char reserve. | **4 paragraphs, 4 questions**, lost here directly. Across the 88 general questions:<br>• 172 of 312 coverage rows were dropped at the soft budget, while 152 guidance OR-fallback passages were selected;<br>• guidance is 143,127 of 201,638 final-context characters (71%);<br>• 77 of 88 questions lose eCFR rows while guidance is selected. | **COS-70.55-Q1:** coverage returns 71.6(b), 71.6(c)(1), **70.55** and 511.1(c)(ii)(2)(i).<br>• Reserve: 70.55 does not fit (818 + 790 > 1,200).<br>• Soft budget: two guidance chunks (1,200 + 702 chars) go first; 70.55 is dropped at 3,600.<br>• **Same registry with eCFR rows first:** 70.55 is selected. The call reproduces the actual selection on the unchanged registry. |

**Ruled out:**
- semantic fallback (never runs for these questions);
- index drift: `search_vector` equals its generated definition in every row of all 80 cited sections;
- duplicate live paths (0);
- removed rows (0);
- the top-k cut (selection walks the registry, not top-k);
- loss between a leg and the registry (none).

**Named-provision questions:**
- The named provision arrives in 12 of 12.
- In 5 of them, the key also cites a companion provision the question does not name: 700.3, 82.1050 and 70.3(v).
  No running leg looks for it.

**The mechanisms are serial, measured** ([alternatives.json](alternatives.json), harness only, production untouched):

| Condition (general questions; 174 required paragraphs) | Required paragraphs in context | Questions with ≥ 1 | Lost |
|---|---|---|---|
| Current | 17 | 14 | – |
| A: the "or" operator word removed from both AND-leg inputs | 21 (+4) | 18 | 0 |
| D: within each tier, eCFR rows ahead of guidance rows at selection | 20 (+3) | 17 | 0 |
| A + D | 32 (+15) | 25 | 0 |

- On its own, A turns the 10 gate questions' required paragraphs from 0 returned into 12 returned, in 8 of the 10
  questions. D's mechanism then drops 8 of those 12.
- Example, COS-73.2725-Q1 under A:
  - 73.2725 ranks 1st, and the leg returns its (c) and (a).
  - Heading promotion lifts 73.50 "Ultramarine blue" (a Part 73 food listing), which takes the reserve.
  - 73.2725(c) and (a) are then dropped behind 8 guidance chunks.
  - Under A + D, both arrive.
- The guidance leg matters ([alternative_scope.json](alternative_scope.json)): removing the operator from the eCFR leg
  only gives 4 paragraphs with or without D. The guidance AND query's off-topic SUPPORTING chunks otherwise still come
  before every eCFR DISCOVERY row.

## C. Source integrity (read-only; [integrity.json](integrity.json))
- All 80 cited sections: `search_vector` is consistent, with no duplicate live paths and no removed rows.
- **Announced text that is not stored.** Eleven rows end in a lead-in such as "shall bear the following warning:", and
  the next stored row is a sibling paragraph.
  - The rows are 740.11(a)(1), (b)(1); 740.12(b); 73.2250(b); 74.2602a(b); 71.1(c); 73.2180(a)(2); 701.13(n);
    701.3(c)(2)(i)(a); 81.30(d), (e).
  - **Confirmed by absence:**
    - the 740.11 aerosol warning ("…Contents under pressure…") is in 369.21 and 501.17 but in no 740.11 row;
    - the 740.12(b) statement ("…For external use only…") is in no 740.12 row.
- **Probably the same omission, not verifiable here:** 73.2725(b) and 73.2180(b) say "shall conform to the following
  specifications" but store none. No eCFR source file is available locally to check.
- **Effect:** 6 questions need one of these rows: COS-71.1-Q2, 73.2180-Q1, 73.2250-Q1, 740.11-Q1, 740.11-Q2 and
  740.12-Q1. Perfect retrieval would still deliver an incomplete provision to them.
- This is an ingestion defect, and repairing it means re-ingestion. It is outside this task.

## D. Highest-priority correction: make the general question's AND query mean AND, in both AND legs

**Change:** in `run_plan` step 3, for a question that names no provision and no docket, give `full_text_ecfr` **and**
`full_text_guidance` the question with its standalone "or" operator words removed. Place the change behind a switch,
off by default.
- Today `websearch_to_tsquery` reads those words as OR.
- `query.literal_or` already implements the removal: "and/or", "either-or" and every other token stay unchanged.
- The existing `REGULUS_ECFR_LITERAL_OR` path covers the eCFR leg only, and that was measured as insufficient.

**Why this one:**
- **It is the most significant cause with a demonstrated fix.** It is the largest single stage where required text is
  lost before ranking can act: 39 paragraphs in 10 questions, every one of them in a section the coverage leg ranks 1–4
  once the gate opens.
- C is larger (91 paragraphs), but no single small correction for it is demonstrated (section F).
- **Measured, harness only:**
  - required paragraphs returned for the 10 gate questions go from 0 to 12;
  - final context gains +4 paragraphs and +4 questions, with **0 lost**.
- **Smallest blast radius:**
  - only questions with a standalone "or" change (12 of 88 general questions here);
  - the other 76 general and all 12 named-provision questions have identical final context, checked citation by
    citation and length by length;
  - no guidance is removed.
- **D comes after, not first.**
  - D alone gains 3. It changes the context of 77 of 88 questions and removes 92 guidance passages, including FDA's
    cosmetic "Lead in Cosmetic Lip Products" guidance in 3 questions, which the CFR-only keys cannot judge.
  - D alone recovers none of the 10 gate questions.

**What it will not do:**
- 8 of the 12 recovered paragraphs are still dropped at selection (D), and 27 of the 39 stay behind the coverage row
  caps (B).
- The measured A + D, +15 paragraphs and 0 lost, is the evidence for the next decision; it is not part of this
  correction.
- The 10 gate questions share one benchmark template ("…restrictions, certification or labeling apply?"). How often a
  standalone "or" occurs in real questions is unmeasured.

## E. Test plan (retrieval only, no model, read-only database)

**Targets**, the 10 gate questions: COS-71.27-Q1, 73.2085, 73.2095, 73.2250, 73.2298, 73.2575, 73.2645, 73.2646,
73.2647 and 73.2725 (all -Q1). Measured with the trace harness:
- neither AND leg's tsquery contains `|`;
- the coverage leg runs in 10 of 10;
- a required paragraph is returned by a leg in ≥ 8 of 10;
- the final context gains ≥ 4 required paragraphs: 73.2250(e), 73.2575(b), 73.2646(b), 73.2647(d).

**Controls:**
1. The 76 general questions without a standalone "or" and the 12 named-provision questions: final context identical,
   source by source and text by text.
2. The 2 other "or" questions (COS-71.1-Q2, UC-COS-013): no required paragraph lost.
3. The frozen 352-row retrieval baseline (`scripts/retrieval_baseline.py`): no row whose keyed section leaves the
   context.
4. The literal-OR parse unit tests:
   - "and/or" and "either-or" are kept;
   - a leading or trailing "or" is dropped;
   - quoted phrases and "-x" exclusions are unchanged.

**Acceptance:** all target thresholds are met **and** 0 required paragraphs are lost in any of the 100 questions or in
the 352 rows. Any loss is a failure.

**Rollback:**
- With the switch off, the code path is byte-identical to today: same system-identity hash, and controls 1 and 3
  unchanged.
- Rolling back means unsetting the switch, or reverting the patch.
- No data, index or configuration file is touched.

## F. Unresolved
1. **C (40 questions, 91 paragraphs):**
   - Located at the section-ranking stage, but its cause inside the weighting is attributed for one question only:
     COS-74.2317-Q1 loses its identifier tokens.
   - Best required-section rank: {{CBEST}}. Whether these are vocabulary gaps or weighting effects is not attributed
     per question.
2. **B:** the ≤ 2 rows per section and ≤ 4 rows limits, plus required paragraphs that share no word with the question
   (anaphoric "these … salicylanilides"). Retrieving the rest of a top-ranked section is untested, and so is its cost
   against the 3,600-char budget.
3. **D:** measured as the multiplier (A + D +15). The relevance of the guidance it removes cannot be scored with
   CFR-only keys; this needs its own control.
4. **Source integrity:** 11 lead-in rows are missing their announced text. Fixing this needs re-ingestion, which this
   task does not allow.
5. **Companion provisions** in 5 named-provision questions: no leg looks for them, and cross-references are off.

**ROOT CAUSE CONFIRMED — one correction recommended.**
