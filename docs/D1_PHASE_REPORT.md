# Phase D1 — complete report

**Regulus AI · evidence-selection defect investigation · 2026-10-02 → 2026-10-05**

Model `Qwen/Qwen3-0.6B` rev `c1899de2`, float32, CPU, no adapter. Read-only PostgreSQL snapshot.
Benchmark sha256 `c009d5f9c649822097b02a6c6aba415715fb0929914ef452acb03c8c3ac4a110`, **unchanged
throughout**. Production code **never modified**: `git diff f570776~1 HEAD --stat -- src/ configs/`
returns nothing at every commit in this phase.

---

## 1. Verdict

> **D1 is a real defect and it is not the cause of the failure rate.**

The investigation confirmed the defect mechanically, then ran five arms to see whether fixing it
recovers answer quality. It does not. Ordering, availability, position and breadth were each tested
directly and each eliminated. The one hypothesis still standing — **section completeness** — was
isolated, specified and built, but could not be measured within this machine's compute budget.

Phase D1 should close. The dominant uncertainty is no longer retrieval; it is **model capability**,
which cannot be settled on 8 GB of RAM.

---

## 2. What D1 is

When a question names a **part** rather than a section, the planner emits one requirement for the
whole part. `regulus.retrieval.evidence.relate()` then returns `REL_EXACT` for *every* row of that
part — its docstring says so: *"Part-level request: every row of the part is exact."* Consequences:

1. Every retrieved section is labelled identically in the prompt: `Tier: EXACT (authoritative text of r1)`.
2. `order_evidence` has no relevance signal left, so its tie-break falls to `e.key`, an **ASCII
   citation string**. `ranking.exact_score` is a constant 100.0 for part rows, so scores cannot break
   the tie either.
3. The surviving set is cut by a hard ceiling.

**Blast radius.** The planner over all 300 benchmark questions: **112 part-level**, 168 with no
provision named, **19 section-level**, 1 mixed. So for 112 questions the system was never asked
"can the model reason over the right provision?" but "can it pick the right provision out of ~20
identically-labelled ones in alphabetical order?"

---

## 3. Method

A frozen 36-question stratified probe (`probe_set.json`, seed 20261002), of which **20 are
part-level** and **18 of those have a keyed section**. The 16 non-part-level rows act as controls.

**Held identical across every arm:** questions, model identity, decoding (greedy, thinking off),
prompt wording and system prompt sha256 `d39dc7bb…`, retrieval queries, tiers, coverage,
answerability, soft budgets, post-processing, citation processing, scoring functions — and from Arm 2
onward the **per-question generation budget, pinned to Arm 0's exact integer**.

**Scoring** is a mechanical proxy, applied identically everywhere: key-element content recall ≥ 0.5
for substantive rows, a refusal-phrase match for trap rows. It is *not* the acceptance rubric.

**The benchmark key is never read by any patch.** `keyed_sections` is used only after an answer
exists, to measure presence, rank, token share and paragraph coverage.

**Freeze verified, not asserted.** Three independent checks:

| Check | Result |
|---|---|
| `identity` block equal across arms | ✅ all arms |
| 16 non-part-level control rows, Arm 0 vs Arm 1 | ✅ **bit-identical** — same prompt sha256, raw output, final answer |
| 9 rows where the Arm 2 ceiling changed nothing, vs Arm 1 | ✅ **9 of 9 bit-identical** |
| 7 rows where the Arm 3 ceiling changed nothing, vs Arm 0 | ✅ **7 of 7 bit-identical** |
| Budget pin, Arm 2 and Arm 3 | ✅ **29/29 rows** used Arm 0's exact budget |

---

## 4. The five arms

| Arm | Intervention | Rows | Status |
|---|---|---:|---|
| **0** | production baseline | 36 | complete |
| **1** | K1 — numeric CFR ordering of EXACT ties | 36 | complete |
| **2** | K1 + whole-Part ceiling 84 / 24,000 chars | 20 | complete, budget-pinned |
| **3** | ceiling only, production ordering | 9 | complete, budget-pinned |
| **4** | full sections (`ordinal = 0` lifted) at the same char budget | 0 | **built, dry-run validated, not measured** |

All interventions are in-process monkeypatches in `scripts/d1_experiment.py`. Nothing was committed
as a production default.

