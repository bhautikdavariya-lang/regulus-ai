# Priority 2 — generation: the right evidence, the wrong deadline

**Case.** "How quickly must IND safety reports be submitted under 21 CFR 312.32?" — after Priority 1,
§312.32(c)(2) (7 calendar days) is in the selected evidence, but the answer gives only the 15-day rule.

**Outcome.** Root cause identified. **No generation change ships**: every prompt change measured to
surface the 7-day rule made the model either dump the section or invent which reports each deadline
applies to — the exact misassignment class the previous tasks fought. Regression tests pin the
evidence, the evaluator's detection of those misassignments, and the generation gap itself (strict
xfail). No production code, configuration or script was changed.

## 1. A harness error found and corrected first

The first trace built its generator with `load_qwen_generator(settings)`, which takes the raw
`configs/model.yaml` decoding: **`do_sample: true`, temperature 0.7, top_p 0.8**. Its outputs were not
reproducible — two runs of the same question gave 56 tokens (15-day only) and 545 tokens (both
deadlines). The answering UI does not decode that way: `serve_ui.Engine` uses
`system_identity.configured_generation_config`, which is **greedy with thinking off**. A second error:
wrapping `generate` with `*args` hid its signature, and the pipeline inspects that signature to decide
whether to pass the per-question token budget, so the run fell back to 128 tokens.

The trace (`work/trace.py`) now runs `Engine.ask` and records the messages through a wrapper with the
generator's exact parameters. **Three runs give byte-identical answers** (`engine_rec_1`, `engine_rec_2`,
and `engine_norec` without the wrapper), so the recording does not perturb generation and the baseline
is deterministic. The sampled runs were discarded and are not evidence of anything.

## 2. Baseline (production engine, greedy)

| wording | answer states | cited | out tokens |
|---|---|---|---|
| "How quickly …" | **15-day only** | (c)(1) | 91 |
| "IND safety reporting timeframes" | 7-day and 15-day | many | 615 |
| "deadline for an unexpected fatal or life-threatening …" | 7-day only (correct) | (c)(2) | 49 |
| "difference between the 15- and 7-calendar-day deadlines" | 15-day → "serious and unexpected", 7-day → "unexpected fatal or life-threatening" | (a) | 71 |

## 3. Root cause

The selected evidence, in prompt order, puts `(c)(1)` at SOURCE 2 and `(c)(2)` at SOURCE 9, both tier
EXACT. Two things in the prompt make the model state `(c)(1)` alone:

1. **The focused answer shape restricts the model to the question's own words.** The question is given
   the `focused` shape with focus terms `quickly, ind, safety, reports, submitted`, and the instruction
   *"plain sentences stating only what the requested provision says about the focus … Do not describe
   the rest of the provision."* `(c)(1)` contains four of the five focus terms; `(c)(2)` — "The sponsor
   must also notify FDA of any unexpected fatal or life-threatening suspected adverse reaction …" —
   contains one. The model states the paragraph that matches. This contradicts system rule 10 ("Never
   drop … a distinction between subsections"), and the later, more specific instruction wins.
2. **The 15-day figure outnumbers the 7-day figure three to one** in the evidence: `(c)(1)`,
   `(c)(1)(v)` (FDA requests) and `(d)(3)` (late determinations) each say "15 calendar days";
   only `(c)(2)` says 7.

The pattern holds across wordings: whichever deadline paragraph shares the most focus terms is the one
stated. For the seven-day question `(c)(2)` matches 7 of 8 focus terms and is stated alone, correctly.
It is Priority 1's root cause again, one layer later: lexical topic matching misses a paragraph that
answers the question in different words.

## 4. Experiments (single-factor, production engine, `work/ablate.py`)

Each variant rewrites one thing in the user message; retrieval, validation, repair and citation
mapping run unchanged.

| variant | "How quickly" states 7-day? | side effect |
|---|---|---|
| baseline | no | — |
| drop the focus line | no | — |
| drop the sub-requirements line | no | — |
| remove "only … Do not describe the rest" | yes | dumps all 14 sources, 681 tokens |
| move (c)(2) next to (c)(1) | yes | dumps the section, 440 tokens; also breaks the document-order guarantee |
| *diagnostic:* remove the other two "15 calendar days" | yes | removes evidence — a probe, never a fix |
| "give every time period … and what each applies to" (two wordings) | yes | **misassigns**: "a serious and unexpected suspected adverse reaction … no later than 7 calendar days" on "How quickly"; on "difference", "the 7-calendar-day deadline applies to … paragraph (c)(1)(i)" — the originally reported failure |
| "quote each sentence that states a time period" | no | on "difference", invents "specified in 21 CFR 312.32(c)(1)(i) and 21 CFR 312.32(c)(1)(v)" |

Every variant that surfaces the 7-day rule does so by enumerating the section or by assigning the
periods itself, and when it assigns them it assigns them wrongly. An incomplete but correct answer
(today) was traded for complete but confidently wrong ones. On those grounds, no change was made.

The evaluator **does** catch the misassignments those prompts produced. The "serious and unexpected …
7 calendar days" sentence is `contradicted` — "the answer states day ['7'] where the evidence states
['15'] (the statement is about 21 CFR 312.32(c)(1) …)" — by the check added in the IND task. So
shipping such a prompt would have shown up as failures rather than passing silently.

## 5. The integration-test failure, verified independently

`tests/integration/test_rag_slow.py::test_rag_end_to_end_one_question` asserts
`len(out.context.text) <= 3600` and fails at **4828**. Verified without touching the working tree:
`git archive HEAD` exported commit `1111365` to the scratchpad and the test ran there with
`PYTHONPATH` pointing at the export. `regulus.rag.selection` loaded from the export and contains
neither the IND fix (`_required_order`) nor Priority 1 (`_referenced_paths`). **It fails at the same
4828 on the committed tree**, before any of the uncommitted work existed. The assertion is a
soft-budget check that a single requested section's required evidence legitimately exceeds.

## 6. Tests

`tests/test_ind_safety_deadlines.py` (+7 tests, 53 → 60, plus one strict xfail):

* both deadline paragraphs and the whole `(c)(1)(i)–(iv)` list reach the model for "How quickly",
  "timeframes", the seven-day question and the difference question
* the misassignment a rejected prompt produced is contradicted; the 7-day subject given the 15-day
  period is contradicted; a correct 7-day statement is supported by its source
* **strict xfail:** a correct 7-day answer to "How quickly" is still failed by the relevance check
  (pre-existing, out of scope; a fix flips the test)

`tests/integration/test_ind_deadline_generation.py` (new; `slow` and `integration`, runs the real model
through `Engine`):

* the direct seven-day question states 7 days, not 15, and cites `(c)(2)`
* the timeframes wording states both deadlines
* the "How quickly" wording is given `(c)(2)`
* **strict xfail:** the "How quickly" wording states the 7-day rule — the generation gap this task found
* evaluation ON and OFF give byte-identical answers and citations, for the seven-day question, "How
  quickly" and a 211.25 control

| suite | result |
|---|---|
| full unit suite | **2,054 passed**, 1 skipped, 4 xfailed (was 2,047 / 3; +7 tests, +1 strict xfail) |
| protected contradiction / negation / modality | **495 passed, 3 xfailed** — unchanged |
| DB integration, not slow | **41 passed** |
| slow generation (`-m "slow and integration"`, new file) | **6 passed, 1 xfailed** (strict) |
| `test_rag_end_to_end_one_question` | fails at 4828 — pre-existing, reproduced on committed `HEAD` |

## 7. Remaining limitations

* **The "How quickly" gap is open.** The model receives `(c)(2)` and does not use it. It is pinned as
  a strict xfail. Fixes worth weighing, each beyond a targeted change and so left to review:
  * a **deterministic verbatim completion**: append, word for word and cited, an EXACT sibling
    paragraph that states a different value of the kind asked for. It never invents a mapping. But
    it cannot tell an umbrella question ("IND safety reports") from a narrowing one ("unexpected
    fatal …") lexically, and would add the 15-day rule to the correct seven-day answer
  * revising when the **focused** shape applies to questions that ask for a value
  * a larger model
* **The relevance false negative** still fails a correct 7-day answer to "How quickly" — strict xfail.
* The prompt shows the 15-day figure three times against one for 7 days. This is faithful to the
  regulation, so it is reported as a contributing factor and not changed.

## Scope

No source, configuration or script changed (no file under `src/`, `configs/` or `scripts/` is newer
than the Priority 1 report). The tracked-modified set is the same 33 files. The frozen 300-question
benchmark was not run; nothing committed. Files written: the two test files and this directory.
