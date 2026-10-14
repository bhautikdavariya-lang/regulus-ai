# Priority 2A — question-aware answer planning, and the evaluator relevance issue

**Outcome.** The "How quickly?" failure is fixed by a small, measured change. It touches 0 of the 300
benchmark prompts, makes no wrong deadline assignment on any tested wording, and keeps the `(c)(1)`
cross-referenced conditions. The evaluator "relevance limitation" reported in the three previous
tasks turned out to be a **test-harness artifact**; it does not occur in production. A *different*
evaluator defect, a completeness over-requirement, was found, traced, pinned, and left unchanged.
All evidence comes from the production engine with greedy decoding.

## Step 1 — how questions are routed today

`planning.shape.analyze_shape` sends almost every deadline question to the same bucket:

| question | mode | exhaustive | focus terms |
|---|---|---|---|
| direct: deadline for an unexpected fatal / life-threatening SAR | focused | no | reporting, deadline, unexpected, fatal, … |
| "How quickly must IND safety reports be submitted?" | focused | no | quickly, ind, safety, reports, submitted |
| "IND safety reporting timeframes" | focused | no | ind, safety, reporting, timeframes |
| "the 7-day and 15-day … deadlines" | focused | no | day, ind, safety, reporting, deadlines |
| "all the reporting deadlines" | focused | no | reporting, deadlines |
| comparison of the 15- and 7-calendar-day deadlines | focused | no | calendar-day, ind, safety, … (comparison wording demoted: one provision named) |
| "IND safety reporting requirements" | focused | no | ind, safety, reporting |
| "Summarize 21 CFR 312.32." / "What does 312.32 require?" | synthesis | no | — |

One specific deadline, all deadlines, a comparison, and a topical narrowing are not distinguished.
All of them get the same instruction: "state **only** what the requested provision says about the
focus … Do not describe the rest of the provision". The model then states whichever deadline
paragraph shares the most words with the question. "all … deadlines" is not exhaustive because
"deadlines" is not one of the shape's requirement nouns. The comparison is demoted because only one
provision is named.

## Step 2 — the plan

