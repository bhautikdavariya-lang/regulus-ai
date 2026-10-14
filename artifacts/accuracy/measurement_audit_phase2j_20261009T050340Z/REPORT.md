# Measurement Audit Phase 2J: relative-clause regression tests and offline candidate validation

**Verdict: INVESTIGATE FURTHER.**

One offline candidate, **JBQP2**, passes all seven tests at claim level and every control and frozen-row check available. It therefore formally meets the stated acceptance criteria. I do **not** classify it SAFE, because a direct precision check shows its qualifier reader misreads determiners and "-ing" nouns at scale (§4.3). The frozen data is too sparse to show whether those misreads produce false contradictions against a claim's own stating passage. The earlier variant JBQP proved they can, on real frozen claims.

Production code is unchanged. The seven tests are added; three are marked `xfail(strict=True)` because the current evaluator fails them. No 300-question run.

## 1. The seven tests and their sources

**Files:**
- `tests/test_accuracy_relative_clause.py` (new);
- `tests/fixtures/accuracy_relative_clause_rows.json` (new).

**Evidence** is **verbatim** eCFR text from the local read-only snapshot (`cfr_records`, snapshot 2026-09-03), taken unchanged from Phase 2I `work/controls_real.json`, with its content hash.

**Claims** are **constructed for testing**, one qualifier or modal changed, and are labelled as such in the fixture and the test module. No claim is presented as regulatory text.

**Each test asserts the claim-level decision:** the support basis, the conflicts, and the claim's final status. It uses the question "What does <citation> require?", so a relevance gate cannot hide the support decision. (Phase 2I showed a generic question masks it.)

| Test | Citation (sha256 prefix) | Constructed claim | Asserts | Production |
|---|---|---|---|---|
| RC1 | 21 CFR 213.122(e) (ab14c46ade) | "Labels, labeling, and other packaging materials that are obsolete or outdated shall be destroyed." | no polarity conflict; not CONTRADICTED | **xfail**: CONTRADICTED by a false polarity conflict |
| RC2 | 21 CFR 212.40(c) (3005e2bcc7) | "You must use in PET drug production any lot that does not meet its specifications." | polarity conflict; not credited; CONTRADICTED | **xfail**: no conflict, **false partial** (drops_a_condition) |
| RC3 | 21 CFR 101.36(b)(2)(i) (20614d372e) | "Any (b)(2)-dietary ingredients that are not present shall be declared." | polarity conflict; not credited; CONTRADICTED | **xfail**: no conflict, **false support** (paraphrase, final "supported") |
| RC4 | 21 CFR 211.115(a) (6c7007ac67) | "… prescribing a system for reprocessing batches that conform to standards or specifications." | a conflict; not credited | pass |
| RC5 | 21 CFR 109.15(b)(2)(i) (51d2dc011f) | the same sentence with "that does not contain PCB's" → "that contains PCB's" | a conflict; not credited | pass |
| RC6 | 21 CFR 73.3110(c)(1) (009ef7a88a) | "Chlorophyllin-copper complex may be used at levels exceeding 0.003 percent by weight of the bone cement." | a conflict; not credited | pass |
| RC7 | 21 CFR 701.13(d), multi-sentence (ea48022d88) | "A decimal fraction may be carried out to more than two places." | a conflict; not credited | pass |

**Why the xfail marks.** They keep the correct expectation unchanged and record the measured defect as the reason. Because they are strict, the suite **fails** the moment one starts passing, so a fix cannot slip in unnoticed. To see the raw failures, run with `--runxfail`.

**Spec note.** The prompt summarises test 4 as "preserve the genuine rule despite a negated qualification". The Phase 2I specification the test reproduces is the **inverted-qualifier** case: a claim of "batches that conform" must not be credited. The test follows the Phase 2I specification.

## 2. Baseline: the current evaluator

**Before any change:** 1832 passed, 1 skipped (`pytest -q tests/ -rs`).

**On the seven tests (raw run, `--runxfail`): 3 fail and 4 pass.**
- **RC1:** `'polarity' not in ['polarity']`. The relative-clause "that do not meet" makes 213.122(e) read as a negated rule, so a correct, narrower claim is contradicted.
- **RC2:** `'polarity' in []`. The claim's "that does not meet" and the rule's "must not" both read as negated, so "must use" vs "must not use" *agree*.
- **RC3:** `'polarity' in []`. The same mechanism: "shall be declared" vs "shall not be declared" agree, and the claim is credited as paraphrase support.
- **RC4–RC7** pass, but only because the inverted qualifier's "not" happens to create a polarity mismatch. Phase 2I showed that protection is accidental.

## 3. Offline candidates

All candidates are copies of the **current** production package in `work/variants/`, built by `work/make_variants_j.py` on the Phase 2I code. Production was never edited.

