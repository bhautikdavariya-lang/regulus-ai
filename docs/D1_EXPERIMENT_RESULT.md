# D1 controlled experiment — result

Date 2026-10-05. Model `Qwen/Qwen3-0.6B` rev `c1899de2`, float32, CPU, no adapter. Production pipeline
unmodified: `git diff f570776~1 HEAD --stat -- src/ configs/` is empty. Benchmark sha256
`c009d5f9…4110`, unchanged.

**The question this was built to answer:** when the keyed section is guaranteed to survive retrieval
and generation capacity is held constant, does answer quality improve?

**Answer: no.** On the 20 part-level rows, mechanical passes go **8 → 7** from production to
K1+ceiling, while keyed-section presence goes **18/18 → 18/18**. Per the pre-agreed decision rule:
**do not increase the context ceiling further.** Investigate section completeness/relevance and model
generation behaviour instead.

---

## 1. Exact code and configuration changes

No file under `src/`, `configs/`, the prompts, the schemas or the benchmark was changed. Both
interventions are in-process monkeypatches in `scripts/d1_experiment.py`, installed by the harness in
its own process.

**K1 — `install_k1()`** wraps `regulus.retrieval.lexical.order_evidence` (the name the retriever calls
at `lexical.py:447`). It calls the real production function first, then re-sorts **only** runs of
`TIER_EXACT` evidence that tie on `(requirement order, ordinal)`, by:

```
(0, int(part), int(section_digits), alpha_suffix, "", paragraph_path, path_ordinal)   # well-formed
(1, 0, 0, "", raw_section, paragraph_path, path_ordinal)                              # unparseable, last
```

Non-EXACT tiers keep production order. `regulus.retrieval.evidence.order_evidence` is left unpatched.

**Ceiling — `install_ceiling()`** wraps `regulus.rag.pipeline.select_evidence` (called at
`pipeline.py:341`). If and only if every requirement in the plan is part-level
(`reference.section is None`), it substitutes `replace(policy, hard_max_results=84,
hard_max_total_chars=24000)`. Soft budgets (`max_results=8`, `max_chars_per_result=1200`,
`max_total_chars=3600`) pass through unchanged. Every other plan gets the production policy object.
**Not committed as a production default.**

**`PinnedBudget`** — a transparent generator proxy that forces `max_new_tokens` to the exact integer
Arm 0 passed for the same question. Added after the first Arm 2 attempt was found to be confounded:
the production budget policy is adaptive (`evidence_multiple` 1.4, `evidence_cap_fraction` 0.75,
`hard_max_tokens` 2048), so a larger evidence package silently buys a larger generation allowance.
Each row also records `budget_adaptive_requested`.

The benchmark key is never read by any patch. `keyed_sections` is used only after the answer exists,
for measurement.

## 2. Commit hashes

| Commit | Contents |
|---|---|
| `f570776` | diagnostics and experiment harness |
| `60118ec` | arms 0–1 complete, Arm 2 pre-registration |
| `d57311b` | pause record and `d1_analyse.py` |
| `06318d9` | `PinnedBudget` and `--only-ids` / `--pin-budget-from` |
| `26b201b` | analysis handles a trimmed arm, verifies the pin |
| `98bbf71` | Arm 2 runbook |

## 3. Freeze confirmation — verified, not asserted

Identical across arms: questions (`probe_set.json`, seed 20261002), model identity, system prompt
sha256 `d39dc7bb…`, decoding (greedy, thinking off), retrieval queries, tiers, coverage,
answerability, soft budgets, post-processing, citation processing, and the scoring functions.

Empirical checks from `analysis_arms012.txt`:

- `identity` block **identical** across all three arms.
- **Budget pin: 20/20 rows used Arm 0's exact per-question budget.** The pin did real work — on
  C-004 the adaptive policy requested 1,696 against Arm 0's 1,536 and was held to 1,536. Without the
  pin the nine large-evidence rows would have risen toward the 2,048 cap.
- Arms 0 vs 1: all **16** non-part-level control rows bit-identical — same prompt sha256, same raw
  output, same final answer.
- Arm 2 vs Arm 1: of the 9 rows where the ceiling changed nothing, **9 of 9 are bit-identical**
  (B-005, C-002, E-010, M-002, M-003, M-004, M-009, M-013, M-014). The harness is deterministic and
  the patches are surgical.

Arm 2 is a deliberately trimmed, ordered 20-row subset (the part-level rows). The 16 non-part-level
rows were not re-run: both patches are provable no-ops for them, already demonstrated by the
bit-identical arm 0 vs arm 1 control.

## 4. Evidence metrics (20 part-level rows; keyed subset n=18)

