# Phase 2L: numeric limit-direction validation with JR

**Run:** 2026-10-09, started 05:31:21Z. Offline only. No production code, tests, fixtures, benchmark or rubric changed (section 5.5).

**Verdict: INVESTIGATE FURTHER**

The best candidate is **JRN2**: JR plus the refined numeric check NUM2.
- It meets the numeric-specific criteria:
  - all 7 relative-clause tests hold;
  - 0 changes across the 170 frozen row-runs;
  - no comparison between different quantities, units or events;
  - ambiguity abstains.
- It still fails three strict criteria:
  - 1 of the 15 Phase 2I checks fails (T3c);
  - 2 of the 11 decision cases fail (DX2, DX4);
  - **3 known false supports remain** (N9, N10, N15).
- All of these failures are pre-existing in production and come from mechanisms outside the numeric check. None is introduced by the candidate.
- Under the rule "do not relax the criteria", that means it is not a safe candidate. The numeric component on its own is not the blocker.

**Correction to the request:** it refers to "47 CFR 73.3110(c)(1)". The section is **21 CFR 73.3110(c)(1)** (chlorophyllin-copper complex in bone cement). All work used the 21 CFR text.

---

## 1. Representation and comparison rules

**Implementation:** `work/make_variants_l.py`, functions `_p2l_bounds` and `_p2l_compare`. The check is separate from JR. It runs inside `compare()`'s quantity block and only:
- appends a `limit_direction` conflict; or
- sets `support_blocked` when that is still empty.

It never removes a conflict and never touches polarity, strength or the gate.

### What a bound is

A bound is an `(relation, value, unit, leading context, trailing context)` tuple, read from a phrase of the form *bound-phrase + optional "a period/total/level of" + number + unit*.

| Relation | Phrases (matched in this order; a span is claimed by the first pattern that matches it) |
|---|---|
| `<=` | do/does/shall/must/may/will/can/should not exceed, not to exceed, not exceeding, no more than, not more than, at most, up to, no/not longer than, maximum of, within (**durations only**) |
| `>=` | at least, not less than, no less than, no/not fewer than, minimum of |
| `<` | less than, fewer than, below, under, shorter than |
| `>` | exceed(s/ed/ing), more than, greater than, above, over, longer than, in excess of |

- **Numbers:** digits with thousands separators and decimals, plus the written-out numbers one to ninety (common subset).
- **Units:** percent/% → `percent`; days, with the calendar/business/working qualifier kept **as part of the unit**; weeks, months, years, hours, minutes; mg, g, kg, ml, l, ppm, ppb, degrees.
- **No unit conversion of any kind:** 12 months ≠ 1 year, ppm ≠ percent, business days ≠ calendar days. Mismatched units are not compared.

**Negation scope.** Negations that belong to the bound phrase ("not to exceed", "not less than") set its relation. Any other negator (*not, no, never, cannot, neither, nor*) earlier in the same clause marks the bound **ambiguous**.
- If any claim bound is ambiguous, the check returns no finding.
- An ambiguous evidence bound is never compared.
- **NUM2 refinement:** negations inside *another* bound phrase earlier in the clause are discounted. This fixes N16: "containing not more than 0.1 percent … at a level not to exceed 0.3 percent".

**Scope gating** ("same quantity, actor, product, event"). Two bounds are compared only if all of these hold:
1. the value is identical after normalisation;
2. the unit is identical;
3. the leading context shares at least one stem (the last 4 content words of the clause before the bound);
4. **NUM2:** if both sides state a trailing context (the first 4 content words after the bound, excluding weight/after/before/per), those share at least one stem. Example: "by weight of **twine**" vs "by weight of **ethylene glycol**" (N9); "after the **detention order is issued**" vs "after the **appeal is filed**" (P5c).

### Comparison