| Candidate | What it does |
|---|---|
| **J0_identity** | the patch scaffolding with no rule enabled (harness check; reproduces production exactly) |
| **JBQ** | Phase 2I's BQ: (a) a negation directly after *that/which/who*, outside a complement clause, does not set the duty's polarity; (b) a **qualifier check**: the same relative-clause verb on both sides with opposite negation is a `qualifier_polarity` conflict |
| **JBQP** | JBQ + a narrow extension. The qualifier check also reads a qualifier stated without a relative pronoun: a noun followed by a participle ("levels **exceeding**"), its negation ("not exceeding"), and "without …ing". Prepositional participles (including, following, using …) are excluded. Verb forms are matched by a key that strips -ing/-s/-es (the shared stemmer reduces "exceed" to "exce" and cannot be used), allowing a prefix difference of up to 2 letters. |
| **JBQP2** | JBQP with **one** narrowing refinement after JBQP produced false conflicts: verb forms must be morphologically **identical** (or differ only by a final "e"; no prefix similarity), and an "-ly" adverb is skipped to reach the clause's verb. |

No blanket rule ignores relative-clause negation, no sentence-local processing is used, and lexical overlap is never treated as agreement.

## 4. Results

### 4.1 Comparison across all measures

| Measure | Production / J0 | JBQ | JBQP | **JBQP2** |
|---|---|---|---|---|
| Seven tests, claim level (`--runxfail`) | 4/7 | 6/7 (RC6: **false support**) | **7/7** | **7/7** |
| Phase 2I real-text checks (15) | 9 | 13 | 14 | 14 (the miss, T3c, is the semicolon case, outside the seven) |
| False supports or partials on real text | 2 (RC2, RC3) | 1 (RC6/T5a) | 0 | 0 |
| False polarity conflicts on real text | 4 | 1 (T3c) | 1 (T3c) | 1 (T3c) |
| Original 33 relative-clause cases removed | 0 | 33 | 33 | 33 |
| Other 45 remaining false conflicts changed | — | 0 | 0 | 0 |
| Genuine-contradiction tests (19) / reading tests (6) | 19 / 6 | 19 / 6 | 19 / 6 | 19 / 6 |
| Real-negation preservation pairs (44) / invented-condition (18) | 44 / 18 | 44 / 18 | 44 / 18 | 44 / 18 |
| New conflicts, replay of all 2,105 recorded comparisons | 0 | 1 (H-006 noun unmasked, known) | **3**: H-006 + **2 false `qualifier_polarity`** (D-004, D-007) | 1 (H-006, known) |
| Claim / answer / score / dimension changes over the 170 frozen row-runs | 0 | 0 | 0 | 0 |
| F-007, F-009, all Phase 2D decisions | unchanged | unchanged | unchanged | unchanged |
| Full suite + seven tests, `--runxfail` | 1837 passed, 3 failed | 1839 passed, 1 failed | 1840 passed | 1840 passed |

**JBQP's false conflicts.** The claims "the consultant requirements include **tamper-evident packaging** requirements" (D-004) and "Tamper-evident **packaging** requirements … shall be established" (D-007) were matched to 211.132's "that **is not packaged** in a tamper-resistant package". The **noun** "packaging" was read as a participle qualifier, and the loose prefix matching equated "packag" with "packaged". JBQP2's exact matching removes these two instances. It does not remove the underlying misreading.

### 4.2 False-support and false-contradiction analysis

- **Production today:** two false credits (RC2 false partial, RC3 false support) and four false polarity conflicts on real text, three of which make the claim CONTRADICTED (213.122(e), 211.115(a), 606.65(d)).
- **JBQ** fixes all of those but credits a claim that inverts a qualifier phrased without a relative pronoun (RC6).
- **JBQP2** introduces no false support on any test or control. Every genuine contradiction stays detectable (19/19, RC2, RC3, RC4–RC7).

### 4.3 Why JBQP2 is not called SAFE: a precision check of its qualifier reader

**What the reader extracts** (`work/participle_extraction.json`):
- From the 376 frozen claim texts, the participle reader extracts 50 distinct "qualifiers". Most are **"-ing" nouns or gerund objects**: "tamper-evident packaging", "stability testing", "expiration dating", "good manufacturing", "include sampling", "air heating". Only a minority are real qualifiers: "hazards requiring", "records documenting", "procedures describing", "specifications impacting".
- The 996 corpus sentences are similar: "device labeling", "informal hearing", "per serving", "committee meeting", next to real ones like "product containing" and "feeds bearing".

**Cross-pair probe** (`work/qualifier_probe.json`): all 376 frozen claims × all 996 real negated-relative corpus sentences, **374,496 pairs**.
- **JBQ raises 261 `qualifier_polarity` conflicts.** 60 rest on the "verb" `the`, from "that is **not the** subject …" in the evidence and "that **the** drug products …" in the claim. That is an extraction defect in Phase 2I's BQ prototype itself.
- **JBQP2 raises 282.** On top of the same 60 `the` cases, misread keys include `manufactur` (42, "good manufacturing"), `heat` (8), `identify` and `conduct` (6 each, gerund objects of "include").

