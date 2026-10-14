# Six-case investigation: evaluation coverage, citations and answerability

**Date:** 2026-10-09 (started 08:02:54Z). **Branch:** `main`. **No commit.** The 300-question benchmark was not run.

**Outcome:**
- Three confirmed root causes were fixed:
  - definitional-question retrieval and evaluation (case 6);
  - citation numbering (cases 1, 5a, 3);
  - short unsupported sentences being ignored, a false-PASS risk found while fixing case 6.
- Three cases are explained but not changed, because the only fixes would weaken a safeguard or need a broader evaluation: cases 2, 4 and 5b. Case 3 is fixed only in part.
- **Measured live, on these questions only:** cases 1 and 5a went from FAIL 60 to PASS 100, and case 6 from NOT EVALUATED to PASS 100.
- Unit and regression tests show no regression; they do not measure accuracy.

## 1. Root causes

**Questions.** Only case 5a (M-020) is a real benchmark question. The others were reconstructed from the case descriptions (`work/repro.py`). Case 2's exact UI outcome was not reproduced with my wording; its *mechanism* was reproduced on a §801.15 question (C4v2).

| Case | Question asked live | Before | First wrong stage | Root cause | Status |
|---|---|---|---|---|---|
| 1 | personnel qualifications, 21 CFR 211.25 | FAIL 60 | generation (marker) | §211.25(a), (b) and (c) were quoted verbatim with a single `[1]` at the end, so the (c) sentence ("adequate number of qualified personnel") cited (a). The regulation confirms the requirement is **§211.25(c)**, and the evaluator's `paragraph_mismatch` was correct. The pipeline's validation did not check which paragraph a marker's words come from. | **confirmed, fixed** |
| 2 | IND safety reporting, 21 CFR 312.32 | FAIL 40 (reported: FAIL 0, repeated, withheld) | generation | Not reproduced on §312.32 (three wordings: PASS 100 / FAIL 75 / FAIL 40). The mechanism was reproduced on "What are the label prominence requirements in 21 CFR 801.15?": with 21 exact sources (2,830 prompt tokens) the 0.6B model looped on one sentence, the repetition stop fired at 256 tokens, and validation flagged `degenerate_output` + `truncated` + `repeated_statement`, so the answer was **withheld (correct)**. Evidence was sufficient. Quoting the provision instead is refused by design, because the question narrows to a topic inside the section (`fallback.quoting_allowed`, `focus_terms`). | **mechanism confirmed; no safe narrow fix** |
| 3 | NDA content, 21 CFR 314.50 | FAIL 0 | generation | (i) Two list items quoted §314.50(a)(2) and (a)(3) but carried `[1]` (paragraph-number confusion). (ii) The model attached "if applicable" to the signature requirement §314.50(a)(5); the phrase exists elsewhere in the section, so validation records only a warning (a measured Stage 7 policy), and the evaluator correctly finds a contradiction. Listing (a) application-form items beside (c) summary items is not itself wrong: both are §314.50 content requirements. | (i) **fixed**; (ii) **confirmed, not changed** |
| 4 | label prominence, 21 CFR 801.15 | FAIL 40 (reported: NOT EVALUATED) | generation | The paraphrases misstate the regulation. For example, "(a)(4) states that the label space must be insufficient": the regulation lists causes of *lacking* prominence, not requirements. The evaluator abstains on 7 such claims (not decisive), which is correct: the evidence is present and correctly mapped, and the claims cannot be verified as written. | **confirmed: evaluator correct** |
| 5a | M-020: what 21 CFR 820.35 adds | FAIL 60 | generation (markers) | Items cited by paragraph number instead of source number, e.g. "nature and details of the complaint **[5]**": that text is §820.35(a)(5) = SOURCE 7, while SOURCE 5 is (a)(3). | **confirmed, fixed** |
| 5b | complaint records, 21 CFR 820.35 | NOT EVALUATED | generation, then evaluator coverage | The answer lists §820.35**(b)** servicing items (date of service, service performed, who serviced, test data) as **complaint-record** contents. Per the regulation that is **substantively wrong**. The evaluator abstained because "complaint records must include A, B, …" is never split into items: `enumeration()` refuses modal heads and `propositions()` splits only verb lists. | **confirmed; evaluator fix tried and rejected** (§4) |
| 6 | "What does FDA stand for?" | NOT EVALUATED | **retrieval** | Keyword search on "fda" + "stand" returned two FDA guidance documents ("good **stand**ing") and 314.103(c)(3), and none of the snapshot's 22 "FDA means the Food and Drug Administration" paragraphs (e.g. **21 CFR 10.3(a)**). Then, in the evaluator: (a) a definition has no operators for the paraphrase rule and is shorter than the descriptive standard's 6-word run; (b) the question was read as being about "stand" while "FDA" was dropped as generic. | **confirmed, fixed** |

