# Answer quality (Stage 3)

Controlled answer generation from the existing model: question analysis,
answer profiles, deterministic scope handling and normalisation, and quality
flags for human review. It does not change the model, retrieval, database,
benchmark, validation, repair, citations or streaming, and it adds no second
model call. It is opt-in: `answer_shape="structured"`. The default remains
`adaptive`. Baseline: [answer_quality_stage3_baseline.md](answer_quality_stage3_baseline.md).

## 1. Why now

The streaming and device stages made the system usable and measurable. The
baseline then showed that the remaining failures are answer failures, not
speed failures:

* out-of-scope questions are answered with citations that pass validation;
* false premises are affirmed;
* citation markers are misattributed;
* questions are echoed;
* only about 37 % of raw claims are judged supported by their cited source.

These are the cheapest problems to address without training, so they come first.

## 2. Pipeline with Stage 3

```text
Question
  ↓ plan_query()                          (unchanged)
  ↓ analyze_shape()                       (unchanged; citation lookups are never exhaustive in structured mode)
  ↓ analyze_question()          ★ Stage 3: type, yes/no, scope
Retrieval → coverage → selection          (unchanged)
  ├─ scope = out_of_scope (named non-U.S. framework) ★ → deterministic answer, NO model call
  ↓ build_package(question_analysis)      ★ profile + weak-evidence / mixed caveat in ANSWER FORMAT
Qwen3-0.6B: ONE generate() call           (unchanged; streamed as a draft)
  ↓ normalize_answer()          ★ markers moved onto their sentence, echoed question removed
Validation → repair → final validation    (unchanged code; runs on the normalised text)
  ↓ mixed-scope note            ★ appended when part of the question was declined
Citations                                 (unchanged)
  ↓ quality_flags()             ★ review signals, in metadata only
Final answer → stream "final" / JSON → UI (unchanged; the UI shows type, scope, flags in Diagnostics)
```

## 3. Question classification (`regulus/planning/intent.py`)

`QuestionAnalysis` has these fields:

* `question_type`
* `is_yes_no`
* `requested_entities`
* `requires_comparison`, `requires_citation`, `requires_procedure`
* `scope_status`, `scope_reason`, `out_of_scope_part`
* `signals`

It is deterministic: regular expressions over the question with the CFR
identifiers masked, plus the Stage 1 plan. Types, in precedence order:
comparison, citation_lookup, scenario, exception_condition, applicability
(including every yes/no question), procedure, definition, explanation,
requirement. Explanation is the default. `insufficient_evidence` is not
guessed from wording; it is an evidence status after retrieval (coverage, and
`weak_evidence` when every source is broad-search only).

**Scope is decided on evidence, not assumed.** Two stricter designs were
tested against all 300 benchmark questions (text only) and the 60 evaluation
questions, and rejected:

| Rule tried | Wrongly declined, of 300 real regulatory questions |
|---|---:|
| "no regulatory vocabulary" → out of scope | 33 (FSVP, HACCP, laser standards, QC unit …) |
| … and "only broad-fallback sources retrieved" | 11: retrieval finds only fallback evidence for those too |
| **named non-U.S. framework, no U.S. reference, no CFR/docket** (adopted) | **0**: it declines exactly SD-001 and S5-083, both EU MDR |