For each claim bound, gather the matching evidence bounds.
- If none match, or the evidence reads the same quantity in two directions, there is no finding.
- Same relation: no finding (equivalent forms).
- **Opposite direction** (`{<=,<}` vs `{>=,>}`): a `limit_direction` **conflict**. The claim is contradicted.
- **Same direction, different inclusivity** (`<=` vs `<`, `>=` vs `>`): `support_blocked` (**boundary**). The claim cannot be credited, but it is not called a contradiction.

**Different values are never compared**, not even when one range contains the other. So two statements that are both true for different ranges produce no finding (P1).

## 2. Design and provenance

### Variants

All are copies of the production `src/regulus/accuracy/`, patched by flag and loaded in place of the package by `work/use_variant_ro.py`. The database is reached only through the server's read-only connection.

| Variant | Flags | Meaning |
|---|---|---|
| L0_identity | — | production (identity check) |
| JR | REL, QUAL, JRQ | Phase 2K restricted relative-clause fallback, unchanged |
| NUM | NUM | the numeric check only |
| JRN | JR + NUM | the first combination |
| NUM2 | NUM2 | the numeric check plus two scope fixes (trailing context; discount other bounds' negations) |
| **JRN2** | JR + NUM2 | **the candidate** |

**One refinement was allowed and used (NUM → NUM2).** It is limited to the numeric component's own scope defects, which were found on N9 (a false conflict) and N16 (a missed reversal). No other component was tuned.

### Labelled data

- **`work/numeric_cases.json`: 16 verdict-level cases (N1–N16).**
  - Evidence: **REAL**, verbatim eCFR sentences from the local snapshot dated 2026-09-03, with content SHA-256.
  - Claims: **CONSTRUCTED**, one bound phrase or unit changed. They are not regulatory text.
  - They cover the categories the brief listed:

    | Category | Cases |
    |---|---|
    | reversed direction | N1, N4, N6, N7, N11, N16 |
    | equivalent forms | N2, N5, N12 |
    | inclusive vs strict | N3, N8 |
    | different quantity | N9 |
    | different unit | N10 |
    | unrelated passage | N13 |
    | missing number | N14 |
    | negation outside the bound | N15 |
    | decimals and percentages | N7, N8, N16 |
    | durations | N1–N3, N10–N13, N15 |

- **`work/numeric_probes.py`: 11 check-level probes (P1–P9, P5b, P5c).** These call `_p2l_compare` directly, with no verdict layer. Evidence is verbatim except P3's, which is trimmed from 131.160(b)(2). They cover: different ranges that are both true, months vs years, ppm vs percent, negation scope, different event with the same number (same and opposite direction), calendar vs business days, "maximum of", and written-out numbers.

**Existing controls, copied unchanged from Phase 2K:**
- 7 permanent tests: RC1–RC7 in `tests/test_accuracy_relative_clause.py`;
- 15 Phase 2I checks (T1a–T5b, `controls_real.json`);
- 11 decision cases and 5 word-reading probes (DX1–DX11, EX1–EX5, `diagnostics.json`);
- frozen controls: 88 false conflicts including the 33 NEG-REL cases, 44 real operator readings, 18 invented-condition cases, 19 genuine contradictions and 6 reading assertions;
- the 2,105-pair replay;
- 170 row-runs: F60 (legacy-reconstructed) + GUIDE8 + REAL17, both aligners.

## 3. Per-variant results

| | L0 (prod) | JR | NUM | JRN | NUM2 | **JRN2** |
|---|---|---|---|---|---|---|
| 7 RC tests (assertions, `--runxfail`) | 4/7 (RC1–3 fail) | 6/7 (RC6 fails) | 4/7 | **7/7** | 4/7 | **7/7** |
| Full suite with `--runxfail` | 1837 pass, 3 fail | 1839 pass, 1 fail | 1837 pass, 3 fail | 1840 pass | 1837 pass, 3 fail | **1840 pass** |
| 15 Phase 2I checks | 9 | 13 | 9 | 14 | 9 | **14** (T3c) |
| 11 decision cases | 7 | 8 | 7 | 9 | 7 | **9** (DX2, DX4) |
| 5 word-reading probes | 5 | 5 | 5 | 5 | 5 | **5** |
| 16 numeric cases (check-level label) | 6 | 6 | 12 | 12 | 14 | **14** (N12, N15) |
| 11 numeric probes | — | — | — | 10 (P5c) | — | **11** |
| Numeric cases wrongly credited (verdict level) | **11** | 11 | 3 | 3 | 3 | **3** |
| 19 genuine contradictions kept | 19 | 19 | 19 | 19 | 19 | **19** |
| 44 real readings / 18 INV / 6 readings | all kept | all kept | all kept | all kept | all kept | **all kept** |
| 88 false conflicts fixed | 10 | 43 | 10 | 43 | 10 | **43** (33/33 NEG-REL) |
| Replay: new / removed conflict pairs | 0/0 | 1/34 | 0/0 | 1/34 | 0/0 | **1/34** |
| `limit_direction` conflicts in 5,839 recorded comparisons | 0 | 0 | 0 | 0 | 0 | **0** |
| 170 row-runs: claim / answer / dimension changes | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | **0/0/0** |

Notes on the table:
- **The 7 tests in a normal run.** Under JRN2, RC1–RC3 report `XPASS(strict)`, which pytest counts as failed: 3 failed, 1837 passed. That is the intended "fail loudly when fixed" signal, not a regression. Shipping would mean removing those three `xfail` markers; no assertion would change.
- **The one new replay pair** belongs to JR and was already reviewed in Phase 2K: H-006, an evidence heading "Who Is **Not** Subject …" that now reads polarity. It changes no verdict.
- **JR alone breaks RC6/T5a and DX7.** Production gets those right only through the spurious relative-clause negation reading ("levels that do **not** exceed"). JR removes that reading, and NUM2 restores the contradiction for the correct reason (`limit_direction`).

## 4. Case by case: false support and false contradiction

**Numeric cases (claim basis / final):**

| Case | Expect | L0 production | JRN2 | Comment |
|---|---|---|---|---|
| N1 at least 1 yr → less than 1 yr | conflict | paraphrase / **supported** ✗ | contradicted ✓ | reversal caught |
| N2 → no less than 1 yr | equivalent | supported ✓ | supported ✓ | |
| N3 → more than 1 yr | boundary | paraphrase / **supported** ✗ | unverifiable ✓ | strict vs inclusive: blocked, not contradicted |
| N4 up to 1 % → above 1 % | conflict | **supported** ✗ | contradicted ✓ | |
| N5 no more than → at most | equivalent | supported ✓ | supported ✓ | |
| N6 no more than → more than | conflict | **supported** ✗ | contradicted ✓ | |
| N7 not more than 0.1 % → greater than | conflict | **supported** ✗ | contradicted ✓ | decimal percent |
| N8 → less than 0.1 % | boundary | **supported** ✗ | unverifiable ✓ | |
| N9 0.1 % of glycol vs "exceeding 0.1 % by weight of twine" | no numeric | **supported** ✗ | **supported** ✗ | check abstains correctly (different quantity); the claim is still wrong (twine limit ≤ 0.3 %), and **credited**, as in production |
| N16 not to exceed 0.3 % → exceeding 0.3 % | conflict | **supported** ✗ | contradicted ✓ | fixed by NUM2 (JRN missed it) |
| N10 15 calendar days → 15 business days | no numeric | **supported** ✗ | **supported** ✗ | check abstains correctly (different unit); the claim is still wrong and **credited**, as in production |
| N11 within 15 calendar days → more than 15 after | conflict | **supported** ✗ | contradicted ✓ | duration |
| N12 may not exceed 20 → no more than 20 | equivalent | **contradicted** ✗ | **contradicted** ✗ | false contradiction from the **strength** operator ("may not" in "a period that may not exceed" read as mandatory); the numeric check correctly finds them equal |
| N13 unrelated 120 days | no numeric | unverifiable ✓ | unverifiable ✓ | |
| N14 "exceed the permitted limit" (no number) | conflict | contradicted ✓ | contradicted ✓ | caught by JR's qualifier polarity; the numeric check has nothing to compare |
| N15 "shall **not** be retained for more than 1 yr" | conflict | paraphrase / **supported** ✗ | **supported** ✗ | the check abstains (negation outside the bound: ambiguous, by design); polarity then agrees spuriously because 211.180(a) contains the noun "exemption" (NEG-NOUN, Phase 2H) |

**Summary.** Production wrongly credits 11 of the 12 claims that are wrong (N13 is not wrong, only unsupported). JRN2 wrongly credits **3**: N9, N10 and N15. All three are credited by production too, and on all three the numeric check behaves as specified. The remaining false contradiction (N12) is also present in production and is not numeric.

**Probes (JRN2 11/11):**
- P1 (different ranges, both true), P2 (months vs year), P3 (ppm vs percent), P4 (negation outside the bound), P5/P5b/P5c (different event, same number) and P6 (calendar vs business days) produce **no finding**.
- P7 (reversal) and P9 (written-out "one year") produce **conflict**.
- P8 ("maximum of") produces no finding.
- **JRN fails P5c:** without NUM2's trailing-context rule, "detain … for more than 20 calendar days after **the appeal is filed**" was contradicted by "… may not exceed 20 calendar days after **the detention order is issued**", a different event.

**Remaining non-numeric failures in JRN2 (all pre-existing):**

| Case | What happens | Mechanism | Production |
|---|---|---|---|
| T3c (701.13(d), multi-sentence) | false polarity conflict; the claim is unverifiable | negation in another sentence of the passage | same |
| DX2 (1141.1(b) "do not apply" vs "apply") | missed contradiction; unverifiable (**not credited**) | shared negated qualifier | worse: **false support** (descriptive) |
| DX4 (113.40(a)(6), the baffle-plate sentence) | false polarity conflict; final still supported | negation in another sentence | same |

## 5. Regression and frozen rows

1. **170 row-runs** (`work/h_cf_*.json`, `cf_diffs.json`): **0 claim, 0 answer and 0 dimension changes** for every variant against `h_current.json`. Nothing is left unexplained.
2. **Numeric exposure in the frozen data** (`work/exposure_frozen.py` → `exposure_frozen.json`):
   - of 2,105 unique claim/evidence pairs, 2,096 have no claim bound;
   - 5 have a claim bound but no evidence bound;
   - 4 share a value and unit, and **all 4 are genuine agreements**: "within 60 days" ×2, "within 5 calendar days", "at least 6 months". The check correctly makes no finding on any of them.

   So on frozen data the check is precise but almost unexercised. Its positive evidence comes from the labelled cases.
3. **Phase 2D.** F-007 and F-009 are unchanged at claim and answer level (part of the 170 row-runs, 0 changes). The content-gate suite (240 tests) passes inside the 1840.
4. **Genuine contradictions** remain detectable: 19/19, plus RC4–RC7, T5a and DX7. JRN2 adds `limit_direction` alongside `qualifier_polarity` on T4a and T4b without changing their outcome.
5. **State:**
   - `src/`, `scripts/`, `tests/`, `web/`: 305 files, **identical** by SHA-256 (`work/manifest_start.sha256` = `manifest_end.sha256`);
   - 23 benchmark, frozen-input and fixture files: **identical** (`benchmark_manifest_*.sha256`);
   - `git status --porcelain`: 63 lines at start and end, **identical** (`git_status_*.txt`; this directory is under `artifacts/accuracy/`, which was already untracked).
   - No package installs, no model download, no 300-question run, no LLM judge.

## 6. Limitations: units, scope and boundaries

- **No unit arithmetic.** Equivalent quantities in different units (12 months / 1 year, 1,000 ppm / 0.1 %) are never compared. This is safe (abstain), but it misses those reversals.
- **Exact values only.** A claim "more than 2 years" against "at least 1 year" is not compared, even though the ranges are related. Nested and overlapping ranges are out of scope. N9 is one: the twine limit ≤ 0.3 % against a claim of > 0.1 %.
- **Scope is lexical.** Actor, product and event are approximated by sharing at least one stem of 4 words before (and, in NUM2, after) the bound. A shared generic word could let two different quantities match. Different words for the same thing will abstain.
- **Negation is clause-local and conservative.** Any outside negator makes the bound ambiguous. N15 shows the cost: the check abstains, so a reversal it could not read safely stays credited by another operator.
- **Only the listed phrases.** Bounds such as "may range from … to …", tables, "between X and Y" and "a maximum level" with no "of" are not read.
- **Exposure.** Only 4 frozen pairs exercise the comparison, all agreements. Every conflict and boundary result comes from 16 constructed-claim cases and 11 probes on 11 real sections. Coverage across the corpus is unmeasured.
- **The legacy-reconstructed F60 evidence** carries the limitations recorded since Phase 2G.

## 7. Verdict: INVESTIGATE FURTHER

| Strict criterion | JRN2 |
|---|---|
| All 7 tests pass with unchanged expectations | **met.** 7/7 assertions; RC1–RC3 would need their strict-xfail markers removed |
| All 15 checks meet expectations | **not met.** 14/15 (T3c) |
| All 11 decision cases meet expectations | **not met.** 9/11 (DX2, DX4) |
| No known false support | **not met.** N9, N10, N15 (all pre-existing; down from 11 in production) |
| Genuine contradictions remain detectable | met |
| Phase 2D intact | met |
| No unexplained changes in the 170 rows | met (0 changes) |
| Numeric comparisons only between comparable quantities and scopes | met (N9, N10, N13; P1–P6) |
| Ambiguity fails conservatively | met (N15, P4) |

**Why not SAFE CANDIDATE:** three criteria fail, and the criteria are not relaxed.

**Why not NO SAFE OPTION:**
- every failure is pre-existing and comes from a named mechanism outside the numeric check:
  - cross-sentence negation (T3c, DX4);
  - shared negated qualifier (DX2);
  - strength read inside a relative clause (N12);
  - NEG-NOUN "exemption" (N15);
  - unit- and range-level misstatements that no operator checks (N9, N10);
- the numeric component met every numeric-specific criterion, introduced no new false contradiction and no frozen-row change, and turned 8 wrongly credited reversals into contradictions (6) or blocked boundaries (2).

**What would need investigating** (not done here):
1. sentence selection within a passage for polarity (T3c, DX4);
2. the main clause vs a shared negated qualifier (DX2);
3. modal strength inside relative clauses (N12);
4. whether a unit-mismatch or range check should *block* credit rather than just abstain (N9, N10). This is the only change that would touch the numeric component, and it would turn abstention into blocking, so it needs its own review.

No candidate was implemented in production.

## Artifacts (`work/`)

- **Variants:** `make_variants_l.py` → `variants/{L0_identity,JR,NUM,JRN,NUM2,JRN2}`.
- **Numeric:** `numeric_cases.json`, `eval_numeric.py` → `numeric_*.json`; `numeric_probes.py` → `numeric_probes_JRN2.json`; `exposure_frozen.py` → `exposure_frozen.json`.
- **Controls:** `eval_real_controls.py` → `real_controls_*.json`; `eval_diagnostics.py` → `diagnostics_*.json`; `eval_controls_h.py` → `controls_result_*.json`.
- **Frozen rows:** `collect_h.py`, `diff_cf.py` → `h_cf_*.json`, `cf_diffs.json`.
- **Suite:** `run_suite_variant.py`.
- **State:** `manifest_*.sha256`, `benchmark_manifest_*.sha256`, `git_status_*.txt`.
