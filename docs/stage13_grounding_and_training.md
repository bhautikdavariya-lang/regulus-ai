# Stage 13: Grounding/Refusal Correction and a Larger Fine-Tune

Stage 12 built a working LoRA pipeline and produced a model that was worse
than the un-finetuned baseline, in a specific and diagnosable way. Stage 13
addresses that failure at two levels, a deterministic grounding layer at
inference and a corrected training dataset, and then runs the largest
fine-tune this hardware allows.

Two results up front, because they differ in strength:

- **The grounding layer works and is measured.** It eliminates unsupported
  answers on the base model (1 to 0) and cuts them on the Stage 12 adapter
  (4 to 1), with **no increase in false refusals** in either case.
- **The training run is still not a meaningful epoch-scale experiment.** A
  full epoch on this machine costs 45.7 hours. The Stage 13 brief asks for
  1 to 3 epochs; what was reachable is reported honestly in section 7 and
  is roughly 2 to 3 times Stage 12, not 20 times.

Code: `src/regulus/grounding/`, `src/regulus/training/grounding_examples.py`,
`src/regulus/evaluation/grounding_eval.py`. Config: `configs/training_v2.yaml`,
`configs/model_training_v2.yaml`. Scripts: `scripts/benchmark_training.py`,
`scripts/compare_grounding.py`. Tests: `tests/test_grounding.py` (30).

---

## 1. What Stage 12 actually showed

From `docs/stage12_model_training.md`, re-measured here with the Stage 13
metrics so the comparison is like for like:

| | Stage 7 (base + RAG) | Stage 12 (LoRA) |
|---|---|---|
| Correct refusals, of 5 required | 4 | 1 |
| Unsupported answers | 1 | 4 |
| False refusals, of 22 answerable | 2 | 3 |
| Identifier grounding accuracy | 0.833 | 0.500 |
| Degenerate answers | 0 | 2 |

Stage 12 was worse on both error directions at once, so this is not a
precision/recall trade-off to be tuned. The mechanism was visible in the two
fabrications: asked about the nonexistent 21 CFR 314.999, the model applied
its learned template to a real passage retrieved from a different section and
presented that passage as the content of 314.999.

### Why the Stage 11 data permitted it

Analysing the Stage 11 refusal examples explains the shortcut the model
learned:

| | v1 (Stage 11) | v2 (Stage 13) |
|---|---|---|
| Refusal-required examples | 500 of 9,445 (5.3 %) | 2,000 of 9,963 (20.1 %) |
| Distinct refusal subtypes | 7 | 14 |
| Supplying legitimate context | 357 (71 %) | 1,773 (89 %) |
| **Whose requested identifier really exists** | **0** | **500** |

Every Stage 11 refusal example named an identifier that did not exist. The
rule "the identifier looks made up, so refuse" satisfies all 500 of them, and
that rule is useless when the identifier is real but the context is about
something else. This is the gap Stage 13 fills, and it is why the fix is not
simply "more negatives".

## 2. Architecture

```
          question
             │
   extract identifier (Stage 5 parser; no identifier -> unchanged path)
             │
   verify against the verified database (read-only)
             │
      ┌──────┴───────────────┬────────────────────────┐
  absent                unverifiable              exists
      │                 (other title)                │
  refuse                pass with note          retrieve (unchanged)
                                                     │
                                          context carries the identifier?
                                                     │
                                          ┌──────────┴──────────┐
                                         no                    yes
                                          │                     │
                                       refuse            model answers
```

Retrieval itself is never altered, so a gated run and an ungated run retrieve
identically and the comparison stays valid. Only the generation step is gated.

## 3. Identifier verification

`regulus.grounding.identifiers.verify_identifier` returns a structured
`IdentifierVerification`, not a boolean:

```python
IdentifierVerification(
    identifier=RequestedIdentifier(kind="section", section="314.999", ...),
    exists=False, verifiable=True, verified_absent=True,
    reason="not_in_snapshot", normalized_identifier="21 CFR 314.999",
    source_type="ecfr", record={},
)
```