**Found while fixing case 6 (confirmed, fixed):** a sentence of 8 words or fewer whose verb is not on a closed list was classified as a "heading" and **silently excluded from evaluation**. With case 6 fixed, "The FDA stands for … [1]" followed by "It regulates all food sold worldwide." would have shown **PASS**, because the unsupported second sentence was ignored.

## 2. Changes

| File | Change | Why |
|---|---|---|
| `src/regulus/retrieval/query.py` (+26) | `definition_term(question)`: the one short term of a definitional question ("What does X stand for / mean", "meaning/definition of X", "Define X", "What is meant by X"). Returns None for anything naming a provision, numbers, or more than 5 words. | case 6 |
| `src/regulus/retrieval/sql.py` (+17) | `ECFR_DEFINITION`: paragraphs that **open** with the term followed by "means" (the CFR definition convention); read-only and parameterised (`%(query)s`, `%(pattern)s`) | case 6 |
| `src/regulus/retrieval/lexical.py` (+26 / −5), `ranking.py` (+10), `models.py` (+3 / −1) | method `definition` (score 80: below exact and structural, above text matches). For a definitional question naming no provision, the lookup runs first. **If it finds the definition**, the keyword search and fallback do not run, because their frame words only match noise; **if not**, retrieval is unchanged. | case 6 |
| `src/regulus/accuracy/verdicts.py` (+50), `answer.py` (+9 / −2) | `judge_definition`: a claim "T stands for / means / refers to / is defined as D" is credited only by a passage that is the CFR's own definition of T, with D equal **word for word** (case, articles, punctuation aside) | case 6 |
| `src/regulus/accuracy/intent.py` (+16 / −4), `relevance.py` (+7 / −3) | A definitional question's topic is its term ("fda"), not its frame ("stand"), via the same `definition_term`. `terms(..., keep=)` lets that term be matched even though it is a generic word elsewhere; this applies only when the intent has the `definition_term` signal. | case 6 |
| `src/regulus/accuracy/claims.py` (+7 / −2) | A short sentence with a pronoun subject ("It regulates …") or "stand(s) / refer(s) / regulate(s)" is a claim, not a heading | false-PASS risk |
| `src/regulus/rag/citation_repair.py` (new, 106 lines), `rag/pipeline.py` (+8) | `repoint_citations`: a marker is renumbered only when the text it is attached to ends in a verbatim run of at least 5 words, at least 60% of that text, found in **exactly one** supplied source and in **none** of the cited ones. It runs after `normalize_answer`, before validation, and is recorded as `generation.citations_repointed`. Only the number changes. | cases 1, 5a, 3 |
| `web/index.html` (+3 / −2) | the stale comment ("score appears only in the details") now says the score appears beside the status. Comment only. | item 9 |
| Tests (new) | `test_retrieval_definition.py` (17), `test_accuracy_definition.py` (16), `test_citation_repair.py` (13), fixture `accuracy_definition_citation_rows.json` (26 verbatim snapshot paragraphs with SHA-256) | |

**Unchanged:** the Phase 2D content gate (no thresholds touched), the numeric-limit fix, contradiction operators, citation-grounding rules, PASS / FAIL / NOT EVALUATED rules (`review.py`), withholding, the repetition stop, the quoting policy, the rubric, and the benchmark.

**Your uncommitted changes in `lexical.py`, `ranking.py`, `sql.py`, `pipeline.py`, `models.py`, `query.py` and `web/index.html` are preserved.** My edits are additive; `changes.patch` has the exact diff against `snapshot_before/`.

One defect of my own was caught and corrected before this report:
- my edits had converted `models.py` and `query.py` from CRLF to LF line endings;
- I restored CRLF, so only the intended lines differ (+3 / −1 and +26 / −0).

## 3. Tests (actual results)

- **New:** 46 passed (17 + 16 + 13). They include these negatives:
  - definitions: a wrong expansion ("Federal Drug Agency", "Food and Drug Agency"), a partial one, a wrong citation, no citation, an unsupported extra sentence, a non-matching gloss for "lot";
  - re-pointing: cited source already right, paraphrase, text in two sources, a nonexistent source, a run under 5 words, a coincidental tail, no markers, a single source.
- **Full suite** (`pytest -q tests/ -rs`): **1977 passed, 1 skipped (pre-existing), 3 xfailed, 0 failed**, i.e. 1931 + 46. One existing safety test (`test_sql_statements_are_read_only_and_parameterised`) failed during development because my SQL parameter was named `%(term)s`. I renamed the parameter; the test is unchanged.
- **Frozen safeguards** (`frozen/`):
  - 170 row-runs: 0 claim, answer or dimension changes; 984 claims before and after;
  - 0 of 2,103 frozen comparisons changed;
  - 19/19 genuine contradictions, 44/44 real readings, 18/18 invented-condition cases;
  - F-007 identical; F-009 s10 still paraphrase by 117.254(a).
- **Rejected experiment:** I let modal-headed noun lists ("must include A, B, …") split into items for case 5b. Every item, including the correct ones, came out unverifiable, and "name, address, and phone number" was shredded. The status stayed NOT EVALUATED, so I **reverted** it (file restored and verified).

