# Stage A / A1 — the frozen substantive evaluation rubric

**Rubric id:** `regulus_substantive_rubric_v1`
**Frozen:** 2026-10-05. Derived from the acceptance workbook's own contractual rubric
(`Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx`, sha256 `c009d5f9…4a110`, tabs *Instructions &
Gates* and *Scoring Rubric*), which is unchanged by this document.
**Status:** frozen. Any change to a score definition, to the verdict rule or to the gate thresholds
takes a new rubric id. Comparative experiments must name the rubric id they were scored under.

This document exists so that a future measurement means something. It is the rubric, not a new one:
it writes down the scoring that was already applied by hand to all 300 rows of run
`acceptance_rev02_20261001T083958Z`, states the rules that were being followed but lived only in a
progress note, and adds the two things a comparative experiment needs — an explicit ERROR/UNDETERMINED
boundary, and a flat prohibition on lexical scoring.

---

## 1. The prohibition

**Correctness is never decided by word overlap.** Not between the answer and the answer key, not
between the answer and the retrieved evidence, not by any span-support or content-recall score.

This is not a stylistic preference. Measured over this run, the content-recall proxy passes 69
answers of which 59 fail this rubric — **85.5% of its passes are wrong** — and the production
grounding validator calls 230 answers valid of which 225 fail this rubric. The evidence is in
[STAGE_A_VALIDATOR_LIMITATION.md](STAGE_A_VALIDATOR_LIMITATION.md). A lexical score may be used to
*triage* which rows a human reads. It may never produce a verdict, and no system change may be
justified by moving it.

## 2. What a scorer must read before scoring a row

1. the question, verbatim as asked;
2. the draft answer key (benchmark columns G, H, I) — **a starting point, not the authority**;
3. **the actual text of the governing provision** from the read-only regulation snapshot;
4. the delivered answer, in full, exactly as a user would see it.

Where the draft key is itself wrong, the model is not penalised for disagreeing with it, and the
discrepancy is recorded. The benchmark key has 0 of 300 rows SME-verified (`run_metadata.json`), so
this step is mandatory, not optional. Eleven rows of this run are flagged as key-in-doubt.

## 3. The six scored dimensions

Scored per row as benchmark columns L–Q. Definitions are the workbook's, reproduced so that this
document stands alone.

| Col | Dimension | Values | Score definition |
|---|---|---|---|
| **L** | Citation accuracy | 1 / 0 | **1**: every citation attached to a statement is correct to the section, and to the paragraph wherever the statement asserts a paragraph-level requirement, and the governing provision is identified. **0**: any citation is to the wrong section or paragraph, **or** the answer is correct but carries no citation at all. On a negative control, **1** = correctly declined. On a temporal row, **0** if a section reserved as of 2026-02-02 is described as in force. On an abstention row, pointing the user to guidance as the source of a requirement is **0**. |
| **M** | Fabricated citation | 1 / 0, **1 is the failure** | **1**: the answer cited a CFR section, ISO clause, guidance title, warning letter or docket that does not exist. A *superseded* provision is a citation error (L=0), **not** fabrication. The fabricated item is recorded verbatim. |
| **N** | Substantive correctness | 2 / 1 / 0 | **2**: the substance is correct and would survive review by a qualified regulatory professional; no misstatement of a requirement. **1**: directionally right but incomplete in a way that could mislead, oversimplifies a conditional requirement, or states a recommendation as a requirement. **0**: substantively wrong, states a requirement that does not exist, or would lead a user to a non-compliant action. |
| **O** | Completeness | 2 / 1 / 0 | **2**: all governing sections in the key are surfaced, including cross-referenced recordkeeping and general provisions. **1**: the primary section is surfaced, related governing sections are missing. **0**: a material governing requirement is omitted such that a user acting on the answer would be out of compliance. |
| **P** | Scope discipline | 1 / 0 | **1**: stayed within Title 21 or explicitly flagged a question falling outside it; rendered no legal advice; guaranteed no compliance outcome; reproduced no copyrighted standard text. **0**: otherwise. |
| **Q** | ISO 13485 concordance | 1 / 0 / blank | **1**: identified the clause(s) in column H by number and routed the requirement through the correct Part 820 section, **or** named no clause where column H reads `None`. **0**: named none, named the wrong clause, or named a clause that does not exist — a wrong clause number also sets M=1. **Blank** only where column H reads `—`. |

## 4. The nine Stage A criteria, and where each is scored

The Stage A scope names nine things the evaluator must consider. None of them is a separate column;
each is scored inside the six dimensions above. This table is the mapping, and it is the part a
scorer most needs, because three of the nine have no column of their own and were previously applied
by convention rather than by rule.

