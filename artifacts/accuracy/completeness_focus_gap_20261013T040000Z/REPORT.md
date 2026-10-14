# Completeness of focused answers: the follow-up over-requirement

**Outcome.** Fixed by two small, additive evaluator changes (+90 / −0 lines), both measured before
adoption. A correct answer to the focused seven-day question now passes. An answer that drops when the
seven-day clock starts now fails for that reason instead of an unrelated one. Every completeness
protection measured holds. Across 299 recorded answers one score changes, toward its hand score. Two
pre-existing defects found on the way are pinned as strict xfails and left unchanged. The rubric and the
citation policy are unchanged.

## Step 1 — baseline (production evaluation package)

Question: "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse
reaction under 21 CFR 312.32?" Live answer (production engine, greedy): "… is no later than 7 calendar days
after the sponsor's initial receipt of the information [9]." Evaluated: verdict **correct**,
completeness **fail**, score 75: *"the answer does not address 21 CFR 312.32(d), which states a requirement
on it"*.

`evaluator._focus_gap` was traced through a line-for-line copy, asserted equal to the production function on
every call (`work/harness.py`):

| group | decision |
|---|---|
| (a) definitions | states no obligation |
| (c) | covered — the answer's claim was decided on SOURCE 9, (c)(2) |
| **(d) follow-up** | **demanded**: (d)(3) carries *report, suspected, adverse, reaction* = 4 of the question's 8 topic words, exactly the on-topic threshold (4) |

All four of those words also occur in (c), the covered group. The words that say *which* deadline is meant —
*unexpected, fatal, life-threatening* — occur in (c) alone.

**Root cause.** The focused completeness check demands every obligation-bearing top-level group of the
provision that shares enough of the question's words. Words the provision uses everywhere are counted as
evidence that a group is what the question asks about. It surfaced when Priority 1 added (d)(3) to this
question's evidence. The same answer had scored PASS 100 in the IND task.

## Step 2 — measurement before any production edit

**`accuracy_validate.py` cannot see the focused completeness check at all.** Its package shim carries no
answer plan (`answer_plan = None`), so `_focus_gap` returns `None` on every row. It was still run to confirm
nothing else moves, and four dedicated measurements were built on **production packages**
(`work/harness.py`): the real retrieval, selection and package, with focused plans and section headings.

1. **Fixtures** (`work/fixtures.py`): 17 cases, answers built from verbatim regulation text or the live answer.
2. **Recorded answers** (`work/rescore_all.py`): all 299 recorded acceptance answers (hand-scored once under
   `regulus_substantive_rubric_v1`) re-scored against current production packages. The markers may not match
   the current numbering, but both rules see identical inputs.
3. **`accuracy_validate.py`**, 120-row sample, with and without the candidates.
4. **Every protected test suite and the full unit suite** with the candidates patched in (`work/candidate_plugin.py`).

### What the measurements changed

* The first candidate compared the question's words across **all** obligation-bearing groups. The
  table-backed test exposed that an unrelated group decided the outcome: 21 CFR 312.32(b), "Review of safety
  information", lacks *suspected / adverse / reaction*, so with it in the evidence those words became
  "distinguishing" and (d) was demanded again. **Restricted to on-topic groups**, the rule no longer depends on
  which unrelated groups are present. Every measurement below was re-run on the final rule.
* The focus-gap change alone turned an answer that **drops the seven-day trigger** — "… no later than 7 calendar
  days" without "after the sponsor's initial receipt of the information" — from FAIL to **PASS 100**. The old
  FAIL had been an accident: it failed the correct answer identically. Nothing compared a time limit's anchor:
  `numeric_limits` returns nothing for "no later than 7 calendar days after …", and no omission was recorded.
  A narrow claim-level check closes that gap, so the focus-gap change does not create a false PASS.

### Results (final rule)

| measure | pre-change | implemented |
|---|---|---|
| correct seven-day answer, live and verbatim (fixture) | FAIL 75 | **PASS 100** |
| seven-day answer dropping the trigger (fixture) | FAIL 75 (unrelated reason) | **FAIL 55**, claim partially supported for the dropped event |
| wrong deadline: 15 days for the fatal / life-threatening category | FAIL 0 | FAIL 0 |
| 211.25 personnel — (c) only / (a) only / all three (the case the check was built for) | FAIL / FAIL / PASS | FAIL / FAIL / PASS |
| follow-up questions answered without (d), two wordings | FAIL | FAIL |
| broad focused "IND safety reporting requirements", (c) only | FAIL | FAIL — every topic word is shared, so the rule is unchanged |
| focused recorded answers where the focus gap demands a group | 12 of 122 (11 hand O=0, 1 O=2) | **the same 12** |
| all 299 recorded answers: scores changed | — | **1**: U-010 correct (100) → partial (40), hand **N=1, O=0** |
| `accuracy_validate.py`, 120 rows | ρ 0.627, 0 false highs, 35 scored | **identical**, 0 rows changed |
| protected suites with candidates patched in | 710 passed, 3 xfailed | 710 passed, 3 xfailed |

**False completeness failures on correct narrow answers:** the seven-day case is fixed. The follow-up case is not
(below). **False PASS on incomplete answers:** none introduced. The trigger-dropping answer now fails for the
right reason, and the 11 recorded answers the check correctly fails still fail. **Broad questions:** unchanged.
**Follow-up questions:** answers missing (d) still fail.

**U-010** — "within what timeframe must a labeler submit to GUDID": the answer says the labeler must respond
"within 30 days", while 21 CFR 830.350(a) says "within 30 days **of receipt of FDA's notification**". It was
scored correct (100) and is now partial (40), which matches the hand rubric (N=1, O=0).