Three properties matter and each is asserted by tests:

1. **Digits are never rewritten.** `21 C.F.R. § 314.999` normalises to
   `21 CFR 314.999`. It never becomes `21 CFR 314.99`, which exists. Only
   punctuation and spacing are normalised.
2. **"Verified absent" is distinct from "cannot verify."** The corpus is
   Title 21 only, so `40 CFR 261.3` returns `verifiable=False` and the gate
   passes it through. Absence of evidence is not treated as evidence of
   absence.
3. **Reserved is distinct from nonexistent.** A part inside a reserved range
   such as `83-98` exists structurally but carries no text, and gets its own
   refusal wording.

Two backends implement the same protocol: `DatabaseIdentifierIndex` (cached
read-only SELECTs, used at inference) and `CorpusIdentifierIndex` (in-memory,
so dataset generation can verify candidates without a query each).

Coverage: existing part, section and paragraph; absent part, section,
paragraph and docket; reserved part and section; a real docket; other CFR
titles; malformed and identifier-free questions.

## 4. The grounding gate

`GroundingConfig` is **disabled by default**, so every existing pipeline is
bit-for-bit unchanged until a caller opts in with `--grounding`.

| Rule | Behaviour |
|---|---|
| `refuse_unverified_identifier` | refuse when the database shows the identifier is not live content |
| `refuse_context_mismatch` | refuse when the identifier exists but no retrieved passage carries it |
| `mismatch_kinds` | mismatch rule applies to section, paragraph and docket requests only |

Part-level questions are excluded from the mismatch rule deliberately: "what
does Part 211 cover" is answerable from any section of Part 211, and applying
the rule there would manufacture false refusals.

Context matching is structural, never similarity-based. A retrieved
`21 CFR 112.45` does not satisfy a request for `21 CFR 314.999` however
similar the text. Paragraph matching does not read across siblings: a request
for `(b)(2)` is not satisfied by `(b)(1)`, nor by the parent `(b)`, because
the parent does not contain the child's text. A request for `(b)` **is**
satisfied by `(b)(1)`.

Refusal wording reuses the project's existing register and matches the
phrasing the v2 training answers use, so the deterministic refusal and the
learned refusal are the same style rather than two competing voices.

## 5. Dataset v2

`data/training/datasets/{training,validation,test}_v2.jsonl` plus
`manifest_v2.json` and `validation_v2.json`. **Stage 11's v1 files are
untouched and still reproduce byte for byte**, verified by regenerating v1
after every code change: hash
`bee32e320fc5c5072b040efc5b5a1caf707bce09c96affd05586a0f039e77a54`.

The new categories keep the context legitimate and vary only whether it
establishes what was asked:

| Category | n | Requested | Provided | Correct behaviour |
|---|---|---|---|---|
| `context_mismatch` | 600 | identifier that does not exist | a real passage from elsewhere | abstain, naming both |
| `wrong_context` | 400 | **a section that really exists** | a real passage from another part | abstain |
| `partial_context` | 100 | a paragraph that really exists | a **sibling** paragraph of the same section | abstain |
| `guidance_mismatch` | 100 | a binding requirement, or a recommendation | the opposite source type | abstain |
| `citation_grounding` | 498 | an answerable question | the supporting source **plus two distractors** | answer, citing only the support |

`citation_grounding` is the deliberate counterweight. Without it, raising the
refusal share from 5.3 % to 20.1 % would reward a model that simply refuses
more often; with it, the model must still answer when the evidence is present,
while leaving legitimate but irrelevant neighbours uncited.

### Composition

| Category | Share | Category | Share |
|---|---|---|---|
| direct_cfr | 20.0 % | citation_grounding | 5.0 % |
| section_paragraph | 15.1 % | abstention | 8.0 % |
| definition | 9.0 % | context_mismatch | 6.0 % |
| relationship | 8.0 % | wrong_context | 4.0 % |
| fda_guidance | 9.8 % | partial_context | 1.0 % |
| cfr_vs_guidance | 5.0 % | guidance_mismatch | 1.0 % |
| citation | 4.0 % | | |
| multi_context | 4.0 % | **answerable / refusal** | **79.9 % / 20.1 %** |

