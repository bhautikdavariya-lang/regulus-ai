# Root-cause matrix

| Question | Category | Final status | Primary failure | Secondary | Root module | Evidence (primary) |
|---|---|---|---|---|---|---|
| S5-003 | exact_provision_lookup | PASS | — | — | — |  |
| S5-007 | exact_provision_lookup | FAIL | F09 Citation attribution failure [proven] |  | citations | initial validation: synthesis_citation_gap |
| S5-010 | direct_requirement | FAIL | F15 Completeness failure [proven] | F08, F09 | generation | final answer lacks expected term(s): ['ISO 13485'] |
| S5-011 | direct_requirement | PASS | — | — | — |  |
| S5-022 | comparison | PASS | — | — | — |  |
| S5-023 | multiple_provisions | PASS | — | — | — |  |
| S5-024 | multiple_provisions | FAIL | F12 Repair failure [proven] | F14, F18 | repair | repair 'extractive_replacement' ran and final validation still fails: ['enumeration_incomplete'] |
| S5-032 | multiple_provisions | PASS | — | — | — |  |
| S5-033 | multiple_provisions | PASS | — | — | — |  |
| S5-101 | multiple_provisions | FAIL | F16 Model capability limitation [probable] | F09, F14 | generation | with exact evidence only, the model still fails: ['synthesis_citation_gap'] |
| AS-04 | multiple_provisions | PASS | (contained) F07 Unsupported generation [needs_review] |  | generation | 1 raw claim(s) share almost no words with the source they cite (heuristic) |
| AS-05 | comparison | PASS | (contained) F09 Citation attribution failure [proven] |  | citations | initial validation: citation_mismatch, provision_citation_mismatch, synthesis_citation_gap |
