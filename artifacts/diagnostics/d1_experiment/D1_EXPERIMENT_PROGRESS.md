# D1 controlled experiment: PAUSED 2026-10-05, 72 of 108 cells complete

Stopped on request. **Arms 0 and 1 are complete and analysed. Arm 2 was killed on its first row.**
Nothing in `src/regulus`, `configs/`, the prompts, the schemas or the benchmark was modified:
`git diff f570776~1 HEAD --stat -- src/ configs/` is empty.

## Where it stopped

| Arm | Status | Output |
|---|---|---|
| Arm 0 — production baseline | **36/36 complete** | `arm0.json` (143 KB) |
| Arm 1 — K1 numeric ordering | **36/36 complete** | `arm1.json` (155 KB) |
| Arm 2 — K1 + part-level ceiling probe | killed during row 1/36 (B-001) | none |

Analysis of the two completed arms: `analysis_arms01.txt`, regenerate with
`.venv/bin/python scripts/d1_analyse.py` (tolerates the missing arm and prints `?` for arm 2).

Commits: harness `f570776`, pause record `16a5855`, arms 0–1 + pre-registration `60118ec`.

## Resume command

```
nohup bash -c '.venv/bin/python scripts/d1_experiment.py \
  --set artifacts/diagnostics/model_probe/probe_set.json --arm 2' > logs/d1_arm2.log 2>&1 &
```

Only arm 2 remains — do **not** re-run arms 0 and 1, their JSON is final. Each arm rewrites its JSON
after every question, so a partial arm restarts from scratch; there is no incremental resume inside an arm.

**Revised runtime estimate for arm 2: 2–3.5 hours, not the 40–60 min first estimated.** Arm 2's
part-level prompts carry 40–61 sources and ~24,000 evidence chars against 18–23 and ~8,850 in
production, so prefill roughly triples and the adaptive budget (`evidence_multiple` 1.4) scales the
generation budget up with it. Row 1 (B-001) had run 11m52s without finishing when it was killed;
the same row took 342 s in arm 0. Nothing else should compete for the CPU.

## Result so far: K1 alone is strictly worse. The pure-ordering hypothesis is falsified.

Measured on the 20 part-level rows (the 16 non-part-level rows are untouched by both patches):

| metric | arm 0 production | arm 1 K1 |
|---|---:|---:|
| keyed section present (of the 18 rows that have a key) | **18** | **12** |
| keyed section at rank 1 | 5 | 3 |
| mechanical passes, part-level | **8** | **5** |
| mechanical passes, all 36 | 9 | 6 |
| mean key recall, raw output (part-level) | 0.430 | 0.369 |
| mean key recall, final answer (part-level) | 0.343 | 0.261 |

Exact McNemar, arm 0 → arm 1: **0 rows gained, 3 lost (B-005, D-013, F-011), p = 0.250.** Not
significant at n=18, but the point estimate is negative and there is not a single gain to offset it.

**Why.** ASCII collation sorts `211.100, 211.101, 211.103, 211.105, 211.110…` ahead of `211.22,
211.42, 211.80`, because it compares the digit strings character by character. For Part 211 the 1xx
band *is* the substantive material — subpart F production and process controls, subpart I laboratory
controls, subpart J records. So the production bug is accidentally well aligned with what Direct
Lookup questions ask about, and numeric ordering replaces that band with subparts A–C (scope,
organization, buildings). Six rows lose the keyed section entirely under K1: D-012, D-013, D-018,
D-019, D-023, F-011. Zero rows gain it.

**This did not match the dry run,** which predicted +5 net keyed presence (40→45 of 73) with 16
rescued and 11 regressed. The dry run ran over all 73 part-level Direct Lookup rows; this probe set
has 20 part-level rows drawn from a stratified sample, and they are concentrated in Parts 211, 117
and 820, where the keyed material sits high in the numeric range. The dry run is not contradicted —
the probe subset is unrepresentative of it on exactly the variable that matters.

## The finding that matters more than either arm: rank does not predict quality

On the 12 rows where the keyed section is present in **both** arms, K1 improved its rank on 4
(M-002, M-003, M-004, M-009, all rank 2→1 or 4→2):

- recall improved on **1**, was unchanged on **3**, fell on **0**
- mechanical pass changed on **0 of 4**

And in arm 0, the keyed section is present on all 18 keyed rows, yet **10 of those 18 still fail**.
Presence is necessary and nowhere near sufficient. Moving the governing provision to the top of the
prompt, on its own, changed no verdict.

