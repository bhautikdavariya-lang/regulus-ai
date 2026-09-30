# Stage 5 Final Report (smoke_gen)

Dataset: stage5_v1 (2 questions, sha256 7cf80fda674fd1ab...). Base Qwen3-0.6B, greedy decoding, default budget. Generated 2026-09-23T04:56:08+00:00.

## BASELINE PERFORMANCE

| Layer | Metric | Value |
|---|---|---|
| Retrieval | questions with every expected provision retrieved exactly | 100% |
| Retrieval | requirement recall (provisions) | 100% |
| Retrieval | multi-provision full recall | n/a |
| Retrieval | range full recall | n/a |
| Retrieval | missing provisions correctly absent | 100% |
| Coverage | state and missing labels as expected | 100% |
| Coverage | incomplete requests detected | 100% |
| Selection | required exact evidence preserved in context | 100% |
| Selection | deterministic | 100% |
| Generation | full pipeline, raw model text valid | 50% (2 generated) |
| Generation | full pipeline, valid after deterministic repair | 100% |
| Generation | valid ONLY because of repair | 50% |
| Generation | controlled (exact evidence only), raw valid | 50% (2 generated) |
| Generation | truncated (full) | 0 |
| Faithfulness | claims supported (heuristic) | 67% of 3 judged claims; 1 not supported |
| Citations | answers with no invalid or mismatched citation | 100% |
| Citations | satisfied provisions whose exact source was cited | 100% |
| Hallucination | raw answers with unsupported content | 50% |
| Hallucination | after repair | 0% |
| Refusal | correct refusals | n/a; false refusals raw: [] |
| Domain boundary | out-of-domain leak (raw) | n/a |
| Latency | end-to-end p50 / p95 / max (ms) | 44836.9 / 48475.9 / 48475.9 |
| Latency | generation p50 / p95 (ms) | 43971.8 / 48353.7 |
| Repair | frequency | 50%; failed repairs: [] |

## FAILURES BY LAYER

| Layer | Questions |
|---|---|
| generation | 1 |
| none | 1 |

### Failing questions

- **S5-042** (missing, layer `generation`): raw answer failed validation: asserted_missing_provision; unsupported content: asserted_missing_provision

## KNOWN LIMITATIONS

- Faithfulness is heuristic (word overlap plus deterministic checks); SUPPORTED is unproven, NOT SUPPORTED is reliable.
- The dataset is 50 questions concentrated on parts 820 and 101; rates have wide confidence intervals.
- Domain-boundary questions cannot be rejected deterministically when no provision or figure is involved; the validator reports them but cannot fix them.
- Latency is CPU-bound; generation dominates every end-to-end number.

## TRAINING-RELEVANT FAILURES

Model-side failures (layers generation / generation_context): 1. Architecture failures (not trainable): 0. Domain leaks (not trainable here): 0.

- partial_answers_with_not_found: 1 question(s) ['S5-042'] -> dataset categories ['partial_provision', 'partial_context']

**Stage 6 recommendation:** DO NOT PROCEED. only 1 model-side failures (threshold 3); training is not justified by this evaluation