General-knowledge questions ("boiling point of water") are therefore answered
under a weak-evidence instruction and flagged, not declined by rule. Mixed
questions (a CFR provision plus an unrelated clause that names something
specific, with no regulatory word and no back-reference) get the regulatory
part answered and the other part explicitly declined. That is 2 of 360
questions: S5-084 ("population of Paris") and D-023 ("the Barr decision
framework", which the sources do not cover).

## 4. Answer profiles (`regulus/rag/answer_plan.py: PROFILES, profile_for`)

One short lead instruction per type, put at the start of the existing ANSWER
FORMAT line. For example:

* **Requirement:** "Begin with one sentence that directly states what is required."
* **Yes/no:** "Begin with Yes, No, or 'The sources do not say', decided only
  by what the sources state. If the sources do not mention something the
  question assumes, say so instead of agreeing with it."
* **Citation lookup:** "Begin with one sentence that names the provision
  answering the question and says what it provides …"

Every profile ends with "Do not restate the question. Put each source number
at the end of the sentence it supports."

**Why prose and no headings.** The template in the brief ("**Direct answer** /
**Requirement** / **Sources**") was not adopted. Earlier live runs showed this
0.6B model copies list- and template-like text it reads last (a bulleted plan
was reproduced verbatim as the answer, coverage 8/8 → 2/8). Sources are
already shown as a separate citations list by the UI. Structure is therefore
asked for as behaviour ("begin with …"), not as headings to fill.

Prompt size: the profile adds about 30–75 tokens (measured in §8).

## 5. Validation and repair (unchanged, now explicit)

```text
generated text → normalize_answer (structured only) → initial validation
  → repair only if initial validation fails → final validation only if repair changed the text
  → final answer
```

If repair makes no change, the final report *is* the initial one. Nothing in
Stage 3 weakens a check. Normalisation runs *before* validation so the
validator judges the text the reader sees, with markers attached to the right
sentence. It moves markers and removes an echoed first sentence; it adds,
reorders or rephrases no words (tested).

## 6. Citations

Unchanged: `build_answer_citations` lists the markers the answer uses plus the
authoritative exact sources of addressed provisions, each traced
`[n] → SOURCE n → tier → requirement`. Stage 3 changes only *which sentence a
marker attaches to* when the model wrote it at the start of a line. Tests
confirm that no citation is invented and every citation maps to a supplied source.

## 7. Quality dimensions and flags

Nothing is combined into a score. Each dimension is labelled by how it is measured:

| Dimension | How measured today | Label |
|---|---|---|
| Correctness | Stage 5 composite over developer-fixed expectations (validation, provisions, expected terms, refusal, claim support) | BENCHMARK-KEYED (not SME) |
| Grounding | claim support heuristic (word overlap with the cited source); unsupported content | AUTOMATIC, heuristic |
| Citation support | citation checks; `citation_mismatch`, `missing_citation` | AUTOMATIC |
| Completeness | requested provisions addressed; expected terms present | BENCHMARK-KEYED |
| Relevance | `excessive_length`, `scope_expansion` signals | signal only; judgement NOT MEASURABLE YET (SME) |
| Structure | `weak_structure`, `missing_direct_answer`, `question_echo`, markers moved | signal only; judgement NOT MEASURABLE YET (SME) |
| Regulatory precision | `missing_condition` (qualifier dropped/misapplied, applicability dropped), `missing_exception` | signal only; judgement NOT MEASURABLE YET (SME) |
| Refusal / scope | expected refusals declined; expected answers given; domain leak; `scope_mismatch` | BENCHMARK-KEYED + AUTOMATIC |
| Hallucination | unsupported figures, fabricated identifiers, `possible_hallucination`, `unsupported_claim` (premise repeated) | AUTOMATIC |

The flags live in `regulus/rag/answer_quality.py: quality_flags`. Each names
the evidence that raised it. A flag is a reason to look, not proof of failure.
The pipeline's own deterministic messages (safe message, not found, out of
scope) are never flagged as if the model had written them.

## 8. Evaluation and human review

`python scripts/evaluate_answer_quality.py --run A=<stage5 run> --run B=<stage5 run> --label stage3_ab`

* Reads Stage 5 outputs (no second generation). It rebuilds each prompt
  deterministically and checks it against the run: the prompt SHA-256 when
  recorded (Stage 3 runs record it), else the character count.
* Writes `results_<run>.jsonl` with the fields listed in the brief: question
  id, prompt hash, question type, sources, answer, citations, validations,
  repair, coverage action, tokens, length, latency, flags.
* Writes one SME review page per question (`review_<run>/<id>.md`): the
  question, the evidence given to the model, the answer, citations,
  validation and flags, and blank fields for the SME's judgement.
* Writes `compare_A_vs_B.md` with every changed question.

Results for this stage: `artifacts/answer_quality/` (see the final report).

## 9. Benchmark limitations

* `stage5_v1.jsonl` expectations were fixed by the developer, not an SME.
* The 300-question REV02 benchmark has no locked key. It was used here only
  as question *text*, to test that the scope rule declines nothing real. No
  row was altered, and no correctness figure is derived from it.

## 10. Regression method

* Default path: unchanged code path, and existing tests unchanged.
  `answer_shape="off"` and `"adaptive"` prompts are byte-identical to before
  (tested).
* A/B: two Stage 5 runs back to back, same model, device, dtype, database,
  retrieval settings and generation settings. Only `answer_shape` differs
  (`adaptive` vs `structured`). Every changed answer is listed with its diff.

## 11. Known limitations

* The classifier is a set of rules. It was checked on 360 questions, but new
  phrasings can be mis-typed; the type only selects a lead instruction.
* Scope refusal covers named non-U.S. frameworks only. General-knowledge
  questions can still be answered from the model's own knowledge. They are
  flagged (`scope_mismatch`, `uncertainty_not_disclosed`), not prevented.
* The model does not always follow the profile. See the A/B results for where it did not.
* Flags are heuristics; claim support is word overlap, not entailment.

## 12. Future training opportunities (not done here)

The A/B record gives targeted material if training is later justified:

* yes/no answers that repeat an unsupported premise;
* general-knowledge answers to out-of-domain questions;
* citation-lookup questions answered with the wrong provision;
* misapplied "if applicable".

These are behaviours a prompt can only partly control in a 0.6B model.

## 13. A/B results (2026-09-29)

A = `adaptive` (current default), Stage 5 run `run_20260929T062550Z`.
B = `structured`, Stage 5 run `run_20260929T064523Z`.

Both runs: 51 questions, back to back, same model, CPU float32, same database,
retrieval and generation settings. Prompt identity was verified for every
question: A by prompt length (A predates hash recording), B by SHA-256.

Evaluation: `artifacts/answer_quality/stage3_ab_20260929T065531Z/`: `summary.json`, `results_{A,B}.jsonl`,
`review_{A,B}/` (51 SME pages each) and `compare_A_vs_B.md` (39 changed questions).

| Dimension (how measured) | A | B |
|---|---:|---:|
| Raw answer passes validation (automatic) | 71.7 % | **88.9 %** |
| Final answer passes validation (automatic) | 89.1 % | **97.8 %** |
| Repair needed (automatic) | 28.3 % | **11.1 %** |
| Unsupported content, raw / final (automatic) | 21.7 % / 21.7 % | **17.8 % / 15.6 %** |
| Claims supported by their cited source, raw (heuristic) | 36.6 % | **52.2 %** |
| Citation checks pass, raw (automatic) | 37 / 46 | **43 / 45** |
| All machine checks pass, final (benchmark-keyed, not SME) | 29 / 51 | 31 / 51 |
| Every expected provision addressed (benchmark-keyed) | 42 / 42 | 42 / 42 |
| Expected refusals: answered anyway (benchmark-keyed) | 3 / 9 (France, boiling point, EU MDR) | **1 / 9** (France) |
| Expected answers given (no false refusal) | 42 / 42 | 42 / 42 |
| Question echo / leading markers moved (signals) | 3 / 0 | 0 / 6 |
| Semantic correctness, relevance, structure, regulatory precision | NOT MEASURABLE YET: requires SME review | same |

Per-question review of the 5 questions the machine composite marks "worse"
in B (the developer's reading, not an SME verdict): 2 are real regressions,
S5-022 ("if applicable" wrongly attached to 820.10(b)(4)) and S5-070 (the
guidance summary lost "510(k)"). The other 3 are artefacts: S5-011's B answer
is more faithful but trips the overlap heuristic; S5-042's A answer *invented
requirements for the nonexistent 820.999* yet passed; and S5-081 is a decline
with an extra sentence. The machine composite is too noisy to rank A and B on
its own. The SME pages are the intended check.

Performance (automatic, median): prompt tokens 1,362.5 → 1,411 (+3.6 %),
generated tokens 107.5 → 103, first token 1.77 → 1.79 s, generation 10.2 →
9.4 s, total 9.7 → 8.4 s (p95 33.6 → 25.9 s), truncated answers 2 → 0.
