# Answer-shape evaluation: probe4

dataset: answer_shape_v1.jsonl
config answer_shape: adaptive

| id | dimension | shape (detected) | shape ok | coverage | qualifiers missing | out-of-scope | citation ok | valid raw | repeats | led blocks | tokens | allowance | truncated | gen s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AS-01 | broad_synthesis | synthesis/section/non-exh | yes | 5/8 | if_applicable, as_appropriate | none | True | True | 0 | 0 | 321 | 1696 | False | 34 |
| AS-03 | explicit_exhaustive | enumeration/section/exh | yes | 7/9 | none | none | True | False | 0 | 9 | 528 | 1696 | False | 51 |
| AS-05 | comparison | comparison/multiple/non-exh | yes | 4/4 | none | none | False | False | 0 | 0 | 264 | 736 | False | 23 |
| AS-06 | conditional | focused/subsection/non-exh | yes | 3/4 | none | none | True | True | 0 | 1 | 70 | 256 | False | 7 |
