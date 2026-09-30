# Regulus AI: metric reference

Every number the model evaluation dashboard shows is defined here. This file
is **generated** from `src/regulus/dashboard/metrics.py` by
`python scripts/generate_metric_docs.py`; the dashboard's ⓘ tooltips are
rendered from the same records, so the two cannot disagree. Do not edit it by
hand.

Three things are true of every entry:

* **A definition is not a judgment.** Each metric says what it measures and,
  just as importantly, what it does not prove. The caveat is part of the
  metric, not a footnote.
* **Direction is declared, never inferred.** A number going up is an
  improvement only where this file says higher is better.
* **Heuristics are labelled.** A metric marked HEURISTIC is an approximation
  with known failure modes, and the dashboard shows that badge beside it.

There is deliberately no composite score. Metrics move in different
directions for different reasons, and one number would hide which.


## Index

* **Evidence pipeline (model-free)** — [Retrieval Correctness](#retrieval-correctness), [Requirement Recall](#requirement-recall), [Per-question Requirement Recall](#per-question-requirement-recall), [Coverage Correctness](#coverage-correctness), [Missing-provision Labelling](#missing-provision-labelling), [Evidence-selection Correctness](#evidence-selection-correctness), [Protected Evidence Preserved](#protected-evidence-preserved), [Evidence Determinism](#evidence-determinism)

* **Retrieval ranking (model-free)** — [Recall@1](#recall1), [Recall@3](#recall3), [Recall@5](#recall5), [Recall@10](#recall10), [Mean Reciprocal Rank](#mean-reciprocal-rank), [Negative Controls Passed](#negative-controls-passed), [Queries Evaluated](#queries-evaluated)

* **Generation and deterministic validation** — [Deterministic Validation Pass (raw)](#deterministic-validation-pass-raw), [Deterministic Validation Pass (final)](#deterministic-validation-pass-final), [Validation Pass, Exact Evidence Only](#validation-pass-exact-evidence-only), [Truncated Answers](#truncated-answers), [Degenerate Answers](#degenerate-answers), [Completion Rate](#completion-rate), [Failed Questions](#failed-questions)

* **Composite correctness** — [Composite Correctness (raw)](#composite-correctness-raw), [Composite Correctness (final)](#composite-correctness-final), [Correct Only After Repair](#correct-only-after-repair), [Failures by Layer](#failures-by-layer)

* **Semantic faithfulness (heuristic)** — [Sentence Faithfulness (raw)](#sentence-faithfulness-raw), [Sentence Faithfulness (final)](#sentence-faithfulness-final), [Unsupported Sentences (raw)](#unsupported-sentences-raw), [Unsupported Sentences (final)](#unsupported-sentences-final), [Hallucination Rate (raw)](#hallucination-rate-raw), [Hallucination Rate (final)](#hallucination-rate-final)

* **Citations** — [Citation Validity](#citation-validity), [Exact-tier Citation Support](#exact-tier-citation-support)

* **Question-type behaviour** — [Refusal Correctness](#refusal-correctness), [False Refusals](#false-refusals), [False Answers](#false-answers), [Domain-boundary Leakage](#domain-boundary-leakage), [Multi-provision Accuracy](#multi-provision-accuracy), [Range Accuracy](#range-accuracy), [Partial / Missing-provision Behaviour](#partial--missing-provision-behaviour)

* **Deterministic repair** — [Repair Frequency](#repair-frequency), [Repair Success](#repair-success), [Repairs by Kind](#repairs-by-kind)

* **Latency and cost** — [Generation Latency p50](#generation-latency-p50), [Generation Latency p95](#generation-latency-p95), [End-to-end Latency p50](#end-to-end-latency-p50), [End-to-end Latency p95](#end-to-end-latency-p95), [Average Generated Tokens](#average-generated-tokens), [Run Duration](#run-duration), [Mean Retrieval Latency](#mean-retrieval-latency), [Worst Retrieval Latency](#worst-retrieval-latency), [Average Prompt Tokens](#average-prompt-tokens), [Generation Throughput](#generation-throughput), [Mean Generation Time](#mean-generation-time)

* **Run composition** — [Answers Generated](#answers-generated), [Questions Skipped Before Generation](#questions-skipped-before-generation), [Benchmark Questions](#benchmark-questions), [Questions Evaluated](#questions-evaluated)

* **Human judgment** — [Manual Reviewer Score (mean)](#manual-reviewer-score-mean)

* **Training process (NOT model quality)** — [Final Training Loss](#final-training-loss), [Final Validation Loss](#final-validation-loss), [Pre-training Validation Loss](#pre-training-validation-loss), [Validation Loss Change](#validation-loss-change), [Optimizer Steps](#optimizer-steps), [Epochs Completed](#epochs-completed), [Trainable Parameters](#trainable-parameters), [Training Examples](#training-examples), [Training Duration](#training-duration), [Best Validation Loss](#best-validation-loss), [Planned Optimizer Steps](#planned-optimizer-steps), [Validation Examples](#validation-examples), [Trainable Share of Parameters](#trainable-share-of-parameters)


## Evidence pipeline (model-free)

### Retrieval Correctness

`retrieval_ok`

Share of questions where the retriever found exact evidence for every provision the question asks about, and found nothing exact for provisions that do not exist.

| | |
|---|---|
| Calculation | questions with retrieval_ok = true / questions evaluated in the evidence phase |
| Direction | higher is better |
| Unit | ratio |
| Read from | `retrieval_results.json` |

**What it does not prove.** Measured without the model. A question whose requested provisions were mis-parsed by the planner fails here even though retrieval itself behaved correctly; the failure layer field distinguishes the two.

### Requirement Recall

`requirement_recall`

Share of individually requested provisions for which exact evidence was retrieved, pooled across all questions.

| | |
|---|---|
| Calculation | requested provisions with exact evidence / requested provisions that exist in the corpus |
| Direction | higher is better |
| Unit | ratio |
| Read from | `retrieval_results.json` |

**What it does not prove.** Pooled over provisions, not questions, so a single question asking for six paragraphs weighs six times a question asking for one.

### Per-question Requirement Recall

`question_recall`

Share of questions for which every requested provision that exists was retrieved.

| | |
|---|---|
| Calculation | questions with full requirement recall / questions with at least one requirement |
| Direction | higher is better |
| Unit | ratio |
| Read from | `retrieval_results.json` |

**What it does not prove.** All-or-nothing per question: retrieving five of six provisions counts as a miss.

### Coverage Correctness

`coverage_ok`

Share of questions where the coverage check reported the expected state (COMPLETE, INCOMPLETE or NO_EXPLICIT_REQUIREMENTS) for the evidence actually gathered.

| | |
|---|---|
| Calculation | questions with coverage_ok = true / questions evaluated |
| Direction | higher is better |
| Unit | ratio |
| Read from | `coverage_results.json` |

**What it does not prove.** Checks the state label and the set of provisions declared missing. It does not check that the evidence is sufficient to answer well.

### Missing-provision Labelling

`coverage_missing_ok`

Share of questions where the provisions the coverage check declared missing exactly match the provisions expected to be missing.

| | |
|---|---|
| Calculation | questions whose missing set equals the expected missing set / questions evaluated |
| Direction | higher is better |
| Unit | ratio |
| Read from | `coverage_results.json` |

**What it does not prove.** Expectations are hand-fixed against the database snapshot; a corpus update can invalidate them.

### Evidence-selection Correctness

`selection_ok`

Share of questions where selection kept every required exact provision within the context budget.

| | |
|---|---|
| Calculation | questions with selection_ok = true / questions evaluated |
| Direction | higher is better |
| Unit | ratio |
| Read from | `selection_results.json` |

**What it does not prove.** Selection can only keep what retrieval found, so this metric is conditioned on retrieval and should not be read alone.

### Protected Evidence Preserved

`protected_preserved`

Share of questions where no protected (required exact) evidence item was dropped by the budget.

| | |
|---|---|
| Calculation | questions with no protected item dropped / questions with at least one protected item |
| Direction | higher is better |
| Unit | ratio |
| Read from | `selection_results.json` |

**What it does not prove.** A drop here is a hard context failure: the model could not have answered correctly.

### Evidence Determinism

`evidence_deterministic`

Share of questions where repeating the evidence phase produced identical plans, evidence and selection.

| | |
|---|---|
| Calculation | questions with deterministic = true / questions evaluated |
| Direction | higher is better |
| Unit | ratio |
| Read from | `evidence_records.jsonl` |

**What it does not prove.** Non-determinism here would make every downstream comparison unsound, so this is a precondition, not a quality measure.

## Retrieval ranking (model-free)

### Recall@1

`recall_at_1`

Share of queries whose expected source is the top-ranked result.

| | |
|---|---|
| Calculation | queries with first_hit_rank = 1 / scored queries |
| Direction | higher is better |
| Unit | ratio |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** Measured on the retrieval benchmark, not the answer benchmark, and with no model in the loop. It says nothing about whether an answer built on that source is right.

### Recall@3

`recall_at_3`

Share of queries whose expected source appears in the top three results.

| | |
|---|---|
| Calculation | queries with first_hit_rank <= 3 / scored queries |
| Direction | higher is better |
| Unit | ratio |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** Recall at a larger k is never lower than at a smaller k, so the four recall figures must be read as a curve, not compared against each other as if they were independent.

### Recall@5

`recall_at_5`

Share of queries whose expected source appears in the top five results.

| | |
|---|---|
| Calculation | queries with first_hit_rank <= 5 / scored queries |
| Direction | higher is better |
| Unit | ratio |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** Only meaningful against the same retrieval benchmark; a different query set makes the number incomparable.

### Recall@10

`recall_at_10`

Share of queries whose expected source appears in the top ten results.

| | |
|---|---|
| Calculation | queries with first_hit_rank <= 10 / scored queries |
| Direction | higher is better |
| Unit | ratio |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** The generation pipeline only ever sees the top-k it is configured for, so recall beyond that k is diagnostic, not a property of the answering system.

### Mean Reciprocal Rank

`mrr`

Mean of one divided by the rank of the first correct result, over the scored queries.

| | |
|---|---|
| Calculation | sum of 1 / first_hit_rank / scored queries |
| Direction | higher is better |
| Unit | ratio |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** Rewards putting the right source first rather than merely somewhere in the list. A query with no hit contributes zero.

### Negative Controls Passed

`negative_control_pass`

Share of deliberately unanswerable queries for which the retriever correctly returned nothing relevant.

| | |
|---|---|
| Calculation | negative controls passed / negative controls |
| Direction | higher is better |
| Unit | ratio |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** The negative-control set is small, so this figure moves a long way on one query. Read it with its denominator.

### Queries Evaluated

`retrieval_queries`

Number of queries in the retrieval benchmark run.

| | |
|---|---|
| Calculation | count of query records |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** Negative controls are included here but excluded from the recall denominators.

## Generation and deterministic validation

### Deterministic Validation Pass (raw)

`valid_raw`

Share of generated answers that pass every deterministic validation check before any repair is applied.

| | |
|---|---|
| Calculation | answers with validation status = valid / answers generated |
| Direction | higher is better |
| Unit | ratio |
| Read from | `generation_results.json` |

**What it does not prove.** Passing validation means nothing checkable is wrong. It is not a judgment that the answer is right; see composite correctness.

### Deterministic Validation Pass (final)

`valid_final`

Share of answers that pass deterministic validation after the deterministic repair layer has run.

| | |
|---|---|
| Calculation | answers with final validation status = valid / answers generated |
| Direction | higher is better |
| Unit | ratio |
| Read from | `generation_results.json` |

**What it does not prove.** This is a property of the pipeline, not of the model. Never read it as model quality, and never compare it against another run's raw figure.

### Validation Pass, Exact Evidence Only

`valid_raw_controlled`

Raw validation pass rate in the controlled condition, where the model is given only the exact evidence for the requested provisions.

| | |
|---|---|
| Calculation | controlled answers with validation status = valid / controlled answers generated |
| Direction | higher is better |
| Unit | ratio |
| Read from | `generation_controlled.jsonl` |

**What it does not prove.** The controlled condition runs only on questions that have exact evidence, so its denominator differs from the full pipeline's. Compare the two rates, never the two counts.

### Truncated Answers

`truncated_count`

Number of answers that hit the token budget before finishing.

| | |
|---|---|
| Calculation | count of answers flagged truncated by the validator |
| Direction | lower is better |
| Unit | count |
| Read from | `generation_results.json` |

**What it does not prove.** Truncation is a budget symptom as much as a model symptom; the generation budget is computed per question from the number of requested provisions.

### Degenerate Answers

`degenerate_count`

Number of answers rejected as degenerate or empty output.

| | |
|---|---|
| Calculation | count of answers with a degenerate or empty validation code |
| Direction | lower is better |
| Unit | count |
| Read from | `generation_results.json` |

**What it does not prove.** Detected by deterministic heuristics on repetition and length.

### Completion Rate

`completion_rate`

Share of questions for which the run produced an answer without erroring.

| | |
|---|---|
| Calculation | completed questions / questions attempted |
| Direction | higher is better |
| Unit | ratio |
| Read from | `data/evaluation/results/*.json` |

**What it does not prove.** Completing is not answering well. This only says the pipeline did not crash or time out.

### Failed Questions

`failed_count`

Number of questions that errored instead of producing an answer.

| | |
|---|---|
| Calculation | count of results with status != completed |
| Direction | lower is better |
| Unit | count |
| Read from | `data/evaluation/results/*.json` |

**What it does not prove.** The failing question ids are listed so the cause can be read rather than guessed.

## Composite correctness

### Composite Correctness (raw)

`correctness_raw`

Share of questions whose raw model answer satisfies every machine-checkable expectation: deterministic validation passed, every requested provision with exact evidence was addressed, the refusal expectation was met, the expected terms appear, and no claim was flagged unsupported by its cited source.

| | |
|---|---|
| Calculation | questions meeting all conditions / questions in the benchmark |
| Direction | higher is better |
| Unit | ratio |
| Read from | `correctness_results.json` |

**What it does not prove.** This is not human-judged accuracy. An answer can satisfy every condition and still be a poor answer; the conditions are necessary, not sufficient.

### Composite Correctness (final)

`correctness_final`

The same composite computed over the repaired answer that a user would actually see.

| | |
|---|---|
| Calculation | questions meeting all conditions after repair / questions in the benchmark |
| Direction | higher is better |
| Unit | ratio |
| Read from | `correctness_results.json` |

**What it does not prove.** Measures the product, not the model. The gap between raw and final is the deterministic repair layer doing work, and must be reported alongside it.

### Correct Only After Repair

`correct_only_after_repair`

Number of questions that are incorrect in the raw model answer and correct only because deterministic repair rewrote them.

| | |
|---|---|
| Calculation | count of questions with correct_raw = false and correct_final = true |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `correctness_results.json` |

**What it does not prove.** This count is the honest size of the raw-versus-final gap. A rise in final correctness that is entirely this number is not model improvement.

### Failures by Layer

`failure_layer_counts`

Per-question attribution of the layer responsible for a failure: retrieval, generation_context, generation, validation, domain_boundary, or none.

| | |
|---|---|
| Calculation | count of questions per attributed layer |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `failure_analysis.json` |

**What it does not prove.** Attribution compares the full pipeline against the controlled exact-evidence condition. A question failing in both is attributed to generation; failing only in the full pipeline is attributed to context.

## Semantic faithfulness (heuristic)

### Sentence Faithfulness (raw)

`faithfulness_raw`  ·  **HEURISTIC**

Share of answer sentences judged SUPPORTED by the source they cite, over the raw model answers.

| | |
|---|---|
| Calculation | sentences labelled SUPPORTED / sentences classified |
| Direction | higher is better |
| Unit | ratio |
| Read from | `semantic_faithfulness_results.json` |

**What it does not prove.** Word overlap is not entailment. SUPPORTED requires an exact-tier citation and at least half the content words shared, which a wrong paraphrase can satisfy. Read NOT SUPPORTED as reliable and SUPPORTED as unproven.

### Sentence Faithfulness (final)

`faithfulness_final`  ·  **HEURISTIC**

The same sentence-level measure over the repaired answers.

| | |
|---|---|
| Calculation | sentences labelled SUPPORTED / sentences classified after repair |
| Direction | higher is better |
| Unit | ratio |
| Read from | `semantic_faithfulness_results.json` |

**What it does not prove.** Repair replaces unsupported sentences with verbatim extracts, which raises this measure by construction. It says nothing about the model.

### Unsupported Sentences (raw)

`unsupported_sentences_raw`  ·  **HEURISTIC**

Number of sentences in raw answers that a deterministic check contradicted, or that share under a quarter of their content words with what they cite.

| | |
|---|---|
| Calculation | count of sentences labelled NOT SUPPORTED before repair |
| Direction | lower is better |
| Unit | count |
| Read from | `semantic_faithfulness_results.json` |

**What it does not prove.** This label is the reliable half of the faithfulness heuristic: each one has a concrete reason attached.

### Unsupported Sentences (final)

`unsupported_sentences_final`  ·  **HEURISTIC**

The same count over the repaired answers.

| | |
|---|---|
| Calculation | count of sentences labelled NOT SUPPORTED after repair |
| Direction | lower is better |
| Unit | count |
| Read from | `semantic_faithfulness_results.json` |

**What it does not prove.** Any remaining unsupported sentence survived the repair layer and deserves individual inspection.

### Hallucination Rate (raw)

`hallucination_raw`

Share of generated answers containing at least one identifier, figure or provision that appears in no supplied source.

| | |
|---|---|
| Calculation | answers with at least one fabricated element / answers generated |
| Direction | lower is better |
| Unit | ratio |
| Read from | `hallucination_results.json` |

**What it does not prove.** Detected deterministically by comparing identifiers and numbers in the answer against the evidence package. It catches fabricated citations and figures, not wrong reasoning stated in the source's own words.

### Hallucination Rate (final)

`hallucination_final`

The same measure over the repaired answers.

| | |
|---|---|
| Calculation | repaired answers with at least one fabricated element / answers generated |
| Direction | lower is better |
| Unit | ratio |
| Read from | `hallucination_results.json` |

**What it does not prove.** Repair removes invalid citations and unsupported statements, so a fall here is largely the repair layer.

## Citations

### Citation Validity

`citation_ok`

Share of answers in which every citation is well-formed and points at a source that was actually supplied.

| | |
|---|---|
| Calculation | answers with no invalid or malformed citation / answers generated |
| Direction | higher is better |
| Unit | ratio |
| Read from | `citation_results.json` |

**What it does not prove.** Checks that the cited source exists in the package, not that it supports the sentence attached to it.

### Exact-tier Citation Support

`exact_source_citation`

Share of requirement statements supported by a citation to an exact-tier source rather than a structural, supporting or discovery source.

| | |
|---|---|
| Calculation | requirement statements citing an exact source / requirement statements with a citation |
| Direction | higher is better |
| Unit | ratio |
| Read from | `citation_results.json` |

**What it does not prove.** Citing a discovery-tier source for a requirement is a specific validation code; this metric aggregates it.

## Question-type behaviour

### Refusal Correctness

`refusal_correct`

Share of questions where the system declined to answer exactly when it should have: declining questions with no supporting evidence and answering those with evidence.

| | |
|---|---|
| Calculation | questions whose refusal behaviour matches the expectation / questions with a refusal expectation |
| Direction | higher is better |
| Unit | ratio |
| Read from | `refusal_results.json` |

**What it does not prove.** Counts both error kinds together. The false-refusal and false-answer lists name the individual questions.

### False Refusals

`false_refusal_count`

Number of answerable questions the system declined.

| | |
|---|---|
| Calculation | count of questions expected to be answered that were declined |
| Direction | lower is better |
| Unit | count |
| Read from | `refusal_results.json` |

**What it does not prove.** Each one is listed by question id, because the count alone hides whether the cause is retrieval or the model.

### False Answers

`false_answer_count`

Number of questions that should have been declined but received a substantive answer.

| | |
|---|---|
| Calculation | count of questions expected to be declined that were answered |
| Direction | lower is better |
| Unit | count |
| Read from | `refusal_results.json` |

**What it does not prove.** The more dangerous of the two refusal errors in a regulatory setting.

### Domain-boundary Leakage

`domain_leak_rate`

Share of out-of-scope questions answered as if they were in scope instead of being declined or bounded.

| | |
|---|---|
| Calculation | out-of-scope questions answered substantively / out-of-scope questions |
| Direction | lower is better |
| Unit | ratio |
| Read from | `domain_boundary_results.json` |

**What it does not prove.** The out-of-scope set is small, so a single question moves this figure a long way. Always read it with its denominator.

### Multi-provision Accuracy

`multi_provision_accuracy`

Share of questions requesting several named provisions where every one of them is addressed.

| | |
|---|---|
| Calculation | multi-provision questions with all provisions addressed / multi-provision questions |
| Direction | higher is better |
| Unit | ratio |
| Read from | `behaviour_results.json` |

**What it does not prove.** Addressed means the provision identifier and its requirement appear; it is not a judgment of how well it was stated.

### Range Accuracy

`range_accuracy`

Share of questions requesting a range of paragraphs where every paragraph in the range is addressed.

| | |
|---|---|
| Calculation | range questions fully addressed / range questions |
| Direction | higher is better |
| Unit | ratio |
| Read from | `behaviour_results.json` |

**What it does not prove.** Ranges whose endpoints do not exist are handled by the missing-provision behaviour instead.

### Partial / Missing-provision Behaviour

`partial_behaviour_ok`

Share of questions containing a provision that does not exist where the answer states the absence instead of inventing content for it.

| | |
|---|---|
| Calculation | questions correctly declaring the absence / questions with an expected missing provision |
| Direction | higher is better |
| Unit | ratio |
| Read from | `behaviour_results.json` |

**What it does not prove.** Asserting that an existing provision is missing is a separate validation code and counts as a failure here too.

## Deterministic repair

### Repair Frequency

`repair_rate`

Share of generated answers the deterministic repair layer had to modify.

| | |
|---|---|
| Calculation | answers with a repair applied / answers generated |
| Direction | lower is better |
| Unit | ratio |
| Read from | `repair_results.json` |

**What it does not prove.** Lower is better as a statement about the model, but a repair is a safety action: a low repair rate together with a low raw validation rate is worse, not better. Read it beside valid_raw.

### Repair Success

`repair_success`

Share of repairs after which the answer passes deterministic validation.

| | |
|---|---|
| Calculation | repairs producing a valid answer / repairs applied |
| Direction | higher is better |
| Unit | ratio |
| Read from | `repair_results.json` |

**What it does not prove.** Success means the repaired text is valid, not that it answers the question; extractive replacement can produce a valid but unhelpful answer.

### Repairs by Kind

`repair_kind_counts`

Counts of each repair action: extractive replacement, safe message, invalid citations removed, mismatched statements replaced, appended missing provisions, truncation noted.

| | |
|---|---|
| Calculation | count of repairs per kind |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `repair_results.json` |

**What it does not prove.** The mix matters more than the total: a rise in safe messages means more questions are being declined at the last step.

## Latency and cost

### Generation Latency p50

`generation_latency_p50`

Median wall-clock time spent inside model generation for one question.

| | |
|---|---|
| Calculation | 50th percentile of per-question generation duration |
| Direction | lower is better |
| Unit | seconds |
| Read from | `latency_results.json` |

**What it does not prove.** Measured on this CPU-only machine while nothing else ran. It is not comparable with a run made under different load or on different hardware.

### Generation Latency p95

`generation_latency_p95`

95th percentile of model generation time for one question.

| | |
|---|---|
| Calculation | 95th percentile of per-question generation duration |
| Direction | lower is better |
| Unit | seconds |
| Read from | `latency_results.json` |

**What it does not prove.** Dominated by the longest answers, so it tracks the per-question token budget as much as model speed.

### End-to-end Latency p50

`e2e_latency_p50`

Median wall-clock time from question to final answer, including planning, retrieval, selection, generation, validation and repair.

| | |
|---|---|
| Calculation | 50th percentile of per-question total duration |
| Direction | lower is better |
| Unit | seconds |
| Read from | `latency_results.json` |

**What it does not prove.** The evidence phases contribute well under a second; the difference from generation latency is mostly database access.

### End-to-end Latency p95

`e2e_latency_p95`

95th percentile of total time from question to final answer.

| | |
|---|---|
| Calculation | 95th percentile of per-question total duration |
| Direction | lower is better |
| Unit | seconds |
| Read from | `latency_results.json` |

**What it does not prove.** Same hardware caveat as the other latency figures.

### Average Generated Tokens

`avg_generated_tokens`

Mean number of tokens the model produced per answer.

| | |
|---|---|
| Calculation | sum of generated tokens / answers generated |
| Direction | informational — neither direction is better |
| Unit | tokens |
| Read from | `generation_full.jsonl` |

**What it does not prove.** Neither more nor fewer tokens is better; the figure explains latency and truncation.

### Run Duration

`run_duration`

Total wall-clock duration of the evaluation run.

| | |
|---|---|
| Calculation | completed_at minus started_at |
| Direction | informational — neither direction is better |
| Unit | seconds |
| Read from | `run_manifest.json` |

**What it does not prove.** Includes resumed segments if the run was interrupted and continued.

### Mean Retrieval Latency

`retrieval_latency_avg`

Mean wall-clock time to answer one retrieval query.

| | |
|---|---|
| Calculation | mean of per-query total duration |
| Direction | lower is better |
| Unit | seconds |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** Hardware-bound and measured without the model loaded, so it is not comparable with the end-to-end latency of an answering run.

### Worst Retrieval Latency

`retrieval_latency_max`

The slowest single retrieval query in the run.

| | |
|---|---|
| Calculation | maximum of per-query total duration |
| Direction | lower is better |
| Unit | seconds |
| Read from | `data/evaluation/results/retrieval-*.json` |

**What it does not prove.** A single outlier, usually a fallback query that had to widen its terms.

### Average Prompt Tokens

`avg_prompt_tokens`

Mean number of tokens sent to the model per question, prompt and retrieved context together.

| | |
|---|---|
| Calculation | sum of input tokens / questions answered |
| Direction | informational — neither direction is better |
| Unit | tokens |
| Read from | `data/evaluation/results/*.json` |

**What it does not prove.** Driven by the context budget, not by model quality. It explains latency.

### Generation Throughput

`tokens_per_second`

Tokens produced per second of model generation time.

| | |
|---|---|
| Calculation | mean or median of generated tokens divided by generation seconds |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `data/evaluation/results/*.json` |

**What it does not prove.** A hardware measurement on this CPU-only machine. It changes with load, not with model quality.

### Mean Generation Time

`avg_generation_seconds`

Mean wall-clock time spent generating one answer.

| | |
|---|---|
| Calculation | total generation seconds / questions answered |
| Direction | lower is better |
| Unit | seconds |
| Read from | `data/evaluation/results/*.json` |

**What it does not prove.** A mean, unlike the Stage 5 percentiles, so one very slow answer moves it. Do not compare it against a p50.

## Run composition

### Answers Generated

`generated_count`

Number of questions for which the model was actually invoked.

| | |
|---|---|
| Calculation | count of questions with generated = true |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `generation_full.jsonl` |

**What it does not prove.** Questions skipped by the pipeline (a deterministic refusal before generation, or no context) are excluded, which is why generation denominators are smaller than the benchmark size.

### Questions Skipped Before Generation

`skipped_count`

Number of questions the pipeline answered deterministically without calling the model.

| | |
|---|---|
| Calculation | count of questions with a skipped_reason |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `generation_full.jsonl` |

**What it does not prove.** A skip can be correct behaviour (declining an out-of-scope question) or a failure (declining an answerable one). The refusal metrics separate them.

### Benchmark Questions

`benchmark_questions`

Number of questions in the benchmark this run was evaluated against.

| | |
|---|---|
| Calculation | count of questions in the benchmark file |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `run_manifest.json` |

**What it does not prove.** Two runs are only comparable when the benchmark content hash matches, not merely the count.

### Questions Evaluated

`questions_evaluated`

Number of benchmark questions this run actually produced a record for.

| | |
|---|---|
| Calculation | count of per-question records |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `generation_full.jsonl` |

**What it does not prove.** Fewer than the benchmark size means the run is partial, and it is marked INCOMPLETE.

## Human judgment

### Manual Reviewer Score (mean)

`manual_score_mean`  ·  **HEURISTIC**

Mean of the scores a human reviewer recorded for the answers in a legacy benchmark run.

| | |
|---|---|
| Calculation | sum of manual scores / answers with a manual score |
| Direction | higher is better |
| Unit | score |
| Read from | `data/evaluation/results/*.json` |

**What it does not prove.** A human judgment entered by hand, on a small sample, by one reviewer without a published rubric. The artifact does not record the scale, so the number is shown exactly as it was written and never as a percentage. It is recorded for provenance, not treated as a measurement, and must not be compared across runs scored by different people.

## Training process (NOT model quality)

### Final Training Loss

`final_train_loss`

Mean training loss over the final logged window of the run.

| | |
|---|---|
| Calculation | train_loss reported by the trainer at the end of training |
| Direction | lower is better |
| Unit | ratio |
| Read from | `training_metrics.json` |

**What it does not prove.** A training-process diagnostic only. Lower training loss does NOT mean a better regulatory model: it can equally mean memorisation, a narrower answer style, or an easier dataset. Only an evaluation run on a benchmark can say whether answer quality changed.

### Final Validation Loss

`final_eval_loss`

Loss on the held-out validation split at the end of training.

| | |
|---|---|
| Calculation | eval_loss from the final evaluation entry of the trainer log |
| Direction | lower is better |
| Unit | ratio |
| Read from | `training_metrics.json` |

**What it does not prove.** Held-out loss is a better generalisation signal than training loss, and still not an accuracy measure. The validation split comes from the same generators as the training data, so it does not test the benchmark's distribution.

### Pre-training Validation Loss

`base_eval_loss`

Validation loss measured on the base model before any optimizer step.

| | |
|---|---|
| Calculation | eval_loss from the evaluation performed before training began |
| Direction | lower is better |
| Unit | ratio |
| Read from | `training_metrics.json` |

**What it does not prove.** The reference point for the training delta. Measured on the same validation split, so it shares its limitations.

### Validation Loss Change

`eval_loss_delta`

Final validation loss minus pre-training validation loss.

| | |
|---|---|
| Calculation | final_eval_loss - base_eval_loss |
| Direction | lower is better |
| Unit | ratio |
| Read from | `training_metrics.json` |

**What it does not prove.** Shows that training moved the model on its own data distribution. It is not evidence of improved answers and must never be displayed beside evaluation accuracy as though the two were the same kind of number.

### Optimizer Steps

`total_steps`

Number of optimizer steps completed.

| | |
|---|---|
| Calculation | global_step at the end of training |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `trainer_state.json` |

**What it does not prove.** Read with epochs, batch size and gradient accumulation; the raw count means little alone.

### Epochs Completed

`epochs_completed`

Number of passes over the training set that finished.

| | |
|---|---|
| Calculation | epoch value at the end of training |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `training_metrics.json` |

**What it does not prove.** A fractional value means the run stopped mid-epoch.

### Trainable Parameters

`trainable_parameters`

Number of parameters the optimizer updated, which for LoRA is the adapter only.

| | |
|---|---|
| Calculation | count reported by the model at training start |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `training_summary.json` |

**What it does not prove.** The base weights are frozen and unchanged; the adapter is a separate artifact that can be detached.

### Training Examples

`training_examples`

Number of examples in the training split after deduplication and benchmark exclusion.

| | |
|---|---|
| Calculation | count of training examples in the dataset manifest |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `dataset_manifest.json` |

**What it does not prove.** Benchmark exclusion removes whole section and part groups, so this count is lower than the generated total by design.

### Training Duration

`training_duration`

Wall-clock duration of the training run.

| | |
|---|---|
| Calculation | train_runtime reported by the trainer |
| Direction | informational — neither direction is better |
| Unit | seconds |
| Read from | `training_metrics.json` |

**What it does not prove.** On this CPU-only machine duration is dominated by hardware, not by the configuration.

### Best Validation Loss

`best_eval_loss`

The lowest validation loss any evaluated checkpoint reached, and the checkpoint the trainer therefore selected.

| | |
|---|---|
| Calculation | best_metric from the trainer state |
| Direction | lower is better |
| Unit | ratio |
| Read from | `trainer_state.json` |

**What it does not prove.** Selecting the checkpoint with the lowest held-out loss is a training-time decision made on the training data's own distribution. Whether that checkpoint answers regulatory questions better is an open question until it is evaluated on a benchmark.

### Planned Optimizer Steps

`planned_steps`

The number of steps the run was configured to take.

| | |
|---|---|
| Calculation | max_steps from the trainer state |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `trainer_state.json` |

**What it does not prove.** A completed step count well below this means the run stopped early, whether by design or by failure.

### Validation Examples

`validation_examples`

Number of held-out examples the validation loss was measured on.

| | |
|---|---|
| Calculation | count of validation examples in the dataset manifest |
| Direction | informational — neither direction is better |
| Unit | count |
| Read from | `metadata.json` |

**What it does not prove.** A small validation subset makes the loss noisy; read the loss curve, not a single point.

### Trainable Share of Parameters

`trainable_percent`

The fraction of the model's parameters the optimizer updated.

| | |
|---|---|
| Calculation | trainable parameters / total parameters |
| Direction | informational — neither direction is better |
| Unit | ratio |
| Read from | `training_summary.json` |

**What it does not prove.** For LoRA this is small by construction and says nothing about how much behaviour changed.


## Reading these together

A few pairings matter more than any single figure.

* **Raw against final.** `valid_raw` and `correctness_raw` describe the
  model. `valid_final` and `correctness_final` describe the product after the
  deterministic repair layer has run. `correct_only_after_repair` is the
  honest size of the gap between them. A rise in the final figure that is
  entirely that count is not model improvement.
* **The full pipeline against exact evidence only.** `valid_raw` and
  `valid_raw_controlled` answer different questions: the first asks whether
  the system works, the second whether the model can work when the evidence
  is perfect. A failure in both is the model; a failure only in the first is
  the context.
* **Repair frequency beside raw validation.** A low `repair_rate` is good
  only when `valid_raw` is high. Low repair with low raw validation means
  problems are going out unrepaired.
* **Training loss against nothing at all.** `final_train_loss` and
  `final_eval_loss` belong to the training process. They are never evidence
  that answers improved; only an evaluation run on a benchmark can show that.


---

73 metrics across 12 families.
