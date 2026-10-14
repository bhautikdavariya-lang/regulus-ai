# Broad-synthesis completeness false PASS

**Outcome.** Fixed and measured. "What does 21 CFR 312.32 require?" answered with (c)(1) alone no longer gets
PASS 100. On 40 named sections answered completely (every top-level obligation, verbatim) and with one
obligation left out (143 answers), incomplete answers that are not a full PASS rise from **6 / 143 to 132 / 143**,
and all **40 / 40** complete answers still pass. Across the 299 recorded acceptance answers two scores change,
both hand-scored N=0 O=0. No rendered prompt changes (0 / 314). The rubric and citation policy are unchanged.
Evaluation correctness only; no accuracy claim about generated answers.

## 1. Root cause

Traced on the production path: `serve_ui.Engine`, with only the model's output scripted
(`work/engine_harness.py`, `work/trace_broad.py`).

| step | "What does 21 CFR 312.32 require?", answered with (c)(1) |
|---|---|
| plan | `synthesis`, not exhaustive; requirement groups (a), (b), (c), (d) |
| evidence | 14 of 25 rows. The question has no words to rank paragraphs by, so selection keeps document order, and the hard ceiling drops **(c)(2) (the 7-day rule), (c)(1)(iii)–(v), (c)(3)–(5), (d)(1)–(3), (e)**. Group (d) is only its heading row, "(d) Followup." |
| post-processing | `shape_validation` §4 flags (a), (b), (d) as uncovered, and repair appends each group's **head row** — for (d), the bare heading "(d) Followup. [14]", which states no obligation. The re-check is then clean |
| claims | all 14 *supported* |
| completeness | **PASS** — "the statements that answer the question cover what it asks for". The evaluator had no completeness check for a synthesis; it relied on the pipeline's group coverage |
| verdict | **correct, PASS 100** |

When every paragraph is in the evidence (the verbatim fixture), a second leak gives the same result: the
pipeline's group test counts a group as present if **any** member is cited, named, word-matched or
cross-referenced. (c)(1) "covers" (c)(2), its sibling inside group (c). (d)(3) "covers" itself because the
answer mentions "paragraph (c)", which (d)(3) cross-references.

**Where an incomplete answer gets PASS 100:** `evaluator._evaluate`'s completeness dimension for a synthesis,
which passes any answer whose statements are supported. Three facts feed it: the ceiling withholds the
provision's obligations, and nothing tells the evaluator; repair satisfies a group with a bare heading; and
group coverage accepts any member. Measured on 40 sections, the false-PASS class is systemic: production
passes **137 of 143** answers that omit a top-level obligation.

**Confirmed pre-existing.** The previous task already recorded this false PASS as a strict xfail, verified on
the evaluator from before that task. This task's matrix shows the same PASS 100 on the code as it stood at the
start (`work/matrix4.json`, production column).

## 2. Before / after

### Matrix (`work/matrix.py`; F = verbatim fixture through the production configuration, P = production database through `Engine`)

| case | before | after |
|---|---|---|
| F1 broad, (c)(1) only (repair adds (a), (b)) | PASS 100 | **FAIL 75** — misses (c)(2), (d)(1)–(3) |
| F2 broad, complete | PASS 100 | PASS 100 |
| F3 broad, missing the 7-day rule | PASS 100 | **FAIL 75** — misses (c)(2) |
| F4 broad, missing follow-up | PASS 100 | **FAIL 75** — misses (d)(1)–(3) |
| F5 focused 7-day, correct | PASS 100 | PASS 100 |
| F6 focused 7-day, starting event dropped | FAIL 55 | FAIL 55 |
| F7 focused 7-day, wrong deadline | FAIL 0 | FAIL 0 |
| F8 focused follow-up, correct (known false fail) | FAIL 75 | FAIL 75 (unchanged, still tracked) |
| F9 211.25 focused: (c) only / (a) only / all three | FAIL / FAIL / PASS | unchanged |
| F9d "What does 211.25 require?", (c) only, completed by repair | PASS 100 | PASS 100 |
| **P1 broad, (c)(1) only, production evidence** | **PASS 100** | **NOT FULLY EVALUATED 95** — 11 obligations withheld |
| P5 focused 7-day, production evidence | PASS 100 | PASS 100 |

### Named-section population (`work/population.py`)

40 sections drawn at random (seed 13) from the snapshot: all rows fit, at least two top-level obligations.

