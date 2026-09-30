# Stage 5 Final Report (smoke_evidence)

Dataset: stage5_v1 (8 questions, sha256 7cf80fda674fd1ab...). Base Qwen3-0.6B, greedy decoding, default budget. Generated 2026-09-22T12:06:43+00:00.

## BASELINE PERFORMANCE

| Layer | Metric | Value |
|---|---|---|
| Retrieval | questions with every expected provision retrieved exactly | 100% |
| Retrieval | requirement recall (provisions) | 100% |
| Retrieval | multi-provision full recall | 100% |
| Retrieval | range full recall | 100% |
| Retrieval | missing provisions correctly absent | 100% |
| Coverage | state and missing labels as expected | 100% |
| Coverage | incomplete requests detected | 100% |
| Selection | required exact evidence preserved in context | 100% |
| Selection | deterministic | 100% |
| Generation | full pipeline, raw model text valid | n/a (0 generated) |
| Generation | full pipeline, valid after deterministic repair | n/a |
| Generation | valid ONLY because of repair | n/a |
| Generation | controlled (exact evidence only), raw valid | n/a (0 generated) |
| Generation | truncated (full) | 0 |
| Faithfulness | claims supported (heuristic) | n/a of 0 judged claims; 0 not supported |
| Citations | answers with no invalid or mismatched citation | n/a |
| Citations | satisfied provisions whose exact source was cited | n/a |
| Hallucination | raw answers with unsupported content | n/a |
| Hallucination | after repair | n/a |
| Refusal | correct refusals | n/a; false refusals raw: [] |
| Domain boundary | out-of-domain leak (raw) | n/a |
| Latency | end-to-end p50 / p95 / max (ms) | None / None / None |
| Latency | generation p50 / p95 (ms) | None / None |
| Repair | frequency | n/a; failed repairs: [] |

## FAILURES BY LAYER

| Layer | Questions |
|---|---|
| not_run | 8 |

### Failing questions


## KNOWN LIMITATIONS

- Faithfulness is heuristic (word overlap plus deterministic checks); SUPPORTED is unproven, NOT SUPPORTED is reliable.
- The dataset is 50 questions concentrated on parts 820 and 101; rates have wide confidence intervals.
- Domain-boundary questions cannot be rejected deterministically when no provision or figure is involved; the validator reports them but cannot fix them.
- Latency is CPU-bound; generation dominates every end-to-end number.

## TRAINING-RELEVANT FAILURES

Model-side failures (layers generation / generation_context): 0. Architecture failures (not trainable): 0. Domain leaks (not trainable here): 0.


**Stage 6 recommendation:** DO NOT PROCEED. only 0 model-side failures (threshold 3); training is not justified by this evaluation