**A methodological correction made mid-phase.** The first Arm 2 attempt was **confounded and
discarded**: the production budget policy is adaptive (`evidence_multiple` 1.4,
`evidence_cap_fraction` 0.75, `hard_max_tokens` 2048), so a larger evidence package silently bought a
larger generation allowance — the nine large rows would have risen to 2,048 against Arm 0's
1,171–1,696. A `PinnedBudget` proxy was added to force Arm 0's exact per-question budget, and Arm 2
was re-run from scratch. The pin demonstrably bit: on C-004 the adaptive policy requested 1,696 and
was held to 1,536.

---

## 5. Results

### Evidence composition (20 part-level rows; keyed subset 18)

| metric | Arm 0 | Arm 1 | Arm 2 | Arm 3 † |
|---|---:|---:|---:|---:|
| keyed section present | **18/18** | **12/18** | **18/18** | 18/18 |
| keyed section at rank 1 | 5 | 3 | 3 | 5 |
| mean keyed rank | 4.9 | 4.1 | **14.3** | 4.9 |
| mean sources in prompt | 13.3 | 13.8 | 27.8 | 14.0 |
| mean evidence tokens | 899 | 906 | 1,662 | 1,235 |
| **max keyed paragraphs in prompt** | **1** | **1** | **1** | **1** |
| mean keyed paragraphs available | 14.1 | 14.1 | 14.1 | 14.1 |

† Arm 3 is Stage A only: 9 rows, of which 7 were provable no-ops.

### Answer quality

| metric | Arm 0 | Arm 1 | Arm 2 |
|---|---:|---:|---:|
| **mechanical passes (20 part-level rows)** | **8** | **5** | **7** |
| mean key recall, raw | 0.430 | 0.369 | 0.414 |
| mean key recall, final answer | 0.343 | 0.261 | 0.284 |
| cites the keyed section | 6 | 6 | 5 |

Arm 3, on its 9 rows: **4 passes, identical to Arm 0's 4**, mean recall **0.439 vs 0.439**.

### Paired significance (exact McNemar)

| comparison | gained | lost | p |
|---|---:|---:|---:|
| Arm 0 → Arm 1 (K1) | 0 | 3 | 0.250 |
| Arm 0 → Arm 2 (K1 + ceiling) | 1 | 2 | 1.000 |
| Arm 1 → Arm 2 (ceiling, given K1) | 2 | 0 | 0.500 |
| Arm 0 → Arm 3 (ceiling alone) | 0 | 0 | 1.000 |

**Nothing in this phase reached significance.** All results are directional at n = 9–20.

---

## 6. The four hypotheses and their fate

**H1 — Ordering is the constraint. ❌ Refuted; the "fix" is worse than the bug.**
K1 lost 3 rows and gained none; keyed presence fell 18/18 → 12/18. ASCII collation sorts
`211.100, 211.101, 211.103` ahead of `211.22, 211.42, 211.80`, and for Part 211 the 1xx band *is* the
substantive material — subpart F production controls, subpart I laboratory controls, subpart J
records. The production defect is accidentally better aligned with Direct Lookup questions than a
correct numeric sort. Six rows lost the keyed section entirely (D-012, D-013, D-018, D-019, D-023,
F-011).

*This also corrected an earlier prediction.* A dry run over all 73 part-level Direct Lookup rows had
forecast +5 net keyed presence. The forecast was not wrong about those 73 rows — the 20-row probe
subset is simply unrepresentative on the one variable that matters.

**H2 — Position is the constraint. ❌ Refuted.**
On the 12 rows where the keyed section was present in both Arm 0 and Arm 1, K1 improved its rank on
4. Recall improved on 1, was unchanged on 3, fell on 0, and **no verdict changed on any of the 4**.

**H3 — Deletion / breadth is the constraint. ❌ Refuted twice, independently.**
Arm 2 restored every deleted keyed section with capacity held constant and scored **7 against
production's 8**. Arm 3 doubled breadth with production's good ranks intact and scored **4 against
4**. Only one row in the whole phase was rescued by making a deleted section available: **D-018**
(211.142 at rank 41 of 48, recall 0.36 → 0.79).

Both regressions against production are attributable to **K1, not the ceiling**: B-005's Arm 2
package is bit-identical to Arm 1, so its 0.60 → 0.00 collapse is pure reordering. Read in isolation
the ceiling is +2/−0 — directionally positive, far from significant, and worth nothing in practice.

