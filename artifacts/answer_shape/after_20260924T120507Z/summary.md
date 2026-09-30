# Answer-shape evaluation: after

dataset: answer_shape_v1.jsonl
config answer_shape: adaptive

| id | dimension | shape (detected) | shape ok | coverage | qualifiers missing | out-of-scope | citation ok | valid raw | repeats | led blocks | tokens | allowance | truncated | gen s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AS-01 | broad_synthesis | synthesis/section/non-exh | yes | 8/8 | none | none | True | True | 0 | 0 | 390 | 1696 | False | 42 |
| AS-02 | focused | focused/subsection/non-exh | yes | 2/3 | none | none | True | True | 0 | 1 | 46 | 256 | False | 5 |
| AS-03 | explicit_exhaustive | enumeration/section/exh | yes | 7/9 | none | none | True | False | 0 | 9 | 528 | 1696 | False | 50 |
| AS-04 | subsection_range | enumeration/multiple/exh | yes | 3/5 | none | none | True | False | 0 | 0 | 455 | 1760 | False | 43 |
| AS-05 | comparison | comparison/multiple/non-exh | yes | 4/4 | none | none | False | False | 0 | 0 | 264 | 736 | False | 23 |
| AS-06 | conditional | focused/subsection/non-exh | yes | 3/4 | none | none | True | True | 0 | 1 | 70 | 256 | False | 7 |
| AS-07 | multi_provision | enumeration/multiple/exh | yes | 4/4 | none | none | True | True | 0 | 0 | 187 | 800 | False | 18 |
| AS-08 | cross_reference | focused/subsection/non-exh | yes | 3/3 | none | none | True | True | 0 | 1 | 43 | 256 | False | 5 |
| AS-09 | direct_fact | direct/part/non-exh | yes | 1/1 | none | none | True | True | 0 | 0 | 395 | 1696 | False | 35 |
