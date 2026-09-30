# Answer-shape evaluation: probe3

dataset: answer_shape_v1.jsonl
config answer_shape: adaptive

| id | dimension | shape (detected) | shape ok | coverage | qualifiers missing | out-of-scope | citation ok | valid raw | repeats | led blocks | tokens | allowance | truncated | gen s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AS-01 | broad_synthesis | synthesis/section/non-exh | yes | 5/8 | if_applicable, as_appropriate | none | True | True | 0 | 5 | 471 | 1696 | False | 49 |
| AS-03 | explicit_exhaustive | enumeration/section/exh | yes | 0/9 | if_applicable, as_appropriate | none | True | True | 0 | 1 | 191 | 1696 | False | 19 |
| AS-05 | comparison | comparison/multiple/non-exh | yes | 4/4 | none | none | False | False | 3 | 0 | 393 | 736 | False | 34 |
| AS-06 | conditional | focused/subsection/non-exh | yes | 1/4 | none | none | True | True | 0 | 0 | 27 | 256 | False | 4 |