**H4 — Section completeness is the constraint. ⚠️ Still standing. Not tested.**
`ECFR_EXACT_PART` filters `AND r.ordinal = 0` (`src/regulus/retrieval/sql.py:64`, commented *"the
first live row of each section in the part"*). A whole-Part request therefore retrieves **one row per
section**. Across all four measured arms the keyed section reached the prompt with a **maximum of one
paragraph — never more, not once** — against a mean of **14.1 paragraphs the section actually has**.
The model is shown a section's heading and opening paragraph and asked for requirements that live in
its subparagraphs.

---

## 7. The single most informative row

**D-012** — *"What charge-in of components controls does Part 211 require?"*, keyed to 211.101,
which has 12 paragraphs.

| arm | sources | evidence tokens | keyed rank | recall | pass |
|---|---:|---:|---:|---:|---:|
| 0 production | 18 | 980 | **2** | **0.00** | 0 |
| 1 K1 | 19 | 1,013 | — (deleted) | 0.30 | 0 |
| 2 K1 + ceiling | 48 | 2,700 | 28 | 0.10 | 0 |
| 3 ceiling only | 40 | 3,026 | **2** | **0.00** | 0 |

The governing provision sits at **rank 2 of 40**, in an evidence package tripled in size, and the
answer scores **zero**. One row refuting availability, position and breadth simultaneously. What it
never received: 211.101's other **11 paragraphs**.

---

## 8. Secondary finding: added context degrades generation behaviour

Not anticipated, and quantified across arms on part-level rows:

| arm | mean evidence tokens | mean generated tokens | hit the budget cap | failed to reach EOS | mean seconds |
|---|---:|---:|---:|---:|---:|
| 0 production | 899 | 386 | 1 | 3/20 | **71** |
| 1 K1 | 906 | 396 | 0 | 0/20 | 55 |
| 2 K1 + ceiling | 1,662 | 473 | 2 | 4/20 | **360** |
| 3 ceiling only | 1,235 | 317 | 1 | 2/9 | **168** |

**D-013 is the clearest case.** Arm 0: 980 evidence tokens, generated **135**, terminated normally,
**17 s**. Arm 3: 3,026 evidence tokens, generated **1,696 — the entire budget**, never reached
end-of-turn, **1,319 s**. Same keyed rank (3), same recall (0.91), same verdict. **12.5× the output
and 78× the latency for identical quality.**

Arm 4 showed the same signature before it was stopped: M-002, an 11.7-second row in Arm 3, ran past
**24 minutes** without completing once its evidence grew from 773 to ~2,600 tokens.

At this model size, enlarging the evidence package makes the model ramble rather than reason.

---

## 9. What was built but not measured — Arm 4

Arm 4 is complete, committed and **dry-run validated**; it was stopped for cost, not for a defect.

- `install_full_sections()` wraps `LexicalRetriever.exact_cfr` and, for whole-Part references only,
  runs `ECFR_EXACT_PART` with the `ordinal = 0` line removed. Derived from the production SQL by text
  surgery with assertions, so columns and filters stay in lockstep.
- `install_section_contiguous_order()` is **required**: production orders EXACT evidence by
  `(requirement, ordinal, key)`, and with full sections that becomes **paragraph-major** — paragraph 0
  of every section, then paragraph 1 of every section — which would shred the text. It keeps
  production's ASCII section order so Arm 4 does not smuggle in K1.
- Same 24,000-char ceiling as Arm 3, so the arms differ only in **how the same budget is allocated**:
  breadth (25.3 distinct sections, 25 keyed paragraphs) versus depth (7.7 sections, **215** keyed
  paragraphs, keyed section fully covered on **9 rows instead of 1**).

`scripts/d1_dryrun_e2.py` runs the pipeline with a stub generator so coverage, `select_evidence`,
Stage 6 `required_only` and Stage 8 `consolidate_evidence` all execute. Validated against the
measured Arm 2 at **20 rows × 5 fields, 0 mismatches** — the fidelity check the Arm 2
pre-registration lacked.

**Cost of finishing it: 3.5–5 hours** at the observed ~20 min/row, against 45–60 min estimated. It
was stopped after 24 minutes on row 1 of 9, with zero rows written.

**The test it would have run,** and which remains the highest-value cheap experiment available:
M-002, M-003 and M-004. Part 820 has 9 sections, so there is **no breadth/depth trade-off** — keyed
section 820.1 at **rank 1 with all 10 of its paragraphs**, same character budget. Arm 0 fails M-002
and M-004 on one paragraph of ten.

---

## 10. What is settled, and what is not

**Settled.**
- D1 exists, its mechanism is fully traced, and it affects 112 of 300 benchmark questions.
- Correcting the ordering makes results **worse**. K1 should not be implemented.
- Raising the context ceiling does not improve answers and costs 2.4–5× latency. **It should not be
  raised in production.**
- Availability and position are not binding: 18/18 keyed sections present and 10–11 rows still fail.
- Enlarging evidence degrades generation termination at this model size.

**Not settled.**
- **Section completeness** — the one live retrieval hypothesis. Built, not measured.
- **Statistical power.** Every comparison p ≥ 0.25 at n = 9–20. A real 15-point effect would be
  invisible here.
- **The proxy metric.** Nothing in this phase was scored against the rubric's L–Q gates (citation
  exactness, fabrication, substantive correctness, completeness, scope, ISO clause). A row can clear
  0.5 recall and still fail the rubric.
