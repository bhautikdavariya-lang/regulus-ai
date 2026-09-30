# Stage 5 Final Report (stage3_A_baseline)

Dataset: stage5_v1 (51 questions, sha256 7cf80fda674fd1ab...). Base Qwen3-0.6B, greedy decoding, default budget. Generated 2026-09-29T06:37:12+00:00.

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
| Generation | full pipeline, raw model text valid | 72% (46 generated) |
| Generation | full pipeline, valid after deterministic repair | 89% |
| Generation | valid ONLY because of repair | 17% |
| Generation | controlled (exact evidence only), raw valid | n/a (0 generated) |
| Generation | truncated (full) | 2 |
| Faithfulness (raw) | claims supported (heuristic) | 37% of 134 judged; 16 not supported |
| Faithfulness (final) | claims supported after repair (heuristic) | 41% of 140 judged; 14 not supported |
| Citations | answers with no invalid or mismatched citation | 80% |
| Citations | satisfied provisions whose exact source was cited | 98% |
| Hallucination | raw answers with unsupported content | 22% |
| Hallucination | after repair | 22% |
| Refusal | correct refusals | 67%; false refusals raw: [] |
| Domain boundary | out-of-domain leak (raw) | 75% |
| Latency | end-to-end p50 / p95 / max (ms) | 9725.4 / 33550.9 / 100240.7 |
| Latency | generation p50 / p95 (ms) | 9920.3 / 33333.2 |
| Repair | frequency | 28%; failed repairs: ['S5-024', 'S5-061', 'S5-090', 'S5-091', 'S5-111'] |
| Answer correctness | RAW model answer, all machine checks pass | 49% (51 questions) |
| Answer correctness | FINAL answer after deterministic repair | 57%; correct only because of repair: ['S5-051', 'S5-070', 'S5-071', 'S5-084'] |
| Multi-provision | every requested provision addressed (raw) | 100% of 5 |
| Range | every requested provision addressed (raw) | 100% of 6 |
| Partial / missing | absent provision named in the final answer | 100%; invented content for it (raw): [] |
| Adversarial | raw answers with unsupported content | 20% of 5 |

## WHAT EACH COLUMN MEANS

The report never merges these five:

1. **Raw model answer** - the text Qwen produced, before anything touched it.
2. **Validator result** - what the deterministic checks said about that raw text.
3. **Repaired answer** - the raw text after the deterministic repair replaced or completed it from verbatim source text.
4. **Semantic correctness of the raw answer** - the machine-checkable composite over the raw text.
5. **Semantic correctness of the final answer** - the same composite over the repaired text; a pass here is a property of the pipeline, not of the model.

Answers valid only because of repair: 0.1739 of the generated set. Answers correct only because of repair: ['S5-051', 'S5-070', 'S5-071', 'S5-084'].

## FAILURES BY LAYER

| Layer | Questions |
|---|---|
| domain_boundary | 3 |
| generation | 14 |
| none | 32 |
| retrieval | 2 |

### Failing questions

- **S5-007** (single, layer `generation`): unsupported content: uncited_statement, low_overlap_with_cited_source, scope_expansion, synthesis_citation_gap, 21 CFR 806.1(b)
- **S5-012** (section, layer `generation`): raw answer failed validation: uncited_statement, low_overlap_with_cited_source, material_group_uncovered, synthesis_citation_gap
- **S5-023** (multi, layer `generation`): unsupported content: 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36
- **S5-024** (multi, layer `generation`): raw answer failed validation: degenerate_output, repeated_statement
- **S5-033** (range, layer `generation`): unsupported content: 21 CFR 101.13, 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36
- **S5-051** (adversarial, layer `generation`): raw answer failed validation: unsupported_figure, low_overlap_with_cited_source; unsupported content: unsupported_figure, low_overlap_with_cited_source
- **S5-060** (general, layer `generation`): raw answer failed validation: invalid_citation; unsupported content: invalid_citation, 21 CFR 213.180(d), 21 CFR 213.180(e)
- **S5-061** (general, layer `generation`): raw answer failed validation: degenerate_output, truncated, invalid_citation, repeated_statement
- **S5-063** (general, layer `generation`): raw answer failed validation: invalid_citation; unsupported content: invalid_citation, 45 CFR 46.115(a)(2), 21 CFR 56.115(a)(2)
- **S5-070** (guidance, layer `generation`): raw answer failed validation: invalid_citation
- **S5-071** (guidance, layer `generation`): raw answer failed validation: invalid_citation
- **S5-080** (domain_boundary, layer `domain_boundary`): model answered an out-of-domain question from its own knowledge (validator has nothing deterministic to reject)
- **S5-082** (domain_boundary, layer `domain_boundary`): model answered an out-of-domain question from its own knowledge (validator has nothing deterministic to reject)
- **S5-083** (domain_boundary, layer `domain_boundary`): model answered an out-of-domain question from its own knowledge (validator caught it)
- **S5-084** (domain_boundary, layer `generation`): raw answer failed validation: unsupported_figure; unsupported content: unsupported_figure
- **S5-090** (citation, layer `retrieval`): retrieval: parser named ['21 CFR part 803']
- **S5-091** (citation, layer `retrieval`): retrieval: parser named ['21 CFR 820.10', '21 CFR part 806']
- **S5-101** (long, layer `generation`): unsupported content: low_overlap_with_cited_source, synthesis_citation_gap, repeated_statement, 21 CFR 101.9, 21 CFR 101.10, 21 CFR 101.36, 21 CFR 101.13
- **S5-111** (refusal, layer `generation`): raw answer failed validation: truncated, invalid_citation, uncited_statement, scope_expansion, qualifier_misapplied

## KNOWN LIMITATIONS

- Faithfulness is heuristic (word overlap plus deterministic checks); SUPPORTED is unproven, NOT SUPPORTED is reliable.
- The dataset is 50 questions concentrated on parts 820 and 101; rates have wide confidence intervals.
- Domain-boundary questions cannot be rejected deterministically when no provision or figure is involved; the validator reports them but cannot fix them.
- Latency is CPU-bound; generation dominates every end-to-end number.

## TRAINING-RELEVANT FAILURES

Model-side failures (layers generation / generation_context): 14. Architecture failures (not trainable): 2. Domain leaks (not trainable here): 3.

- multi_provision_answers: 4 question(s) ['S5-023', 'S5-024', 'S5-033', 'S5-101'] -> dataset categories ['multi_provision', 'range_provision']
- grounded_general_answers: 3 question(s) ['S5-060', 'S5-061', 'S5-063'] -> dataset categories ['grounded_topic', 'grounded_definition']
- grounded_guidance_answers: 2 question(s) ['S5-070', 'S5-071'] -> dataset categories ['guidance_answer', 'fda_guidance']
- grounded_single_provision: 1 question(s) ['S5-007'] -> dataset categories ['direct_cfr', 'section_paragraph']
- grounded_section_summary: 1 question(s) ['S5-012'] -> dataset categories ['direct_cfr']
- non_fabrication: 1 question(s) ['S5-051'] -> dataset categories ['wrong_context', 'context_mismatch', 'citation_grounding']
- domain_boundary_refusal: 1 question(s) ['S5-084'] -> dataset categories ['abstention']
- answer_when_evidence_exists: 1 question(s) ['S5-111'] -> dataset categories ['direct_cfr', 'grounded_topic', 'section_paragraph']

**Stage 6 recommendation:** PROCEED. 14 of 46 generated answers fail for model-side reasons with the evidence architecture working
