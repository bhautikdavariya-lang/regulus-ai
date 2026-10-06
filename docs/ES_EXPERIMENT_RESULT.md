# Evidence-supply experiment — result and decision

Deliverables 6–10. Control vs ES-1 on the frozen 36-row diagnostic subset, scored under
`regulus_substantive_rubric_v1`. Phase 1 taxonomy and the intervention design are in
[ES_PHASE1_TAXONOMY.md](ES_PHASE1_TAXONOMY.md).

```
.venv/bin/python scripts/es_experiment.py --arm control
.venv/bin/python scripts/es_experiment.py --arm es1      --pin-from artifacts/stage_b/run_control.jsonl
.venv/bin/python scripts/es_experiment.py --arm es1_deep --pin-from artifacts/stage_b/run_control.jsonl
.venv/bin/python scripts/es_compare.py --with-verdicts
```

Production was not modified. Model, prompt, decoding, post-processing, benchmark and rubric are
unchanged; the generation allowance was pinned to the control arm's own per-question value. Control
reproduces the Stage A baseline byte-for-byte, so control verdicts are the frozen Stage A verdicts.

---

## 1. Decision: **REFINE**

ES-1's E1 edit works exactly as designed and should be kept, but **not shipped as it stands**. It
converts an evidence-supply failure into a correct answer on 1 of the 14 rows where it put the
governing provision in front of the model, and it creates two regressions that must be fixed first.
The depth arm is pure cost and should be dropped.

The experiment's own criterion — *"the intervention succeeds only if it produces a meaningful
increase in substantive correctness"* — is **not met**. 0 → 1 PASS out of 36 is not a meaningful
increase.

But the experiment did what it was for: it moved 14 rows out of "we cannot tell" and into a
measured answer, and it found the next binding constraint, which is not retrieval.

## 2. The headline numbers

| | control | es1 | es1_deep |
|---|---|---|---|
| **Governing provision supplied** | **0 / 36** | **14 / 36** | **14 / 36** |
| **Substantive PASS** | **0** | **1** | **1** |
| N=2 (substantively correct) | 0 | 1 | 1 |
| N distribution (0 / 1 / 2) | 28 / 8 / 0 | 22 / 13 / 1 | 22 / 13 / 1 |
| Rows whose N improved / worsened | — | **6 / 0** | 6 / 0 |
| Rows whose L improved / worsened | — | 1 / **3** | 1 / 3 |
| Cites the governing section | 2 | 9 | 9 |
| Answers withheld | 10 | **12** | 12 |
| Mean evidence tokens | 681.7 | 694.7 (+1.9%) | 694.8 |
| Mean prompt tokens | 1766.6 | **1733.9 (−1.9%)** | 1735.8 |
| Mean evidence blocks | 8.3 | 8.1 | 8.2 |
| Mean latency | 33.4 s | 37.9 s (+13%) | **41.8 s (+25%)** |
| Mean generated tokens | 252.0 | 310.4 (+23%) | 310.4 |
| Hit the pinned token ceiling | 0 | 1 | 1 |
| Errors | 0 | 0 | 0 |

By stratum, which says which mechanism the fix actually reaches:

| Stratum | n | supplied: control → es1 → es1_deep |
|---|---|---|
| A1a part listing ASCII-truncated | 12 | **0 → 12 → 12** |
| A1b trigram cut-off | 6 | 0 → 2 → 2 |
| A2 reachable at greater depth | 12 | 0 → 0 → 0 |
| B unreachable at any depth | 4 | 0 → 0 → 0 |
| C corpus gap / reserved | 2 | 0 → 0 → 0 |

## 3. What each edit did

**E1 — relevance-ordered part listing: works, 12 of 12.** Every whole-part row now receives the
sections the question is about instead of the ASCII-first ones, and it does so while the prompt gets
*smaller* (−1.9% tokens, −0.2 blocks). This is the "minimum sufficient evidence" requirement met
rather than asserted. Keep it.

**E2 — trigram cut-off relaxation: 2 of 6, and the shortfall is explained.** E2 only lifts the
`min_trigram_similarity` filter. On the other 4 rows the governing section had already passed
`is_useful` because it was found by full text, and it was cut by the **budget** instead. A-004 is the
clean case: 558.6 retrieved at rank 6, byte-identical evidence in both arms. E2 addresses the wrong
half of its own stratum.

**Depth (`top_k` 8 → 48): no effect at all.** `es1_deep` produced a **byte-identical answer to es1
on all 36 rows**, with identical evidence on 35 of 36, for +3.9 s per row. The depth probe had shown
7 of the 12 A2 subset rows reachable at `top_k ≤ 48`, and they were reached — the candidates entered
the pool and then none of them won a budget slot, because nothing in ES-1 reserves one for optional
evidence. **Depth without admission is wasted work. Drop this arm.**

## 4. The result that matters most: supply is not the constraint

Of the **14 rows that gained the governing provision**, exactly **1 produced a substantively correct
answer**.

- `evidence_now_present_and_correct`: **D-004**
- `evidence_now_present_but_still_wrong`: **B-003, C-003, D-001, D-003, D-006, D-007, D-009, D-022,
  D-024, D-027, F-001, F-002, K-005**

