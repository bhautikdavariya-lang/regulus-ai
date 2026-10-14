# Stage A: two-sentence window gate. NOT APPLIED

Date: 2026-10-13. Production evaluator unchanged (`verdicts.py` sha fc69001c…). Nothing committed; the
frozen benchmark was not run; no generation was run.

## Decision

The candidate (`candidate_window_gate_NOT_APPLIED.diff`) would accept a window when each sentence carries ≥ 3 of
the claim's core terms that the other lacks. Measured on the evidence below, it **cannot preserve existing
safeguards**. The brief's stop condition applies, so the change was not applied.

## What was established

### 1. On frozen data the threshold is inert (verified)

`work/window_census.py` re-scored stored answers offline, with no generation: F60 + GUIDE8 + REAL17 under both
aligners, plus the frozen rows in the test fixtures. That is 274 row-runs and 6,288 `judge_window` calls.

Only 8 distinct windows reach the verbatim-run gate:

| window | today | runs (S1/S2) | own-terms | at threshold 3 |
|---|---|---|---|---|
| F-004 grounds | accepted | 11 / 5 | 5 / 3 | accepted (unchanged) |
| G-004 Drug Facts type size | accepted | 12 / 20 | 3 / 3 | accepted (unchanged) |
| D-009 "charge-in of components" | rejected | 19 / 1 | 9 / **2** | rejected; **a threshold of 2 would admit this false support** |
| D-007, D-009 records, D-008, H-001, F-003 | rejected | ≤ 4 | min ≤ 1 | rejected |

Threshold 3 is therefore supported by both sides: real positives have min own-terms 3, and real negatives have at
most 2. The margin is thin (one term), and the frozen set contains no paraphrased two-sentence positive.

### 2. On constructed cases the candidate admits fabrications (verified)

`work/window_cases.py` uses the verbatim 211.192 text and the lexical aligner, comparing `judge_window` with the
full claim verdict:

| case | current | candidate |
|---|---|---|
| P1 correct S2+S3 paraphrase | unverifiable | **supported** ✔ |
| P2 near-verbatim merge / P3 S3+S4 merge / P4 quarantine (condition kept) | supported | supported |
| N1 merged claim + fabricated "within 30 days" | unverifiable | **supported ✘** |
| N2 merged claim, duty reassigned to "FDA" | unverifiable | **supported ✘** |
| N6 merged claim narrowed to "only … not distributed" | unverifiable | **supported ✘** |
| N3 extra unsupported duty ("reported to FDA within 15 days") | unverifiable | unverifiable |
| N4 negation / N5 weakened modal | contradicted | contradicted |
| N7 F-007 shape (one sentence carries, other adds terms) | unverifiable | unverifiable |
| N8 omitted "if it fails specifications" condition | supported ✘ (single-sentence path) | supported ✘ (unchanged) |

### 3. Why: the paraphrase judge itself has the gaps (verified, pre-existing, new finding)

`work/single_sentence_probe.py` tested one-sentence answers on **current production code** (no window involved),
using the focused 211.192 question:

| answer | evaluator only | production pipeline |
|---|---|---|
| faithful S2 | supported | PASS 100 |
| "FDA must thoroughly investigate …" | supported | **PASS 100** (false pass) |
| "Only a failure of a batch that has not been distributed … must be investigated" (contradicts "whether or not distributed") | supported | **PASS 100** (false pass) |
| "… must be thoroughly investigated within 30 days" | supported | FAIL 0: validation withheld it before delivery |

The judge has no actor-substitution check, no restrictive-scope ("only/solely") check, and no evaluator-side check
for a period that is absent from the evidence. For merged claims, the 5-word verbatim run is the only thing hiding
these gaps. Relaxing it simply extends the gaps to windows.

A clause-split alternative (`work/clause_probe.py`: judge each ", and" clause separately) does not help. The
single-sentence judge accepts the N1/N2/N6 clauses as well.

### 4. Why the broad cells moved FAIL 40 → PASS 100 in the earlier report (step 5)

The merged answer covers S2–S4 and omits S1, the QCU review-before-release obligation.

- On "What does 21 CFR 211.192 require?" (synthesis), PASS 100 would be a **false pass**. It arises only because
  completeness treats the one-paragraph section as a single unit (Stage B). Cell 1b (verbatim S2–S4) already
  shows PASS 100 on current code for the same reason.
- On "What are the investigation requirements under 21 CFR 211.192?" (focused), S2–S4 is complete for the
  question's scope. S1 is not an investigation requirement, so PASS 100 there would be legitimate.

## Regression tests added

`tests/test_accuracy_window_support.py` uses the fixture `tests/fixtures/accuracy_211_192_rows.json` (verbatim,
sha 623102…48ad):

| test | current code | candidate |
|---|---|---|
| near-verbatim two-sentence merge supported | pass | pass |
| correct two-sentence paraphrase supported | strict xfail | XPASS (intended) |
| F-007 shape not window support | pass | pass |
| merged claim with fabricated period / actor / narrowed scope not supported (3) | pass | **fail ×3** |
| partial support not full support | pass | pass |
| negation / weakened modal contradicted (2) | pass | pass |
| single-sentence FDA actor / narrowed scope / unstated period (3) | strict xfail (pre-existing gaps) | strict xfail |
| unstated period withheld by the pipeline | pass | pass |
| complete verbatim broad answer passes | pass | pass |
| merged answer to the focused question is evaluated (was NOT EVALUATED) | strict xfail | XPASS |
| broad answer omitting S1 does not pass | strict xfail (Stage B) | strict xfail |

These tests prove two things. The safeguards a window change must keep are now locked: three tests fail under the
candidate. The wanted behaviours are recorded as strict xfails, so any change to them shows up immediately. The
existing test 13b (F-007) is retained unchanged.

## Recommended sequence (for review)

1. Add three narrow judge checks, each blocking support and never contradicting:
   - an actor named in the claim that differs from the evidence's actor (including a passive regulated-party duty
     restated as FDA's);
   - a restrictive qualifier ("only", "solely", "limited to") absent from the evidence;
   - a figure or period absent from the evidence.
   Each closes a verified PASS-100 false pass on its own.
2. Then re-measure the own-terms window alternative against `test_accuracy_window_support.py` and the census.

## Remaining (unchanged by this stage)

| Case | Status |
|---|---|
| Focused merged 211.192 answer | NOT EVALUATED |
| Focused verbatim S2–S4 answer (S4 judged off-topic in isolation) | FAIL 55 |
| Paraphrased S4 | unverifiable (FAIL 40) |
| Pronoun-led claims | FAIL 40 |
| Single-sentence FDA actor and narrowed scope | false PASS 100 |
| N8 omitted condition | false support |

## Commands and results

- `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_accuracy_window_support.py` → 10
  passed, 6 xfailed. On the candidate copy: 5 failed (3 safeguards, 2 strict XPASS), 7 passed, 4 xfailed.
- `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_accuracy_*.py
  tests/test_answer_value_plan.py tests/test_ind_safety_deadlines.py` → **745 passed, 10 xfailed**.
  The 735 earlier passes plus the 10 new passing tests.
