# Stage 4: AI failure observatory and baseline quality gate

Diagnostic stage. It answers one question for every evaluated answer: **where
did it first become wrong?** It changes no answer, no model, no data and no
default. The only pipeline change adds diagnostic fields: the raw model
output and the repair input are now kept.

Artifacts:

* `artifacts/diagnostics/stage4_baseline_20260929T073732Z/`: the evaluated
  run; traces generated once.
* `artifacts/diagnostics/stage4_rediagnosed_20260929T082457Z/`: the final
  diagnoses. It re-applies the corrected rules to the same traces, and the
  evidence was rebuilt and verified identical by hash for all 79 questions.
  It adds `manual_review.jsonl` and `reviewed_distribution.json`.

## 1. Objective and baseline

| Item | State (verified 2026-09-29) |
|---|---|
| Model | Qwen/Qwen3-0.6B, revision c1899de, no adapter; weights sha256 `f47f71177f32…` |
| Device / dtype | `auto` → CPU float32 (MPS opt-in only) |
| Pipeline default | `answer_shape="adaptive"`, validation `repair`, one generation call, streaming on |
| Database | read-only, cfr_records 65,341 rows |
| Benchmark | REV02 xlsx sha256 `c009d5f9c649…` (unchanged, no locked key); `stage5_v1.jsonl` `7cf80fda674f…` |
| Version control | **none**: the project is not a git repository, so no git state could be recorded; hashes stand in |

## 2. Current architecture and trace points

```text
User question
  ↓ plan_query / analyze_shape            trace: intent_type, scope (diagnostic), answer_shape, requested provisions
  ↓ LexicalRetriever.run_plan             trace: retrieval_query, parameters, every candidate (order, method, score)
  ↓ coverage + select_evidence            trace: coverage, selected_context (hashed), dropped, evidence_sufficiency ★
  ↓ build_package / prompt                trace: prompt_hash, prompt_token_count, max_new_tokens
  ↓ Qwen3-0.6B (one call)                 trace: model identity, timings, RAW MODEL OUTPUT ★
  ↓ validate_answer (initial)             trace: initial_validation (status, codes, problems)
  ↓ repair_answer                         trace: repair_type, REPAIR INPUT ★, repair output
  ↓ validate_answer (final, if repaired)  trace: final_validation
  ↓ citations                             trace: final_citations, citation_support
Final answer → stream / UI                trace: final_answer, final_output_hash
```

★ = new in Stage 4. **Finding:** before this stage, production `repair` mode
overwrote the model's text and kept no copy. The raw output of the
temperature incident had never been recorded anywhere; only the Stage 5
evaluation mode (`annotate`) kept it. It is now in
`metadata.raw_model_output` and `metadata.repair_input`, with no effect on
the answer (tested).

## 3. Failure taxonomy (`regulus/observability/taxonomy.py`)

F01 intent · F02 scope · F03 retrieval miss · F04 retrieval ranking · F05
evidence-insufficiency detection · F06 evidence interpretation · F07
unsupported generation · F08 regulatory qualifier · F09 citation attribution ·
F10 validation false positive · F11 validation false negative · F12 repair ·
F13 safe fallback · F14 answer structure · F15 completeness · F16 model
capability · F17 evaluation/data · F18 performance/inference · F19
pipeline/state · F20 UI/presentation · **UNKNOWN / NEEDS_REVIEW**.

Each record carries:

* `question_id`, `failure_class`, `severity` (critical/major/minor), `confidence`
  (proven/probable/needs_review), `primary`, `secondary_causes`, `evidence`
  (required), `module`, `reproducible`, `regression_status` and `notes`.

A record without evidence is rejected. Heuristic-only findings are
`needs_review` and never make a question FAIL on their own.

## 4. Diagnostic schema (`regulus/observability/trace.py`)

One JSON object per question with every field listed in the brief (§2 above).
Source texts are recorded as SHA-256 hashes, not copies; the model output and
final answer are recorded in full. No database URL, environment, credentials
or user identity is recorded (tested for secrets). `run_diagnostics.py
--from-traces` re-diagnoses a saved run without generating: it rebuilds the
evidence from the database and refuses any question whose evidence hash
differs from the trace.

## 5. Evidence sufficiency (`regulus/observability/sufficiency.py`)

