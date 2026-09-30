# Answer-shape evaluation: streaming_stage_check

dataset: answer_shape_v1.jsonl
config answer_shape: adaptive

| id | dimension | shape (detected) | shape ok | coverage | qualifiers missing | out-of-scope | citation ok | valid raw | repeats | led blocks | tokens | allowance | truncated | gen s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AS-01 | broad_synthesis | synthesis/section/non-exh | yes | 8/8 | none | none | True | True | 0 | 0 | 390 | 1696 | False | 41 |
| AS-03 | explicit_exhaustive | enumeration/section/exh | yes | 7/9 | none | none | True | False | 0 | 9 | 528 | 1696 | False | 50 |
| AS-05 | comparison | comparison/multiple/non-exh | yes | 4/4 | none | none | False | False | 0 | 0 | 264 | 736 | False | 22 |