Total 9,963 examples, train/validation/test 7,958 / 1,058 / 947, seed 42,
hash `656d69b284db62bf945ffd100a4f52b36a1652b06d43b03239e7facba8c4a71b`,
eCFR snapshot 2026-09-03.

### Validation

All Stage 11 gates plus the new Stage 13 checks, run against the database:

| Check | Result |
|---|---|
| Structural invalid | 0 |
| Duplicate ids / question-answer pairs | 0 / 0 |
| Invalid sources / invalid citations | 0 / 0 |
| Negative validation failures | 0 |
| **Grounding validation failures** | **0** |
| Benchmark leakage (question+answer across splits) | 0 |
| Group overlap across splits | 0 |
| Secret findings | 0 |

The grounding check verifies claims the new categories make: every
`context_mismatch` identifier is confirmed absent from the database, every
`wrong_context` and `partial_context` requested identifier is confirmed to
**exist**, the supplied context is confirmed not to be the requested source,
`guidance_mismatch` source types match their declared direction, and
`citation_grounding` cites its supporting source and no distractor.

### Benchmark exclusion, stated precisely

Exclusion is **lexical, not semantic**, and this is what it actually
prevents: a generated question is dropped if it normalises to a benchmark
question, or if it names the same CFR/docket identifiers and reaches word-set
Jaccard 0.5, or, when no identifier is present, Jaccard 0.75. A benchmark
question rephrased with different words and no shared identifier would
survive. No claim of semantic leakage prevention is made.

## 6. Grounding metrics

New module `regulus.evaluation.grounding_eval`, reported by
`scripts/compare_grounding.py`. The existing reviewer scores and objective
measurements are unchanged and still reported.

One measurement subtlety had to be resolved first. The un-finetuned model
often answers **and then** appends "The available regulatory sources do not
provide enough information to answer this." Counting that as a refusal would
have credited Stage 7 with a perfect refusal rate while hiding that it
answered. Answers are therefore classified into three states: `refusal`
(declines, supplying nothing else), `hedged` (supplies content and also
disclaims) and `answer`. Sentences that describe the sources rather than
answer the question are not counted as content. Stage 7 produces 10 hedged
answers among 22 answerable questions; Stage 12 and the Stage 13 runs produce
none.

## 7. Hardware constraint (measured, not assumed)

`scripts/benchmark_training.py` times real optimizer steps on real examples.

| | |
|---|---|
| Device | CPU only, float32, 4 threads, 7.91 GB RAM (about 3.3 GB free) |
| GPU | none present |
| Usable training examples | 7,757 of 7,958 (204 skipped as over 1,280 tokens, 2.6 %) |
| Token length: median / p95 / max | 547 / 1,135 / 2,712 |
| Peak resident memory | 3.05 GB |
| **One epoch** | **970 steps, 45.7 hours** |

Gradient checkpointing was measured rather than assumed: turning it **off**
made steps *slower* (206 to 265 s versus 170 s), because with roughly 3 GB
free the extra activation memory costs more in paging than recomputation
costs in arithmetic. It stays on.

A correction worth recording: the first benchmark walked the dataset in its
sorted order, which begins with the short abstention examples, and reported
an optimistic 170 s per step. Stage 12's real run implies about 280 s per
step for a representative mix. Rather than bet on either figure, the run was
bounded by wall-clock time instead of by a step count.

**The Stage 13 brief asks for 1 to 3 epochs. That is 46 to 137 hours here and
was not attempted.** Per the brief's own instruction not to fake a completed
experiment, the limitation is reported rather than worked around.

### Deadline-bounded training

`DeadlineCallback` watches the clock and, when the projected next step would
leave less than the reserve before the deadline, asks the Trainer to
evaluate, save and stop. The run therefore always ends with an evaluated,
selectable checkpoint rather than being killed mid-step. The reserve covers
the final validation pass, the checkpoint save, the adapter reload and the
inference check.

