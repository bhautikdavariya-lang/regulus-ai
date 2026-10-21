# Retrieval baseline - retrieval_baseline_20261021T064608Z_b225fba9

Retrieval only: the production pipeline with a generator stub (no model, no external API). **Gold keys are developer-keyed or draft and NOT SME-verified** (0 of 352 rows verified): every figure below is a measurement against those keys, not an accuracy result.

- git HEAD `6f949381550f` + working tree, code sha256 `8b3a903ef20e01b5` (158 files)
- dataset `data/evaluation/datasets/retrieval_baseline_v1.jsonl` sha256 `b0893eb873103850`, rows run 352
- eCFR identity `9657a55c247d24f9`, guidance `428b3dbd390bb3d8`; database unchanged during run: **True**
- semantic fallback: production; top_k 8; grounding off; general_evidence_order: **tier**; min_trigram_similarity: **0.4**
- canonical record sha256 `d893dbad8c55ab49f9fd61a7094631d0be74ba296701841a4cf467b11dd9f141` (timings excluded)
- generation requests answered by the stub: 323; errors: 0

## Question-level baseline (section level: any row of an expected section counts)

| Group | n | in candidates | candidate rank <= 8 | in top_k | in context | reaches prompt | retrieved, not in context | median context chars | guidance share |
|---|---|---|---|---|---|---|---|---|---|
| identifier | 119 | 113 (95.0%) | 91 (76.5%) | 111 (93.3%) | 108 (90.8%) | 107 (89.9%) | 5 (4.2%) | 8797 | 0.0283 |
| identifier/retrieval_v2 | 7 | 7 (100.0%) | 7 (100.0%) | 7 (100.0%) | 7 (100.0%) | 7 (100.0%) | 0 (0.0%) | 4806 | 0.0434 |
| identifier/benchmark_rev02 | 112 | 106 (94.6%) | 84 (75.0%) | 104 (92.9%) | 101 (90.2%) | 100 (89.3%) | 5 (4.5%) | 8819.5 | 0.0277 |
| plain_language | 157 | 123 (78.3%) | 65 (41.4%) | 102 (65.0%) | 93 (59.2%) | 93 (59.2%) | 30 (19.1%) | 3600 | 0.6445 |
| plain_language/retrieval_v2 | 22 | 16 (72.7%) | 12 (54.5%) | 14 (63.6%) | 12 (54.5%) | 12 (54.5%) | 4 (18.2%) | 3600.0 | 0.5155 |
| plain_language/benchmark_rev02 | 135 | 107 (79.3%) | 53 (39.3%) | 88 (65.2%) | 81 (60.0%) | 81 (60.0%) | 26 (19.3%) | 3600 | 0.6642 |

## Target-level stages (one expected section = one count)

| Group | targets | corpus_gap | not_retrieved | candidate_unattributed | dropped | in_context_model_not_called | in_prompt | drop reasons |
|---|---|---|---|---|---|---|---|---|
| identifier | 185 | 12 | 7 | 0 | 20 | 1 | 145 | {'hard_ceiling_chars': 14, 'hard_ceiling_count': 1, 'filtered': 1, 'soft_budget': 2, 'consolidated_reserved': 2} |
| plain_language | 245 | 1 | 92 | 0 | 51 | 0 | 101 | {'soft_budget': 30, 'filtered': 25, 'max_results': 1} |

Provision level (paragraph targets such as 812.3(m) must match the paragraph):

| Group | n | in candidates | in context | reaches prompt |
|---|---|---|---|---|
| identifier | 119 | 89 (74.8%) | 87 (73.1%) | 87 (73.1%) |
| plain_language | 157 | 122 (77.7%) | 90 (57.3%) | 90 (57.3%) |

## The audit's eight failure cases

| id | key status | target | exists | cand. rank | top_k rank | stage | drop reasons | context chars (guidance) |
|---|---|---|---|---|---|---|---|---|
| retrieval-015 (key) | developer_keyed_not_sme | 21 CFR 803.50 [provision] | True | 22 | None | dropped | soft_budget | 3600 (2729) |
| retrieval-027 (key) | developer_keyed_not_sme | 21 CFR 820.10(c) [section] | True | None | None | not_retrieved |  | 3600 (2587) |
| retrieval-027 (key) | developer_keyed_not_sme | 21 CFR 820.10(c) [provision] | True | None | None | not_retrieved |  | 3600 (2587) |
| retrieval-032 (key) | developer_keyed_not_sme | 21 CFR 314.50 [provision] | True | None | None | not_retrieved |  | 3600 (2612) |
| retrieval-032 (key) | developer_keyed_not_sme | 21 CFR 312.20 [provision] | True | None | None | not_retrieved |  | 3600 (2612) |
| retrieval-037 (key) | developer_keyed_not_sme | 21 CFR 312.20 [provision] | True | None | None | not_retrieved |  | 3600 (2448) |
| S-007 (key) | draft_unverified | 21 CFR 111.16 [provision] | True | None | None | not_retrieved |  | 3600 (2295) |
| S-007 (alt) | audit_reading_unverified | 21 CFR 111.15 [provision] | True | 25 | 5 | dropped | soft_budget | 3600 (2295) |
| D-016 (key) | draft_unverified | 21 CFR 211.122 [provision] | True | None | None | not_retrieved |  | 3600 (2077) |
| D-016 (key) | draft_unverified | 21 CFR 211.125 [provision] | True | 25 | 7 | dropped | soft_budget | 3600 (2077) |
| P-009 (key) | draft_unverified | 21 CFR 812.2 [provision] | True | None | None | not_retrieved |  | 3600 (2489) |
| P-009 (key) | draft_unverified | 21 CFR 812.3(m) [section] | True | None | None | not_retrieved |  | 3600 (2489) |
| P-009 (key) | draft_unverified | 21 CFR 812.3(m) [provision] | True | None | None | not_retrieved |  | 3600 (2489) |
| K-005 (key) | draft_unverified | 21 CFR 56.107 [provision] | True | None | None | not_retrieved |  | 3600 (2568) |
| K-005 (key) | draft_unverified | 21 CFR 56.111 [provision] | True | 4 | 4 | dropped | filtered | 3600 (2568) |