| | complete: full PASS | one obligation left out: **not** full PASS |
|---|---|---|
| before | 40 / 40 | 6 / 143 |
| after | 40 / 40 | **132 / 143** |

### Real answers (production engine, greedy; six questions, each generated once, assessed both ways)

| question | before | after |
|---|---|---|
| What does 21 CFR 211.25 require? | PASS 100 | PASS 100 |
| What does 21 CFR 111.12 require? | PASS 100 | PASS 100 |
| What does 21 CFR 117.40 require? | PASS 100 | PASS 100 |
| What does 21 CFR 312.32 require? | FAIL 75 | FAIL 75 |
| What does 21 CFR 211.67 require? | FAIL 40, completeness *pass* | FAIL 15, completeness **fail**: never states (c), "Records shall be kept of maintenance, cleaning, sanitizing, and inspection" — a genuine omission |
| What does 21 CFR 820.10 require? | FAIL 40, completeness *pass* | FAIL 35, completeness **not established**: (b)(2), (b)(3) addressed only by unverifiable paraphrase |

### Recorded answers

All 299 recorded answers were re-scored on current production packages, without generation:

| id | hand | before | after |
|---|---|---|---|
| NC-013 (part 1250) | N=0, O=0 | FAIL 50, completeness pass | FAIL 25, completeness **fail** |
| NC-018 (part 830) | N=0, O=0 | FAIL 0, completeness pass | FAIL 0, completeness **fail** |

No other score changes. **Power caveat:** only 4 of the 147 recorded synthesis answers name a provision, and only
those two reach a completeness PASS. The other synthesis answers are general questions that name no provision,
whose evidence is a search sample. The check does not apply to them, and their own completeness false PASSes
(e.g. B-002, hand O=0, PASS 100) are a different problem, untouched here. That is why the 40-section population
was built: the recorded answers cannot test this rule.

`accuracy_validate.py` (120 rows): identical, 0 rows changed. Its package shim carries no answer plan, so it
cannot see plan-based completeness checks; it is reported as a check that nothing else moved.

## 3. Fix

`src/regulus/accuracy/evaluator.py` (+95 / −1): `_synthesis_gap()`, applied after `_focus_gap`. It runs only for
a **synthesis of a named provision**. Its unit is a **top-level obligation** of the requested provision: a
source stating a mandatory requirement that is not a subparagraph of another source that does. A list under an
obligation is its detail, not further units, so the check asks for the provision's obligations, not every
paragraph.

An obligation counts as **represented** if either:
- a statement was verified against it, or
- the answer reproduces it: a verbatim run of at least 8 words (all of it if shorter) covering at least 60 % of
  its words. Text that repair appends counts; a shared stock phrase does not.

Three further rules:
- A lead-in ("Labeling must include:") is represented when it or any of its items is.
- A bare heading states no obligation and never stands in for one.
- An obligation that only unverifiable statements touch is *not established*, not *missing*, as in `_focus_gap`.

Outcome, applied only to an existing completeness PASS, which it can only withdraw:
- an unrepresented obligation → **FAIL**;
- otherwise, only-unverified obligations → **NOT ESTABLISHED**;
- otherwise, obligations of the provision **withheld by the ceiling** → **NOT ESTABLISHED**, because the
  evaluator cannot judge completeness against text it never saw.

`src/regulus/rag/generation.py` (+8): `GenerationPackage.withheld` holds the requested provisions' own EXACT rows
that the hard ceiling dropped, as (citation, text). It is **never rendered**: 0 of 314 prompts change, and a
test asserts the withheld text is absent from the prompt. The evaluator reads it through the evidence wrapper
like the package's other attributes.

**Considered and rejected:**
- **T alone** (withheld → not established): fixes the production case, but cannot see anything when the
  section fits, so F1, F3 and F4 still pass.
- **Group-level coverage (G, G2, G3):** G used the aligned source, which mis-assigns near-identical paragraphs
  — 211.25(b) aligned to (a) — and broke the protected repaired-synthesis case. G2's verbatim run of 8 words
  was fooled by the stock phrase that (c)(1) and (d)(3) share. G3 fixes that but, being group-level, cannot
  see (c)(2) missing beside (c)(1): 91 / 143.