## 8. Training run

Held fixed from Stage 12 so the experiment stays interpretable: LoRA r 16,
alpha 32, dropout 0.05, the same seven verified target modules (re-verified
programmatically: 28 modules each), 10,092,544 trainable parameters (1.665 %),
batch 1 with gradient accumulation 8, max sequence length 1,280, gradient
checkpointing on, seed 42. Two things changed deliberately: the dataset (v1 to
v2) and the learning rate (2e-4 to 1e-4).

| | Stage 12 | **Stage 13** |
|---|---|---|
| Dataset | v1 | **v2** |
| Learning rate | 2e-4 | **1e-4** |
| Optimizer steps | 40 | **90** |
| Examples seen | 320 | **720** |
| Epochs | 0.044 | **0.093** |
| Wall-clock | 204 min | **359.5 min** |
| Validation subset | 64, unstratified | **100, stratified by category** |
| Median step | ~276 s | **220.7 s** |

Tokenisation: 7,755 of 7,958 usable, 203 skipped as over 1,280 tokens (2.6 %),
**0 truncated**, median 546 and p95 1,135 tokens.

The stratified validation subset realises this distribution, recorded in the
run summary and never chosen by looking at performance: direct_cfr 19,
section_paragraph 14, definition 13, relationship 9, abstention 8,
citation_grounding 6, context_mismatch 6, fda_guidance 6, cfr_vs_guidance 5,
citation 4, multi_context 4, wrong_context 4, guidance_mismatch 1,
partial_context 1.

### Losses

| Checkpoint | Validation loss |
|---|---|
| Base model, before training | 1.0956 |
| checkpoint-40 | 0.2275 |
| checkpoint-80 | 0.0940 |
| **checkpoint-90 (selected)** | **0.0723** |

Training loss fell from 0.645 to 0.060 over the 19 logged points, ending at a
mean of 0.279. **Validation loss was still falling steeply when the deadline
stopped the run**, so checkpoint-90 is the last one reached, not a converged
optimum. Selection was by validation loss alone; the test split and the
benchmark played no part.

### How the run ended

The deadline callback stopped it: with 26 minutes left against a 25-minute
reserve it requested an evaluation, a save and a stop after step 90. The run
therefore finished with an evaluated, selected checkpoint, at 18:14 against
the 18:30 target, having measured a median step of 220.7 s across all 90
steps. That median sits between the optimistic benchmark (170 s) and the
Stage 12-derived estimate (280 s), which is why a step count fixed in advance
would have missed the target in one direction or the other.

### Inference check

The adapter reloads onto a freshly loaded base model and generates. On a
validation example asking about 21 CFR 112.45(b)(1)(vi) it produced
`21 CFR 112.45(b)(1)(vi) [1], in the section on what measures must I take for
agricultural water ...`, 76 tokens in 27.0 s. This verifies the adapter
functions; it says nothing about correctness, and the probe is from the
validation subset used for selection rather than held out.

## 9. Evaluation

All runs use the same benchmark, retriever, retrieval configuration, prompt,
decoding parameters and seed. Retrieval is verified identical: every run
shows 930.30 average input tokens, 3,069.30 average context characters, 2.81
sources per question and 9 fallback activations.

**Where the gate intentionally changes what reaches the generator, that is
reported rather than hidden**: in the gated runs the generator is not called
for 3 of 27 questions, because the gate refused first.

### Ablation: the gate alone, before any retraining

| | Stage 7 base | **base + gate** | Stage 12 LoRA | **Stage 12 + gate** |
|---|---|---|---|---|
| Correct refusals (of 5) | 4 | **5** | 1 | **4** |
| Refusal rate | 0.800 | **1.000** | 0.200 | **0.800** |
| Unsupported answers | 1 | **0** | 4 | **1** |
| **False refusals (of 22)** | 2 | **2** | 3 | **3** |
| **False refusal rate** | 0.091 | **0.091** | 0.136 | **0.136** |
| Identifier grounding accuracy | 0.833 | **1.000** | 0.500 | **1.000** |
| Citation validity | 1.000 | 1.000 | 0.944 | **1.000** |
| Degenerate answers | 0 | 0 | 2 | **1** |
| Gate refusals | 0 | 3 | 0 | 3 |