## Negative controls

retrieval_v2 negatives passing retrieval_eval's rule (no exact_cfr result in top_k): 13/15; excluding structural parent rows: 14/15. Benchmark controls (answer-level behaviour; shown descriptively): gate blocked 8/22, model would be called 14/22. 'Pre-generation fallback' is the pipeline's own answer when it blocks before the model; when the model would be called, nothing after generation is recorded (the stub's empty text would make it meaningless).

| id | named identifiers (exists in DB) | exact_cfr in top_k (excl. parent rows) | gate | blocked | model called | pre-generation fallback |
|---|---|---|---|---|---|---|
| retrieval-008 | 21 CFR 820.30(b)(1) (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| retrieval-035 | - | 0 (0) | UNKNOWN | False | True | - |
| retrieval-040 | 21 CFR 314.999 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| retrieval-041 | 21 CFR 820.999 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| retrieval-042 | 21 CFR 11.75 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| retrieval-043 | 21 CFR part 1400 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| retrieval-044 | 21 CFR part 999 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| retrieval-045 | - | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | no_evidence |
| retrieval-046 | - | 0 (0) | UNKNOWN | False | True | - |
| retrieval-047 | - | 0 (0) | UNKNOWN | False | True | - |
| retrieval-048 | 21 CFR 820.50 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| retrieval-049 | 21 CFR 201.327(z) (False) | 1 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| retrieval-050 | - | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | value_not_established |
| retrieval-051 | 21 CFR part 820 (True) | 9 (9) | ANSWERABLE | False | True | - |
| retrieval-052 | - | 0 (0) | UNKNOWN | False | True | - |
| NC-001 | 21 CFR 111.900 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| NC-002 | 21 CFR 117.999 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| NC-003 | 21 CFR part 820 (True) | 9 (9) | ANSWERABLE | False | True | - |
| NC-004 | 21 CFR part 211 (True) | 64 (64) | ANSWERABLE | False | True | - |
| NC-005 | 21 CFR 820.20 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| NC-006 | - | 0 (0) | UNKNOWN | False | True | - |
| NC-007 | 21 CFR part 111 (True) | 88 (88) | ANSWERABLE | False | True | - |
| NC-008 | - | 0 (0) | UNKNOWN | False | True | - |
| NC-009 | - | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | value_not_established |
| NC-010 | 21 CFR part 11 (True) | 14 (14) | ANSWERABLE | False | True | - |
| NC-011 | 21 CFR 820.30 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| NC-012 | - | 0 (0) | UNKNOWN | False | True | - |
| NC-013 | 21 CFR part 1250 (True) | 48 (48) | ANSWERABLE | False | True | - |
| NC-014 | 21 CFR 101.9(k)(5) (False) | 1 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| NC-015 | - | 0 (0) | UNKNOWN | False | True | - |
| NC-016 | 21 CFR 820.30(j) (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| NC-017 | 21 CFR 820.15 (False) | 0 (0) | INSUFFICIENT_EVIDENCE | True | False | provision_not_found |
| NC-018 | 21 CFR part 830 (True) | 20 (20) | ANSWERABLE | False | True | - |
| NC-019 | - | 0 (0) | UNKNOWN | False | True | - |
| NC-020 | 21 CFR part 4 (True) | 14 (14) | ANSWERABLE | False | True | - |
| NC-021 | 21 CFR part 820 (True) | 15 (15) | ANSWERABLE | False | True | - |
| NC-022 | - | 0 (0) | UNKNOWN | False | True | - |

## Unresolved gold-key questions (need an SME)

- **audit_alternatives** (1): S-007
- **key_target_not_in_snapshot** (13): M-031, M-032, M-033, M-034, M-034, M-034, M-035, M-036, M-037, M-038, M-039, M-040, X-004
- **part_only_key** (12): F-022, L-015, M-030, P-007, T-005, T-006, T-007, T-008, Z-004, SD-010, SD-011, SD-013
- **no_cfr_key** (19): T-011, T-012, C-001, C-005, PB-001, PB-003, PB-004, PB-007, PB-008, SD-001, SD-002, SD-003, SD-004, SD-005, SD-006, SD-007, SD-008, SD-009, SD-012
- **named_identifier_not_in_key** (2): retrieval-017, SD-010
- **zero_heading_overlap_and_never_retrieved** (31): retrieval-027, retrieval-031, retrieval-032, retrieval-034, S-007, L-010, D-005, M-003, M-004, M-006, M-007, M-009, M-011, M-013, M-014, M-015, M-016, M-017, M-018, M-041, M-042, E-004, P-002, P-003, P-009, T-001, T-002, K-003, Y-008, PB-002, PB-005
- **negative_control_key_mentions_sections** (0): none

Rows by kind: {'section_scored': 276, 'negative_control': 37, 'part_only_key': 12, 'no_cfr_key': 19, 'docket_targets': 14}
