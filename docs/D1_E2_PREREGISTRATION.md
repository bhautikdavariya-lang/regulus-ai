# D1-E2 pre-registration and runbook

Date 2026-10-05. Follow-on to `docs/D1_EXPERIMENT_RESULT.md`, which established that neither evidence
ordering (K1) nor ceiling relief improves answer quality, and identified **section completeness** as
the one constraint no arm could relieve.

Production is untouched: `git diff f570776~1 HEAD --stat -- src/ configs/` is empty. K3 is **not**
implemented. Both arms are in-process monkeypatches in `scripts/d1_experiment.py`.

## The question

D1-E2 separates two things that Arm 2 bundled and could not distinguish:

- **Breadth** — more *sections* in the prompt, each still one paragraph.
- **Depth** — complete *sections*, each with all its paragraphs.

They are tested **at the same character budget (24,000)**, so the arms differ only in how that budget
is spent. That makes it a genuine allocation experiment rather than a "more context" experiment.

## The arms

| Arm | Ordering | Retrieval | Ceiling | Budget |
|---|---|---|---|---|
| 0 (measured) | production ASCII | `ordinal = 0` | 24 results / 9,000 chars | adaptive |
| 2 (measured) | K1 numeric | `ordinal = 0` | 84 / 24,000 | pinned to arm 0 |
| **3 — breadth** | **production ASCII** | `ordinal = 0` | 84 / 24,000 | pinned to arm 0 |
| **4 — depth** | section-major ASCII | **all paragraphs** | 400 / 24,000 | pinned to arm 0 |

**Arm 3 — `install_ceiling_for(84, 24000)` only.** No K1. This is the configuration the previous
experiment never tested: it keeps production's good keyed-section ranks *and* adds the sections the
9,000-char ceiling was deleting.

**Arm 4 — `install_full_sections()` + `install_section_contiguous_order()` + `install_ceiling_for(400, 24000)`.**
`install_full_sections` wraps `LexicalRetriever.exact_cfr` and, for whole-Part references only, runs
`ECFR_EXACT_PART` with the `AND r.ordinal = 0` line removed, so every paragraph of every section is
retrieved. The query is derived from the production SQL by text surgery with assertions, so the column
list and filters stay in lockstep with it.

`install_section_contiguous_order` is **required, not optional**. Production orders EXACT evidence by
`(requirement, ordinal, key)`. With one row per section every ordinal is 0, so the order is effectively
the citation string. With full sections the ordinals run 0..n and that same rule becomes
**paragraph-major** — paragraph 0 of every section, then paragraph 1 of every section — which shreds
the text. The patch restores section-major order and deliberately keeps production's **ASCII** section
order, not numeric, so Arm 4 does not smuggle in K1. Arm 4 therefore bundles completeness with a
contiguity fix; Arm 3 is the ordering-free comparator.

**Held identical across all arms:** model (`Qwen3-0.6B` rev `c1899de2`, float32, CPU), decoding
(greedy, thinking off), prompt wording and system prompt sha256 `d39dc7bb…`, soft budgets,
post-processing, citation processing, coverage, answerability, scoring functions, and the
**per-question generation budget, pinned to arm 0's exact integer** via `PinnedBudget`. The benchmark
key is never read by any patch; it is used only after composition, for measurement.

## Dry-run fidelity — validated this time

`scripts/d1_dryrun_e2.py` runs the pipeline end to end with a stub generator, so coverage,
`select_evidence`, the Stage 6 `required_only` narrowing and Stage 8 `consolidate_evidence` all
execute. Checked against the measured Arm 2: **20 rows × 5 fields, 0 mismatches.**

This is the defect in the Arm 2 pre-registration, now fixed: that one called `select_evidence`
directly, skipping `required_only` and `consolidate_evidence`, and overstated source counts
(predicted 9 for M-013, measured 6).

## Predicted evidence composition (20 part-level rows, keyed subset n=18)

| metric | arm 0 | arm 2 | **arm 3** | **arm 4** |
|---|---:|---:|---:|---:|
| keyed section present | 18 | 18 | **18** | **14** |
| keyed section at rank 1 | 5 | 3 | **5** | 6 |
| mean keyed rank | 4.9 | 14.3 | **4.9** | 11.4 |
| mean source blocks | 13.3 | 27.8 | 25.3 | 55.8 |
| mean **distinct sections** | 13.3 | 27.8 | **25.3** | **7.7** |
| mean evidence chars | 4,543 | 8,596 | 9,143 | 13,218 |
| **keyed paragraphs in prompt** | 23 | 24 | 25 | **215** |
| keyed paragraphs available | 395 | 395 | 395 | 395 |
| **rows with the keyed section fully covered** | 1 | 1 | 1 | **9** |

Arm 3 reproduces arm 0's keyed ranks exactly (mean 4.9, five at rank 1) while nearly doubling the
sections. Arm 4 multiplies the keyed text by roughly 9× and fully covers the keyed section on 9 rows
instead of 1 — at the cost of dropping breadth to 7.7 sections and losing the keyed section on 4 rows
(D-018, D-019, D-023, F-011), whose sections fall outside the narrower ASCII window.

