# D1 controlled experiment: PAUSED 2026-10-02, 2 of 108 cells complete

Stopped on request. The pipeline, the benchmark and every file under `src/regulus` are untouched: the two
interventions exist only as runtime wrappers inside `scripts/d1_experiment.py`.

## Where it stopped

| Arm | Status | Output |
|---|---|---|
| Arm 0 — production baseline | **2 of 36 rows** (B-001, B-002) | `arm0.json` (overwritten on resume; partial) |
| Arm 1 — K1 numeric ordering | not started | — |
| Arm 2 — K1 + part-level ceiling probe | not started | — |

Harness commit: **`f570776938cd4d3ebe21bb7729ce4f3e2f4ecca5`** — "Diagnostics and D1 experiment harness
(read-only; no production change)". `git diff HEAD~1 --stat -- src/` is empty, confirming no production
source was modified.

## Resume command

```
nohup bash -c 'for a in 0 1 2; do .venv/bin/python scripts/d1_experiment.py \
  --set artifacts/diagnostics/model_probe/probe_set.json --arm $a; done' > logs/d1_experiment.log 2>&1 &
```

Each arm rewrites `arm<N>.json` after every question, so a partial arm is safe to restart from scratch;
there is no incremental resume inside an arm. Progress: `grep -v "Loading weights" logs/d1_experiment.log`.

## Runtime estimate, revised from the two completed rows

B-001 took **201.6 s** (13 sources, 1,181 evidence tokens) and B-002 **23.1 s**. The earlier three-condition
run averaged ~35 s per production row, so the first row is an outlier — probably a long generation rather
than a slow prompt. Budget on the observed spread:

- Arm 0: ~25–35 min
- Arm 1: ~25–35 min (same prompt size, different order)
- Arm 2: ~40–60 min (part-level prompts grow from ~24 to up to 84 sources, roughly 2,500 → 5,000+ prompt
  tokens, so prefill dominates)

Total **1.5–2.5 hours** of CPU model time. Nothing else should compete for the CPU while it runs.

## What the two arms do, exactly (for review before resuming)

Both are monkey-patches installed by the experiment script in its own process. No production default changes.

**K1 — `install_k1()`** wraps `regulus.retrieval.lexical.order_evidence`, the name the retriever calls at
`lexical.py:447`. It calls the real production function first, then re-sorts **only** runs of evidence that
are `TIER_EXACT` and tie on `(requirement order, ordinal)`, using:

```
(0, int(part), int(section_digits), alpha_suffix, "", paragraph_path, path_ordinal)   # well-formed
(1, 0, 0, "", raw_section, paragraph_path, path_ordinal)                              # unparseable, last
```

Verified on the real corpus forms: `111.1 → (0,111,1,…)`, `111.103 → (0,111,103,…)`,
`184.1141a → (0,184,1141,'a',…)`, and `820.20-820.30 → (0,820,20,…)`, i.e. a range sorts at its first
endpoint, which is its regulatory position. `float()` would raise on 20 of the 7,906 sections.
Non-EXACT tiers keep production order untouched. `regulus.retrieval.evidence.order_evidence` itself is
left unpatched and was asserted unchanged in the pre-flight.

**Ceiling probe — `install_ceiling()`** wraps `regulus.rag.pipeline.select_evidence`, the name the pipeline
calls at `pipeline.py:341`. If and only if every requirement in the plan is part-level
(`reference.section is None`), it substitutes `replace(policy, hard_max_results=84,
hard_max_total_chars=24000)`. Soft budgets (`max_results=8`, `max_chars_per_result=1200`,
`max_total_chars=3600`) are passed through unchanged. Every other plan gets the production policy object.

The raised char ceiling is part of the arm by necessity: 84 sections of Part 111 render to roughly 14,000
characters, so the production 9,000-char ceiling would truncate near 50 sections and the probe would
measure the character ceiling instead of the count ceiling. 84 covers the largest part in the probe set.

**The benchmark key is never read by either patch.** `keyed_sections` is used only after the answer exists,
to compute presence, rank, token share and paragraph coverage.

## Frozen across all three arms

Questions (the 36-row `probe_set.json`, seed 20261002), model (`Qwen3-0.6B` rev `c1899de2`, float32, CPU,
no adapter), system prompt sha256 `d39dc7bb…`, decoding (greedy, thinking off, adaptive budget), retrieval
queries, tiers, coverage, answerability, soft budgets, post-processing, citation logic, and the scoring
functions carried over from `model_probe_conditions.py`. Each arm's JSON records the model identity, the
config fingerprint, the system-prompt hash and the installed patch list, so the freeze is auditable per file.

## Metrics captured per question

Evidence: keyed present, keyed rank, source count, evidence chars, evidence tokens, tokens before the keyed
section, keyed token share, paragraphs of the keyed section present versus how many the section has, the
section list and the tier list. Answer: raw and final key-element recall, the existing mechanical pass
(recall ≥ 0.5, or a refusal match on trap rows), whether the keyed section is cited, whether any citation
marker is present, model-called, answerability state, coverage state, repair and final validation. Plus
prompt hash, prompt tokens, budget, generated tokens, eos flag and seconds.

## Baselines already available for comparison

- `artifacts/diagnostics/model_probe/phase567_conditions.json` — the same 36 questions under production,
  simplified and focused-evidence prompts (B/C/A), same model and decoding.
- `artifacts/diagnostics/model_probe/d1_dryrun.json` — the evidence-composition dry run over all 73
  part-level Direct Lookup rows: current vs K1 vs K2 vs K1+K2, produced with the real production
  ordering and selection functions and validated at 71 of 72 against the recorded run.

Pre-registered expectation from the dry run, for the part-level subset: K1 moves keyed-section presence
from 40 to 45 of 73, rescuing 16 and regressing 11. If measured answer quality does not track keyed-section
presence and rank, evidence position is not the binding constraint on these rows.

## Not done, deliberately

K2 (tier semantics), K3 (relevance ranking), section-completeness changes, any production commit of the
ceiling, and any re-run of the 300-question benchmark.