- **Trap behaviour.** NC-018 and SD-010 failed in every arm, consistent with both capacity limits and
  a missing deterministic check. Evidence changes cannot separate those.
- **Model capability**, which no arm here can address.

**Two errors I made and corrected mid-phase, both recorded:** the first Arm 2 run was confounded by
the adaptive budget and was discarded and re-run; and the Arm 2 pre-registration overstated source
counts because it called `select_evidence` directly, bypassing `required_only` and
`consolidate_evidence` (predicted 9 sources for M-013, measured 6). The Arm 3/4 dry run was validated
against ground truth before use, specifically to prevent a repeat.

---

## 11. Cost

| | |
|---|---|
| CPU model time | ~6.5 hours across arms 0–3, plus ~0.9 h of discarded or stopped runs |
| Slowest single rows | SD-010 42 min (Arm 2), D-013 22 min (Arm 3) |
| Rows measured | 36 + 36 + 20 + 9 = **101 question-arm cells** |
| Production changes | **zero** |

---

## 12. Recommendation

**Close Phase D1.** Do not implement K1. Do not raise the production context ceiling. Do not run
Stage B — 11 more rows at ~4 hours will not overturn five arms of consistent results.

**Then, in priority order:**

1. **Settle completeness cheaply, if at all.** Run Arm 4 on **M-002, M-003, M-004 only** — three
   rows, no breadth/depth trade-off, keyed section at rank 1 with full text. At ~20 min/row that is
   ~1 hour and it closes H4. If those rows do not move, completeness is eliminated too and retrieval
   is exonerated end to end.
2. **Re-score against the rubric, not the proxy.** The acceptance gates are what the project is
   judged on, and no arm here touched them. This is analysis work, not compute.
3. **CP-01 on a 24 GB CUDA host — this is now the critical path.** The reasoning categories scored
   0/20 Cross-Reference, 0/20 Application, 0/23 Distinction, 0/11 Temporal in the 300-question run,
   and no prompt, evidence or configuration change has ever produced a single correct trap refusal in
   10 attempts. Phase D1 has now eliminated the retrieval explanations one by one, which sharpens
   rather than answers that question. 8 GB cannot hold a 4B model at float32, and quantising it would
   break the equal-dtype rule that makes the comparison valid.
4. **If completeness does survive step 1**, the fix is *not* a blunt lift of `ordinal = 0` — that
   costs breadth and loses the keyed section on 4 of 18 rows. It is relevance-ranked Part selection
   (K3) *plus* full-text retrieval of the selected sections: identify the governing section, then
   fetch it whole. K3 remains deliberately unimplemented.

---

## 13. Artefacts

| Path | Contents |
|---|---|
| `scripts/d1_experiment.py` | the harness; arms 0–4, `PinnedBudget`, `--only-ids`, `--pin-budget-from` |
| `scripts/d1_analyse.py` | regenerates every deliverable table; tolerates trimmed arms; verifies the pin |
| `scripts/d1_dryrun_e2.py` | pipeline-faithful composition dry run, stub generator, validated 20×5 |
| `artifacts/diagnostics/d1_experiment/arm{0,1,2,3}.json` | measured arms, with full identity and patch records |
| `artifacts/diagnostics/d1_experiment/dryrun_arm{2,3,4}.json` | predicted composition |
| `artifacts/diagnostics/d1_experiment/analysis_arms012.txt` | full analysis output |
| `docs/D1_EXPERIMENT_RESULT.md` | arms 0–2 result, 10 deliverables |
| `docs/D1_E2_PREREGISTRATION.md` | arms 3–4 design, pre-registered discriminator, runbook |
| `docs/MODEL_IMPLEMENTATION_AUDIT.md`, `docs/MODEL_SIZE_VS_PIPELINE_ANALYSIS.md` | the diagnostic that identified D1 |

Commits: `f570776` harness · `60118ec` arms 0–1 · `d57311b` pause · `06318d9` budget pin ·
`26b201b` analysis · `98bbf71` runbook · `a643fcb` arms 0–2 result · `1077919` D1-E2 build.