| State | Decided by |
|---|---|
| EVIDENCE_NOT_FOUND | no requested provision has exact evidence, or nothing in the prompt |
| EVIDENCE_PARTIAL | some requested provisions found, some not |
| EVIDENCE_INSUFFICIENT | the question asks for a **kind of value** (temperature, date, duration/frequency, money, form number, count) and no supplied source contains one; or only broad-search sources were found |
| EVIDENCE_SUFFICIENT | every requested provision has exact evidence, and any requested kind of value is present |
| UNKNOWN | a general question with ordinary sources: not decidable by rule |

It is general, with no topic or number rules. **Limitations:** SUFFICIENT
means "nothing checkable is missing", not "answers the question". It cannot
tell whether *a* date in the evidence is *the* date asked for. It trusts the
plan's reading of the requested provision, so when the plan misreads it
(S5-090), sufficiency is judged on the wrong provision. It is diagnostic only;
nothing acts on it yet.

## 6. Evaluation method

* **Golden diagnostic set:** `data/evaluation/datasets/diagnostic_v1.jsonl`,
  79 questions covering all 16 required categories.
  * 60 developer-keyed questions (the Stage 5 and answer-shape sets).
  * 3 UI examples, with facts **DB-derived**, e.g. "no Part 211 row contains a numeric temperature".
  * 16 benchmark questions, taken first-N per benchmark question type
    (deterministic, no cherry-picking), as **question text only: NEEDS_SME**.
    No expectation was invented for them, so they are reported UNVERIFIED.
* **Per question:** the production pipeline, the full trace, two labelled heuristics
  (claim word overlap; provisions named that appear in no supplied source *text*),
  and the **controlled condition**: the same model given exact evidence only, to
  separate model capability from context.
* **Determinism:** 10 questions re-run, raw and final output identical **10/10**.
* **Classification:** automatic rules (`regulus/observability/diagnose.py`), then
  a developer review of every failing row against its trace, recorded separately
  in `manual_review.jsonl`. It is not SME review.

### Rule corrections made during review (general, not per question)

The first automatic pass over-counted, and the corrections are part of the
method. Each correction is a general rule change:

1. An identifier the model names is not "fabricated" if a supplied source's
   *text* mentions it; sources cross-reference, e.g. "see § 820.7".
2. Claim word overlap alone gives `needs_review`, never a failure.
3. Validation false negatives (F11) count only proven or probable raw failures.
4. The declined part of a mixed question is excluded from fallback relevance.
5. The `truncated` code is not evidence that repair failed; it describes the
   generation, not the repaired text.
6. A failure contained by a *relevant* fallback is minor.
7. The fallback relevance check applies only to fallbacks that quote text.
8. "Presented as the requested provision" (F20) applies only when the request
   was a whole part or section.
9. A safe message on an answerable question is a failure to answer.

## 7. Failure distribution (79 questions)

Final status, developer-reviewed: **PASS 39 · FAIL 22 · NEEDS_REVIEW 2 · UNVERIFIED 14 · UNVERIFIED_WITH_FAILURES 2.**
The 22 FAIL and 2 NEEDS_REVIEW are keyed questions; the 16 UNVERIFIED are
the unkeyed benchmark questions.

Primary failure of the 26 failing questions (reviewed):

| Module | Count | Classes |
|---|---:|---|
| Generation | 12 | F15 completeness 5, F08 qualifier 3, F07 unsupported 2, F16 capability 2 |
| Scope | 3 | F02: two general-knowledge questions answered, and the EU MDR question answered |
| Sufficiency | 3 | F05: invented temperature, penalty amount, compliance date |
| Intent / plan | 2 | F01: a provision mentioned as context treated as the one requested |
| Repair | 2 | F12 |
| Presentation | 2 | F14 |
| Citations | 1 | F09 |
| Inference | 1 | F18 degenerate loop |

All failure records, automatic (a question can have several):

* F07 ×27 · F09 ×19 · F08 ×9 · F15 ×8 · F16 ×8 · F14 ×7
* F05 ×6 · F11 ×6 · F18 ×5 · F12 ×5 · F02 ×3 · F13 ×2 · F20 ×1 · UNKNOWN ×1

Most F07/F09 records are *contained*: validation caught them and repair
produced a valid final answer.