- **The first unit rule:** wrongly failed 4 of 40 complete answers, all short lead-ins ("(c) You must
  either:"). That led to the full-length and lead-in rules above.
- **Changing repair, or selection, for this question:** not done. They would change delivered answers, which
  this evaluation-correctness task does not need.

## 4. Regression protection

| suite | result |
|---|---|
| `tests/test_accuracy_completeness_synthesis.py` (new) | **19 passed**. On the pre-change code: **13 fail** — every defect test and the unit tests — and **6 pass**, the controls that must hold either way |
| `tests/test_accuracy_completeness_focus.py` | the strict xfail recording this defect **flipped** and is now an assertion; the follow-up xfail is unchanged |
| full unit suite | **2,120 passed**, 1 skipped, 4 xfailed |
| protected — content gate, contradiction scope, numeric limits, relative clause, pass integrity, claims, relevance, answer validation, answerability, citation grounding, definition, evaluation, claim extraction, guidance logic, question review, observer, IND deadlines, completeness focus and synthesis, answer shape, generation contract, value plan | **872 passed, 4 xfailed** |
| DB integration (not slow) | **41 passed** |
| real model (`slow and integration`): IND deadline generation + `tests/integration/test_synthesis_completeness_live.py` (new) | **21 passed** |
| `accuracy_regression.py`: 312.32 synthesis, focused 7-day, 211.25 synthesis | **exact evidence PASS, payload PASS, live PASS** — byte-identical ON/OFF |

Not run: the frozen benchmark. `test_rag_slow::test_rag_end_to_end_one_question` is still the pre-existing
failure at 4828.

## 5. Safety analysis

* **Focused questions are untouched.** The check returns `None` unless the plan is a synthesis of a named
  provision. The focused seven-day, follow-up and 211.25 cases are unchanged, and a test asserts the focused
  seven-day answer is not asked for the section.
* **Completeness is not weakened.** The check only re-examines an existing completeness PASS and can only turn
  it into FAIL or NOT ESTABLISHED. It never grants a pass and never touches another dimension.
* **Not "every paragraph".** Detail under an obligation is not a unit; definitions and headings are not
  obligations. A complete answer to all 40 sampled sections, and complete real answers to three, still pass.
* **Repair is still credited.** Verbatim text it appends represents an obligation. The 211.25
  repaired-synthesis protection holds.
* **Withheld evidence lowers confidence, not the verdict.** It makes completeness *not established*, never
  *fail*: the answer may be complete, but the evaluator did not see enough to say so.
* **Contradiction, negation / modality, numeric, citation, relevance and scope checks** are not modified, and
  their suites pass.

## 6. Remaining limitations

* **11 of 143 omissions still pass**, mostly where the dropped obligation's words also appear in another
  paragraph the answer reproduces.
* **Paraphrase:** a correct but unverifiable paraphrase of an obligation yields NOT ESTABLISHED, not PASS (as for
  820.10). Seen on 1 of 6 real answers; the base rate is not measured.
* **General questions naming no provision** are outside the check. Their completeness false PASSes (e.g. B-002)
  remain.
* **Part-level questions:** the check applies, and the ceiling withholds many sections, so most
  "What does part X require?" syntheses can no longer be a full PASS. Only two recorded examples exist, both
  hand O=0; real complete part-level answers were not tested.
* **Still tracked as strict xfails, not fixed here:** the focused follow-up false failure ("follow-up" vs
  "followup").
* **Recorded, not fixed:** the adjacent-sentence window never granting partial credit, and a dangling lead-in
  ("…such as:") that absorbs the next sentence. The latter turned a complete constructed answer with (c)(1)(i)
  into FAIL 0 (matrix F2x).
* **Selection** still drops (c)(2) and (d)(1)–(3) for "What does 21 CFR 312.32 require?". The answers are no
  more complete; the evaluator now says so.

## 7. Change inventory

* Changed: `src/regulus/accuracy/evaluator.py` (untracked package; diff against the task-start copy) and
  `src/regulus/rag/generation.py` (already modified by earlier work; only this task's +8 lines added). Exact
  diff: `change.diff`.
* New: `tests/test_accuracy_completeness_synthesis.py`, `tests/integration/test_synthesis_completeness_live.py`.
  Updated: `tests/test_accuracy_completeness_focus.py` (flipped xfail → assertion).
* Byte-identical to the task start: `shape_validation.py`, `pipeline.py`, `answer_plan.py`, `operators.py`,
  `answer.py`. No config, script, rubric, citation policy, benchmark, acceptance dataset or historical result
  touched. The tracked-modified set is still 35 files.
* The frozen benchmark was not run. Nothing committed.