This is the central Stage 13 result. The gate removes the targeted failures
and **adds no false refusals at all**: the two questions Stage 7 wrongly
declined (`baseline-007`, `baseline-011`) are exactly the two the gated base
run declines, and the three Stage 12 wrongly declined are exactly the three
the gated Stage 12 run declines. The gate fired on precisely three questions
in both runs, `baseline-023`, `baseline-026` and `baseline-027`, all three
correctly.

The one unsupported answer remaining under the gated Stage 12 adapter is
`baseline-024`, which asks for an exact storage temperature range in
21 CFR Part 211. Part 211 genuinely exists, so the gate correctly passes the
question through, and the model then answers from an irrelevant
equipment-identification paragraph. **This is the residue the deterministic
layer cannot reach and the training data must handle**, which is what
`wrong_context` and `partial_context` exist for.

### Stage 13 adapter

Retrieval is identical to Stage 7 and Stage 12 in the ungated run. In the
gated run the generator is not called for 3 of 27 questions because the gate
refused first; that is the only intended difference.

| | Stage 7 base | Stage 12 LoRA | **Stage 13 LoRA** | **Stage 13 + gate** |
|---|---|---|---|---|
| Correct refusals (of 5) | 5 | 2 | 3 | **4** |
| Refusal rate | 1.000 | 0.400 | 0.600 | 0.800 |
| **Unsupported answers** | 0 | 3 | 1 | **0** |
| **False refusals (of 22)** | 2 | 3 | **1** | **1** |
| **False refusal rate** | 0.091 | 0.136 | **0.045** | **0.045** |
| Identifier grounding | 1.000 | 0.667 | 0.833 | **1.000** |
| Citation validity | 1.000 | 0.944 | **1.000** | **1.000** |
| Degenerate answers | 0 | 2 | **0** | **0** |
| Answers carrying citations | 1 | 18 | 24 | 22 |
| Reviewer mean (0-2) | **1.11** | 0.59 | 0.556 | 0.630 |
| Reviewer, hallucination category | 1.80 | 1.00 | 1.60 | **2.00** |

**The gated Stage 13 adapter is the best configuration measured on grounding.**
It has zero unsupported answers, the lowest false-refusal rate of any run,
perfect identifier grounding and citation validity, no degeneration, and a
perfect score on the hallucination category. The gate changed exactly three
answers, all of them nonexistent identifiers refused correctly.

**Its reviewer mean is still well below Stage 7 (0.63 against 1.11)**, and
that gap is the honest headline. It is concentrated entirely outside
grounding: general knowledge 0.20, reasoning 0.20 and FDA/eCFR 0.43 against
Stage 7's 1.00, 1.00 and 0.86.

### What the training fixed that the gate could not

Two of the three critical cases were fixed by the corrected data alone:

- **21 CFR 314.999.** Ungated, the adapter answers: *"The available eCFR data
  contains 21 CFR 111.360 [1], 21 CFR 1.360 [2], but no data on 21 CFR
  314.999. The provided sources do not establish what 21 CFR 314.999
  requires."* Stage 12 fabricated a sanitation requirement from the same
  context. This is the `context_mismatch` behaviour.
- **baseline-024, the storage-temperature question.** Part 211 genuinely
  exists, so the gate correctly passes it through and can do nothing more.
  The adapter quotes the retrieved paragraph and then states *"It does not
  state a required storage temperature range, so I cannot describe it from
  the available data."* Stage 12 presented the same irrelevant paragraph as
  the answer. This is the `wrong_context` and `partial_context` behaviour,
  and it is the clearest evidence that the training half of Stage 13 was
  necessary.

### What the training did not fix