The full matrix is in `root_cause_matrix.md`, with the reviewed overrides in
`manual_review.jsonl`.

## 8. Scorecard (`scorecard.json`)

Each metric has a label: AUTOMATED, DEVELOPER-KEYED or NOT YET MEASURABLE.
There is no composite score.

| Stage | Metric | Value | Label |
|---|---|---|---|
| Intent | accuracy | NOT YET MEASURABLE (no verified intent labels) | — |
| Scope | keyed out-of-scope questions declined by the current pipeline | 1 / 4 | DEVELOPER-KEYED |
| Retrieval | keyed provision retrieved as exact evidence | 37 / 37 | DEVELOPER-KEYED |
| Retrieval | ranking | NOT YET MEASURABLE (needs per-candidate relevance labels) | — |
| Sufficiency | distribution | SUFFICIENT 48 · INSUFFICIENT 11 · NOT_FOUND 10 · UNKNOWN 8 · PARTIAL 2 | AUTOMATED |
| Generation | raw answers with unsupported content (proven/probable) | see F07 records | AUTOMATED |
| Generation | raw claims: supported / unsupported / uncertain (heuristic) | 82 / 71 / 153 | AUTOMATED, heuristic |
| Validation | raw answers rejected | 22 / 69 | AUTOMATED |
| Validation | false negatives (F11) | 6 | AUTOMATED |
| Validation | false positives (F10) | NOT YET MEASURABLE automatically; 4 found by review (leading-marker misattribution) | review |
| Repair | repair rate; final valid after repair | 22 / 69; 13 / 22 | AUTOMATED |
| Citations | answers with a marker | 63 / 69 | AUTOMATED |
| Citations | semantic citation correctness | NOT YET MEASURABLE (SME) | — |
| Final answer | keyed machine checks pass | 39 / 63 reviewed (31 / 63 automatic before review) | DEVELOPER-KEYED |
| Final answer | correctness, grounding, relevance, structure, regulatory precision | NOT YET MEASURABLE (SME) | — |
| Latency | median first token / generation / total | 1.8 s / 12.1 s / 10.1 s | AUTOMATED |

## 9. Root-cause matrix (failing rows, reviewed)

| Question | Status | Primary | Secondary | Module | Evidence |
|---|---|---|---|---|---|
| UI-04 temperature | FAIL | F05 | F03 (review), F07, F11, F13, F20 | sufficiency | see §10 |
| S5-051 penalty amount | FAIL | F05 | F07, F11, F13 | sufficiency | "$1,000" invented; no source contains an amount |
| S5-052 compliance date | FAIL | F05 | F11, F15 | sufficiency | "by the date specified…"; no source contains a date |
| S5-080 / S5-082 general knowledge | FAIL | F02 | F05, F07, F11 | scope | answered (echo; "100°C [1]"); no scope stage in the default mode |
| S5-083 EU MDR | FAIL | F02 | F05, F09 | scope | invented EU answer; the diagnostic classifier does flag it out of scope |
| S5-090 citation lookup | FAIL | F01 | F03, F15 | intent | "part 803" (criteria) read as the requested provision; 820.10(b)(3) never retrieved |
| S5-091 citation lookup | FAIL | F01 | F15, F16 | intent | "part 806" read as requested, so enumeration; (b)(4) retrieved but not named |
| S5-053 false premise | FAIL | F07 | F08, F11 | generation | affirms "annual … audits"; no source contains either word |
| AS-09 definition | NEEDS_REVIEW | F07 (needs review) | — | generation | claim-overlap heuristic only; answer echoes the question |
| S5-006, S5-010, S5-031, AS-02, AS-06 | FAIL | F15 | — | generation | a keyed element missing (e.g. "validation of systems"; S5-031 labels only) |
| AS-01, AS-03 (+ BM-S-019 unverified) | FAIL | F08 | F09, F12 | generation | "if applicable" attached to unconditional requirements |
| S5-012, BM-F-002 | FAIL | F16 | F09 | generation | citation attribution still fails with exact evidence only |
| S5-024, AS-04 | FAIL | F12 | F14, F18 | repair | repair ran and the result still fails (extractive quote capped at 3 sources) |
| S5-100 | FAIL | F14 | F10 | presentation | verbatim copy instead of the plain-English explanation asked for |
| S5-007 | FAIL | F09 | F07 | citations | a sentence cites a source that lacks its cross-reference |
| S5-061 | FAIL | F18 | F13 | inference | degenerate loop, so the safe message; an answerable question gets no answer |

