# Stage A — baseline report: the true current failure distribution

Stage A deliverable 6. Baseline run `acceptance_rev02_20261001T083958Z`: Qwen3-0.6B
(`c1899de2…`), CPU float32, greedy decoding, LexicalRetriever top_k 8 with semantic fallback,
all 300 questions of benchmark Rev 02 (sha256 `c009d5f9…4a110`, recorded unchanged). Scored under
`regulus_substantive_rubric_v1`.

Reproduce the whole chain:

```
python3 scripts/stage_a_dataset.py           # join benchmark + run + verdicts -> dataset.jsonl
python3 scripts/stage_a_proxy_check.py       # the mechanical validators vs the rubric
python3 scripts/stage_a_output_integrity.py  # D2: raw output vs delivered answer
python3 scripts/stage_a_citations.py         # A3: citation / grounding layers
python3 scripts/stage_a_attribute.py         # the attribution below
```

Production was not modified, the model was not changed, no prompt was changed, retrieval was not
redesigned, H4 was not implemented and nothing was re-run. Every figure comes from analysis of
outputs that already existed.

---

## 1. The headline

**10 PASS / 289 FAIL / 1 ERROR — a 3.3% pass rate, all seven acceptance gates failing.** That number
is unchanged by Stage A, and it is now trustworthy: it comes from reading all 300 answers against
the regulation text, not from any overlap score.

What Stage A changes is the *attribution*. Of the 290 rows that are not a pass:

| Category | Rows | Share | What it means |
|---|---|---|---|
| **MODEL_ANSWER** | 141 | **48.6%** | the model had the governing provision, or needed none, and still answered wrongly |
| **EVIDENCE_SUPPLY** | 126 | **43.4%** | the governing provision never reached the model |
| **UNDETERMINED** | 21 | **7.2%** | the verdict itself cannot be relied on |
| **CITATION_GROUNDING** | 2 | **0.7%** | substance right, failed on grounding alone |
| **OUTPUT_PROCESSING** | **0** | **0.0%** | post-processing turned a passing answer into a failing one |

The decision procedure is ordered, first-match-wins and documented in
`scripts/stage_a_attribute.py`; per-row results with the deciding fact are in
`artifacts/stage_a/attribution_rows.jsonl`.

## 2. Answering the question Stage A was set

> What percentage of failures are genuinely model-answer failures, what percentage are
> output-processing failures, what percentage are citation/grounding failures, and what percentage
> cannot yet be determined?

- **Model-answer failures: 48.6%** (141 rows). 99 rows had the governing section in the evidence
  package and the answer was still wrong, partial or unresponsive; 42 rows are negative controls,
  scope boundaries and traps that required a refusal or a judgement rather than a lookup, and got
  neither.
- **Output-processing failures: 0.0%** (0 rows). Not "small" — zero, within the bound of what the
  data can show. Post-processing changes 164 of 300 answers and removes 574 sentences, and on no row
  did it convert an answer that would have passed into one that failed. Five rows have a named
  processing defect that degraded the answer without changing the verdict.
- **Citation/grounding failures: 0.7%** (2 rows), upper bound **2.8%** (8 rows) if six borderline
  rows resolve as citation failures. Citations are wrong constantly — 85.1% of cited answers carry a
  wrong citation — but on all but 2–8 rows the substance was wrong too, so fixing the citation would
  not produce a passing answer.
- **Cannot yet be determined: 7.2%** (21 rows): 11 rows where the draft answer key is itself in
  doubt, 9 rows the scorer judged genuinely borderline, 1 technical execution error.

One structural answer the four categories did not anticipate: **43.4% of failures are an
evidence-supply problem**, which is neither a model-answer failure nor an output-processing failure
nor a citation failure. It is reported as its own category rather than folded into "model
capability", because doing otherwise would contaminate exactly the comparison the next phase wants
to make.

## 3. The judgement call, stated plainly

