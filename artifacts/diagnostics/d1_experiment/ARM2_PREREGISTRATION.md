# Arm 2 pre-registration

Written **before** Arm 2 produced any answer. Arm 0 and Arm 1 were complete; Arm 2 was still generating.
Evidence composition below is computed by running the real production retrieval and `select_evidence`
with the K1 patch installed and the probe policy applied — no model call, so no answer was seen.

Reproduce: `scratchpad/predict_arm2.py` (retrieval + selection only).

## Predicted evidence composition, Arm 2 (K1 + part-level ceiling 84 / 24,000 chars)

| id | keyed section(s) | rank arm0 | rank arm1 | **rank arm2 (pred)** | sources arm2 | chars arm2 |
|---|---|---:|---:|---:|---:|---:|
| B-001 | 600.10, 600.11, 210.2 | 1 | 3 | 3 | 44 | 23,900 |
| B-005 | 606.20, 606.100, 606.160 | 1 | 5 | 2 | 17 | 7,940 |
| C-002 | 701.3, 701.11, 701.13 | 2 | 3 | 3 | 10 | 6,532 |
| C-004 | 700.11, 700.35 | 1 | 2 | 2 | 12 | 11,278 |
| D-012 | 211.101 | 2 | — | 28 | 48 | 23,761 |
| D-013 | 211.103 | 3 | — | 29 | 48 | 23,761 |
| D-018 | 211.142, 211.150 | 15 | — | 41 | 48 | 23,761 |
| D-019 | 211.160 | 17 | — | 43 | 48 | 23,761 |
| D-023 | 211.160, 211.192 | 17 | — | 43 | 48 | 23,761 |
| E-010 | 11.10, 11.30 | 2 | 4 | 4 | 10 | 4,221 |
| F-009 | 117.135 | 5 | 19 | 19 | 61 | 23,333 |
| F-011 | 117.150 | 11 | — | 25 | 61 | 23,333 |
| M-002 | 820.1 | 2 | 1 | 1 | 9 | 4,932 |
| M-003 | 820.1 | 2 | 1 | 1 | 9 | 4,932 |
| M-004 | 820.1 | 2 | 1 | 1 | 9 | 4,932 |
| M-009 | 820.3 | 4 | 2 | 2 | 9 | 4,932 |
| M-013 | 820.10 | 1 | 4 | 5 | 9 | 4,932 |
| M-014 | 820.10 | 1 | 4 | 5 | 9 | 4,932 |
| NC-018 | (none — trap) | — | — | — | 20 | 9,254 |
| SD-010 | (none — trap) | — | — | — | 48 | 23,761 |

**Keyed-section presence, the 18 part-level rows that have a key: arm0 18/18, arm1 12/18, arm2 18/18.**

## The pre-registered discriminating prediction

Arm 2 restores *availability* on every row — but at a far worse *rank* on the five Part 211 rows
(2/3/15/17/17 → 28/29/41/43/43) and inside a prompt of 48 equally-labelled `Tier: EXACT` sources
instead of 18.

So Arm 2 separates the two hypotheses cleanly:

- If **availability** is the binding constraint, Arm 2 ≥ Arm 0 on answer quality.
- If **relevance discrimination** is the binding constraint, Arm 2 ≤ Arm 0 despite 18/18 presence,
  because the model now has to find the governing provision among 48 indistinguishable sources.

Arm 1 has already falsified the pure-ordering hypothesis: 18/18 → 12/18 presence, 8 → 5 passes,
zero rows gained, six lost.

## Two constraints that no arm in this experiment can relieve

1. **`ECFR_EXACT_PART` returns `ordinal = 0` only** (`src/regulus/retrieval/sql.py:64`) — one row per
   section. Measured over Arm 0's part-level rows: the keyed section reaches the prompt with a **maximum
   of 1 paragraph** and a mean of **0.82**, against a mean of **14.1 paragraphs that the section actually
   has**. No keyed section anywhere in Arm 0 arrived with more than one paragraph. Raising the ceiling adds
   more *sections*, not more of the *right* section.
2. **The char ceiling, not the count ceiling, is what binds in production.** D-012 selects 18 of 60
   retrieved sections at **8,850 of 9,000 chars**, with all 42 drops recorded as `hard_ceiling_chars` and
   none as `hard_ceiling_count`. The 24-result ceiling is never reached on these rows.