Per the experiment's own rule, those 13 rows have **transitioned from an evidence problem to a model
or output problem** and must be reclassified for the next stage. They should not be attacked with
more retrieval work.

The one success, **D-004**, is clean: 211.34 supplied at rank 1, returned verbatim and correctly
cited, both key answer elements present. It is flagged borderline because the answer then appends
five unresponsive paragraphs; each is accurately quoted and correctly cited to its own section
(markers checked individually: [6] 211.110(a), [7] 211.111, [8] 211.113(a), [9] 211.115(a)), so no
requirement is misstated and the frozen PASS rule is satisfied.

Six rows improved partially (N 0 → 1): A-002, D-004, D-006, D-022, D-024, D-027. No row's substance
got worse. That is real but small movement, and it is the honest size of the effect.

## 5. Regressions and safety

**R1 — withholding is now the binding constraint, and it destroys correct content.** Four
supply-gained rows delivered nothing (D-001, D-003, D-007, D-009) against two in control. On three
of them the raw model output contained the right answer:

- **D-003**: raw output answered 211.25 correctly — education, training and experience to perform
  assigned functions; CGMP training by qualified individuals on a continuing basis and with
  sufficient frequency. Suppressed in full.
- **D-009**: raw output stated 211.84(a) correctly — components withheld from use until the lot is
  sampled, tested or examined and released by the quality control unit. Suppressed in full.
- **D-001**: raw output quoted 210.2(a)'s supplement-not-supersede rule verbatim, which is the
  question. Suppressed in full, because the draft led with an unrelated 211.68(a) quotation.

Three of the four lost the L=1 credit they held in control, where a wrong-but-cited answer scored
L=1 and nothing-delivered scores L=0. **This qualifies Stage A's finding that output processing
causes 0 failures.** That was true given the baseline's poor evidence. Improve the evidence and the
all-or-nothing withholding defect (Stage A's D2-3) starts eating correct answers.

**R2 — one safety regression, F-002.** Control withheld and delivered nothing. es1 delivers
"a 'qualified facility' under Part 117 is a facility that has been approved by the FDA for food
safety" — fabricated; 117.3 defines it by average annual monetary value of food sold. Better
evidence produced a more dangerous answer. This is the same pattern H4 showed and is the reason the
withholding gate must not simply be loosened.

**R3 — generation grew.** Mean generated tokens +23%, one row (D-007) ran to the full pinned
allowance of 1,696 tokens without emitting end-of-turn. Richer, more on-point evidence invites longer
source-dump answers, which is also what triggers the withholding in R1.

**What did not regress:** no fabricated citations in either arm (M=0 throughout), no substance
worsened on any row, scope discipline held at P=1 everywhere, no errors, no truncation notices, and
context did not grow — prompt tokens fell. The B and C strata correctly showed no improvement, which
is the negative control on the measurement holding.

## 6. Recommendation

1. **Keep E1, do not ship it yet.** It is the only edit with a clean mechanism and a 12/12 hit rate,
   and it is free in context terms. It must not ship while R1 stands, because on four rows it
   converts a delivered answer into no answer at all.
2. **Fix withholding before any further retrieval work.** Partial delivery — show the statements that
   validate, suppress the rest, label what was suppressed — is now the highest-value change in the
   system, and this experiment produced three concrete cases where it would deliver a correct answer
   the user never saw. Note the countervailing evidence from H4 and from F-002 here: loosening the
   gate without discrimination ships wrong answers. Any change must be measured on substantive
   correctness **and** on the wrong-answer-delivery rate.
3. **Drop the depth arm.** Byte-identical output for +25% latency.
4. **Replace E2 with optional-evidence ordering.** The 4 rows it missed were cut by budget, not by
   the filter. Reserving one prompt slot for the best question-matching CFR section would address
   both those rows and, on the Phase 1 evidence, the A2 stratum that depth alone could not reach.
5. **Reclassify the 13 rows** listed in §4 from evidence-supply to model/output for the next stage.
   Do not keep modifying retrieval to compensate for them.

## 7. Scope and limits

- **36 rows, one stratified subset.** The A1a result (12/12) is unambiguous; the single PASS is one
  row and carries no statistical weight. Nothing here supports a claim about the full 126.
- **Single scorer**, no second-reviewer agreement figure, as in Stage A.
- **The validator's own code stream was not captured** — `record()` reads it from the wrong metadata
  nesting, so `validation_*`, `repair` and `stop_reason` are null in all three arms. They are null
  identically, so the arms stay comparable; the safety analysis uses signals the runs captured in
  full (withholding from the fallback builder's wording, non-termination from hitting the pinned
  allowance, fabrication from rubric column M). Fix before the next run, and re-run all arms if so.
- **Latency is machine-local** on an 8 GB CPU host. Two arms must never run concurrently: two model
  instances swap the machine and inflate per-row latency roughly tenfold (measured: 213 s vs 22 s).
  The first es1 attempt was contaminated this way and was discarded and re-run.