| metric | Arm 0 production | Arm 1 K1 | Arm 2 K1+ceiling |
|---|---:|---:|---:|
| keyed section present | **18/18** | **12/18** | **18/18** |
| keyed section at rank 1 | 5 | 3 | 3 |
| mean keyed rank (present only) | 4.94 | 4.08 | **14.33** |
| mean sources in prompt | 13.35 | 13.75 | **27.80** |
| mean evidence chars | 4,543 | 4,512 | **8,596** |
| mean evidence tokens | 899 | 906 | 1,662 |
| mean prompt tokens | 2,227 | 2,248 | 3,775 |
| mean tokens before keyed section | 209 | 223 | **747** |
| mean keyed token share % | 12.95 | 17.25 | 11.11 |
| **max keyed paragraphs in prompt** | **1** | **1** | **1** |
| mean keyed paragraphs in prompt | 0.82 | 0.57 | 0.86 |
| mean keyed paragraphs the section has | 14.11 | 14.11 | 14.11 |
| mean seconds per question | 71 | 55 | 360 |

The ceiling did what it was built to do: every keyed section survives, source count doubles. It also
pushed the keyed section three times deeper into the prompt and tripled the competing context.

## 5. Answer-quality metrics (same 20 rows)

| metric | Arm 0 | Arm 1 | Arm 2 |
|---|---:|---:|---:|
| **mechanical passes** | **8** | **5** | **7** |
| pass rate % | 40.0 | 25.0 | 35.0 |
| mean key recall, raw output | 0.430 | 0.369 | 0.414 |
| mean key recall, final answer | 0.343 | 0.261 | 0.284 |
| cites the keyed section | 6 | 6 | 5 |
| has any citation | 20 | 19 | 17 |
| model was called | 20 | 20 | 20 |
| mean generated tokens | 386 | 396 | 473 |
| finished on EOS | 17 | 20 | 16 |

Exact McNemar on paired mechanical pass:

| comparison | gained | lost | p | n paired |
|---|---:|---:|---:|---:|
| Arm 0 → Arm 1 (K1) | 0 | 3 | 0.250 | 20 |
| Arm 0 → Arm 2 (K1+ceiling) | 1 | 2 | 1.000 | 20 |
| Arm 1 → Arm 2 (ceiling, given K1) | **2** | **0** | 0.500 | 20 |

## 6. Question-by-question delta

Rank / sources / raw recall / pass, in that order per arm.

| id | type | keyed | rk0 | rk1 | rk2 | n0 | n1 | n2 | rec0 | rec1 | rec2 | p0 | p1 | p2 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B-001 | Direct Lookup | 600.10, 600.11, 210.2 | 1 | 3 | 3 | 13 | 14 | 42 | 0.18 | 0.09 | 0.36 | 0 | 0 | 0 |
| B-005 | Direct Lookup | 606.20, 606.100, 606.160 | 1 | 5 | 5 | 16 | 16 | 16 | 0.60 | 0.00 | 0.00 | **1** | 0 | 0 |
| C-002 | Direct Lookup | 701.3, 701.11, 701.13 | 2 | 3 | 3 | 10 | 10 | 10 | 0.67 | 1.00 | 1.00 | 1 | 1 | 1 |
| C-004 | Direct Lookup | 700.11, 700.35 | 1 | 2 | 2 | 9 | 10 | 12 | 0.85 | 0.85 | 0.85 | 1 | 1 | 1 |
| D-012 | Direct Lookup | 211.101 | 2 | — | 28 | 18 | 19 | 48 | 0.00 | 0.30 | 0.10 | 0 | 0 | 0 |
| D-013 | Direct Lookup | 211.103 | 3 | — | 29 | 18 | 19 | 48 | 0.91 | 0.27 | 0.91 | 1 | 0 | **1** |
| D-018 | Direct Lookup | 211.142, 211.150 | 15 | — | 41 | 18 | 19 | 48 | 0.36 | 0.29 | 0.79 | 0 | 0 | **1** |
| D-019 | Direct Lookup | 211.160 | 17 | — | 43 | 18 | 19 | 48 | 0.46 | 0.46 | 0.46 | 0 | 0 | 0 |
| D-023 | Application | 211.192, 211.160 | 17 | — | 43 | 18 | 19 | 48 | 0.07 | 0.00 | 0.00 | 0 | 0 | 0 |
| E-010 | Application | 11.10, 11.30 | 2 | 4 | 4 | 10 | 10 | 10 | 0.19 | 0.19 | 0.19 | 0 | 0 | 0 |
| F-009 | Distinction | 117.135 | 5 | 19 | 19 | 23 | 23 | 61 | 0.30 | 0.30 | 0.00 | 0 | 0 | 0 |
| F-011 | Application | 117.150 | 11 | — | 25 | 23 | 23 | 61 | 0.50 | 0.43 | 0.43 | **1** | 0 | 0 |
| M-002 | Distinction | 820.1 | 2 | 1 | 1 | 6 | 6 | 6 | 0.14 | 0.14 | 0.14 | 0 | 0 | 0 |
| M-003 | Distinction | 820.1 | 2 | 1 | 1 | 6 | 6 | 6 | 0.80 | 0.80 | 0.80 | 1 | 1 | 1 |
| M-004 | Cross-Reference | 820.1 | 2 | 1 | 1 | 6 | 6 | 6 | 0.30 | 0.40 | 0.40 | 0 | 0 | 0 |
| M-009 | Distinction | 820.3 | 4 | 2 | 2 | 6 | 6 | 6 | 0.57 | 0.57 | 0.57 | 1 | 1 | 1 |
| M-013 | Cross-Reference | 820.10 | 1 | 4 | 4 | 6 | 6 | 6 | 0.38 | 0.38 | 0.38 | 0 | 0 | 0 |
| M-014 | Cross-Reference | 820.10 | 1 | 4 | 4 | 6 | 6 | 6 | 0.67 | 0.50 | 0.50 | 1 | 1 | 1 |
| NC-018 | Negative Control | (trap) | — | — | — | 19 | 19 | 20 | 0.50 | 0.25 | 0.25 | 0 | 0 | 0 |
| SD-010 | Scope/Boundary | (trap) | — | — | — | 18 | 19 | 48 | 0.17 | 0.17 | 0.17 | 0 | 0 | 0 |

