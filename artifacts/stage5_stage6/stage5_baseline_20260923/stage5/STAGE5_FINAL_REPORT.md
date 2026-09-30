# Stage 5 Final Report (stage5_baseline_20260923)

Dataset: stage5_v1 (51 questions, sha256 7cf80fda674fd1ab...). Base Qwen3-0.6B, greedy decoding, default budget. Generated 2026-09-23T06:16:07+00:00.

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
| Generation | full pipeline, raw model text valid | 76% (46 generated) |
| Generation | full pipeline, valid after deterministic repair | 93% |
| Generation | valid ONLY because of repair | 17% |
| Generation | controlled (exact evidence only), raw valid | 83% (36 generated) |
| Generation | truncated (full) | 2 |
| Faithfulness (raw) | claims supported (heuristic) | 50% of 98 judged; 27 not supported |
| Faithfulness (final) | claims supported after repair (heuristic) | 54% of 109 judged; 13 not supported |
| Citations | answers with no invalid or mismatched citation | 91% |
| Citations | satisfied provisions whose exact source was cited | 94% |
| Hallucination | raw answers with unsupported content | 26% |
| Hallucination | after repair | 15% |
| Refusal | correct refusals | 89%; false refusals raw: ['S5-050'] |
| Domain boundary | out-of-domain leak (raw) | 25% |
| Latency | end-to-end p50 / p95 / max (ms) | 41627.7 / 139011.6 / 279322.5 |
| Latency | generation p50 / p95 (ms) | 40787.5 / 138345.4 |
| Repair | frequency | 24%; failed repairs: ['S5-062', 'S5-090', 'S5-091'] |
| Answer correctness | RAW model answer, all machine checks pass | 57% (51 questions) |
| Answer correctness | FINAL answer after deterministic repair | 71%; correct only because of repair: ['S5-020', 'S5-041', 'S5-042', 'S5-050', 'S5-051', 'S5-084', 'S5-111'] |
| Multi-provision | every requested provision addressed (raw) | 100% of 5 |
| Range | every requested provision addressed (raw) | 100% of 6 |
| Partial / missing | absent provision named in the final answer | 100%; invented content for it (raw): ['S5-041', 'S5-042'] |
| Adversarial | raw answers with unsupported content | 20% of 5 |

## WHAT EACH COLUMN MEANS

The report never merges these five:

1. **Raw model answer** - the text Qwen produced, before anything touched it.
2. **Validator result** - what the deterministic checks said about that raw text.
3. **Repaired answer** - the raw text after the deterministic repair replaced or completed it from verbatim source text.
4. **Semantic correctness of the raw answer** - the machine-checkable composite over the raw text.
5. **Semantic correctness of the final answer** - the same composite over the repaired text; a pass here is a property of the pipeline, not of the model.

Answers valid only because of repair: 0.1739 of the generated set. Answers correct only because of repair: ['S5-020', 'S5-041', 'S5-042', 'S5-050', 'S5-051', 'S5-084', 'S5-111'].

## FAILURES BY LAYER

| Layer | Questions |
|---|---|
| domain_boundary | 1 |
| generation | 9 |
| generation_context | 4 |
| none | 35 |
| retrieval | 2 |

### Failing questions

- **S5-012** (section, layer `generation`): raw answer failed validation: provision_citation_mismatch, low_overlap_with_cited_source; unsupported content: provision_citation_mismatch, low_overlap_with_cited_source
- **S5-020** (multi, layer `generation_context`): raw answer failed validation: provision_citation_mismatch, citation_mismatch; unsupported content: provision_citation_mismatch, citation_mismatch; the same model answers correctly when given exact evidence only
- **S5-023** (multi, layer `generation`): unsupported content: 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36
- **S5-033** (range, layer `generation`): unsupported content: 21 CFR 101.13, 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36
- **S5-041** (missing, layer `generation_context`): raw answer failed validation: asserted_missing_provision; unsupported content: asserted_missing_provision; the same model answers correctly when given exact evidence only
- **S5-042** (missing, layer `generation`): raw answer failed validation: asserted_missing_provision; unsupported content: asserted_missing_provision
- **S5-050** (adversarial, layer `generation_context`): raw answer failed validation: refusal_with_evidence, low_overlap_with_cited_source; refused although exact evidence was supplied; the same model answers correctly when given exact evidence only
- **S5-051** (adversarial, layer `generation`): raw answer failed validation: unsupported_figure, low_overlap_with_cited_source; unsupported content: unsupported_figure, low_overlap_with_cited_source
- **S5-062** (general, layer `generation`): raw answer failed validation: truncated
- **S5-063** (general, layer `generation`): unsupported content: 45 CFR 46.115(a)(2), 21 CFR 56.115(a)(2)
- **S5-083** (domain_boundary, layer `domain_boundary`): model answered an out-of-domain question from its own knowledge (validator has nothing deterministic to reject)
- **S5-084** (domain_boundary, layer `generation`): raw answer failed validation: unsupported_figure; unsupported content: unsupported_figure
- **S5-090** (citation, layer `retrieval`): retrieval: parser named ['21 CFR part 803']
- **S5-091** (citation, layer `retrieval`): retrieval: parser named ['21 CFR 820.10', '21 CFR part 806']
- **S5-101** (long, layer `generation`): unsupported content: 21 CFR 101.13, 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36
- **S5-111** (refusal, layer `generation_context`): raw answer failed validation: provision_citation_mismatch, uncited_statement; unsupported content: provision_citation_mismatch, uncited_statement; the same model answers correctly when given exact evidence only

## KNOWN LIMITATIONS

- Faithfulness is heuristic (word overlap plus deterministic checks); SUPPORTED is unproven, NOT SUPPORTED is reliable.
- The dataset is 50 questions concentrated on parts 820 and 101; rates have wide confidence intervals.
- Domain-boundary questions cannot be rejected deterministically when no provision or figure is involved; the validator reports them but cannot fix them.
- Latency is CPU-bound; generation dominates every end-to-end number.

## TRAINING-RELEVANT FAILURES

Model-side failures (layers generation / generation_context): 13. Architecture failures (not trainable): 2. Domain leaks (not trainable here): 1.

- multi_provision_answers: 4 question(s) ['S5-020', 'S5-023', 'S5-033', 'S5-101'] -> dataset categories ['multi_provision', 'range_provision']
- partial_answers_with_not_found: 2 question(s) ['S5-041', 'S5-042'] -> dataset categories ['partial_provision', 'partial_context']
- non_fabrication: 2 question(s) ['S5-050', 'S5-051'] -> dataset categories ['wrong_context', 'context_mismatch', 'citation_grounding']
- grounded_general_answers: 2 question(s) ['S5-062', 'S5-063'] -> dataset categories ['grounded_topic', 'grounded_definition']
- grounded_section_summary: 1 question(s) ['S5-012'] -> dataset categories ['direct_cfr']
- domain_boundary_refusal: 1 question(s) ['S5-084'] -> dataset categories ['abstention']
- answer_when_evidence_exists: 1 question(s) ['S5-111'] -> dataset categories ['direct_cfr', 'grounded_topic', 'section_paragraph']

**Stage 6 recommendation:** PROCEED. 13 of 46 generated answers fail for model-side reasons with the evidence architecture working