## The decisive rows

Nine rows get the keyed section **present and completely covered** in Arm 4, against one paragraph in
production. Arm 0 fails five of them, and those five are the test:

| id | keyed | arm 0 rank / paras | arm 4 rank / paras | arm 0 pass |
|---|---|---|---|---:|
| D-012 | 211.101 | 2 — 1/12 | 6 — **12/12** | **0** |
| M-013 | 820.10 | 1 — 1/12 | 11 — **12/12** | **0** |
| M-002 | 820.1 | 2 — 1/10 | 1 — **10/10** | **0** |
| M-004 | 820.1 | 2 — 1/10 | 1 — **10/10** | **0** |
| E-010 | 11.10, 11.30 | 2 — 2/15 | 17 — **15/15** | **0** |
| D-013 | 211.103 | 3 — 1/1 | 18 — 1/1 | 1 |
| M-003 | 820.1 | 2 — 1/10 | 1 — **10/10** | 1 |
| M-009 | 820.3 | 4 — 1/14 | 23 — **14/14** | 1 |
| M-014 | 820.10 | 1 — 1/12 | 11 — **12/12** | 1 |

M-002, M-003 and M-004 are the cleanest cases in the whole programme: Part 820 has 9 sections, so
there is **no breadth/depth trade-off at all** — the keyed section 820.1 sits at **rank 1** with
**all 10 of its paragraphs**, at the same character budget. If quality does not improve there, the
completeness hypothesis is dead.

## Pre-registered discriminator — committed before any Arm 3 or Arm 4 answer exists

Read against arm 0's **8 of 20** part-level passes:

1. **Arm 4 > arms 0 and 3** → section completeness is the binding constraint. The fix is the
   `ordinal = 0` filter in `ECFR_EXACT_PART`, not any ceiling or ordering change.
2. **Arm 3 > arms 0 and 4** → breadth at a good rank is what helps; completeness is not the issue,
   and the 9,000-char ceiling is worth revisiting after all.
3. **Both ≈ arm 0** → neither availability, position, breadth nor completeness is binding. The
   remaining explanations are relevance ranking (K3) and model capability, and the latter cannot be
   settled on this 8 GB machine — that is what CP-01 on a 24 GB CUDA host is for.
4. **Both < arm 0** → added context is actively harmful at this model size, which would itself be a
   finding about 0.6B and would argue for narrowing evidence, not widening it.

Expect no significance at n = 18–20; every comparison in the previous experiment landed at p ≥ 0.25.
These are directional results and will be reported as such. No causal claim will rest on aggregate
correlation.

## Runbook

All commands from the project root. Code is committed; **no edits are needed between steps.**

### Stage A — the 9 decisive rows, both arms (~45 min total)

```
nohup .venv/bin/python scripts/d1_experiment.py \
  --set artifacts/diagnostics/model_probe/probe_set.json --arm 3 \
  --pin-budget-from artifacts/diagnostics/d1_experiment/arm0.json \
  --only-ids M-002,M-003,M-004,M-013,M-014,M-009,E-010,D-013,D-012 \
  --out artifacts/diagnostics/d1_experiment > logs/d1_arm3a.log 2>&1 &
```

then, after it finishes:

```
nohup .venv/bin/python scripts/d1_experiment.py \
  --set artifacts/diagnostics/model_probe/probe_set.json --arm 4 \
  --pin-budget-from artifacts/diagnostics/d1_experiment/arm0.json \
  --only-ids M-002,M-003,M-004,M-013,M-014,M-009,E-010,D-013,D-012 \
  --out artifacts/diagnostics/d1_experiment > logs/d1_arm4a.log 2>&1 &
```

Watch either with `tail -f logs/d1_arm3a.log | grep -vE "Loading weights"`.

**Stop and read the result before Stage B.** If the five arm-0 failures do not move in Arm 4, the
completeness hypothesis is already answered and the remaining 11 rows are not worth 4 hours.

### Stage B — the remaining 11 rows (~3.5–4 h, only if Stage A warrants it)

Same two commands with
`--only-ids B-001,B-005,C-002,C-004,D-018,D-019,D-023,F-009,F-011,NC-018,SD-010`.
Each arm rewrites its JSON after every question, so partial arms are safe.

### Analysis

```
.venv/bin/python scripts/d1_analyse.py | tee artifacts/diagnostics/d1_experiment/analysis_e2.txt
```

Check the `budget pin: N/N` line first. If it reports a mismatch, the arm is confounded and void.

## Runtime warning

Arm 2 cost 2.0 hours for 20 rows, with SD-010 alone taking 42 minutes. Arms 3 and 4 carry comparable
or larger prompts (mean 9,143 and 13,218 evidence chars against Arm 2's 8,596), so budget **4.5–5.5
hours for both full arms**. Stage A exists so that cost is only paid if the cheap rows justify it.
Stop `serve_ui` and leave the CPU free.

## Not implemented, deliberately

K2 (tier semantics), K3 (relevance ranking), any production default change, any schema, coverage,
answerability or benchmark change, and any re-run of the 300-question benchmark.