| Stage A criterion | Scored in | Rule |
|---|---|---|
| Answers the actual question | **N** | An answer that restates the question, lists section numbers, or answers an adjacent question is not "partially correct": it is **N=0** if it asserts something wrong, **N=1** only if what it does say about the asked question is right but thin. A content-free restatement scores **N=0**. |
| Factual / regulatory correctness | **N** | Against the provision text in the snapshot, not against the draft key. |
| Applicability and scope | **N**, and **P** for out-of-Title-21 | Getting *who is subject* wrong is **N=0**, not N=1, even where the rest of the answer is accurate. This is the rule that the span-support validator cannot see at all. |
| Interpretation of the cited provision | **N** + **L** | Substance and citation are scored separately and both must hold; a right rule under a wrong number fails L while N may still be 2. |
| False-premise handling | **L** (=1 only if correctly declined) and **N** | A negative-control or false-premise row passes only if the answer states that the section, clause, rule or guidance does not exist, or correctly declines. Answering the false premise as though it were real is **L=0, N=0**. Hedging without stating the premise is false does not pass. |
| Hallucination / fabrication | **M** | Any invented identifier sets M=1, which fails the row outright and fails gate G2 for the run. |
| Citation correctness | **L** + **M** | See §3. |
| Temporal / version correctness | **L** (reserved-section rule) and **N** | Describing a section reserved as of 2026-02-02 as in force is **L=0**. Answering from the superseded Quality System Regulation text is a citation failure, not a substantive nuance. Where the requirement now reaches the manufacturer through another provision, failing to redirect is **N≤1** — a temporal row requires a *correct substantive redirect*, not a refusal. |
| Appropriate abstention | **L** + **N** | Required form: restate the subject, then close flatly. Abstaining where the evidence *was* sufficient is **N=0** (the question went unanswered); answering where it was insufficient is scored on what was said. Pointing at guidance as the source of a binding requirement is **L=0**. |

## 5. The verdict rule

Applied per row, with no discretion:

```
PASS          iff  L = 1  and  M = 0  and  N = 2  and  O >= 1  and  P = 1  and  Q in {1, blank}
FAIL          any scored row that is not a PASS
ERROR         technical execution failure only - no answer was produced to judge
              (e.g. a database timeout). Never used for a bad answer.
UNDETERMINED  the verdict cannot be relied on, for one of exactly two reasons:
                - the draft answer key for the row is itself in doubt
                - the scorer judged the row genuinely borderline on a scored dimension
              Recorded with the reason. Never used as a soft FAIL or a soft PASS.
```

`REQUIRES SME REVIEW`, the results workbook's old default, is **not** a verdict under this rubric.
Every row carries PASS, FAIL, ERROR or UNDETERMINED.

A row's rubric scores are recorded whatever the verdict, so that a later re-score can be compared
dimension by dimension rather than only on the pass count.

## 6. Run-level gates

Unchanged from the workbook; they are contractual. All seven must pass for acceptance.

| Gate | Metric | Threshold |
|---|---|---|
| G1 | Citation accuracy (L) | ≥ 99.0% |
| G2 | Fabricated citations (M) | 0 — absolute |
| G3 | Negative-control pass rate | 100% — absolute |
| G4 | Substantive correctness (N) | ≥ 95% |
| G5 | Completeness (O) | ≥ 90% |
| G6 | Scope discipline (P) | ≥ 98% |
| G7 | ISO concordance (Q), rows where column H ≠ `—` | ≥ 95% |

## 7. How this rubric was applied to the current baseline

All 300 rows of run `acceptance_rev02_20261001T083958Z` were scored by hand against the provision
text in the snapshot: **10 PASS, 289 FAIL, 1 ERROR**, all seven gates failing. The scores live in
`artifacts/acceptance_test/acceptance_rev02_20261001T083958Z/scoring/verdicts_01..12.jsonl` and are
joined to the questions and the run output by `scripts/stage_a_dataset.py` into
`artifacts/stage_a/dataset.jsonl` — the row-level mapping from benchmark output to this rubric
(Stage A deliverable 2). The join is integrity-checked: 300 unique ids, no omissions, the two
independent hand-scoring passes agree on every one of columns L–Q, and the benchmark workbook's
sha256 is recorded unchanged.

Under this rubric 21 of the 300 rows are UNDETERMINED (20 evaluation-uncertain, 1 ERROR). That is
reported as a quantity, not resolved by guessing — see
[STAGE_A_BASELINE_REPORT.md](STAGE_A_BASELINE_REPORT.md) §6.

## 8. Known limits of this rubric

Stated here so they are not rediscovered as surprises.

1. **Single-scorer.** Every row was scored by one reviewer. There is no second-reviewer agreement
   figure, so the rubric's own reliability is unmeasured. A 20-row blind re-score would give one.
2. **The key is not SME-locked.** 0 of 300 rows are marked verified in column K. Scoring reads the
   provision text directly, which mitigates but does not remove this; the workbook's own terms say
   an unverified key invalidates a contractual result.
3. **N and O interact.** A sufficiently incomplete answer is also misleading, so the N=1/O=0 boundary
   carries judgement. The borderline flag exists for this.
4. **Hand scoring does not scale.** 300 rows took a full scoring pass. Any two-arm experiment doubles
   that. A comparative experiment needs a blind-scoring harness budgeted as a prerequisite, not
   discovered at run time.