## Two constraints found while instrumenting selection — neither arm can relieve either

Both are read-only observations from the real production functions, recorded in
`ARM2_PREREGISTRATION.md` (sha256 `ba836c7e…`) and reproducible with `scripts/sel_accounting.py`.

1. **`ECFR_EXACT_PART` returns `ordinal = 0` only** — `src/regulus/retrieval/sql.py:64`, commented
   "the first live row of each section in the part". So a whole-Part request retrieves **one row per
   section**. Over arm 0's part-level rows the keyed section reaches the prompt with a **maximum of 1
   paragraph** and a mean of **0.82**, against a mean of **14.1 paragraphs the section actually has**.
   Not one keyed section in the whole arm arrived with more than a single paragraph. Raising the
   ceiling adds more *sections*; it cannot add more of the *right* section. D-012 is the clean case:
   211.101 present at rank 2, and recall 0.00.
2. **The binding production limit is `hard_max_total_chars`, not `hard_max_results`.** D-012 selects
   18 of 60 retrieved sections at **8,850 of 9,000 chars**, and all 42 drops are recorded as
   `hard_ceiling_chars` with **none** as `hard_ceiling_count`. The 24-result ceiling is never reached
   on any part-level row in this probe set. Any future ceiling work must move the char ceiling; moving
   the count ceiling alone would do nothing.

## Arm 2's prediction is already pre-registered

`ARM2_PREREGISTRATION.md` was written and committed (`60118ec`) **before** arm 2 produced any
answer, from retrieval and selection only. It predicts keyed presence restored to **18/18**, but at
much worse ranks on the Part 211 rows (2/3/15/17/17 → 28/29/41/43/43) inside prompts of 40–61
equally-labelled `Tier: EXACT` sources. That makes arm 2 a clean discriminator:

- arm 2 ≥ arm 0 on answer quality ⇒ **availability** was the binding constraint;
- arm 2 ≤ arm 0 despite 18/18 presence ⇒ **relevance discrimination** is the binding constraint.

Given that rank improvements moved no verdicts in arm 1, and that every keyed section still arrives
as a single paragraph, the second outcome is the one to expect. Arm 2 is worth finishing because it
is the measurement that distinguishes them, not because the ceiling is a candidate fix.

## Frozen across all arms, and verified rather than asserted

Questions (the 36-row `probe_set.json`, seed 20261002), model (`Qwen3-0.6B` rev `c1899de2`, float32,
CPU, no adapter), system prompt sha256 `d39dc7bb…`, decoding (greedy, thinking off, adaptive budget),
retrieval queries, tiers, coverage, answerability, soft budgets, post-processing, citation logic and
the scoring functions carried from `model_probe_conditions.py`.

Verified in `analysis_arms01.txt`: the `identity` block is identical across arms; question ids and
order are identical; and all **16 non-part-level control rows are bit-identical between arms 0 and 1
— same prompt sha256, same raw output, same final answer.** All 20 part-level prompts changed. That
is the evidence the patch is surgical and the harness deterministic.

## Deliverable status against the brief

| # | Deliverable | Status |
|---|---|---|
| 1 | Exact code/config changes | done — `scripts/d1_experiment.py`, `install_k1` / `install_ceiling`, no production change |
| 2 | Commit hash | done — `f570776` harness, `60118ec` arms 0–1 |
| 3 | Freeze confirmation | done, and empirically verified via the 16 bit-identical control rows |
| 4 | Evidence metrics table | arms 0–1 done; arm 2 column pending |
| 5 | Answer-quality metrics table | arms 0–1 done; arm 2 column pending |
| 6 | Question-by-question delta | arms 0–1 done; arm 2 column pending |
| 7 | Rescued / non-rescued examples | arm 1 done (0 rescued, 3 regressed); arm 2 pending |
| 8 | Interpretation in the stated framework | partial — "K1 materially better" is falsified; the K1-vs-ceiling split needs arm 2 |
| 9 | Unresolved items | drafted above (the two selection constraints, the dry-run divergence, n=18 power) |
| 10 | Next D1 experiment | not written — depends on arm 2 |

## Not done, deliberately

K2 (tier semantics), K3 (relevance ranking), section-completeness changes, tier/schema/coverage/
answerability changes, any production commit of the raised ceiling, and any re-run of the
300-question benchmark.