- **21 CFR Part 1400.** Ungated, the adapter asserts that the eCFR data
  *contains* Part 1400 and attaches retrieved guidance titles to it, which is
  a false existence claim rather than Stage 12's degenerate list. The gate
  refuses it deterministically. Every v2 `context_mismatch` fake-part example
  supplied eCFR context, while this question retrieves only guidance, so the
  case was never demonstrated in training.
- **Answering at all on general questions.** 14 of the 20 scored failures
  share one shape: the model reports which documents were retrieved and what
  their legal status is, then stops. Asked the purpose of the FDA it replies
  that the sources do not establish what the FDA is. All 2,000 v2 refusal
  examples open with the same frame, "The provided source is X [1], which
  ...", so the frame was reinforced 2,000 times while no example ever showed
  extracting a usable answer from thin context. The model learned the frame
  rather than the judgment.

### Failure classification

`scripts/analyze_failures.py` sorts the 20 failures and names the layer:

| Class | n | Layer |
|---|---|---|
| A, nonexistent identifier answered | 2 | grounding gate (both already refused when gated) |
| E, CFR / guidance confusion | 2 | training data |
| G, refused although supported | 1 | training data balance |
| H, unsupported despite a valid identifier | 1 | training data |
| K, described sources instead of answering | 14 | training data |

## 10. Safety

| | |
|---|---|
| Database writes | 0 |
| Evaluation dataset modifications | 0 |
| Benchmark modifications | 0 |
| Stage 11 dataset (v1) modifications | 0, verified by byte-identical regeneration |
| Stage 12 results modifications | 0 |
| External downloads | 0 |

The grounding layer is read-only: every statement is a SELECT with named
server-side parameters through the Stage 5 connection, which the server holds
read-only. Training never connects to the database at all.

## 11. Limitations

- **Not an epoch-scale experiment.** See section 7. Any comparison between
  the Stage 13 adapter and Stage 12 confounds the data change with a still
  very small training budget.
- **The benchmark has 5 refusal-required and 22 answerable questions.** Rates
  move in steps of 0.2 and 0.045 respectively; single-question changes should
  not be over-read. Counts are reported alongside every rate for this reason.
- **The gate only acts when the Stage 5 parser recognises an identifier.**
  Questions naming a regulation in prose are unaffected.
- **Benchmark exclusion is lexical**, as stated in section 5.
- **Reviewer scores remain assistant judgments** and need human confirmation.
- The gate cannot help when the requested identifier exists but the answer is
  still unsupported by the retrieved passage, as `baseline-024` shows.

## 12. Verdict and next stage

**Best observed configuration under the available compute budget: the Stage 13
adapter with the grounding gate enabled.** It is not production ready, and the
gap to Stage 7 on general answering is the reason.

What Stage 13 established:

1. **The two-layer design is justified by measurement, not assumption.** The
   gate fixes nonexistent identifiers that the model gets wrong even after
   training (Part 1400). The training fixes context relevance that the gate
   cannot reach (baseline-024). Neither layer alone reaches zero unsupported
   answers with one false refusal; together they do.
2. **Refusal share is a real dial with a real cost.** Going from 5.3 % to
   20.1 % refusal-required examples moved unsupported answers from 3 to 1 and
   false refusals from 3 to 1, but cost 14 answers that became source
   descriptions. The quantity was not the whole problem: the uniformity of
   the refusal frame was.
3. **Grounding and answering are separable and were traded, not both won.**
   The hallucination category reached a perfect 2.00 while general knowledge
   fell to 0.20.

Stage 14 therefore rebalances the data rather than training longer on the
same mixture: refusal share cut to 13.4 %, refusal openings varied, three
answer-side categories added that lead with substance
(`grounded_definition`, `grounded_topic`, `guidance_answer`), and the
guidance-context negative case added that Part 1400 exposed. See
`configs/training_v3.yaml` and `docs/stage14_overnight_training.md`.

The remaining open questions are unchanged by this stage: a full epoch needs
hardware this project does not have, and the reviewer scores need human
confirmation.