## Step 3 — the change

`src/regulus/accuracy/evaluator.py` (+42 / −0):

* `_distinguishing_topic_terms()`: among the provision's **on-topic**, obligation-bearing requirement groups,
  the question's topic words that some carry and others do not. Empty when there are fewer than two such groups
  or none differ, and then `_focus_gap` behaves exactly as before.
* `_focus_gap()`: a group is demanded only if, in addition to today's tests, it carries a distinguishing word
  whenever there are any. It can only *stop* demanding a group, and only when the question's own words say it
  is about another one.

`src/regulus/accuracy/operators.py` (+48 / −0):

* `dropped_time_anchor()` and `OMISSION_TIME_ANCHOR`. When a claim states a time **limit** ("no later than",
  "within", "not more than", "by" …), its evidence states the **same** period anchored to an event ("after",
  "of", "from" …), and the claim gives **no** anchor, `compare()` records an omission. An omission is never a
  conflict: by the existing verdict ladder the claim is at most partially supported. A paraphrased anchor is
  accepted unread, and a period used as a label ("the 7-calendar-day deadline") is not a limit.

Exact diff: `change.diff`.

## Step 4 — tests

`tests/test_accuracy_completeness_focus.py` (new, 18 tests + 2 strict xfails). Verbatim 21 CFR 312.32 is served
through the real plan, retrieval, package and validator on the production configuration.
`tests/fixtures/accuracy_312_32_rows.json` (new) carries the snapshot date and content hash per paragraph.

1. correct seven-day answer → PASS 100; (d) not demanded
2. seven-day answer dropping when the clock starts → FAIL, with the claim's reason naming the dropped event; the
   same trigger in other words is not called dropped
3. broad focused question → (d) still demanded; whole-section question → synthesis, completed by the pipeline
4. follow-up question answered without follow-up → FAIL, (d) demanded
5. comparison of both deadlines → both supported, (d) not demanded; reversed deadlines still contradicted
6. the anchor check: seven parametrised claims, no anchor asked of an unanchored period, an omission never a conflict

`tests/integration/test_ind_deadline_generation.py`: the strict xfail from Priority 2A, which recorded this
defect on the live answer, **flipped** and is now an assertion that the live seven-day answer is PASS 100.

| suite | result |
|---|---|
| full unit | **2,100 passed**, 1 skipped, 5 xfailed (+18 tests; xfails: 3 relative-clause + 2 new strict) |
| protected — content gate, contradiction scope, numeric limits, relative clause, pass integrity, claims, relevance, answer validation, answerability, citation grounding, definition, evaluation, claim extraction, guidance logic, question review, observer, IND deadlines, completeness focus | **734 passed, 5 xfailed** |
| DB integration | **41 passed** |
| real model (`slow and integration`, IND deadline generation) | **17 passed** |
| `accuracy_regression.py`: seven-day, follow-up, 211.25 | **exact evidence PASS, payload PASS, live PASS** — byte-identical ON/OFF |

Not run: the frozen 300-question benchmark. `test_rag_slow::test_rag_end_to_end_one_question` is still the
pre-existing failure at 4828.

## Unexpected findings, all reported, none changed

1. **False PASS in the synthesis path (pre-existing).** "What does 21 CFR 312.32 require?" answered with (c)(1)
   alone is completed by the pipeline with (a) and (b) but **not (d)**. The 7-day rule is never stated, yet the
   answer is assessed **PASS 100**. Verified identical on the pre-change evaluator (a temporary copy of `src/`
   with the task-start files). The focus gap does not judge synthesis answers. Strict xfail.
2. **False completeness failure on a correct follow-up answer (pre-existing, unchanged).** The question's
   "follow-up" does not match the regulation's "followup", so the only word that tells the groups apart is
   *after*, which (c)(1) also contains ("15 calendar days after the sponsor determines"). (c) is demanded of an
   answer about follow-up. Strict xfail.
3. **A two-sentence window never grants partial credit** (existing design, `BORNE_OUT = (SUPPORTED, PARAPHRASE)`).
   When a dropped anchor or any dropped condition is found through a window, the claim stays *unverifiable*
   rather than becoming *partial*. U-010's answer verdict is right (partial); its claim category is the window's.
4. The comparison answer stays *partial*: the completeness element "the 15-calendar-day" is matched literally
   and is not found in "15 calendar days". This is pre-existing.

## Remaining risks

* **Lexical.** Distinguishing words are found by word matching, so a synonym or a spelling variant (follow-up /
  followup) can leave the right word unmatched. The rule then falls back to today's behaviour or, as in the
  follow-up case, leans on a weak word.
* **The anchor check sees only explicit limit wording** with a period of the same number and unit. A dropped
  trigger stated any other way ("the clock is 7 days") is not caught, and an anchor the claim does give is
  never checked for being the right one.
* **One check, one changed recorded score.** On the recorded answers this change is almost inert: the focus gap
  changed no recorded score, and the anchor check fired on one. Its benefit is confirmed on the live
  seven-day question and the constructed fixtures, not as a rate on a population.
* No improvement in answer accuracy is claimed: the evaluator changed, not the answers.

## Scope

Changed: `src/regulus/accuracy/evaluator.py`, `src/regulus/accuracy/operators.py`. The accuracy package was
already untracked, so the diff is against task-start copies (`change.diff`). Tests: one new test file, one new
fixture, and an untracked integration test file updated. The tracked-modified set is unchanged at 35 files. No
benchmark questions, historical results, rubric, citation policy, weights or configuration were touched.
Nothing committed.