## 4. Live reproduction and retest

All runs go through the real `serve_ui.Engine.ask` with the local model `--offline`, the read-only database and UI defaults, answered with evaluation on and then off (`work/repro_before.json`, `work/repro_after.json`).

| Case | Before | After | Answers / citations identical with evaluation on vs off |
|---|---|---|---|
| 1 | FAIL 60 | **PASS 100** | yes / yes |
| 2 | FAIL 40 | FAIL 40 | yes / yes |
| 3 | FAIL 0 | FAIL 0 (2 citations corrected; still fails on the genuine "if applicable" contradiction) | yes / yes |
| 4 | FAIL 40 | FAIL 40 | yes / yes |
| 5a | FAIL 60 | **PASS 100** (12/12 statements cite a supporting source) | yes / yes |
| 5b | NOT EVALUATED | NOT EVALUATED | yes / yes |
| 6 | NOT EVALUATED | **PASS 100**: answer "The FDA stands for the Food and Drug Administration. [1]", evidence 21 CFR 10.3(a), 117.3, 121.3 | yes / yes |

**What changed in the answers themselves:**
- For cases 1, 3 and 5a the delivered answer is **identical apart from the corrected marker numbers**, so generation was not altered.
- Case 6's answer changed because its evidence changed: before, it was a definition followed by unrelated guidance text; after, the definition alone.

**Other live checks:**
- **Variant runs** (`work/repro_variants.json`): re-pointing fired on two fresh answers. In C2v3, §312.32(c)(1) and (c)(1)(i) were verified by text and the evaluator now marks both citations correct. In C4v1, 77 of 86 words (90%) are verbatim only in §801.15(c)(1)(i)(D)(3).
- **Withholding:** C4v2 (looping generation) was withheld, as the safeguard requires.

## 5. What improved

- **Retrieval:** definitional questions about a term the CFR defines with "means".
- **Citation accuracy:** misnumbered markers whose words are verbatim in exactly one source.
- **Evaluation coverage:** definitions decided by identity, and short unsupported sentences now evaluated instead of ignored.
- **Not changed:** generation itself. The model still loops (case 2 mechanism), misparaphrases (case 4), invents conditions (case 3) and merges subsections (case 5b).

## 6. Limitations and risks

- **Evidence base.** Improvements are measured on 7 live questions (6 reconstructed) plus 5 variants, nothing more. No claim is made about benchmark-level accuracy.
- **Case 1's PASS** relies on the **existing** rule that a statement with no citation of its own is a gap, not a citation defect: 4 of its 5 verbatim statements carry no marker. This rule was not changed; whether a PASS should require every statement to be cited is a policy question for a separate decision.
- **Definition lookup:**
  - only CFR definitions phrased "<term> means …" are found ("Combination product includes" is not);
  - up to 3 definitions are kept, shortest first, and they may come from different parts with different scopes (e.g. "lot" in 110.3 vs 114.3);
  - the evaluator credits only the exact definiens, so a correct but differently worded expansion is NOT EVALUATED, not PASS;
  - "U.S." is treated as one token; other abbreviations inside a definiens end it early, which can only miss a credit.
- **Citation re-pointing** acts only on verbatim runs of at least 5 words that make up at least 60% of the cited text. Paraphrased content with a wrong marker is left for the evaluator to fail, as before.
- **A wrong expansion** ("FDA stands for the Federal Drug Agency [1]") is FAIL 0, never PASS. Its explanation says "the answer declines", because all of its words are generic, so the sentence is read as restating the question. The status is right; the wording is imprecise.
- **Unresolved, with the safest alternatives:**
  - **Case 2:** reduce prompt size for topic-focused questions (evidence allocation), or adjust decoding. Both change every answer and need a broader evaluation; withholding stays correct meanwhile.
  - **Case 3 "if applicable":** promoting `condition_not_in_cited_source` from warning to repair would reverse a measured Stage 7 decision; re-measure before changing it.
  - **Case 5b:** item-level judging of modal noun lists needs list-head-aware support (an item must belong to the head's subsection) before it can be enabled without shredding lists or crediting cross-subsection items. Until then NOT EVALUATED is the honest result.
  - **Case 4:** a generation-quality issue; the evaluator is correct.

## 7. Confirmation

- **No 300-question run, no commit.** No dependency was installed.
- **Database:** read-only connection only, asserted in every script.
- **Benchmark, frozen inputs, fixtures used by frozen runs, and the rubric:** identical (`benchmark_manifest_before/after.sha256`).
- **Protected safeguards:** verified as in §3.
- **Git status:** 65 → 71 lines. The new lines are `M models.py`, `M query.py` (previously unmodified tracked files) and four untracked new files. No existing line changed (`git_status_before/after.txt`).

**Artifacts:**
- `snapshot_before/`, `changes.patch`, `manifest_*`;
- `work/` (repro scripts and JSON, traces, fixture fetch);
- `frozen/` (170-row battery);
- `tests_full_suite_after.txt`.
