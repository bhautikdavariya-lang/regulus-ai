# Root-cause matrix

| Question | Category | Final status | Primary failure | Secondary | Root module | Evidence (primary) |
|---|---|---|---|---|---|---|
| S5-001 | exact_provision_lookup | PASS | — | — | — |  |
| S5-002 | exact_provision_lookup | PASS | — | — | — |  |
| S5-003 | exact_provision_lookup | PASS | — | — | — |  |
| S5-004 | exact_provision_lookup | PASS | — | — | — |  |
| S5-005 | exact_provision_lookup | PASS | — | — | — |  |
| S5-006 | exact_provision_lookup | FAIL | F15 Completeness failure [proven] |  | generation | final answer lacks expected term(s): ['validation'] |
| S5-007 | exact_provision_lookup | FAIL | F09 Citation attribution failure [proven] |  | citations | initial validation: synthesis_citation_gap |
| S5-008 | exact_provision_lookup | PASS | — | — | — |  |
| S5-010 | direct_requirement | FAIL | F15 Completeness failure [proven] | F08, F09 | generation | final answer lacks expected term(s): ['ISO 13485'] |
| S5-011 | direct_requirement | PASS | — | — | — |  |
| S5-012 | multiple_provisions | FAIL | F16 Model capability limitation [probable] | F09 | generation | with exact evidence only, the model still fails: ['synthesis_citation_gap'] |
| S5-013 | multiple_provisions | PASS | — | — | — |  |
| S5-020 | multiple_provisions | PASS | — | — | — |  |
| S5-021 | multiple_provisions | FAIL | F16 Model capability limitation [probable] | F09 | generation | with exact evidence only, the model still fails: ['synthesis_citation_gap'] |
| S5-022 | comparison | PASS | — | — | — |  |
| S5-023 | multiple_provisions | PASS | — | — | — |  |
| S5-024 | multiple_provisions | FAIL | F12 Repair failure [proven] | F14, F18 | repair | repair 'extractive_replacement' ran and final validation still fails: ['enumeration_incomplete'] |
| S5-030 | multiple_provisions | PASS | — | — | — |  |
| S5-031 | multiple_provisions | FAIL | F15 Completeness failure [proven] |  | generation | final answer lacks expected term(s): ['830', '821', '803', '806'] |
| S5-032 | multiple_provisions | PASS | — | — | — |  |
| S5-033 | multiple_provisions | PASS | — | — | — |  |
| S5-040 | evidence_insufficient | PASS | — | — | — |  |
| S5-041 | evidence_insufficient | FAIL | F08 Regulatory qualifier failure [probable] | F09 | generation | initial validation: qualifier_dropped (warnings) |
| S5-042 | evidence_insufficient | PASS | — | — | — |  |
| S5-043 | evidence_insufficient | PASS | — | — | — |  |
| S5-044 | evidence_insufficient | PASS | — | — | — |  |
| S5-045 | evidence_insufficient | PASS | — | — | — |  |
| S5-050 | numerical_requirement | PASS | — | — | — |  |
| S5-051 | numerical_requirement | PASS | — | — | — |  |
| S5-052 | numerical_requirement | PASS | — | — | — |  |
| S5-053 | false_premise | FAIL | F07 Unsupported generation [probable] | F08, F11 | generation | yes/no question: the raw answer affirms terms no supplied source contains: ['annual', 'audits'] |
| S5-054 | false_premise | PASS | — | — | — |  |
| S5-060 | direct_requirement | PASS | (contained) F09 Citation attribution failure [proven] |  | citations | initial validation: invalid_citation |
| S5-061 | direct_requirement | FAIL | F13 Safe-fallback failure [proven] | F09, F14, F18 | repair | the safe message replaced the answer: an answerable question received no answer (raw failed: ['degenerate_output']) |
| S5-062 | direct_requirement | PASS | — | — | — |  |
| S5-063 | direct_requirement | PASS | (contained) F09 Citation attribution failure [proven] |  | citations | initial validation: invalid_citation |
| S5-070 | guidance_vs_regulation | PASS | (contained) F09 Citation attribution failure [proven] |  | citations | initial validation: invalid_citation |
| S5-071 | guidance_vs_regulation | PASS | (contained) F09 Citation attribution failure [proven] |  | citations | initial validation: invalid_citation |
| S5-072 | guidance_vs_regulation | PASS | — | — | — |  |
| S5-080 | out_of_scope_general | FAIL | F02 Scope classification failure [proven] | F05, F11 | scope | expected to decline (stage5_v1:S5-080); final answer supplies content; diagnostic scope = in_scope; the pipeline mode did not use a scope decision |
| S5-081 | out_of_scope_general | PASS | — | — | — |  |
| S5-082 | out_of_scope_general | FAIL | F02 Scope classification failure [proven] | F05, F11 | scope | expected to decline (stage5_v1:S5-082); final answer supplies content; diagnostic scope = in_scope; the pipeline mode did not use a scope decision |
| S5-083 | out_of_scope_framework | PASS | — | — | — |  |
| S5-084 | mixed_scope | PASS | (contained) F07 Unsupported generation [proven] |  | generation | initial validation: unsupported_figure |
| S5-090 | citation_specific | NEEDS_REVIEW | F21 Answerability false block [needs_review] |  | answerability | generation blocked (WRONG_PROVISION: 21 CFR part 803 is named as the provision being referred to, not as the one asked for; the retrieved evidence is that provi |
| S5-091 | citation_specific | FAIL | F15 Completeness failure [proven] | F08, F09, F13, F16 | generation | final answer lacks expected term(s): ['(b)(4)', '806'] |
| S5-100 | multiple_provisions | FAIL | F16 Model capability limitation [probable] | F09 | generation | with exact evidence only, the model still fails: ['synthesis_citation_gap'] |
| S5-101 | multiple_provisions | FAIL | F16 Model capability limitation [probable] | F09, F14 | generation | with exact evidence only, the model still fails: ['synthesis_citation_gap'] |
| S5-110 | direct_requirement | PASS | — | — | — |  |
| S5-111 | direct_requirement | PASS | (contained) F08 Regulatory qualifier failure [probable] | F09, F18 | generation | initial validation: qualifier_misapplied (warnings) |
| S5-112 | direct_requirement | PASS | — | — | — |  |
| AS-01 | direct_requirement | FAIL | F08 Regulatory qualifier failure [probable] |  | generation | initial validation: qualifier_misapplied (warnings) |
| AS-02 | exact_provision_lookup | FAIL | F15 Completeness failure [proven] |  | generation | final answer lacks 1 expected point(s) |
| AS-03 | multiple_provisions | FAIL | F08 Regulatory qualifier failure [probable] | F09, F16 | generation | initial validation: qualifier_misapplied (warnings) |
| AS-04 | multiple_provisions | PASS | (contained) F07 Unsupported generation [needs_review] |  | generation | 1 raw claim(s) share almost no words with the source they cite (heuristic) |
| AS-05 | comparison | PASS | (contained) F09 Citation attribution failure [proven] |  | citations | initial validation: citation_mismatch, provision_citation_mismatch, synthesis_citation_gap |
| AS-06 | conditional_requirement | FAIL | F15 Completeness failure [proven] |  | generation | final answer lacks 1 expected point(s) |
| AS-07 | multiple_provisions | PASS | — | — | — |  |
| AS-08 | cross_reference | PASS | — | — | — |  |
| AS-09 | definition | NEEDS_REVIEW | F07 Unsupported generation [needs_review] |  | generation | 2 raw claim(s) share almost no words with the source they cite (heuristic) |
| UI-01 | direct_requirement | NEEDS_REVIEW | F14 Answer-structure failure [proven] |  | presentation | structure: repeated_statement |
| UI-04 | numerical_requirement | PASS | — | — | — |  |
| UI-06 | evidence_insufficient | PASS | — | — | — |  |
| BM-S-001 | direct_requirement | UNVERIFIED_WITH_FAILURES | F14 Answer-structure failure [proven] | F18 | presentation | structure: repeated_statement |
| BM-S-002 | direct_requirement | UNVERIFIED | F07 Unsupported generation [proven] |  | generation | raw answer names provisions not in the evidence: ['21 CFR 111.17'] |
| BM-S-005 | cross_reference | UNVERIFIED | — | — | — |  |
| BM-S-012 | scenario | UNVERIFIED | — | — | — |  |
| BM-S-015 | comparison | UNVERIFIED | F14 Answer-structure failure [proven] |  | presentation | structure: repeated_statement |
| BM-S-017 | scenario | UNVERIFIED | — | — | — |  |
| BM-S-019 | cross_reference | UNVERIFIED_WITH_FAILURES | F08 Regulatory qualifier failure [probable] |  | generation | initial validation: qualifier_dropped (warnings) |
| BM-F-002 | comparison | UNVERIFIED_WITH_FAILURES | F16 Model capability limitation [probable] | F09, F14 | generation | with exact evidence only, the model still fails: ['provision_citation_mismatch'] |
| BM-M-031 | exact_provision_lookup | UNVERIFIED | — | — | — |  |
| BM-M-032 | exact_provision_lookup | UNVERIFIED | — | — | — |  |
| BM-PB-001 | evidence_insufficient | UNVERIFIED_NEEDS_REVIEW | F07 Unsupported generation [needs_review] |  | generation | 1 raw claim(s) share almost no words with the source they cite (heuristic) |
| BM-PB-006 | out_of_scope_framework | UNVERIFIED | — | — | — |  |
| BM-PB-007 | out_of_scope_framework | UNVERIFIED | F18 Performance/inference failure [proven] |  | inference | initial validation: truncated |
| BM-NC-001 | false_premise | UNVERIFIED | — | — | — |  |
| BM-NC-002 | false_premise | UNVERIFIED | — | — | — |  |
| BM-NC-003 | false_premise | UNVERIFIED | F08 Regulatory qualifier failure [probable] |  | generation | initial validation: applicability_dropped, qualifier_dropped (warnings) |