EVIDENCE_SUPPLY is computed, not labelled: a row lands there when it names a governing section and
no retrieved evidence item carries that section. 71 rows retrieved nothing from the key at all. The
other 51 are **part-level** plans, where the retriever supplied the part's passages but not the
governing section as a source — `ECFR_EXACT_PART` filters `ordinal = 0`
(`src/regulus/retrieval/sql.py:64`), so on those rows the keyed section reaches the prompt with at
most one paragraph against a mean of 14.1 that it has (measured in phase D1).

Counting those 51 rows the other way — the right part was retrieved, so call the evidence sufficient
— gives:

| | As reported | If part-level counts as supplied |
|---|---|---|
| MODEL_ANSWER | 141 (48.6%) | **192 (66.2%)** |
| EVIDENCE_SUPPLY | 126 (43.4%) | **75 (25.9%)** |

**Either way the model-answer share is the largest single category**, so the headline conclusion does
not depend on the call. It is flagged because the 51 rows must be resolved before a model-size
comparison is scored, not after.

The same 51 rows are the whole of this attribution's disagreement with the free-text cause the
scorer recorded per row: 30 of them were labelled "model reasoning (right evidence, wrong answer)",
on the reading that retrieving the part counts as having the evidence. Everywhere else the two agree.

## 4. By question type

| Type | n | Model | Evidence supply | Undetermined | Citation | Pass |
|---|---|---|---|---|---|---|
| Direct Lookup | 188 | 80 | 85 | 16 | 2 | 5 |
| Distinction | 23 | 13 | 9 | 1 | — | 0 |
| Negative Control | 22 | 14 | 4 | — | — | 4 |
| Cross-Reference | 20 | 10 | 9 | 1 | — | 0 |
| Application | 20 | 9 | 10 | 1 | — | 0 |
| Scope/Boundary | 15 | 12 | 1 | 1 | — | 1 |
| Temporal/Version | 11 | 2 | 8 | 1 | — | 0 |
| Abstention | 1 | 1 | — | — | — | 0 |

Reading across: the reasoning categories (Cross-Reference, Application, Distinction) score **0 passes
out of 63** and split roughly evenly between the two causes, so neither cause alone explains them.
The 22 negative controls are overwhelmingly model-answer failures — 14 of 18 non-passing rows needed
no retrieval at all, and the system answered the false premise instead of rejecting it.

## 5. What the three separated questions each answered

Stage A required that these not be collapsed. They were not, and they give three different answers.

**Is the answer substantively correct?** Almost never. 18 of 299 scored answers reach N=2; 10 clear
the full PASS rule. Gate G4 (substantive) stands at 26.3% against a 95% threshold.

**Is the answer correctly grounded?** Almost never, and independently of the above. 87.7% of
delivered answers carry a citation, 35.1% of those cite the governing provision — 28.4% once the
matches that merely echo a section named in the question are removed — and 14.9% score L=1.
Gate G1 at 11.7% against 99%. The dominant error is the right part and the wrong section (63 rows),
not fabrication (2 rows). Crucially, **70 answers cite the governing section and are still
substantively wrong**, which is why one score could not have carried both questions. Detail:
[STAGE_A_CITATION_GROUNDING.md](STAGE_A_CITATION_GROUNDING.md).

**Did post-processing preserve the model's useful output?** Mostly yes, and where it did not, the
removed text was usually the model's own invention. 164 of 300 answers are altered; of the 46
withheld drafts, the 8 that could have contained a passing answer were read in full and none did;
processing *supplies* the governing section on 25 rows and loses it on 5. Five named defects, verdict-changing on zero rows. Detail:
[STAGE_A_D2_OUTPUT_INTEGRITY.md](STAGE_A_D2_OUTPUT_INTEGRITY.md).

## 6. What remains unknown, and why it is not guessed

| Unknown | Rows | What would resolve it |
|---|---|---|
| Draft answer key in doubt | 11 | SME verification of those rows against eCFR; the benchmark has 0 of 300 rows key-verified |
| Borderline rubric judgement | 9 | second-reviewer adjudication. 6 of the 9 scored N=2 and are unresolved only on the citation verdict, so they are the difference between a 0.7% and a 2.8% citation-failure share |
| Execution error | 1 | re-run S-025 (database statement timeout) |
| Would the model answer correctly if given the rule? | 126 | unanswerable from this run on the evidence-supply rows: the model was never given the provision. A capability comparison must be scored on the 99+42 rows where it was, or the arms are confounded |
| Rubric's own reliability | all 300 | single-scorer; no inter-rater agreement figure exists |

