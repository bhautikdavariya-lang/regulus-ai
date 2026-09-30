# Answer-quality Stage 3: baseline (before any Stage 3 change)

Recorded 2026-09-29 from the code as it stood after the streaming and
MPS-evaluation stages. Every weakness below is taken from recorded outputs;
nothing is inferred.

Baseline evidence:

* Stage 5 run `stage3_A_baseline`: 51 questions of `stage5_v1.jsonl`, the
  configured production pipeline under the evaluation protocol.
  `artifacts/stage5_stage6/run_20260929T062550Z/stage5/`
* The CPU float32 device-comparison run: 60 questions, production
  `repair` mode. `artifacts/latency/cpu_fp32_20260929T045001Z/`

## Configuration

| | |
|---|---|
| Model | Qwen/Qwen3-0.6B, base, no adapter (revision c1899de) |
| Device / dtype | `auto` → CPU float32 (MPS opt-in only; see `mps_float16_evaluation.md`) |
| Decoding | greedy (`do_sample=False`), thinking off, no repetition penalty |
| Token budget | adaptive allowance per question, ceiling 2,048 (`answer_length_policy.md`) |
| Answer shape | `adaptive` (Stage 12, `adaptive_answer_shape.md`) |
| Validation | `repair` in production; Stage 5 uses `annotate` and derives the repaired answer with the same repair code |

## Current answer pipeline

```text
Question
  ↓  plan_query()            Stage 1: requested provisions (deterministic)
  ↓  analyze_shape()         Stage 12: synthesis / focused / enumeration / comparison / direct
Retrieval (LexicalRetriever.run_plan: exact CFR lookups → full text → OR fallback / trigram)
  ↓  check_coverage()        exact evidence per requested provision
Context construction (select_evidence: required → children → structural → supporting → discovery)
  ↓  build_package()         sources with tiers, plan lines, token allowance
Prompt (fixed system prompt + QUESTION / REQUESTED PROVISIONS / EVIDENCE / ANSWER FORMAT)
  ↓
Qwen3-0.6B: ONE generate() call (streamed as a draft when a listener is attached)
  ↓
Validation (validate_answer: identities, citations, coverage, figures, answer-shape checks)
  ↓
Repair if validation fails (deterministic: strip invalid markers, replace mismatched
statements, append missing provisions/items verbatim, extractive replacement, safe message)
  ↓
Final validation (re-run ONLY if repair changed the text; otherwise final = initial)
  ↓
Citation processing (build_answer_citations: cited markers + authoritative exact sources)
  ↓
Final answer → streaming "final" event / JSON → UI
```

Deterministic answers that bypass the model: a requested provision with no
exact evidence (`refuse_unsupported`), nothing retrieved (`no_context`), and
the optional Stage 13 grounding gate.

## Stage 5 baseline measurements (A)

| Measure (Stage 5 definitions) | Value |
|---|---:|
| Retrieval OK / coverage OK / selection OK | 96.1 % / 98.0 % / 98.0 % |
| Raw answer passes validation | 71.7 % (33 / 46 generated) |
| Final answer passes validation (after repair) | 89.1 % |
| Repair frequency | 28.3 % |
| Unsupported content, raw | 21.7 % |
| All machine checks pass, raw / final | 49.0 % / 56.9 % |
| Claims supported by their cited source (heuristic), raw / final | 36.6 % / 41.4 % |
| Correct refusals (refusal expected) | 66.7 % |
| Out-of-domain content answered (domain leak, raw) | 75 % of domain-boundary questions |
| False refusals | 0 % |
| Latency p50 / p95 (total) | 9.7 s / 33.6 s |

"All machine checks pass" is Stage 5's conservative composite over the
developer-fixed expectations in `stage5_v1.jsonl`. It is not an SME-verified
correctness score: the 300-question acceptance benchmark has no locked key
(`benchmark_key_integrity_investigation.md`: 0 SME decisions, scoring blocked).

## Observed weaknesses (with evidence)

1. **Out-of-scope questions are answered, with citations, and pass validation.**
   S5-082 "What is the boiling point of water in Celsius?" → "The boiling point
   of water is 100°C at standard atmospheric pressure. [1]", status *valid*.
   S5-080 "What is the capital of France?" → "What is the capital of France? [1]",
   *valid*. S5-083 (EU MDR) → an invented answer about MDDS assignment.
   Correct refusals: 66.7 %; domain leak 75 %.
2. **False premises are affirmed.** S5-053 "Does 21 CFR 820.10(b)(2) require
   annual traceability audits?" → "21 CFR 820.10(b)(2) requires annual
   traceability audits. [1]", status *valid*. The source says nothing about
   audits. S5-052 (a compliance date) → "by the date specified in the
   requirements", also *valid*.
3. **Citation markers at the start of a line are misattributed.** In 15 of 55
   answers the model writes "[1] 21 CFR 820.10(c) requires …". The validator
   attaches a marker to the sentence *before* it, so each such citation is read
   as supporting the previous statement (e.g. S5-022, AS-05).
4. **The question is echoed** in 4 answers (S5-062, S5-080, S5-082, AS-09).
5. **Low claim-level support**: 36.6 % of raw claims are judged supported by
   the source they cite (heuristic; the rest are uncertain or unsupported).
6. **Mixed questions** (S5-084: a CFR provision plus "the population of
   Paris") fail validation and are replaced wholesale by an extractive answer.
7. **Citation-lookup questions are answered as enumerations.** S5-091 "Which
   provision of 21 CFR 820.10 refers to part 806?" parses "part 806" as a
   second requested provision, so the Stage 12 shape becomes an exhaustive
   enumeration and every paragraph is listed.

Already correct, and to be preserved:

* Nonexistent provisions and dockets are refused deterministically.
* No false refusals.
* Requested-provision completeness is 100 % for multi-provision and range
  questions.
* Qualifiers are kept and flagged when lost.
* Streaming shows a draft and replaces it with the validated answer.