UI-01 is NEEDS_REVIEW (F14, repeated statement). Contained, and therefore
PASS: S5-084 (fabricated population figure caught; the fallback quoted the
relevant (b)(3)) and S5-111 (qualifier issue repaired). Four rows the automatic
pass failed are PASS after review (S5-021, S5-101, S5-041, S5-050), all for
reasons stated in `manual_review.jsonl`.

## 10. Temperature incident (UI example 4), proven from the trace

Question: "What exact storage temperature range does 21 CFR Part 211 require for all finished tablets?"

| # | Stage | What the trace shows |
|---|---|---|
| 1 | Intent / scope | requirement, in scope; answer shape *focused* on "storage, temperature, range, finished, tablets" |
| 2 | Plan | one requested provision: `21 CFR part 211` (part level) |
| 3 | Retrieval | exact part lookup: 60 candidates, **one lead row per section**; full-text search 0 hits; no fallback (the exact lookup "succeeded") |
| 4 | Evidence present? | **No.** The only relevant paragraph, 21 CFR 211.142(b) ("storage … under appropriate conditions of temperature, humidity, and light"), exists in the database but was never a candidate (the part lookup returns 211.142's lead row, not (b)). **No row of Part 211 contains a numeric temperature** (database query). |
| 5 | Selection | 18 of 60 placed in the prompt in string order of section number (211.100 … 211.184); 42 dropped at the character ceiling; none mentions temperature |
| 6 | Sufficiency | EVIDENCE_INSUFFICIENT: a temperature is requested and none is in the evidence; nothing acts on this |
| 7 | Raw model output | "…finished tablets be stored at a temperature range of **20°C to 25°C** [1]…", citing 211.100(a) |
| 8 | Initial validation | **caught it**: `unsupported_figure: 20, 25` (true positive) |
| 9 | Repair | `extractive_replacement` received the raw text and quoted the first 3 exact rows of the requested provision (211.100(a), 211.101, 211.103: production procedures, yields) |
| 10 | Final validation | passed that text (it cannot judge relevance) |
| 11 | Presentation | the quote is labelled "the verified text of the requested provision(s)" |

**Why the final answer was large, unrelated Part 211 text:** the repair
fallback quotes a requested provision's first exact sources. For a
part-level request those are the lead rows of Part 211's first sections in
string order, and nothing checks them against the question's topic.

**Root cause: multiple modules, in order.**

1. Retrieval (F03): part-level lookup plus no in-part topic search; the answering paragraph was never retrieved.
2. Sufficiency (F05): no stage recognised that a numeric value was requested and absent.
3. Generation (F07): the model invented a value.
4. Repair (F13, F20): an irrelevant fallback presented as the requested provision.

Validation worked. The correct answer (from the database): Part 211 sets no
numeric range; 211.142(b) requires storage under *appropriate conditions of
temperature*.

## 11. Regression gates

A future module change is accepted only if **all** of these hold:

* **(A) Existing passing questions:** the 39 reviewed PASS rows stay PASS, and
  any change of status is explained in writing.
* **(B) Known failures:** the targeted failure class decreases on the golden set.
* **(C) Cross-category:** no other failure class increases on any category.
* **(D) Determinism:** re-running the gate on unchanged code gives identical raw
  and final outputs (10/10 today); `--from-traces` re-diagnosis gives identical diagnoses.
* **(E) Integrity:**
  * the benchmark hash is `c009d5f9c649…`;
  * `stage5_v1` is `7cf80fda674f…`;
  * `diagnostic_v1` is unchanged unless the change is approved;
  * the database is read-only.
* **Tests** pass: full suite, integration, observability.
* **Explainability:** the change states which rule or module it targets.

A change that fixes 20 questions but breaks 5 PASS rows is flagged for
review, not accepted. How to run the gate:

```
python scripts/run_diagnostics.py --repeat 10 --label <change>
```

Then compare its `diagnoses.jsonl` against `stage4_rediagnosed_20260929T082457Z`.

## 12. UI example questions

| # | Example | Status | Evidence |
|---|---|---|---|
| 1 | What does 21 CFR Part 11 cover? | NEEDS_REVIEW | answers from Part 11 text; a repeated statement; content unverified (SME) |
| 2 | …specific requirements of 21 CFR 314.999? | PASS | deterministic "not in the eCFR data" (S5-043) |
| 3 | …Part 1400 … artificial intelligence…? | PASS | deterministic "not in the eCFR data" (S5-044) |
| 4 | …exact storage temperature range … Part 211…? | **FAIL** | the temperature incident (§10) |
| 5 | What does 21 CFR 820.10 require? | **FAIL** | F08: "if applicable" attached to the unconditional UDI requirement (AS-01) |
| 6 | Summarize FDA guidance FDA-2023-D-99999. | PASS | docket absent (DB-verified), so a deterministic decline |

2 of the 6 shown examples fail and 1 is unverified. None has an SME-verified
expected answer. The examples should become a gated subset of the golden set.

## 13. Recommended next module

The data by count: **generation is the primary module in 12 of 26 failing
questions**. But 7 of those 12 are behaviours a 0.6B model controls poorly
through prompting (completeness details, misapplied "if applicable",
attribution under exact evidence), and Stage 3's opt-in structured mode
already targets some of them.

The data by severity: all three critical-severity failures and every
fabricated value that reached a user or needed a fallback come from **scope
(3) + sufficiency (3) + intent/plan (2) = 8 questions**. All three are
deterministic modules, fixable without training, and in each case the
diagnostic already detects the condition (scope out-of-framework, requested
value absent, misread requested provision) but nothing acts on it.

**Recommendation: an answerability gate before generation.** Act on the
scope decision, on evidence sufficiency for requested kinds of values, and
on the context-vs-request reading of mentioned provisions. It should be
followed by the repair fallback's relevance: never present unrelated quoted
text as the answer.

Retrieval is **not** the leading cause. Keyed provisions were retrieved 37/37.
Retrieval misses appear only downstream of a plan misreading (S5-090) or of
the part-level lookup design (UI-04); both are worth fixing within the gate
work. Generation quality (F15/F08) is second in priority, and it's the natural
place for Stage 3 adoption or later training.

## 14. What was deliberately not changed

* Model and weights; the verified database; benchmark files and keys.
* Retrieval; prompts and the system prompt; generation parameters; validation
  and repair logic.
* CPU/MPS defaults; streaming; the UI.
* No second LLM, no agent, no new framework, no question-specific rule.

The only runtime change is two extra metadata fields (raw output, repair
input), tested to leave answers unchanged.

## 15. New code and tests

* `src/regulus/observability/`: `taxonomy.py`, `sufficiency.py`, `trace.py`,
  `diagnose.py`.
* `scripts/run_diagnostics.py` (full run, `--repeat`, `--from-traces`).
* `data/evaluation/datasets/diagnostic_v1.jsonl`.
* `rag/pipeline.py`: `raw_model_output`, `repair_input`.
* `tests/test_observability.py`: 23 tests covering the taxonomy, every
  sufficiency state, raw preservation, trace completeness and determinism,
  secrets, and diagnosis patterns.

## 16. External references (engineering practice only; no regulatory content used)

* Barnett et al., *Seven Failure Points When Engineering a Retrieval Augmented
  Generation System*, CAIN 2024: https://arxiv.org/abs/2401.05856 . Its failure
  points map onto F03, F04, F05, F07 and F15.
* Es et al., *RAGAS: Automated Evaluation of Retrieval Augmented Generation*:
  https://arxiv.org/html/2309.15217v1 . It separates context recall and precision
  from faithfulness and answer relevance, which is why the scorecard separates
  retrieval from generation metrics.
* NIST AI 600-1, *AI RMF Generative AI Profile*: treats confabulation as a
  distinct risk and recommends measuring confidently wrong outputs and surfacing
  uncertainty. This motivates F05/F07 and the sufficiency states.
  https://docs.modulos.ai/frameworks/nist-ai-rmf/generative-ai-profile
* OpenTelemetry GenAI semantic conventions (request model, token usage, finish
  reason, input/output messages per model call). The trace fields align with
  them, for a later export: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/