## 7. Rescued and non-rescued

| bucket | n | rows |
|---|---:|---|
| rescued by K1 | 0 | — |
| regressed by K1 | 3 | B-005, D-013, F-011 |
| **rescued only by K1+ceiling** | **1** | **D-018** |
| regressed by K1+ceiling vs production | 2 | B-005, F-011 |
| wrong in all three arms | 11 | B-001, D-012, D-019, D-023, E-010, F-009, M-002, M-004, M-013, NC-018, SD-010 |
| …of which the keyed section was present in **every** arm | 6 | B-001, E-010, F-009, M-002, M-004, M-013 |
| **keyed section present in Arm 2 but answer still wrong** | **11** | B-001, B-005, D-012, D-019, D-023, E-010, F-009, F-011, M-002, M-004, M-013 |

**The one genuine rescue — D-018.** Keyed 211.142 and 211.150. Production put 211.142 at rank 15 of
18 and failed (recall 0.36); K1 deleted it; the ceiling restored it at rank 41 of 48 and the answer
passed at recall 0.79. This is the only row in the experiment where making a deleted section
available converted a failure into a pass.

**The two losses are attributable to K1, not the ceiling.** B-005's Arm 2 evidence package is
*bit-identical to Arm 1* (16 sources, same prompt hash), so its 0.60 → 0.00 collapse is pure K1
reordering — the ceiling never touched it. F-011 had already failed under K1 and stayed failed. So
the ceiling's own contribution, read as Arm 1 → Arm 2, is **+2 gained, 0 regressed**.

**The decisive non-rescues.** Six rows had the keyed section present in all three arms and failed in
all three: B-001, E-010, F-009, M-002, M-004, M-013. On M-002 and M-004 the keyed section (820.1) sat
at **rank 1 of 6** in Arm 2 — top of a six-source prompt — and recall was 0.14 and 0.40. F-009 got
61 sources with the key at rank 19 and recall fell to 0.00.

## 8. Interpretation

Against the framework set for this experiment:

- **"K1 materially better ⇒ ordering is the problem" — falsified.** K1 alone is strictly worse:
  0 gained, 3 lost, keyed presence 18/18 → 12/18. ASCII collation sorts `211.100, 211.101, 211.103`
  ahead of `211.22, 211.42, 211.80`; for Part 211 the 1xx band *is* the substantive material
  (subpart F production controls, subpart I laboratory controls, subpart J records), so the
  production defect is accidentally better aligned with Direct Lookup questions than a correct
  numeric sort is.
- **"Only K1+ceiling better ⇒ deletion is the problem" — not supported.** Arm 2 restored every
  deleted keyed section with generation capacity held constant and still scored **7 vs production's
  8**. Deletion converted exactly **one** failure (D-018) into a pass out of six candidate rows.
- **"Neither better ⇒ investigate relevance ranking and section completeness" — this is the
  outcome.** The evidence points at completeness first.