These probe pairs are unrelated sentences, so here they are noise. But the same misreading against a claim's **stating** passage would be a **false contradiction**, the harm Phases 2F–2G removed for H-003. JBQP showed it happening on real frozen claims (D-004, D-007). JBQP2 only removed those two instances.

**The core limitation is architectural.** Telling a participle qualifier ("levels exceeding") from an "-ing" noun ("packaging requirements") needs part-of-speech or syntactic information that the evaluator does not have. A regex cannot draw that line reliably, and adding further exclusion lists would be exactly the escalating heuristics this phase was told to avoid. The relative-clause half (JBQ) is more principled, but it carries its own determiner defect (`the`) and misses non-relative inversions.

## 5. Frozen-row and Phase 2D regression

**Every candidate changes zero claim verdicts, zero answer verdicts, zero scores and zero dimension states** across all 170 frozen row-runs (`work/h_cf_*.json`, `cf_diffs.json`). Each was a full re-run under both aligners. F-007, F-009 and every Phase 2D content-gate decision are unchanged. **All 240 content-gate tests pass** under every candidate (they are part of the full suite).

As Phase 2I showed, unchanged frozen verdicts do not prove the claim-level logic is right, because this mechanism changes no frozen verdict in production either. That is why the real-text tests and the precision probe carry the decision.

## 6. Full-suite results (production logic, unchanged)

| Command | Result |
|---|---|
| `pytest -q tests/test_accuracy_relative_clause.py` | 5 passed, 3 xfailed |
| `pytest -q tests/test_accuracy_relative_clause.py --runxfail` | 5 passed, **3 failed** (RC1, RC2, RC3, as in §2) |
| Relevant files: contradiction_scope 8, claims 41, guidance_logic 29, content_gate 240, claim_extraction 35, citation_grounding 19, relevance 67, evaluation 31 | all passed |
| `pytest -q tests/ -rsx` | **1837 passed, 3 xfailed, 1 skipped, 0 failed** (47 deselected) |

The skip is pre-existing (`tests/test_dashboard_health.py:576`, "no current evaluation in this repository"). There are **no new failures**: the only non-passing results are the three documented xfails.

## 7. Remaining uncertainty and limitations

- **Constructed claims.** The seven tests use verbatim evidence but constructed claims. No real answer in the frozen data inverts a qualifier, so the risks are demonstrated rather than observed in production answers.
- **Legacy evidence.** The 33 frozen cases are on legacy-reconstructed evidence; there are no exact prompt-evidence snapshots for these rows.
- **Probe scope.** The probe pairs are unrelated sentences, so they measure how often the reader misfires, not the false-contradiction rate on stating passages. That rate is **unmeasured**.
- **Untested shapes.** T3c (a semicolon-joined rule) and claims that invert a qualifier in other forms ("free of", "non-…") were not tested.
- **Shared stemmer.** It reduces "exceed" to "exce". The candidates use their own verb key; production code does not have one.

## 8. Recommended next step (not started)

1. Decide whether the evaluator may use a **part-of-speech or dependency parse** for qualifier detection. That is an architectural decision, not a heuristic, and it is the only route seen here that can separate participle qualifiers from "-ing" nouns.
2. If not, restrict any qualifier check to **relative clauses on both sides**, fix the determiner defect, and accept, with a documented `xfail`, that a non-relative inversion like RC6 is not caught.
3. Either way, add the precision probe as a measured gate: the qualifier reader's extractions from real claims, hand-labelled. The seven tests stay as they are.

## 9. Changes made and verification

| Item | Result |
|---|---|
| New files | `tests/test_accuracy_relative_clause.py`, `tests/fixtures/accuracy_relative_clause_rows.json` |
| `src/` | **identical** by SHA-256; the accuracy package matches the pre-phase snapshot (`work/snapshot_before/`) |
| Existing tests, fixtures, benchmark questions/answers, frozen inputs, rubric, scoring | unchanged (manifests `work/*manifest_*.sha256`; only the two new files were added) |
| Phase 2D gate | untouched |
| Git status | 62 → **63** lines; the only new line is `?? tests/test_accuracy_relative_clause.py` (the fixture falls under the already-untracked `tests/fixtures/`) |
| Database | read-only, SELECT only (no new queries this phase; Phase 2I corpus outputs reused) |
| 300-question benchmark / production implementation | not run / not done |

## Artifacts (`work/`)

- `make_variants_j.py` → `variants/{J0_identity, JBQ, JBQP, JBQP2}`.
- Evaluation: `eval_real_controls.py` → `real_controls_*.json`; `eval_controls_h.py` → `controls_result_*.json`; `collect_h.py` / `diff_cf.py` → `h_cf_*.json`, `cf_diffs.json`.
- Precision checks: `participle_extraction.json`, `qualifier_probe.json`.
- State: `snapshot_before/`, `manifest_*.sha256`, `benchmark_manifest_*.sha256`, `git_status_*.txt`.
