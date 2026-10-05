# Arm 2 runbook — manual terminal execution

All code is already committed at **`26b201b`**. **No code changes are required between any step.**
Run every command from the project root:

```
cd "/Users/sensussoftsoftware/Desktop/Prachi Patel/Regulus AI.nosync"
```

Arms 0 and 1 are final. **Do not re-run them** — `arm0.json` and `arm1.json` must not be overwritten.

---

## Step 0 — preflight (seconds)

```
pgrep -fl d1_experiment || echo "nothing running - good"
pgrep -fl "serve_ui|uvicorn|streamlit" || echo "UI stopped - good"
pg_isready
git log --oneline -1
git status --short
```

Expect: nothing running, `accepting connections`, HEAD at `26b201b`, clean tree.
If the UI is up, stop it — it competes for the CPU and distorts timings.

---

## Step 1 — smoke test, one row (~4–6 min)

Proves two things before you commit the full run: that the ceiling patch actually enlarges the
evidence package on a Part 211 row, and that the budget pin holds.

```
.venv/bin/python scripts/d1_experiment.py \
  --set artifacts/diagnostics/model_probe/probe_set.json \
  --arm 2 \
  --pin-budget-from artifacts/diagnostics/d1_experiment/arm0.json \
  --only-ids D-013 \
  --out /tmp/d1_smoke
```

Then inspect it:

```
.venv/bin/python - <<'EOF'
import json
g=lambda f:{r['id']:r for r in json.load(open(f))['rows']}
a0=g('artifacts/diagnostics/d1_experiment/arm0.json')
a1=g('artifacts/diagnostics/d1_experiment/arm1.json')
a2=g('/tmp/d1_smoke/arm2.json')
i='D-013'
print(f"{'field':28} {'arm0':>8} {'arm1':>8} {'arm2':>8}")
for k in ('n_sources','evidence_chars','evidence_tokens','prompt_tokens','budget',
          'generated_tokens','keyed_rank','keyed_present','recall_raw','mechanical_pass','seconds'):
    print(f"  {k:26} {str(a0[i][k]):>8} {str(a1[i][k]):>8} {str(a2[i][k]):>8}")
print("  pinned_to:",a2[i]['budget_pinned_to']," adaptive_would_have_been:",a2[i]['budget_adaptive_requested'])
EOF
```

### Decision gate — read this before continuing

| Check | Pass condition | If it fails |
|---|---|---|
| ceiling works | `n_sources` **> 18** (arm 0 was 18) | **STOP.** The ceiling patch is not reaching selection; do not spend hours. Tell me. |
| key restored | `keyed_present` is `True` (arm 1 lost it) | STOP and tell me — the premise of the arm is wrong. |
| budget pinned | `budget` **== 1696**, equal to arm 0 | STOP. The pin failed; the run would be confounded again. |
| budget confound real | `budget_adaptive_requested` **> 1696** | If it equals 1696, the confound was smaller than thought on this row — note it, continue. |

Only continue to Step 2 if the first three rows of that table pass.

---

## Step 2 — the 20-row Arm 2 (~1.5–2 h)

Runs the part-level rows in order of how informative the ceiling effect is: the six rows where K1
deleted the keyed section first, then composition-change rows, then the two provable no-ops last.

```
nohup .venv/bin/python scripts/d1_experiment.py \
  --set artifacts/diagnostics/model_probe/probe_set.json \
  --arm 2 \
  --pin-budget-from artifacts/diagnostics/d1_experiment/arm0.json \
  --only-ids D-013,D-019,D-012,D-023,D-018,F-011,M-013,M-002,M-003,M-009,M-014,C-004,B-005,M-004,NC-018,F-009,SD-010,B-001,C-002,E-010 \
  --out artifacts/diagnostics/d1_experiment \
  > logs/d1_arm2.log 2>&1 &
```

Watch it:

```
tail -f logs/d1_arm2.log | grep -vE "Loading weights"
```

`arm2.json` is rewritten after **every** question, so the run is safe to kill at any point and you
keep the completed rows. There is no mid-arm resume — restarting replays from the first id.

Rough per-tier cost: the six Tier-1 rows ~45 min, the twelve Tier-2 rows ~60 min, the last two ~1 min.

To stop early:

```
pkill -f "d1_experiment.py.*--arm 2"
```

---

## Step 3 — analysis (seconds)

```
.venv/bin/python scripts/d1_analyse.py | tee artifacts/diagnostics/d1_experiment/analysis_arms012.txt
```

It tolerates the trimmed arm, prints the paired n for every McNemar test, and asserts the budget pin
row by row. The line to read first is:

```
budget pin: N/N rows pinned to arm0's exact budget  (all identical)
```

If that says `!! MISMATCH`, the arm is confounded and the comparison is void.

---

## Step 4 — commit the result

```
git add -A artifacts/diagnostics/d1_experiment
git status --short
git commit -m "D1 arm 2: budget-pinned ceiling probe on the 20 part-level rows"
git diff f570776~1 HEAD --stat -- src/ configs/   # must print nothing
```

The last command printing nothing is the standing proof that no production code changed.

---

## What the result means

One question: **when the keyed section is guaranteed to survive retrieval and generation capacity is
held constant, does answer quality improve?**

- **Yes** (Arm 2 passes > Arm 0's 8 of 20, recall up) → evidence deletion is a confirmed contributor;
  next step is K3 relevance-ranked Part selection.
- **No** (passes ≤ 8 despite the keyed section present) → **do not raise the context ceiling further.**
  Investigate section completeness and relevance, or model generation behaviour. The leading candidate
  is already identified: `ECFR_EXACT_PART` filters `ordinal = 0`
  (`src/regulus/retrieval/sql.py:64`), so the keyed section reaches the prompt with at most **one**
  paragraph against a mean of **14.1** it actually has.

K2 and K3 are **not** implemented in this run, as instructed.
