"""The metric definition registry.

Single source of truth for what every number on the dashboard means, how it
is calculated, which direction is better, and what it does not prove. The
API serves it, the UI renders its tooltips from it, and
`docs/model_dashboard_metrics.md` is generated from it, so the three cannot
drift apart.

Adding a metric to an adapter without adding it here raises.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .schemas import (
    COUNT,
    HIGHER_IS_BETTER,
    INCONSISTENT,
    INFORMATIONAL,
    LOWER_IS_BETTER,
    MISSING,
    OK,
    RATIO,
    SCORE,
    SECONDS,
    TOKENS,
    MetricResult,
)

# metric families, used to group the UI and the generated document
EVIDENCE = "evidence"
RETRIEVAL = "retrieval"
GENERATION = "generation"
CORRECTNESS = "correctness"
FAITHFULNESS = "faithfulness"
CITATION = "citation"
BEHAVIOUR = "behaviour"
REPAIR = "repair"
COST = "cost"
TRAINING = "training"
DATASET = "dataset"
HUMAN = "human"

FAMILY_ORDER = (
    EVIDENCE, RETRIEVAL, GENERATION, CORRECTNESS, FAITHFULNESS, CITATION,
    BEHAVIOUR, REPAIR, COST, DATASET, HUMAN, TRAINING,
)

FAMILY_TITLES = {
    EVIDENCE: "Evidence pipeline (model-free)",
    RETRIEVAL: "Retrieval ranking (model-free)",
    GENERATION: "Generation and deterministic validation",
    CORRECTNESS: "Composite correctness",
    FAITHFULNESS: "Semantic faithfulness (heuristic)",
    CITATION: "Citations",
    BEHAVIOUR: "Question-type behaviour",
    REPAIR: "Deterministic repair",
    COST: "Latency and cost",
    DATASET: "Run composition",
    HUMAN: "Human judgment",
    TRAINING: "Training process (NOT model quality)",
}


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    name: str
    family: str
    definition: str
    calculation: str
    direction: str
    unit: str = RATIO
    caveats: str = ""
    heuristic: bool = False
    source_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _d(**kwargs: Any) -> MetricDefinition:
    return MetricDefinition(**kwargs)


_DEFINITIONS: tuple[MetricDefinition, ...] = (
    # ---------------------------------------------------------------- evidence
    _d(
        key="retrieval_ok", name="Retrieval Correctness", family=EVIDENCE,
        definition="Share of questions where the retriever found exact evidence for every provision the question asks about, and found nothing exact for provisions that do not exist.",
        calculation="questions with retrieval_ok = true / questions evaluated in the evidence phase",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Measured without the model. A question whose requested provisions were mis-parsed by the planner fails here even though retrieval itself behaved correctly; the failure layer field distinguishes the two.",
        source_hint="retrieval_results.json",
    ),
    _d(
        key="requirement_recall", name="Requirement Recall", family=EVIDENCE,
        definition="Share of individually requested provisions for which exact evidence was retrieved, pooled across all questions.",
        calculation="requested provisions with exact evidence / requested provisions that exist in the corpus",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Pooled over provisions, not questions, so a single question asking for six paragraphs weighs six times a question asking for one.",
        source_hint="retrieval_results.json",
    ),
    _d(
        key="question_recall", name="Per-question Requirement Recall", family=EVIDENCE,
        definition="Share of questions for which every requested provision that exists was retrieved.",
        calculation="questions with full requirement recall / questions with at least one requirement",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="All-or-nothing per question: retrieving five of six provisions counts as a miss.",
        source_hint="retrieval_results.json",
    ),
    _d(
        key="coverage_ok", name="Coverage Correctness", family=EVIDENCE,
        definition="Share of questions where the coverage check reported the expected state (COMPLETE, INCOMPLETE or NO_EXPLICIT_REQUIREMENTS) for the evidence actually gathered.",
        calculation="questions with coverage_ok = true / questions evaluated",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Checks the state label and the set of provisions declared missing. It does not check that the evidence is sufficient to answer well.",
        source_hint="coverage_results.json",
    ),
    _d(
        key="coverage_missing_ok", name="Missing-provision Labelling", family=EVIDENCE,
        definition="Share of questions where the provisions the coverage check declared missing exactly match the provisions expected to be missing.",
        calculation="questions whose missing set equals the expected missing set / questions evaluated",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Expectations are hand-fixed against the database snapshot; a corpus update can invalidate them.",
        source_hint="coverage_results.json",
    ),
    _d(
        key="selection_ok", name="Evidence-selection Correctness", family=EVIDENCE,
        definition="Share of questions where selection kept every required exact provision within the context budget.",
        calculation="questions with selection_ok = true / questions evaluated",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Selection can only keep what retrieval found, so this metric is conditioned on retrieval and should not be read alone.",
        source_hint="selection_results.json",
    ),
    _d(
        key="protected_preserved", name="Protected Evidence Preserved", family=EVIDENCE,
        definition="Share of questions where no protected (required exact) evidence item was dropped by the budget.",
        calculation="questions with no protected item dropped / questions with at least one protected item",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="A drop here is a hard context failure: the model could not have answered correctly.",
        source_hint="selection_results.json",
    ),
    _d(
        key="evidence_deterministic", name="Evidence Determinism", family=EVIDENCE,
        definition="Share of questions where repeating the evidence phase produced identical plans, evidence and selection.",
        calculation="questions with deterministic = true / questions evaluated",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Non-determinism here would make every downstream comparison unsound, so this is a precondition, not a quality measure.",
        source_hint="evidence_records.jsonl",
    ),
    # -------------------------------------------------------------- generation
    _d(
        key="valid_raw", name="Deterministic Validation Pass (raw)", family=GENERATION,
        definition="Share of generated answers that pass every deterministic validation check before any repair is applied.",
        calculation="answers with validation status = valid / answers generated",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Passing validation means nothing checkable is wrong. It is not a judgment that the answer is right; see composite correctness.",
        source_hint="generation_results.json",
    ),
    _d(
        key="valid_final", name="Deterministic Validation Pass (final)", family=GENERATION,
        definition="Share of answers that pass deterministic validation after the deterministic repair layer has run.",
        calculation="answers with final validation status = valid / answers generated",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="This is a property of the pipeline, not of the model. Never read it as model quality, and never compare it against another run's raw figure.",
        source_hint="generation_results.json",
    ),
    _d(
        key="valid_raw_controlled", name="Validation Pass, Exact Evidence Only", family=GENERATION,
        definition="Raw validation pass rate in the controlled condition, where the model is given only the exact evidence for the requested provisions.",
        calculation="controlled answers with validation status = valid / controlled answers generated",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="The controlled condition runs only on questions that have exact evidence, so its denominator differs from the full pipeline's. Compare the two rates, never the two counts.",
        source_hint="generation_controlled.jsonl",
    ),
    _d(
        key="generated_count", name="Answers Generated", family=DATASET,
        definition="Number of questions for which the model was actually invoked.",
        calculation="count of questions with generated = true",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="Questions skipped by the pipeline (a deterministic refusal before generation, or no context) are excluded, which is why generation denominators are smaller than the benchmark size.",
        source_hint="generation_full.jsonl",
    ),
    _d(
        key="skipped_count", name="Questions Skipped Before Generation", family=DATASET,
        definition="Number of questions the pipeline answered deterministically without calling the model.",
        calculation="count of questions with a skipped_reason",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="A skip can be correct behaviour (declining an out-of-scope question) or a failure (declining an answerable one). The refusal metrics separate them.",
        source_hint="generation_full.jsonl",
    ),
    _d(
        key="truncated_count", name="Truncated Answers", family=GENERATION,
        definition="Number of answers that hit the token budget before finishing.",
        calculation="count of answers flagged truncated by the validator",
        direction=LOWER_IS_BETTER, unit=COUNT,
        caveats="Truncation is a budget symptom as much as a model symptom; the generation budget is computed per question from the number of requested provisions.",
        source_hint="generation_results.json",
    ),
    _d(
        key="degenerate_count", name="Degenerate Answers", family=GENERATION,
        definition="Number of answers rejected as degenerate or empty output.",
        calculation="count of answers with a degenerate or empty validation code",
        direction=LOWER_IS_BETTER, unit=COUNT,
        caveats="Detected by deterministic heuristics on repetition and length.",
        source_hint="generation_results.json",
    ),
    # ------------------------------------------------------------- correctness
    _d(
        key="correctness_raw", name="Composite Correctness (raw)", family=CORRECTNESS,
        definition="Share of questions whose raw model answer satisfies every machine-checkable expectation: deterministic validation passed, every requested provision with exact evidence was addressed, the refusal expectation was met, the expected terms appear, and no claim was flagged unsupported by its cited source.",
        calculation="questions meeting all conditions / questions in the benchmark",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="This is not human-judged accuracy. An answer can satisfy every condition and still be a poor answer; the conditions are necessary, not sufficient.",
        source_hint="correctness_results.json",
    ),
    _d(
        key="correctness_final", name="Composite Correctness (final)", family=CORRECTNESS,
        definition="The same composite computed over the repaired answer that a user would actually see.",
        calculation="questions meeting all conditions after repair / questions in the benchmark",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Measures the product, not the model. The gap between raw and final is the deterministic repair layer doing work, and must be reported alongside it.",
        source_hint="correctness_results.json",
    ),
    _d(
        key="correct_only_after_repair", name="Correct Only After Repair", family=CORRECTNESS,
        definition="Number of questions that are incorrect in the raw model answer and correct only because deterministic repair rewrote them.",
        calculation="count of questions with correct_raw = false and correct_final = true",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="This count is the honest size of the raw-versus-final gap. A rise in final correctness that is entirely this number is not model improvement.",
        source_hint="correctness_results.json",
    ),
    _d(
        key="failure_layer_counts", name="Failures by Layer", family=CORRECTNESS,
        definition="Per-question attribution of the layer responsible for a failure: retrieval, generation_context, generation, validation, domain_boundary, or none.",
        calculation="count of questions per attributed layer",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="Attribution compares the full pipeline against the controlled exact-evidence condition. A question failing in both is attributed to generation; failing only in the full pipeline is attributed to context.",
        source_hint="failure_analysis.json",
    ),
    # ------------------------------------------------------------ faithfulness
    _d(
        key="faithfulness_raw", name="Sentence Faithfulness (raw)", family=FAITHFULNESS,
        definition="Share of answer sentences judged SUPPORTED by the source they cite, over the raw model answers.",
        calculation="sentences labelled SUPPORTED / sentences classified",
        direction=HIGHER_IS_BETTER, unit=RATIO, heuristic=True,
        caveats="Word overlap is not entailment. SUPPORTED requires an exact-tier citation and at least half the content words shared, which a wrong paraphrase can satisfy. Read NOT SUPPORTED as reliable and SUPPORTED as unproven.",
        source_hint="semantic_faithfulness_results.json",
    ),
    _d(
        key="faithfulness_final", name="Sentence Faithfulness (final)", family=FAITHFULNESS,
        definition="The same sentence-level measure over the repaired answers.",
        calculation="sentences labelled SUPPORTED / sentences classified after repair",
        direction=HIGHER_IS_BETTER, unit=RATIO, heuristic=True,
        caveats="Repair replaces unsupported sentences with verbatim extracts, which raises this measure by construction. It says nothing about the model.",
        source_hint="semantic_faithfulness_results.json",
    ),
    _d(
        key="unsupported_sentences_raw", name="Unsupported Sentences (raw)", family=FAITHFULNESS,
        definition="Number of sentences in raw answers that a deterministic check contradicted, or that share under a quarter of their content words with what they cite.",
        calculation="count of sentences labelled NOT SUPPORTED before repair",
        direction=LOWER_IS_BETTER, unit=COUNT, heuristic=True,
        caveats="This label is the reliable half of the faithfulness heuristic: each one has a concrete reason attached.",
        source_hint="semantic_faithfulness_results.json",
    ),
    _d(
        key="unsupported_sentences_final", name="Unsupported Sentences (final)", family=FAITHFULNESS,
        definition="The same count over the repaired answers.",
        calculation="count of sentences labelled NOT SUPPORTED after repair",
        direction=LOWER_IS_BETTER, unit=COUNT, heuristic=True,
        caveats="Any remaining unsupported sentence survived the repair layer and deserves individual inspection.",
        source_hint="semantic_faithfulness_results.json",
    ),
    _d(
        key="hallucination_raw", name="Hallucination Rate (raw)", family=FAITHFULNESS,
        definition="Share of generated answers containing at least one identifier, figure or provision that appears in no supplied source.",
        calculation="answers with at least one fabricated element / answers generated",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="Detected deterministically by comparing identifiers and numbers in the answer against the evidence package. It catches fabricated citations and figures, not wrong reasoning stated in the source's own words.",
        source_hint="hallucination_results.json",
    ),
    _d(
        key="hallucination_final", name="Hallucination Rate (final)", family=FAITHFULNESS,
        definition="The same measure over the repaired answers.",
        calculation="repaired answers with at least one fabricated element / answers generated",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="Repair removes invalid citations and unsupported statements, so a fall here is largely the repair layer.",
        source_hint="hallucination_results.json",
    ),
    # ---------------------------------------------------------------- citation
    _d(
        key="citation_ok", name="Citation Validity", family=CITATION,
        definition="Share of answers in which every citation is well-formed and points at a source that was actually supplied.",
        calculation="answers with no invalid or malformed citation / answers generated",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Checks that the cited source exists in the package, not that it supports the sentence attached to it.",
        source_hint="citation_results.json",
    ),
    _d(
        key="exact_source_citation", name="Exact-tier Citation Support", family=CITATION,
        definition="Share of requirement statements supported by a citation to an exact-tier source rather than a structural, supporting or discovery source.",
        calculation="requirement statements citing an exact source / requirement statements with a citation",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Citing a discovery-tier source for a requirement is a specific validation code; this metric aggregates it.",
        source_hint="citation_results.json",
    ),
    # --------------------------------------------------------------- behaviour
    _d(
        key="refusal_correct", name="Refusal Correctness", family=BEHAVIOUR,
        definition="Share of questions where the system declined to answer exactly when it should have: declining questions with no supporting evidence and answering those with evidence.",
        calculation="questions whose refusal behaviour matches the expectation / questions with a refusal expectation",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Counts both error kinds together. The false-refusal and false-answer lists name the individual questions.",
        source_hint="refusal_results.json",
    ),
    _d(
        key="false_refusal_count", name="False Refusals", family=BEHAVIOUR,
        definition="Number of answerable questions the system declined.",
        calculation="count of questions expected to be answered that were declined",
        direction=LOWER_IS_BETTER, unit=COUNT,
        caveats="Each one is listed by question id, because the count alone hides whether the cause is retrieval or the model.",
        source_hint="refusal_results.json",
    ),
    _d(
        key="false_answer_count", name="False Answers", family=BEHAVIOUR,
        definition="Number of questions that should have been declined but received a substantive answer.",
        calculation="count of questions expected to be declined that were answered",
        direction=LOWER_IS_BETTER, unit=COUNT,
        caveats="The more dangerous of the two refusal errors in a regulatory setting.",
        source_hint="refusal_results.json",
    ),
    _d(
        key="domain_leak_rate", name="Domain-boundary Leakage", family=BEHAVIOUR,
        definition="Share of out-of-scope questions answered as if they were in scope instead of being declined or bounded.",
        calculation="out-of-scope questions answered substantively / out-of-scope questions",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="The out-of-scope set is small, so a single question moves this figure a long way. Always read it with its denominator.",
        source_hint="domain_boundary_results.json",
    ),
    _d(
        key="multi_provision_accuracy", name="Multi-provision Accuracy", family=BEHAVIOUR,
        definition="Share of questions requesting several named provisions where every one of them is addressed.",
        calculation="multi-provision questions with all provisions addressed / multi-provision questions",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Addressed means the provision identifier and its requirement appear; it is not a judgment of how well it was stated.",
        source_hint="behaviour_results.json",
    ),
    _d(
        key="range_accuracy", name="Range Accuracy", family=BEHAVIOUR,
        definition="Share of questions requesting a range of paragraphs where every paragraph in the range is addressed.",
        calculation="range questions fully addressed / range questions",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Ranges whose endpoints do not exist are handled by the missing-provision behaviour instead.",
        source_hint="behaviour_results.json",
    ),
    _d(
        key="partial_behaviour_ok", name="Partial / Missing-provision Behaviour", family=BEHAVIOUR,
        definition="Share of questions containing a provision that does not exist where the answer states the absence instead of inventing content for it.",
        calculation="questions correctly declaring the absence / questions with an expected missing provision",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Asserting that an existing provision is missing is a separate validation code and counts as a failure here too.",
        source_hint="behaviour_results.json",
    ),
    # ------------------------------------------------------------------ repair
    _d(
        key="repair_rate", name="Repair Frequency", family=REPAIR,
        definition="Share of generated answers the deterministic repair layer had to modify.",
        calculation="answers with a repair applied / answers generated",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="Lower is better as a statement about the model, but a repair is a safety action: a low repair rate together with a low raw validation rate is worse, not better. Read it beside valid_raw.",
        source_hint="repair_results.json",
    ),
    _d(
        key="repair_success", name="Repair Success", family=REPAIR,
        definition="Share of repairs after which the answer passes deterministic validation.",
        calculation="repairs producing a valid answer / repairs applied",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Success means the repaired text is valid, not that it answers the question; extractive replacement can produce a valid but unhelpful answer.",
        source_hint="repair_results.json",
    ),
    _d(
        key="repair_kind_counts", name="Repairs by Kind", family=REPAIR,
        definition="Counts of each repair action: extractive replacement, safe message, invalid citations removed, mismatched statements replaced, appended missing provisions, truncation noted.",
        calculation="count of repairs per kind",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="The mix matters more than the total: a rise in safe messages means more questions are being declined at the last step.",
        source_hint="repair_results.json",
    ),
    # -------------------------------------------------------------------- cost
    _d(
        key="generation_latency_p50", name="Generation Latency p50", family=COST,
        definition="Median wall-clock time spent inside model generation for one question.",
        calculation="50th percentile of per-question generation duration",
        direction=LOWER_IS_BETTER, unit=SECONDS,
        caveats="Measured on this CPU-only machine while nothing else ran. It is not comparable with a run made under different load or on different hardware.",
        source_hint="latency_results.json",
    ),
    _d(
        key="generation_latency_p95", name="Generation Latency p95", family=COST,
        definition="95th percentile of model generation time for one question.",
        calculation="95th percentile of per-question generation duration",
        direction=LOWER_IS_BETTER, unit=SECONDS,
        caveats="Dominated by the longest answers, so it tracks the per-question token budget as much as model speed.",
        source_hint="latency_results.json",
    ),
    _d(
        key="e2e_latency_p50", name="End-to-end Latency p50", family=COST,
        definition="Median wall-clock time from question to final answer, including planning, retrieval, selection, generation, validation and repair.",
        calculation="50th percentile of per-question total duration",
        direction=LOWER_IS_BETTER, unit=SECONDS,
        caveats="The evidence phases contribute well under a second; the difference from generation latency is mostly database access.",
        source_hint="latency_results.json",
    ),
    _d(
        key="e2e_latency_p95", name="End-to-end Latency p95", family=COST,
        definition="95th percentile of total time from question to final answer.",
        calculation="95th percentile of per-question total duration",
        direction=LOWER_IS_BETTER, unit=SECONDS,
        caveats="Same hardware caveat as the other latency figures.",
        source_hint="latency_results.json",
    ),
    _d(
        key="avg_generated_tokens", name="Average Generated Tokens", family=COST,
        definition="Mean number of tokens the model produced per answer.",
        calculation="sum of generated tokens / answers generated",
        direction=INFORMATIONAL, unit=TOKENS,
        caveats="Neither more nor fewer tokens is better; the figure explains latency and truncation.",
        source_hint="generation_full.jsonl",
    ),
    _d(
        key="run_duration", name="Run Duration", family=COST,
        definition="Total wall-clock duration of the evaluation run.",
        calculation="completed_at minus started_at",
        direction=INFORMATIONAL, unit=SECONDS,
        caveats="Includes resumed segments if the run was interrupted and continued.",
        source_hint="run_manifest.json",
    ),
    # ----------------------------------------------------------------- dataset
    _d(
        key="benchmark_questions", name="Benchmark Questions", family=DATASET,
        definition="Number of questions in the benchmark this run was evaluated against.",
        calculation="count of questions in the benchmark file",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="Two runs are only comparable when the benchmark content hash matches, not merely the count.",
        source_hint="run_manifest.json",
    ),
    _d(
        key="questions_evaluated", name="Questions Evaluated", family=DATASET,
        definition="Number of benchmark questions this run actually produced a record for.",
        calculation="count of per-question records",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="Fewer than the benchmark size means the run is partial, and it is marked INCOMPLETE.",
        source_hint="generation_full.jsonl",
    ),
    # ------------------------------------------------------------------- human
    _d(
        key="manual_score_mean", name="Manual Reviewer Score (mean)", family=HUMAN,
        definition="Mean of the scores a human reviewer recorded for the answers in a legacy benchmark run.",
        calculation="sum of manual scores / answers with a manual score",
        direction=HIGHER_IS_BETTER, unit=SCORE, heuristic=True,
        caveats="A human judgment entered by hand, on a small sample, by one reviewer without a published rubric. The artifact does not record the scale, so the number is shown exactly as it was written and never as a percentage. It is recorded for provenance, not treated as a measurement, and must not be compared across runs scored by different people.",
        source_hint="data/evaluation/results/*.json",
    ),
    # ---------------------------------------------------------------- training
    _d(
        key="final_train_loss", name="Final Training Loss", family=TRAINING,
        definition="Mean training loss over the final logged window of the run.",
        calculation="train_loss reported by the trainer at the end of training",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="A training-process diagnostic only. Lower training loss does NOT mean a better regulatory model: it can equally mean memorisation, a narrower answer style, or an easier dataset. Only an evaluation run on a benchmark can say whether answer quality changed.",
        source_hint="training_metrics.json",
    ),
    _d(
        key="final_eval_loss", name="Final Validation Loss", family=TRAINING,
        definition="Loss on the held-out validation split at the end of training.",
        calculation="eval_loss from the final evaluation entry of the trainer log",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="Held-out loss is a better generalisation signal than training loss, and still not an accuracy measure. The validation split comes from the same generators as the training data, so it does not test the benchmark's distribution.",
        source_hint="training_metrics.json",
    ),
    _d(
        key="base_eval_loss", name="Pre-training Validation Loss", family=TRAINING,
        definition="Validation loss measured on the base model before any optimizer step.",
        calculation="eval_loss from the evaluation performed before training began",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="The reference point for the training delta. Measured on the same validation split, so it shares its limitations.",
        source_hint="training_metrics.json",
    ),
    _d(
        key="eval_loss_delta", name="Validation Loss Change", family=TRAINING,
        definition="Final validation loss minus pre-training validation loss.",
        calculation="final_eval_loss - base_eval_loss",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="Shows that training moved the model on its own data distribution. It is not evidence of improved answers and must never be displayed beside evaluation accuracy as though the two were the same kind of number.",
        source_hint="training_metrics.json",
    ),
    _d(
        key="total_steps", name="Optimizer Steps", family=TRAINING,
        definition="Number of optimizer steps completed.",
        calculation="global_step at the end of training",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="Read with epochs, batch size and gradient accumulation; the raw count means little alone.",
        source_hint="trainer_state.json",
    ),
    _d(
        key="epochs_completed", name="Epochs Completed", family=TRAINING,
        definition="Number of passes over the training set that finished.",
        calculation="epoch value at the end of training",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="A fractional value means the run stopped mid-epoch.",
        source_hint="training_metrics.json",
    ),
    _d(
        key="trainable_parameters", name="Trainable Parameters", family=TRAINING,
        definition="Number of parameters the optimizer updated, which for LoRA is the adapter only.",
        calculation="count reported by the model at training start",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="The base weights are frozen and unchanged; the adapter is a separate artifact that can be detached.",
        source_hint="training_summary.json",
    ),
    _d(
        key="training_examples", name="Training Examples", family=TRAINING,
        definition="Number of examples in the training split after deduplication and benchmark exclusion.",
        calculation="count of training examples in the dataset manifest",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="Benchmark exclusion removes whole section and part groups, so this count is lower than the generated total by design.",
        source_hint="dataset_manifest.json",
    ),
    _d(
        key="training_duration", name="Training Duration", family=TRAINING,
        definition="Wall-clock duration of the training run.",
        calculation="train_runtime reported by the trainer",
        direction=INFORMATIONAL, unit=SECONDS,
        caveats="On this CPU-only machine duration is dominated by hardware, not by the configuration.",
        source_hint="training_metrics.json",
    ),
    _d(
        key="best_eval_loss", name="Best Validation Loss", family=TRAINING,
        definition="The lowest validation loss any evaluated checkpoint reached, and the checkpoint the trainer therefore selected.",
        calculation="best_metric from the trainer state",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="Selecting the checkpoint with the lowest held-out loss is a training-time decision made on the training data's own distribution. Whether that checkpoint answers regulatory questions better is an open question until it is evaluated on a benchmark.",
        source_hint="trainer_state.json",
    ),
    _d(
        key="planned_steps", name="Planned Optimizer Steps", family=TRAINING,
        definition="The number of steps the run was configured to take.",
        calculation="max_steps from the trainer state",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="A completed step count well below this means the run stopped early, whether by design or by failure.",
        source_hint="trainer_state.json",
    ),
    _d(
        key="validation_examples", name="Validation Examples", family=TRAINING,
        definition="Number of held-out examples the validation loss was measured on.",
        calculation="count of validation examples in the dataset manifest",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="A small validation subset makes the loss noisy; read the loss curve, not a single point.",
        source_hint="metadata.json",
    ),
    _d(
        key="trainable_percent", name="Trainable Share of Parameters", family=TRAINING,
        definition="The fraction of the model's parameters the optimizer updated.",
        calculation="trainable parameters / total parameters",
        direction=INFORMATIONAL, unit=RATIO,
        caveats="For LoRA this is small by construction and says nothing about how much behaviour changed.",
        source_hint="training_summary.json",
    ),
    # --------------------------------------------------------------- retrieval
    _d(
        key="recall_at_1", name="Recall@1", family=RETRIEVAL,
        definition="Share of queries whose expected source is the top-ranked result.",
        calculation="queries with first_hit_rank = 1 / scored queries",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Measured on the retrieval benchmark, not the answer benchmark, and with no model in the loop. It says nothing about whether an answer built on that source is right.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    _d(
        key="recall_at_3", name="Recall@3", family=RETRIEVAL,
        definition="Share of queries whose expected source appears in the top three results.",
        calculation="queries with first_hit_rank <= 3 / scored queries",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Recall at a larger k is never lower than at a smaller k, so the four recall figures must be read as a curve, not compared against each other as if they were independent.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    _d(
        key="recall_at_5", name="Recall@5", family=RETRIEVAL,
        definition="Share of queries whose expected source appears in the top five results.",
        calculation="queries with first_hit_rank <= 5 / scored queries",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Only meaningful against the same retrieval benchmark; a different query set makes the number incomparable.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    _d(
        key="recall_at_10", name="Recall@10", family=RETRIEVAL,
        definition="Share of queries whose expected source appears in the top ten results.",
        calculation="queries with first_hit_rank <= 10 / scored queries",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="The generation pipeline only ever sees the top-k it is configured for, so recall beyond that k is diagnostic, not a property of the answering system.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    _d(
        key="mrr", name="Mean Reciprocal Rank", family=RETRIEVAL,
        definition="Mean of one divided by the rank of the first correct result, over the scored queries.",
        calculation="sum of 1 / first_hit_rank / scored queries",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Rewards putting the right source first rather than merely somewhere in the list. A query with no hit contributes zero.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    _d(
        key="negative_control_pass", name="Negative Controls Passed", family=RETRIEVAL,
        definition="Share of deliberately unanswerable queries for which the retriever correctly returned nothing relevant.",
        calculation="negative controls passed / negative controls",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="The negative-control set is small, so this figure moves a long way on one query. Read it with its denominator.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    _d(
        key="retrieval_queries", name="Queries Evaluated", family=RETRIEVAL,
        definition="Number of queries in the retrieval benchmark run.",
        calculation="count of query records",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="Negative controls are included here but excluded from the recall denominators.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    _d(
        key="retrieval_latency_avg", name="Mean Retrieval Latency", family=COST,
        definition="Mean wall-clock time to answer one retrieval query.",
        calculation="mean of per-query total duration",
        direction=LOWER_IS_BETTER, unit=SECONDS,
        caveats="Hardware-bound and measured without the model loaded, so it is not comparable with the end-to-end latency of an answering run.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    _d(
        key="retrieval_latency_max", name="Worst Retrieval Latency", family=COST,
        definition="The slowest single retrieval query in the run.",
        calculation="maximum of per-query total duration",
        direction=LOWER_IS_BETTER, unit=SECONDS,
        caveats="A single outlier, usually a fallback query that had to widen its terms.",
        source_hint="data/evaluation/results/retrieval-*.json",
    ),
    # ------------------------------------------------- legacy answer evaluation
    _d(
        key="completion_rate", name="Completion Rate", family=GENERATION,
        definition="Share of questions for which the run produced an answer without erroring.",
        calculation="completed questions / questions attempted",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Completing is not answering well. This only says the pipeline did not crash or time out.",
        source_hint="data/evaluation/results/*.json",
    ),
    _d(
        key="failed_count", name="Failed Questions", family=GENERATION,
        definition="Number of questions that errored instead of producing an answer.",
        calculation="count of results with status != completed",
        direction=LOWER_IS_BETTER, unit=COUNT,
        caveats="The failing question ids are listed so the cause can be read rather than guessed.",
        source_hint="data/evaluation/results/*.json",
    ),
    _d(
        key="avg_prompt_tokens", name="Average Prompt Tokens", family=COST,
        definition="Mean number of tokens sent to the model per question, prompt and retrieved context together.",
        calculation="sum of input tokens / questions answered",
        direction=INFORMATIONAL, unit=TOKENS,
        caveats="Driven by the context budget, not by model quality. It explains latency.",
        source_hint="data/evaluation/results/*.json",
    ),
    _d(
        key="tokens_per_second", name="Generation Throughput", family=COST,
        definition="Tokens produced per second of model generation time.",
        calculation="mean or median of generated tokens divided by generation seconds",
        direction=INFORMATIONAL, unit=COUNT,
        caveats="A hardware measurement on this CPU-only machine. It changes with load, not with model quality.",
        source_hint="data/evaluation/results/*.json",
    ),
    _d(
        key="avg_generation_seconds", name="Mean Generation Time", family=COST,
        definition="Mean wall-clock time spent generating one answer.",
        calculation="total generation seconds / questions answered",
        direction=LOWER_IS_BETTER, unit=SECONDS,
        caveats="A mean, unlike the Stage 5 percentiles, so one very slow answer moves it. Do not compare it against a p50.",
        source_hint="data/evaluation/results/*.json",
    ),
    # ------------------------------------------- acceptance test (hand-scored)
    # These are the contractual rubric's own columns, scored by a human reading
    # each answer against the verified corpus under `regulus_substantive_rubric_v1`
    # (docs/STAGE_A_RUBRIC.md). The dashboard tabulates recorded verdicts; it
    # scores nothing. Every one of them carries the same two caveats, which the
    # run's `problems` state in full: the answer key is an unverified draft, and
    # a comparative run may inherit a row's verdict from an earlier run.
    _d(
        key="acceptance_full_pass", name="Acceptance Pass Rate", family=CORRECTNESS,
        definition="Share of scored benchmark rows that pass the acceptance rubric's whole verdict rule.",
        calculation="rows with L=1 and M=0 and N=2 and O>=1 and P=1 and Q in {1, blank} / rows scored (ERROR rows excluded)",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Hand-scored against a DRAFT answer key: the workbook requires SME verification before the test is administered and states that an unverified key invalidates the result, so this is indicative, not contractual. It is also not the live per-answer accuracy indicator, which measures one answer against its own evidence under a different rubric.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_citation_accuracy", name="Citation Accuracy (L)", family=CITATION,
        definition="Share of scored rows where every citation is correct to the section, and to the paragraph wherever the statement asserts a paragraph-level requirement.",
        calculation="rows with L=1 / rows scored",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="A correct answer carrying no citation at all scores 0 here. Gate G1 requires 99%.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_fabrication_rate", name="Fabricated Citations (M)", family=FAITHFULNESS,
        definition="Share of scored rows that cite a CFR section, ISO clause, guidance title, warning letter or docket that does not exist.",
        calculation="rows with M=1 / rows scored",
        direction=LOWER_IS_BETTER, unit=RATIO,
        caveats="Gate G2 is zero and absolute: one fabricated identifier fails the run outright. A superseded provision is a citation error, not a fabrication.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_substantive_correct", name="Substantive Correctness, fully correct (N=2)", family=CORRECTNESS,
        definition="Share of scored rows whose substance is correct and would survive review by a qualified regulatory professional.",
        calculation="rows with N=2 / rows scored",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Getting who is subject to a requirement wrong is N=0, not N=1, however accurate the rest is. Gate G4 scores points earned out of maximum on the 0-2 scale, not this share.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_substantive_partial", name="Substantive Correctness, directionally right (N>=1)", family=CORRECTNESS,
        definition="Share of scored rows that are at least directionally right about the requirement asked about.",
        calculation="rows with N>=1 / rows scored",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="N=1 means incomplete in a way that could mislead, or a recommendation stated as a requirement. It is NOT a pass and must never be quoted as accuracy.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_completeness", name="Completeness (O>=1)", family=CORRECTNESS,
        definition="Share of scored rows where at least the primary governing section was surfaced.",
        calculation="rows with O>=1 / rows scored",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="O=1 still means related governing sections are missing. Gate G5 scores points out of maximum on the 0-2 scale.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_scope_discipline", name="Scope Discipline (P)", family=CORRECTNESS,
        definition="Share of scored rows that stayed within Title 21 or flagged a question outside it, rendered no legal advice, guaranteed no compliance outcome and reproduced no copyrighted standard text.",
        calculation="rows with P=1 / rows scored",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="The easiest dimension to pass: a refusal scores 1 here. A high value says little on its own.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_iso_concordance", name="ISO 13485 Concordance (Q)", family=CORRECTNESS,
        definition="Share of in-scope rows that identified the ISO 13485 clause by number and routed the requirement through the correct Part 820 section.",
        calculation="in-scope rows with Q=1 / in-scope rows (those the workbook puts in ISO scope)",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="The denominator is only the rows the workbook scopes for ISO, so it is much smaller than the benchmark. A wrong clause number also sets M=1.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_negative_control_pass", name="Negative-control Pass Rate", family=CORRECTNESS,
        definition="Share of the benchmark's negative-control rows that pass: the answer states that the section, clause, rule or guidance does not exist, or correctly declines.",
        calculation="negative-control rows passing the verdict rule / negative-control rows scored",
        direction=HIGHER_IS_BETTER, unit=RATIO,
        caveats="Gate G3 requires 100% and is absolute. Hedging without stating that the premise is false does not pass.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_rows_hand_scored", name="Rows Read by Hand for This Run", family=HUMAN,
        definition="How many of the run's rows a human read and scored for THIS run, rather than inheriting a verdict from an earlier run.",
        calculation="rows with scoring_basis = manual_rubric_read / rows with a verdict",
        direction=HIGHER_IS_BETTER, unit=COUNT,
        caveats="An inherited verdict is carried over on the grounds that the delivered answer did not change. That is a legitimate protocol for a comparative run, but it is not evidence about this run's answers, so the split is reported rather than hidden.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
    _d(
        key="acceptance_rows_errored", name="Rows With No Answer to Judge", family=DATASET,
        definition="How many rows recorded a technical execution failure, so no answer exists to score.",
        calculation="rows with result = ERROR / rows with a verdict",
        direction=LOWER_IS_BETTER, unit=COUNT,
        caveats="Excluded from every rate above, because the rubric says ERROR is a technical failure and never a bad answer. Counting them as failures would understate the model; ignoring them silently would overstate the coverage.",
        source_hint="artifacts/acceptance_test/<run>/scoring/verdicts_*.jsonl",
    ),
)

REGISTRY: dict[str, MetricDefinition] = {d.key: d for d in _DEFINITIONS}


class UnknownMetricError(KeyError):
    """Raised when an adapter emits a metric that has no definition."""


def definition(key: str) -> MetricDefinition:
    try:
        return REGISTRY[key]
    except KeyError:
        raise UnknownMetricError(
            f"metric {key!r} has no MetricDefinition; add one to src/regulus/dashboard/metrics.py"
        ) from None


def has_definition(key: str) -> bool:
    return key in REGISTRY


def all_definitions() -> tuple[MetricDefinition, ...]:
    return _DEFINITIONS


def definitions_payload() -> dict[str, Any]:
    """What the API serves and the UI renders its tooltips from."""
    return {
        "families": [
            {
                "key": family,
                "title": FAMILY_TITLES[family],
                "metrics": [d.to_dict() for d in _DEFINITIONS if d.family == family],
            }
            for family in FAMILY_ORDER
        ],
        "by_key": {d.key: d.to_dict() for d in _DEFINITIONS},
        "count": len(_DEFINITIONS),
    }


def make_metric(
    key: str,
    value: float | None,
    *,
    numerator: int | None = None,
    denominator: int | None = None,
    source: str | None = None,
    status: str | None = None,
    note: str | None = None,
    recomputed_from: str | None = None,
) -> MetricResult:
    """Build a MetricResult, taking name, unit and direction from the registry.

    An adapter can therefore never label a metric with the wrong direction,
    and a metric with no definition raises instead of reaching the UI.
    """
    d = definition(key)
    if status is None:
        status = OK if value is not None else MISSING
    return MetricResult(
        key=d.key,
        display_name=d.name,
        value=value,
        unit=d.unit,
        direction=d.direction,
        numerator=numerator,
        denominator=denominator,
        definition_key=d.key,
        source=source or d.source_hint or None,
        status=status,
        note=note,
        recomputed_from=recomputed_from,
    )


def ratio_metric(
    key: str,
    numerator: int | None,
    denominator: int | None,
    *,
    stored: float | None = None,
    source: str | None = None,
    tolerance: float = 0.005,
) -> MetricResult:
    """A proportion recomputed from counts and cross-checked against the artifact.

    The stored value always wins for display: a disagreement is reported as a
    bug in the evaluator, never silently corrected here.
    """
    note = None
    if numerator is not None and not denominator:
        # No applicable questions: the proportion was not measured. "0 / 0" is
        # not a count a reader should see, and it must never read as 0%.
        numerator = denominator = None
        note = "no applicable questions in this run, so this was not measured"
    recomputed = (numerator / denominator) if numerator is not None and denominator else None
    value = stored if stored is not None else recomputed
    status = OK if value is not None else MISSING
    if stored is not None and recomputed is None and note:
        status = INCONSISTENT
        note = f"the evaluator stored {stored}, but the records hold no applicable questions to recount it from"
    if stored is not None and recomputed is not None and abs(stored - recomputed) > tolerance:
        status = INCONSISTENT
        note = (
            f"stored value {stored:.4f} disagrees with {numerator}/{denominator} = "
            f"{recomputed:.4f} recomputed from the per-question records"
        )
    return make_metric(
        key, value, numerator=numerator, denominator=denominator,
        source=source, status=status, note=note,
        recomputed_from="per-question records" if recomputed is not None else None,
    )


def unknown_keys(keys: Iterable[str]) -> list[str]:
    return sorted({k for k in keys if k not in REGISTRY})
