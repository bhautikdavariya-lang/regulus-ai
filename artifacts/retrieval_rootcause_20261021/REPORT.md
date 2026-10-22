# Regulus: root cause of regulatory retrieval failures (2026-10-21)

**Scope:** retrieval only: what is searched, matched, ranked, capped, selected and passed on. No model was run, and no
answer was used as evidence.

**State traced:**
- **Code:** byte-identical throughout. The changes to files tracked at 6f94938 hash 3a246702… before and after.
- **Commits during the task:** the git user committed (a4471fe…83b32fe at 13:49–13:52, then fbd2e60 at 14:18, a draft of
  this report). None of them changed code content. Nothing was committed or pushed by this investigation.
- **Switches:** no `REGULUS_*` variable set, so `REGULUS_ECFR_LITERAL_OR` is off.
- **Semantic loader:** refused, with 0 attempts.
- **Database:** session read-only, and the corpus fingerprint and write counters were identical before and after every
  run.

**Question set:** the 100 cosmetics questions with verified answer keys (step6 `selection.json`).
- 88 name no provision (general questions). These are where retrieval fails.
- 12 name a provision, and none names a docket.
- Required evidence is the paragraphs the key cites.

**Verification:** 4 independent read-only verifiers (code, numbers, causal logic, integrity and brief) re-derived the
claims. Their corrections are applied below.

## A. The pipeline that actually runs

```
question ─ plan_query ─┬─ names a provision (12) → exact_cfr (+ parent row for a paragraph reference)
                       │      → EXACT (required) / STRUCTURAL (optional) · step 3 also runs · named provision arrives 12/12
                       └─ general question (88): lexical.py run_plan
   3a  definition_term → definition_ecfr       definitional questions only ("what does X mean/stand for", "define X",
                                               "meaning of X", "meant by X"); a hit skips steps 3, 5, 5b, 5c (0/100 here)
   3   full_text_ecfr(question), full_text_guidance(question)    websearch_to_tsquery: every word ANDed, but a
                                               standalone "or" becomes OR · limit 16 each · → SUPPORTING
   5   trigram_ecfr                            ≤ 4 words, identifier-like, or eCFR AND rows < top_k (8)
   5b  section_coverage_ecfr(content_terms)    GATE: eCFR AND rows < 3 · idf-weighted lexeme coverage per section
                                               → top 4 sections, ≤ 2 rows per section, ≤ 4 rows → DISCOVERY
   5   OR fallback (8 longest words)           only if < 3 distinct AND/exact/definition candidates across both
                                               corpora; eCFR leg skipped when 5b added rows · guidance → DISCOVERY (≤ 8)
   5c  defined_terms_ecfr                      general questions that invoke definitions
   6   merge → classify → order_evidence       EXACT, STRUCTURAL, SUPPORTING by score, DISCOVERY by score
       5b rows moved behind ALL other evidence (lexical.py:605–611)
       heading promotion → SUPPORTING, first   specific heading (≥ 2 words, in the question) plus an eCFR row of the same
                                               part in another section · ≤ 3 rows
   selection.py select_evidence (general question)
       eCFR reserve 1,200 chars: eCFR rows only, STRUCTURAL → SUPPORTING → DISCOVERY, registry order
       soft budget 3,600 chars, ≤ 8 sources: tier by tier, registry order → guidance DISCOVERY precedes 5b rows
```

