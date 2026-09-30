# Stage 14: Overnight Rebalanced Fine-Tune

One controlled overnight experiment. Stage 13 fixed grounding and broke
answering; Stage 14 tests whether rebalancing the training data recovers the
answering without losing the grounding.

Exactly one variable changes from Stage 13: **the dataset**. The LoRA shape,
target modules, learning rate, sequence budget, validation protocol and seed
are all held fixed, so any difference is attributable to the data.

Config: `configs/training_v3.yaml` (data), `configs/model_training_v3.yaml`
(run). Output: `models/qwen3-0.6b-lora/stage14_v1/`. Results:
`data/evaluation/results/stage14_v1/`.

---

## 1. What Stage 13 measured, and what it implied

| | Stage 7 base | Stage 12 | Stage 13 | Stage 13 + gate |
|---|---|---|---|---|
| Unsupported answers (of 5) | 0 | 3 | 1 | **0** |
| False refusals (of 22) | 2 | 3 | **1** | **1** |
| Identifier grounding | 1.000 | 0.667 | 0.833 | **1.000** |
| Degenerate answers | 0 | 2 | **0** | **0** |
| Reviewer mean | **1.11** | 0.59 | 0.556 | 0.630 |
| Reviewer, hallucination | 1.80 | 1.00 | 1.60 | **2.00** |

The grounding work succeeded. The answering regressed: general knowledge fell
to 0.20 and reasoning to 0.20, against Stage 7's 1.00 for both.

Of Stage 13's 20 scored failures, **14 shared one shape**: the model reported
which documents had been retrieved and what their legal status was, then
stopped, instead of answering. Asked the purpose of the FDA it replied that
the sources do not establish what the FDA is.

The cause was in the data, not the architecture. All 2,000 of v2's
refusal-required examples opened with the same frame, "The provided source is
X [1], which ...", so that frame was reinforced 2,000 times while no example
ever demonstrated extracting a usable answer from thin or partly relevant
context. The model learned the frame rather than the judgment.

## 2. What changed in v3

Composition, not scale. v3 holds 9,720 examples against v2's 9,963.

| | v2 (Stage 13) | **v3 (Stage 14)** |
|---|---|---|
| Refusal-required | 2,000 (20.1 %) | **1,300 (13.4 %)** |
| Answer-side grounding categories | 498 | **1,930** |
| Distinct refusal openings | 1 | **4** |
| Fake-part examples with guidance context | 0 | **yes** |
| Categories | 14 | 17 |

Three new answer-side categories, all of which lead with the regulatory
substance rather than with source commentary:

| Category | n | What it teaches |
|---|---|---|
| `grounded_definition` | 332 | define a term from the one passage that defines it, among two distractors |
| `grounded_topic` | 600 | answer a topical question from the single passage that addresses it, answer first |
| `guidance_answer` | 500 | answer a guidance question from guidance, labelled non-binding, without refusing |

The grounding categories that produced the Stage 13 wins are kept but
trimmed: `context_mismatch` 500, `wrong_context` 300, `partial_context` 50,
`guidance_mismatch` 50, plus `abstention` 400.

One targeted addition: `fake_part_guidance_context`. Stage 13 answered "What
does 21 CFR Part 1400 say?" by asserting the eCFR *contains* Part 1400 and
attaching retrieved guidance titles to it. Every v2 fake-part example had
supplied eCFR context, so the case where only guidance comes back was never
demonstrated. This is a generalised fix across many parts, not a fix aimed at
the benchmark question.

### Dataset identity

| | |
|---|---|
| Examples | 9,720 (train 7,755 / validation 1,028 / test 937) |
| SHA-256 | `86f4c012e7c0a2d673eec863fc9b92aca77188db0062e6e6678ea179f6c70ca4` |
| Seed | 42 |
| eCFR snapshot | 2026-09-03 |

Validation: structural 0 invalid, duplicates 0, invalid sources 0, invalid
citations 0, negative-validation failures 0, **grounding-validation failures
0**, group overlap across splits 0, secret findings 0.

### Prior datasets remain reproducible

Changing the generators silently broke v2's hash. Because this project has
kept every earlier dataset reproducible, the new behaviour is gated behind
two config flags (`varied_refusal_openings`, `guidance_context_negatives`)
that default to the old behaviour. Verified after every change:

| Dataset | Hash | Reproduces |
|---|---|---|
| v1 (Stage 11) | `bee32e32...` | yes |
| v2 (Stage 13) | `656d69b2...` | yes |
| v3 (Stage 14) | `86f4c012...` | yes |

## 3. Metric corrections made this stage

Two bugs in my own Stage 13 metrics were found and fixed; they changed the
reported numbers for **every** run, including the historical ones.

1. **Sentence splitting broke on abbreviations.** "the U.S. Food and Drug
   Administration" split into two fragments, so a pure refusal appeared to
   contain substantive content. This had reported Stage 13's false-refusal
   rate as a perfect 0.000; the true figure is 0.045.
2. **The pipeline's own refusal was counted as content.** Its second
   sentence, "No sufficiently relevant eCFR or FDA guidance passage was
   retrieved for the question", matched no refusal phrase, so the
   deterministic refusal was scored as an unsupported answer. This had
   understated Stage 7, which actually has zero.

A third refinement: on refusal-required questions, an answer that quotes real
retrieved text and then states it does not establish the claim is now counted
as `hedged`, not as an unsupported answer. That is the behaviour Stage 13
trains for, and `baseline-024` is exactly this case.

## 4. Training run

*(filled in when the run completes)*

## 5. Evaluation

*(filled in when the run completes)*

## 6. Safety

*(filled in when the run completes)*

## 7. Verdict

*(filled in when the run completes)*
