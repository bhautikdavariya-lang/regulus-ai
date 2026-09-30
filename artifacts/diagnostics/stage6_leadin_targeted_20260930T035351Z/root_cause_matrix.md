# Root-cause matrix

| Question | Category | Final status | Primary failure | Secondary | Root module | Evidence (primary) |
|---|---|---|---|---|---|---|
| S5-007 | exact_provision_lookup | PASS | — | — | — |  |
| S5-010 | direct_requirement | FAIL | F15 Completeness failure [proven] | F08, F09 | generation | final answer lacks expected term(s): ['ISO 13485'] |
| S5-011 | direct_requirement | PASS | — | — | — |  |
| S5-024 | multiple_provisions | FAIL | F12 Repair failure [proven] | F14, F18 | repair | repair 'extractive_replacement' ran and final validation still fails: ['enumeration_incomplete'] |
| AS-04 | multiple_provisions | PASS | (contained) F07 Unsupported generation [needs_review] |  | generation | 1 raw claim(s) share almost no words with the source they cite (heuristic) |
