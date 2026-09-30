# Stage 5 Final Report (run_20260924T070134Z)

Dataset: stage5_v1 (51 questions, sha256 7cf80fda674fd1ab...). Base Qwen3-0.6B, greedy decoding, default budget. Generated 2026-09-24T08:16:36+00:00.

## BASELINE PERFORMANCE

| Layer | Metric | Value |
|---|---|---|
| Retrieval | questions with every expected provision retrieved exactly | 100% |
| Retrieval | requirement recall (provisions) | 100% |
| Retrieval | multi-provision full recall | 100% |
| Retrieval | range full recall | 100% |
| Retrieval | missing provisions correctly absent | 100% |
| Coverage | state and missing labels as expected | 98% |
| Coverage | incomplete requests detected | 100% |
| Selection | required exact evidence preserved in context | 100% |
| Selection | deterministic | 100% |
| Generation | full pipeline, raw model text valid | 85% (46 generated) |
| Generation | full pipeline, valid after deterministic repair | 96% |
| Generation | valid ONLY because of repair | 11% |
| Generation | controlled (exact evidence only), raw valid | 86% (36 generated) |
| Generation | truncated (full) | 0 |
| Faithfulness (raw) | claims supported (heuristic) | 53% of 94 judged; 23 not supported |
| Faithfulness (final) | claims supported after repair (heuristic) | 54% of 104 judged; 17 not supported |
| Citations | answers with no invalid or mismatched citation | 96% |
| Citations | satisfied provisions whose exact source was cited | 89% |
| Hallucination | raw answers with unsupported content | 20% |
| Hallucination | after repair | 13% |
| Refusal | correct refusals | 67%; false refusals raw: ['S5-050', 'S5-051', 'S5-052'] |
| Domain boundary | out-of-domain leak (raw) | 75% |
| Latency | end-to-end p50 / p95 / max (ms) | 35206.3 / 132507.5 / 271987.6 |
| Latency | generation p50 / p95 (ms) | 43492.6 / 131926.6 |
| Repair | frequency | 15%; failed repairs: ['S5-091', 'S5-101'] |
| Answer correctness | RAW model answer, all machine checks pass | 55% (51 questions) |
| Answer correctness | FINAL answer after deterministic repair | 65%; correct only because of repair: ['S5-041', 'S5-042', 'S5-050', 'S5-051', 'S5-052'] |
| Multi-provision | every requested provision addressed (raw) | 100% of 5 |
| Range | every requested provision addressed (raw) | 100% of 6 |
| Partial / missing | absent provision named in the final answer | 100%; invented content for it (raw): ['S5-041', 'S5-042'] |
| Adversarial | raw answers with unsupported content | 0% of 5 |

## WHAT EACH COLUMN MEANS

The report never merges these five:

1. **Raw model answer** - the text Qwen produced, before anything touched it.
2. **Validator result** - what the deterministic checks said about that raw text.
3. **Repaired answer** - the raw text after the deterministic repair replaced or completed it from verbatim source text.
4. **Semantic correctness of the raw answer** - the machine-checkable composite over the raw text.
5. **Semantic correctness of the final answer** - the same composite over the repaired text; a pass here is a property of the pipeline, not of the model.

Answers valid only because of repair: 0.1087 of the generated set. Answers correct only because of repair: ['S5-041', 'S5-042', 'S5-050', 'S5-051', 'S5-052'].

## FAILURES BY LAYER

| Layer | Questions |
|---|---|
| domain_boundary | 3 |
| generation | 8 |
| generation_context | 3 |
| none | 35 |
| retrieval | 2 |

### Failing questions

- **S5-007** (single, layer `generation_context`): unsupported content: low_overlap_with_cited_source, 21 CFR 806.1(b); the same model answers correctly when given exact evidence only
- **S5-023** (multi, layer `generation`): unsupported content: 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36
- **S5-024** (multi, layer `generation`): unsupported content: 21 CFR 807.20
- **S5-033** (range, layer `generation`): unsupported content: 21 CFR 101.13, 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36
- **S5-041** (missing, layer `generation_context`): raw answer failed validation: asserted_missing_provision; unsupported content: asserted_missing_provision; the same model answers correctly when given exact evidence only
- **S5-042** (missing, layer `generation`): raw answer failed validation: asserted_missing_provision; unsupported content: asserted_missing_provision
- **S5-050** (adversarial, layer `generation`): raw answer failed validation: refusal_with_evidence, low_overlap_with_cited_source; refused although exact evidence was supplied
- **S5-051** (adversarial, layer `generation_context`): raw answer failed validation: refusal_with_evidence, low_overlap_with_cited_source; refused although exact evidence was supplied; the same model answers correctly when given exact evidence only
- **S5-052** (adversarial, layer `generation`): raw answer failed validation: requirement_not_addressed, refusal_with_evidence; refused although exact evidence was supplied; addressed [] of ['r1']
- **S5-063** (general, layer `generation`): unsupported content: 45 CFR 46.115(a)(2), 21 CFR 56.115(a)(2)
- **S5-080** (domain_boundary, layer `domain_boundary`): model answered an out-of-domain question from its own knowledge (validator has nothing deterministic to reject)
- **S5-082** (domain_boundary, layer `domain_boundary`): model answered an out-of-domain question from its own knowledge (validator has nothing deterministic to reject)
- **S5-083** (domain_boundary, layer `domain_boundary`): model answered an out-of-domain question from its own knowledge (validator has nothing deterministic to reject)
- **S5-090** (citation, layer `retrieval`): retrieval: parser named ['21 CFR part 803']
- **S5-091** (citation, layer `retrieval`): retrieval: parser named ['21 CFR 820.10', '21 CFR part 806']
- **S5-101** (long, layer `generation`): raw answer failed validation: provision_citation_mismatch, citation_mismatch, low_overlap_with_cited_source; unsupported content: provision_citation_mismatch, citation_mismatch, low_overlap_with_cited_source, 21 CFR 101.13, 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36

## KNOWN LIMITATIONS

- Faithfulness is heuristic (word overlap plus deterministic checks); SUPPORTED is unproven, NOT SUPPORTED is reliable.
- The dataset is 50 questions concentrated on parts 820 and 101; rates have wide confidence intervals.
- Domain-boundary questions cannot be rejected deterministically when no provision or figure is involved; the validator reports them but cannot fix them.
- Latency is CPU-bound; generation dominates every end-to-end number.

## TRAINING-RELEVANT FAILURES

Model-side failures (layers generation / generation_context): 11. Architecture failures (not trainable): 2. Domain leaks (not trainable here): 3.

- multi_provision_answers: 4 question(s) ['S5-023', 'S5-024', 'S5-033', 'S5-101'] -> dataset categories ['multi_provision', 'range_provision']
- non_fabrication: 3 question(s) ['S5-050', 'S5-051', 'S5-052'] -> dataset categories ['wrong_context', 'context_mismatch', 'citation_grounding']
- partial_answers_with_not_found: 2 question(s) ['S5-041', 'S5-042'] -> dataset categories ['partial_provision', 'partial_context']
- grounded_single_provision: 1 question(s) ['S5-007'] -> dataset categories ['direct_cfr', 'section_paragraph']
- grounded_general_answers: 1 question(s) ['S5-063'] -> dataset categories ['grounded_topic', 'grounded_definition']

**Stage 6 recommendation:** PROCEED. 11 of 46 generated answers fail for model-side reasons with the evidence architecture working