**Availability is necessary and nowhere near sufficient.** In Arm 2, 18 of 18 keyed sections are
present and **11 of those 18 rows still fail**. In Arm 0, 18 present and 10 fail. Position does not
rescue them either: where K1 improved the keyed rank on 4 rows, recall moved on 1 and **no verdict
changed on any**.

**The constraint the experiment could not relieve, and the leading explanation.**
`ECFR_EXACT_PART` filters `AND r.ordinal = 0` (`src/regulus/retrieval/sql.py:64`, commented "the
first live row of each section in the part"). A whole-Part request therefore retrieves **one row per
section**. Measured across all three arms, the keyed section reaches the prompt with a **maximum of 1
paragraph** — never more, in any arm — against a mean of **14.1 paragraphs the section actually
has**. The ceiling adds more *sections*; it cannot add more of the *right* section. D-012 is the
clean demonstration: 211.101 present at rank 2 of 18 in production, and recall 0.00.

So the model is usually being shown the keyed section's *heading and opening paragraph* and asked for
requirements that live in its subparagraphs. That is a retrieval-completeness defect, not an
ordering defect and not a ceiling defect.

**Causality claims are limited to what the design supports.** The paired within-question design plus
the bit-identical control rows license causal attribution of the *evidence-composition* change. No
comparison here reaches significance: the strongest is Arm 1 → Arm 2 at +2/−0, p = 0.500. With
n = 18–20 these are directional results, and no aggregate correlation is treated as causal.

## 9. What remains unresolved

1. **The ceiling was never tested without K1.** Arm 2 bundles both. The isolated ceiling effect is
   only readable as Arm 1 → Arm 2 (+2, −0, p = 0.500). A production-ordering-plus-ceiling arm is
   missing, and it is the most promising untested configuration — selection accounting shows
   production ordering keeps the keyed section's good rank *and* the raised ceiling adds the missing
   sections.
2. **Statistical power.** n = 18–20, every comparison p ≥ 0.25. A real 15-point effect could be
   missed here.
3. **The ceiling relief was partial.** `PART_HARD_MAX_CHARS = 24000` was sized from a comment
   estimating "84 sections ≈ 14k chars", which counted body text only. With the
   `SOURCE`/`Tier`/`Citation`/`Heading` scaffolding the ceiling actually charges, Part 211 reaches
   23,761 chars and still drops sections: 48 of 60 survive, not all 60.
4. **The mechanical proxy is not the rubric.** Pass = key-element content recall ≥ 0.5, or a refusal
   match on trap rows. A row can clear 0.5 and still fail the rubric on citation, completeness or
   scope. Nothing here was re-scored against the rubric's L–Q columns.
5. **Traps are still 0.** NC-018 and SD-010 failed in all three arms, consistent with both capacity
   limits and a missing deterministic check; evidence changes cannot separate those.
6. **My Arm 2 pre-registration overstated source counts and ranks.** It called `select_evidence`
   directly and so bypassed `consolidate_evidence` (`pipeline.py:362`). Predicted 9 sources for
   M-013, measured 6. Its qualitative prediction — keyed presence restored to 18/18 — was correct.
7. **Cost.** Arm 2 took 2.0 hours of CPU for 20 rows; SD-010 alone took 42 minutes.

## 10. Recommended next D1 experiment

**D1-E2: isolate section completeness, which is the only constraint this experiment identified and
could not relieve.** Two arms on the same 20 part-level rows, same model, same decoding, **budget
pinned to Arm 0** exactly as here, benchmark key used only for measurement:

- **Arm 3 — ceiling only, production ordering.** Drop K1 entirely; keep the raised whole-Part
  ceiling. Separates the ceiling from the ordering change that cost 3 rows, and tests the
  configuration that selection accounting predicts is best. Cheap: no new mechanism.
- **Arm 4 — full keyed-section text.** Retrieve *all* paragraphs of each section in the part
  (lift the `ordinal = 0` filter for whole-Part requests), with the ceiling raised enough to hold
  them. This is the direct test of the single-paragraph constraint. Expect large prompts, so run it
  on the 6 Part 211/117 rows first.

Pre-register the discriminator before running: if Arm 4 materially beats Arms 0–3, section
completeness is the binding constraint and the fix is in `ECFR_EXACT_PART`, not in any ceiling or
ordering. If Arm 4 also fails with the full keyed text present at good rank, the remaining
explanations are relevance ranking (K3) and model capability — and the latter cannot be settled on
this machine, which is what CP-01 on a 24 GB CUDA host is for.

**Do not raise the production context ceiling.** It bought one row out of six candidates, at 5× the
latency, and left 11 of 18 rows failing with the keyed section in front of the model.

K2, K3, tier/schema/coverage/answerability changes, and any production default change remain
**not implemented**, as instructed.