No category was inferred to fill a gap. The attribution leaves 7.2% undetermined rather than
assigning it.

## 7. Does Stage A's decision rule hold?

> Stage A is complete only when we have a reliable baseline that distinguishes model capability
> vs system/output problem vs citation/grounding problem vs evaluation uncertainty.

Yes, with one qualification.

- **Model capability vs system/output: distinguished.** Output processing is bounded at zero
  verdict-changing failures by a complete review of the 24 rows where it was possible. The
  system-side failure that does exist is evidence supply, measured separately at 126 rows.
- **Citation/grounding: distinguished, and bounded at 2–8 rows** as a *sole* cause, while measured
  separately as a pervasive defect (85.1% of cited answers).
- **Evaluation uncertainty: quantified at 21 rows**, with the resolution path for each.
- **The qualification:** within model capability, the 99 "had the rule and got it wrong" rows and the
  51 part-level rows are not yet separated by measurement. That separation is a prerequisite for the
  next comparative experiment, not for closing Stage A.

The evaluation problem Stage A was called to fix is fixed: a rubric exists, it is frozen, it is
applied to all 300 rows, and the metric that could mark a wrong answer correct is now measured
(85.5% of its passes are wrong) and ruled out of use —
[STAGE_A_VALIDATOR_LIMITATION.md](STAGE_A_VALIDATOR_LIMITATION.md).

## 8. What this means for what comes next

Stated as findings, not as a plan; the sequencing decision is the user's.

1. **Do not spend Stage B on post-processing.** It cannot buy pass-rate; it is worth 5 rows of
   quality and it is currently a net safety asset.
2. **Do not spend Stage B on citation selection expecting pass-rate.** It is worth 2–8 rows. It is
   nonetheless mandatory for acceptance, since G1 and G2 are contractual gates.
3. **The two live candidates are evidence supply (126 rows) and model capability (141 rows).** Both
   are large; neither is refuted by this baseline. Phase D1 already refuted ordering, position,
   breadth and completeness as causes *on rows where the section was supplied* — which is a
   different population from these 126 rows, where the section was never supplied at all. The
   `ordinal = 0` filter is a specific, measured, unrefuted mechanism.
4. **Any model-size comparison needs its population frozen first**, to the rows where the governing
   provision actually reached the prompt (99 supplied + 42 no-provision-needed). Scored on the full
   300 it would measure retrieval, not capability. This is the population-freeze prerequisite already
   recorded against CP-01, now with a defensible row list.
5. **A blind-scoring harness is a prerequisite, not an optimisation.** The rubric's only
   implementation is a human reading answers; a two-arm experiment on 141 rows is 282 answers to
   score by hand.

## 9. Artefacts

| Path | Contents |
|---|---|
| `artifacts/stage_a/dataset.jsonl` | deliverable 2 — 300 rows joining benchmark question, run output and rubric verdict; integrity-checked |
| `artifacts/stage_a/dataset_manifest.json` | input sha256s, including the benchmark workbook recorded unchanged |
| `artifacts/stage_a/proxy_check.json` + `proxy_rows.jsonl` | deliverable 3 — the mechanical validators scored against the rubric |
| `artifacts/stage_a/output_integrity.json` + `output_integrity_rows.jsonl` | deliverable 4 — raw vs delivered, per stage |
| `artifacts/stage_a/d2_candidate_review.jsonl` | the 24-row hand review behind the zero |
| `artifacts/stage_a/citation_grounding.json` + `citation_rows.jsonl` | deliverable 5 — the five citation layers |
| `artifacts/stage_a/attribution.json` + `attribution_rows.jsonl` | deliverable 6 — this report's figures |
| `docs/STAGE_A_RUBRIC.md` | deliverable 1 — the frozen rubric |
