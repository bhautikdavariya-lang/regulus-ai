# Stage 5: Comprehensive Baseline Evaluation

Stage 5 answers one question before any training is considered: **what is
failing, and is the model actually the bottleneck?** It measures each layer
separately so a failure can be attributed rather than averaged away.

Results live in `artifacts/stage5_stage6/<run_id>/stage5/`, never
overwritten. This document describes the method; the numbers are in
`STAGE5_FINAL_REPORT.md` and the JSON files beside it.

## 1. Dataset

`data/evaluation/datasets/stage5_v1.jsonl`, 51 questions, each carrying its
own expectations, fixed by hand against the database before the run:

```json
{"id": "S5-041", "category": "missing",
 "question": "What do 21 CFR 820.10(b)(1) through (b)(5) require?",
 "expected_requirements": ["...(b)(1)", "...(b)(2)", "...(b)(3)", "...(b)(4)", "...(b)(5)"],
 "expected_exact":       ["...(b)(1)", "...(b)(2)", "...(b)(3)", "...(b)(4)"],
 "expected_missing":     ["21 CFR 820.10(b)(5)"],
 "expected_behavior": "partial", "expected_terms": ["830", "821", "803", "806"],
 "domain": "regulatory"}
```

Categories: single, parent, section, multi, range, missing, nonexistent,
adversarial, general, guidance, domain_boundary, citation, long, refusal.
The file is registered as a protected benchmark, so training data excludes
it by question **and** by group.

## 2. Phases

```
question
  │
  ├─ evidence phase (no model, seconds)
  │     plan_query -> run_plan -> check_coverage -> select_evidence
  │     retrieval_ok / coverage_ok / selection_ok, plus determinism
  │
  └─ generation phase (model, two generations per question)
        A. full pipeline   plan -> retrieval -> coverage -> selection -> generate -> validate
        B. controlled      same question, EXACT evidence only ("perfect evidence")
```

Comparing A with B localises a failure: an answer that fails in A but
passes in B is a context problem, not a model-capability problem; one that
fails in both is the model with the evidence it needs.

The pipeline runs with `validation_behavior="annotate"`, so the raw model
text and its validator report are recorded before any repair. The repair is
then applied explicitly and validated again, so these five never merge:

1. raw model answer;
2. validator result on the raw answer;
3. repaired answer;
4. correctness of the raw answer;
5. correctness of the final answer.

## 3. What is measured

| # | Measure | Artifact |
|---|---|---|
| 1 | retrieval correctness | `retrieval_results.json` |
| 2 | requirement recall (per provision, and per question) | `retrieval_results.json` |
| 3 | coverage correctness (state and missing labels) | `coverage_results.json` |
| 4 | evidence-selection correctness | `selection_results.json` |
| 5 | protected exact-evidence preservation | `selection_results.json` |
| 6 | raw generation correctness | `generation_results.json`, `correctness_results.json` |
| 7 | semantic faithfulness, raw and final | `semantic_faithfulness_results.json` |
| 8 | answer completeness | `generation_results.json`, `behaviour_results.json` |
| 9 | citation validity | `citation_results.json` |
| 10 | citation support (which tier supports which requirement) | `citation_results.json` |
| 11 | unsupported / hallucinated claims | `hallucination_results.json` |
| 12 | refusal correctness | `refusal_results.json` |
| 13 | false refusals | `refusal_results.json` |
| 14 | multi-provision accuracy | `behaviour_results.json` |
| 15 | range accuracy | `behaviour_results.json` |
| 16 | partial / missing-provision behaviour | `behaviour_results.json` |
| 17 | domain-boundary behaviour | `domain_boundary_results.json` |
| 18 | truncation | `generation_results.json` |
| 19 | repair frequency | `repair_results.json` |
| 20 | repair success | `repair_results.json` |
| 21 | final answer correctness | `correctness_results.json` |
| 22 | generation latency p50 / p95 | `latency_results.json` |
| 23 | end-to-end latency p50 / p95 | `latency_results.json` |

Plus `failure_analysis.json` (per question: which layer failed and why) and
`stage5_training_plan.json` (the machine-readable planning artifact).

## 4. Correctness, and what it does not mean

`correctness_results.json` reports a composite that a machine can decide:

* deterministic validation passed (no unsupported content, no citation
  mismatch, nothing truncated, nothing degenerate, no requirement omitted);
* every requested provision with exact evidence is addressed;
* the refusal expectation is met;
* the expected terms appear;
* no claim was flagged as unsupported by its cited source.

An answer that passes has nothing checkable wrong with it. That is not the
same as a human judging it right, and the report says so. The composite is
computed twice, once over the raw model text and once over the repaired
text; the repaired figure is a property of the pipeline, not of the model.

## 5. Faithfulness method and limits

Sentence level. SUPPORTED means the sentence cites an EXACT source, shares
at least half its content words with it, and failed no deterministic check.
NOT SUPPORTED means a deterministic check failed on it (a missing provision
asserted, a figure absent from every source, a wrong-source citation) or it
shares under a quarter of its content words with what it cites. Everything
between is UNCERTAIN. Refusals and "not found" statements are deterministic
and counted apart.

Word overlap is not entailment. A paraphrase can share words and still
misstate the source, and a correct restatement in fresh words can score
UNCERTAIN. Read NOT SUPPORTED as reliable and SUPPORTED as unproven.

## 6. Running it

```bash
python scripts/run_stage5.py --check                 # environment only
python scripts/run_stage5.py                         # full run into a new run directory
python scripts/run_stage5.py --run-dir <dir>         # resume; finished phases are skipped
python scripts/run_stage5.py --run-dir <dir> --skip-generation   # rebuild reports from saved records
python scripts/run_stage5.py --adapter <dir>         # same evaluation with a trained adapter
```

The generation phase appends one JSON line per question, so an interrupted
run continues from the next question. The report phase is a pure function
of those lines and can be re-run at any time.

Resource rule: the run refuses to start while another model-sized Python
process is alive, because this machine cannot hold two models. Below 3 GB
free it warns and proceeds; below 1 GB it stops.