**Code references:**
- [lexical.py:411](../../src/regulus/retrieval/lexical.py#L411) `run_plan`, with steps 3a/3/5/5b/5c/6 at
  :505/:518/:557/:564/:588/:596. The gate is at :566.
- `SECTION_COVERAGE_ROWS_PER_SECTION = 2` at :147. `coverage_slots = top_k // 2` = 4 is both the section limit and the
  row limit (:565, :1007).
- RC1 SQL at [sql.py:153](../../src/regulus/retrieval/sql.py#L153). Rows that match no question lexeme can never be
  returned.
- `content_terms` at [query.py:141](../../src/regulus/retrieval/query.py#L141) drops stop words, tokens under 3
  characters, and tokens containing a digit.
- Selection: [selection.py:399–452](../../src/regulus/rag/selection.py#L399), with `_optional_order` at :483. Policy
  values are in [context.py:56–81](../../src/regulus/rag/context.py#L56).
- **Not running:**
  - the semantic fallback: `general_questions=False` ([fallback.py:75](../../src/regulus/retrieval/fallback.py#L75));
  - cross-references;
  - the literal-OR switch.

**Trace fidelity** ([tools/trace_retrieval.py](tools/trace_retrieval.py), [traces_all/](traces_all/)):
- Every leg was wrapped to record its input, the tsquery PostgreSQL built from it, and its rows.
- The selection replay equals the real selection in 87 of 88 general questions. The exception, COS-74.2304-Q1, is an
  unmodelled duplicate-consolidation step that involves no required paragraph.
- The coverage SQL, recomputed with every section and row exposed, reproduces the leg's rows in 58 of 58 keyed
  questions where it ran.

## B. Root causes

Base: the 68 general questions whose key cites eCFR text, with 174 required paragraphs. A mis-parsed key, "(b)(2)(i)-(iv)",
is excluded.
- **17 of 174** required paragraphs reach the context today.
- All required paragraphs arrive in 5 questions; none arrive in 54.

Each missing paragraph is assigned to its first loss ([refined_classes.json](refined_classes.json), built from
[prevalence.json](prevalence.json) and [rank_check.json](rank_check.json)).

| # | Lost at | Mechanism | How it is shown | Paragraphs / questions |
|---|---|---|---|---|
| **A** | Coverage gate (lexical.py:566) | A standalone "or" splits the AND query into an OR. The tail branch alone matches ≥ 3 off-topic rows, so the coverage leg never runs, and the off-topic rows become SUPPORTING. | **Intervention.** Removing the operator opens the gate. The leg then returns 12 of the 39 (in 8 of 10 questions); the other 27 are held by the limits in B. | **39 / 10** |
| **B1** | Coverage per-section cap (≤ 2 rows) | The section is reached, but the required paragraph is beyond its section's 2 rows, or shares no word with the question. | **Recomputed SQL**, with fidelity 58/58. | **22 / 16**. 3 share no lexeme: 700.15(b), (c); 70.3(v) in COS-82.1206-Q1. |
| **B2** | Coverage total limit (≤ 4 rows) | The section ranks 3rd or 4th, but sections 1–2 take all 4 rows. | Recomputed SQL. | **5 / 3** |
| **C** | Section ranking (top 4 sections) | The required section ranks below 4th. | **Located by stage only.** The cause inside the weighting is not attributed. | **87 / 39**. Best rank: 5–8 in 11 questions, 9–20 in 6, 21–100 in 14, over 100 in 8. |
| **D1** | Selection order (selection.py:424) | Coverage rows are moved behind everything. Guidance OR-fallback chunks (~1,500 chars each) therefore spend the 3,600-char budget first, and eCFR rows get in mainly through the 1,200-char reserve. | **Intervention.** With eCFR rows first in the same registry, they are selected. | **3 / 3** directly. Across 88 questions, 172 of 312 coverage rows were not selected (171 at the soft budget). Guidance is 143,127 of 201,638 context characters (71%). |
| **D2** | Usefulness filter | 700.14(a) is rejected by `is_useful`. | Trace. | 1 / 1 |

**Causal chains of the traced examples** ([causal/causal_checks.json](causal/causal_checks.json)):
- **A, COS-73.2725-Q1**, "…restrictions, certification **or** labeling apply?":
  - tsquery `…'restrict' & 'certif' | 'label' & 'appli'`;
  - branch 1 matches 0 eCFR rows; `'label' & 'appli'` matches 415 rows in 196 sections;
  - returned: 16 rows of 1271.90 (HCT/P donors) and 16 off-topic guidance chunks (HCT/P, food, medical gases,
    labeling, blood);
  - the coverage leg is skipped, and the final context is 8 rows of 1271.90.
- **B1, COS-700.25-Q2:** 700.25 ranks 1st, but (d) "Requests for exemptions" is its 6th row.
- **B1, COS-700.15-Q1:** 700.15 ranks 1st. (b) "These halogenated salicylanilides … deemed to be adulterated" and (c)
  match none of the question's 8 lexemes.
- **C, COS-74.2317-Q1:** `content_terms` drops "17", "D&C" and "No.". 74.2317 ranks 103rd of 6,294 matching sections;
  restoring "17 D&C" lifts it to 10th, which is still outside the top 4. Identifier loss is therefore one contributor,
  not the whole cause.
- **D1, COS-70.55-Q1:**
  - coverage returns 70.55, but it misses the reserve (818 + 790 > 1,200);
  - two guidance chunks (1,200 + 702 chars) spend the budget first, so 70.55 is dropped;
  - the same registry with eCFR rows first selects it.

**Ruled out:**
- semantic fallback (never runs);
- index drift: `search_vector` equals its generated definition in all 80 cited sections;
- duplicate live paths and removed rows (0);
- the top-k cut (selection walks the registry);
- loss between a leg and the registry (none).

**Named-provision questions:**
- The named provision arrives in 12 of 12.
- 8 of the 12 keys also cite a companion provision. In 5 it does not arrive (700.3(j), (m); 82.1050 ×3; 70.3(v)),
  because no running leg looks for it.

**The stages are serial; harness comparison** ([alternatives.json](alternatives.json),
[alternative_scope.json](alternative_scope.json); production untouched):

| Condition (general questions) | Required in context | Questions with ≥ 1 | Required lost | Side effect |
|---|---|---|---|---|
| Current | 17 / 174 | 14 | – | – |
| A: "or" operator word removed from both AND legs | 21 (+4) | 18 | 0 | Off-topic OR-fallback guidance in the 10 changed questions: +18,261 chars. In COS-71.27-Q1 ("list it, **or** exempt it"), the OR branch's 80.35 and 73.1 rows are displaced. |
| A on the eCFR leg only | 21 (+4, the same 4) | – | 0 | – |
| D: within each tier, eCFR rows ahead of guidance at selection | 20 (+3) | 17 | 0 | Changes 77 of 88 contexts. Guidance passages fall from 152 to 55; 92 of the removed passages belong to documents that leave the context entirely, including FDA's cosmetic "Lead in Cosmetic Lip Products" guidance (fully in 3 questions, partly in 1). |
| A + D | 32 (+15) | 25 | 0 | Both sets of side effects. |
| A (eCFR leg only) + D | – (4 of the gate questions' paragraphs) | – | 0 | The guidance AND query's off-topic SUPPORTING chunks still precede every eCFR DISCOVERY row. |

- No single change recovers more than 4 of the 157 missing paragraphs. Their interaction delivers +15.
- Of the 12 paragraphs A returns, D's mechanism drops 8.
- The coverage limits (B1/B2) hold 27 of the 39 A paragraphs.

## C. Source integrity (read-only; [integrity.json](integrity.json), [absence_check.json](absence_check.json))
- All 80 cited sections: `search_vector` is consistent, with no duplicate live paths and no removed rows.
- **Ingestion drops undesignated text after a lead-in.** 13 stored rows end by announcing text, such as "shall bear the
  following warning:" or "the following names are adopted…". The announced text is in no stored row; the next stored
  row is a sibling paragraph.
- **Corroborated against the local eCFR snapshot**
  (`artifacts/benchmark_verification/…/sources/ecfr_2026-10-14/`), where the text exists as an unnumbered line:
  - 740.11(a)(1): "Warning—Avoid spraying in eyes. Contents under pressure…"
  - 740.11(b)(1): "Warning—Use only as directed…"
  - 740.12(b): "Caution—For external use only…"
  - 701.3(c)(2)(i)(a), (b), (c): the ingredient-name lists
  - 701.13(n): the abbreviation list
- **By structure only** (Parts 71, 73, 74 and 81 are not in the local snapshot): 71.1(c), 73.2180(a)(2), 73.2250(b),
  74.2602a(b), 81.30(d), (e).
- **Probably the same omission:** 73.2725(b) and 73.2180(b), which say "shall conform to the following specifications"
  and store none.
- **Effect:** 6 questions need one of these rows: COS-71.1-Q2, 73.2180-Q1, 73.2250-Q1, 740.11-Q1, 740.11-Q2 and
  740.12-Q1. Perfect retrieval would still give them an incomplete provision.
- Repairing this needs re-ingestion, which is out of scope for this task.

## D. Highest-priority correction (deferred)

**Candidate: D1, selection order.** For a general question, compete eCFR rows ahead of guidance rows within each tier
in `select_evidence`. Retrieval, tiers, budgets and limits stay unchanged.

**Why it is the highest priority:**
- It is the stage where most of what retrieval does find is thrown away: 171 of 312 coverage rows, with 71% of context
  characters going to guidance OR-fallback text.
- Every upstream fix depends on it. Gate questions: A alone 4, A + D 12. Over all general questions, A + D gains 15 with
  0 lost.
- A is not a sound first correction on its own:
  - its isolated gain equals the eCFR-only path (the same 4 paragraphs);
  - it adds 18,261 chars of off-topic guidance;
  - where the "or" offers real alternatives (COS-71.27-Q1), it displaces rows that the OR branch had found.

**Why it is deferred, for one specific reason:** D's cost cannot be measured.
- The verified keys cite only CFR text, so "0 required paragraphs lost" says nothing about the 97 guidance passages it
  removes (152 → 55).
- Those removed passages include FDA's cosmetic lead guidance.
- No guidance-relevance judgement exists for these 100 questions.
- Until it does, no single correction is adequately supported, and **no change is recommended now.**

## E. Test plan (for D1, once the deferral reason is resolved; retrieval only, no model, read-only database)

**Precondition, which removes the deferral:**
- A blind, pre-registered relevance judgement of every guidance passage D removes or adds, against its question.
- The rule is fixed in advance, before any implementation run.

**Targets (harness or switch, measured with the trace tools):**
- 70.55 (COS-70.55-Q1), 71.15(b) (COS-71.15-Q2) and 701.3(b) (COS-701.3-Q1) enter the context.
- Coverage rows selected, out of 312, rise from 140.

**Controls:**
1. **Named-provision questions (12):** run them too; the final context must be identical (D applies only to general
   questions, but this must be measured, not assumed).
2. **Frozen 352-row retrieval baseline** (`scripts/retrieval_baseline.py`): no row whose keyed section leaves the
   context (section-level metric).
3. **Guidance:** no passage judged relevant under the precondition is removed.
4. **The 17 required paragraphs already in context:** none lost.

**Acceptance:** all targets met, and 0 losses in controls 1–4. Any loss is a failure. Thresholds are as set here, not
adjusted after the run.

**Rollback:**
- The change goes behind a new, separately named switch, off by default.
- With the switch off, retrieval output and the identity fingerprint are expected to be unchanged. This is verified
  after implementation by controls 1 and 2.
- Rolling back means unsetting the switch, or reverting the patch. No data, index or configuration file is involved.

## F. Unresolved
1. **C, section ranking (87 paragraphs, 39 questions; the largest class):**
   - Located at the stage, but its cause inside the coverage weighting is not attributed.
   - Identifier loss explains part of one case (74.2317: 103rd → 10th).
2. **B1/B2 limits (27 paragraphs, plus 27 of the 39 A paragraphs):**
   - Retrieving more of a top-ranked section is untested against the budget.
   - 3 required paragraphs share no word with their question.
3. **A's form.** Removing "or" is wrong where the question offers real alternatives (COS-71.27-Q1). A gate that does
   not depend on OR-branch matches is not yet designed or tested.
4. **Source integrity:** 13 lead-in rows are missing their announced text, which needs re-ingestion.
5. **Companion provisions:** 5 named-provision questions are missing a companion provision their key cites.

**ROOT CAUSE PARTIALLY CONFIRMED — correction deferred for one specific reason.**