The pipeline, not the model, pairs each period with what it applies to. In Priority 2, every
instruction that asked the model to do that pairing produced wrong pairings ("a serious and
unexpected suspected adverse reaction … 7 calendar days"). `answer_plan.value_entries` decides:

* **value requested** — `selection_value_kind` (Priority 1): a time period, including "how quickly",
  "timeframes", "time limits", "timeline"
* **condition each value applies to** — the paragraph's own eCFR heading, verbatim. If any period's
  source has no heading, the plan abstains rather than describe it in words the pipeline made up
* **one provision or several** — it fires only when the requested provision's EXACT sources state at
  least **two different** periods. Each distinct period is represented once, by the first source in
  document order that states it, so the 15-day rule (stated in `(c)(1)`, `(c)(1)(v)` and `(d)(3)`) is
  one entry, not three. That is not "listing every deadline"
* **narrowing vs. umbrella** — question words found in the *section's* heading ("IND safety
  reporting") name the whole section. If the remaining words carry one entry's heading (≥ 60 %),
  the question is about that one condition: the plan returns nothing, and the prompt is unchanged
* each entry carries **the source's own value clause, verbatim**: from the clause boundary before
  the period to the end of its sentence, so the trigger and any cross-reference come with it

It is rendered as one plan line under REQUESTED PROVISIONS (where the codebase already puts lists),
plus a list-free ANSWER FORMAT line that replaces the focus-only one. For the "How quickly" prompt:

```
  periods stated, each with the reports it applies to and when it runs from: IND safety reports: in no case
  later than 15 calendar days after the sponsor determines that the information qualifies for reporting under
  paragraph (c)(1)(i), (c)(1)(ii), (c)(1)(iii), or (c)(1)(iv) of this section [2]; Unexpected fatal or
  life-threatening suspected adverse reaction reports: The sponsor must also notify FDA of any unexpected fatal
  or life-threatening suspected adverse reaction as soon as possible but in no case later than 7 calendar days
  after the sponsor's initial receipt of the information [9]
```

The design was trialled on the real model **before** any source change (`work/trial.py`, which
injects the lines on the way to the model). The first variant gave each period with its heading
only. Pairings were correct, but the model cited the 15-day line to `[1]` = `(a)` (the definitions)
in 4 of 5 answers and dropped both triggers. The verbatim-clause variant fixed both. The implemented
prompts are byte-identical to the trialled ones.

## Step 3 — the change

| file | change |
|---|---|
| `src/regulus/rag/answer_plan.py` (+129) | `ValueEntry`; `value_entries()`; an optional `values` field on `AnswerPlan` (empty by default; serialised only when set); the plan line in `plan_lines`; the value instruction in `format_line` |
| `src/regulus/rag/generation.py` (+9/−3) | `build_package` attaches the values to the plan |

`extract_heading` was **not** changed. It reads only single-token designations, so `"(c)(1) IND
safety reports."` has no heading for it. It also supplies group headings for every plan, so the
value plan uses its own reader instead of altering prompts elsewhere.

### Prompt-level regression check (no generation)

`work/prompts.py` renders the exact user message for all 300 benchmark questions plus 14 probes. It
was checked to equal the engine's actual prompts byte-for-byte. Before vs. after:

* **benchmark: 0 of 300 prompts changed**
* changed: "How quickly", "timeframes", "the 7-day and 15-day …", "all the reporting deadlines", the comparison
* unchanged: the direct seven-day question, "Summarize", "What does … require?", "IND safety reporting
  requirements", follow-up, 211.180 retention (plan abstains: no headings), 211.25, 803.53 and 806.10
  (one period each)

## Before / after (production engine, greedy)

| question | before | after |
|---|---|---|
| "How quickly …" | 15-day only, cites `(c)(1)`, 91 tokens | **both rules**, 15-day → `(c)(1)` with its four cross-referenced conditions, 7-day → `(c)(2)` with its trigger, 117 tokens |
| "timeframes" | both, but enumerates 8+ paragraphs, 615 tokens | both, same two sentences, 117 tokens |
| comparison | 15-day → "serious and unexpected", 7-day → fatal/LT, cites `(a)` only | both, each to its own category, cites `(c)(1)` and `(c)(2)` |
| direct seven-day | 7-day, cites `(c)(2)` | **byte-identical** |
| "Summarize 21 CFR 312.32." | — | prompt byte-identical; still answered |

After the change, every answer on these five wordings that states a deadline pairs it with the
right category. No sentence gives 7 days to anything but unexpected fatal or life-threatening
reactions, and none gives them 15.

## Step 4 — tests

* `tests/test_answer_value_plan.py` (new, **24**): routing for umbrella, narrowing, broad, no-value,
  single-period, headingless, non-EXACT; one entry per distinct period; verbatim clauses keep the
  trigger and the `(c)(1)(i)–(iv)` cross-reference; rendering unchanged without values; the final
  instruction stays list-free.
* `tests/integration/test_ind_deadline_generation.py` (real model, `Engine`, greedy):
  * the strict xfail from Priority 2 **flipped** (XPASS) when the fix landed — its purpose — and is
    replaced by a stronger assertion: both rules, each cited to its own paragraph, never `(a)`
  * new: both-timeframes ×2 (with the four conditions), comparison, no misassignment on 5 wordings,
    broad question still answered, ON/OFF ×4
  * **16 passed, 1 strict xfail** (below)
* `tests/test_ind_safety_deadlines.py`: relevance tests made production-faithful (Step 5)

| suite | result |
|---|---|
| full unit | **2,082 passed**, 1 skipped, 3 xfailed (was 2,054 / 4) |
| protected — contradiction, scope, numeric limits, relative clause, pass integrity, claims, relevance, validation, answerability, answer shape, generation contract | **589 passed, 3 xfailed** (the relative-clause xfails, unchanged) |
| DB integration | **41 passed** |
| real model, new and updated | **16 passed, 1 xfailed (strict)** |
| `accuracy_regression.py` — How quickly, comparison, 211.25 | **exact evidence PASS, payload PASS, live PASS** — byte-identical ON/OFF |

Not run: the frozen 300-question benchmark. `test_rag_slow::test_rag_end_to_end_one_question` still
fails at 4828, which is pre-existing and was reproduced on committed `HEAD` in Priority 2.

## Step 5 — the evaluator relevance issue

**It is a test-harness artifact, not a production defect.** The relevance check reads each source's
heading together with its text. In production every 21 CFR source carries its **section** heading,
here "IND safety reporting." The `judge()` test harness builds sources with no heading unless one is
passed. Evaluated in-process against the **real** package (`work/relevance_trace.py`):

| answer | production | harness without headings |
|---|---|---|
| correct 7-day, paraphrased | **relevant, correct** | irrelevant, off_topic |
| both rules, paraphrased | **correct** | partial |
| 15 days given to the fatal / LT category | contradicted, incorrect | contradicted, incorrect |

The IND, Priority 1 and Priority 2 reports called this a pre-existing relevance limitation. That was
wrong: it was never observed in production, only through the harness. **No evaluator change is
proposed for relevance.** The strict xfail that recorded it is replaced by production-shaped tests:
correct answers are relevant and correct, a reversed deadline is still contradicted, and the
harness-versus-production difference is itself pinned.

### A different evaluator defect, found while tracing

Every live answer above was failed on **completeness** — including the direct seven-day answer,
whose prompt and output are byte-identical before and after this task. The evaluator was not
changed here, so this predates the task. Mechanism:

`evaluator._focus_gap` requires every obligation-bearing **top-level group** of the requested
section (`(a)`, `(c)`, `(d)`) that is "on topic" and that no answering statement covers. "On topic"
means sharing enough of the question's words. Group `(d)` (Followup) contains `(d)(3)`: "…must
report such suspected adverse reaction in an IND safety report …". It shares *report, suspected,
adverse, reaction* with the direct seven-day question, so a correct "7 calendar days" answer fails
for not covering follow-up. My first guess, that the section heading caused it, was measured and is
wrong: the groups stay on topic on their text alone.

It surfaced through **Priority 1**. Its value rank added `(d)(3)` (it states a period) to the
direct seven-day question's evidence, and that question's evaluation fell from PASS 100 in the IND
task to FAIL 75 with the same correct answer. I did not evaluate that wording live in Priority 1,
so I missed the side effect then. It is pinned by a strict xfail on the live answer.

**Proposed narrow fix, not implemented** (the brief forbids weakening completeness checks without
review): in `_focus_gap`, judge a group on-topic only on the question's *distinguishing* words —
the words that do not appear in every obligation-bearing group of the section. For the direct
seven-day question, *report, suspected, adverse, reaction* occur in both `(c)` and `(d)`, while
*unexpected, fatal, life-threatening* occur only in `(c)`, so `(d)` would no longer be required. For
"How quickly", every topic word is shared, so the check falls back to today's behaviour and still
requires `(d)`. That is arguably right for a question about all reporting timing. It should be
measured with `accuracy_validate.py` before adoption.

## Remaining limitations

* **The plan covers time periods only.** Other value kinds (amounts, temperatures, counts) and
  periods from headingless paragraphs (211.180 retention) are left to the focused answer as before.
* The comparison answer pairs each deadline with its category but does not add an explicit
  "the difference is …" sentence.
* "all the reporting deadlines" gets the two **distinct** periods. The `(c)(1)(v)` FDA-request and
  `(d)(3)` late-determination clocks, which are also 15 days, are not enumerated; by design, the plan
  does not list every deadline.
* The answers copy the plan's wording closely. That is accurate and verbatim, but terse.
* Lexical routing still decides narrowing (≥ 60 % of the condition words in one heading). A question
  naming a condition by synonym is treated as umbrella and gets both periods, which is complete
  rather than wrong.
* The completeness over-requirement above is open (strict xfail).

## Scope

Changed: `src/regulus/rag/answer_plan.py`, `src/regulus/rag/generation.py`. Both were unmodified at
`HEAD` before this task, so their diff is exactly this change (+138/−3). Tests: one new file and two
untracked test files extended. No model weights, configuration, rubric, citation policy, benchmark
files or other pre-existing work were touched. Nothing committed.
