# SUPERSEDED — the experiment completed on 2026-10-06.
# Result and decision: [ES_EXPERIMENT_RESULT.md](ES_EXPERIMENT_RESULT.md).
# This file is kept as the record of the paused state; its "what remains" section is done.

# Evidence-supply experiment — state as of 2026-10-05, and how to resume

Paused after the `es1` arm, by the user's decision, to continue the next day. Nothing is half-written:
every artifact below is complete and on disk, and no process is running.

**Production is unchanged.** Nothing under `src/regulus` has been modified at any point. The arms are
installed in-process by wrapping `regulus.rag.pipeline.select_evidence` and by copying the config
dataclass. The benchmark and the frozen rubric are untouched.

---

## 1. What is done

| Phase | State | Artifacts |
|---|---|---|
| 1 — taxonomy of the 126 evidence-supply rows | **complete** | `artifacts/stage_b/phase1_trace.jsonl`, `phase1_depth.jsonl`, `phase1_rows.jsonl`, `phase1_taxonomy.json`; written up in [ES_PHASE1_TAXONOMY.md](ES_PHASE1_TAXONOMY.md) |
| 2 — intervention design (ES-1) | **complete** | [ES_PHASE1_TAXONOMY.md](ES_PHASE1_TAXONOMY.md) §3 |
| 3 — experimental implementation | **complete** | `scripts/es_experiment.py` |
| 4 — frozen 36-row diagnostic subset | **complete, frozen before any treatment ran** | `artifacts/stage_b/subset_frozen.json` |
| control arm (36 rows) | **complete**, reproduces the Stage A baseline byte-for-byte | `artifacts/stage_b/run_control.jsonl`, `meta_control.json` |
| `es1` arm (E1+E2, 36 rows) | **complete** | `artifacts/stage_b/run_es1.jsonl`, `meta_es1.json` |
| mechanical comparison control vs es1 | **complete** | `artifacts/stage_b/comparison.json`, `comparison_rows.jsonl` |
| scoring packet for es1 | **built, not yet scored** | `artifacts/stage_b/scoring_packet_es1.md` (18 rows) |

## 2. What remains

Three things, in order.

**(a) Run the `es1_deep` arm — ~25–30 min of machine time.** It is the only arm that can move the
A2 stratum (12 of the 36 subset rows), where the governing section is not returned at `top_k=8` but is
at 24–96. Single process only, nothing else loaded:

```
cd "<repo>"
.venv/bin/python scripts/es_experiment.py --arm es1_deep --pin-from artifacts/stage_b/run_control.jsonl
```

The script resumes: rows already in `run_es1_deep.jsonl` are skipped, so an interruption is safe.

**(b) Hand-score the changed answers under `regulus_substantive_rubric_v1`.** 18 rows for `es1`
(listed in §4) plus whatever `es1_deep` changes. Rows whose answer is byte-identical to control
inherit the frozen Stage A verdict and must not be re-scored — `es_compare.py` computes both lists.
Write verdicts to `artifacts/stage_b/verdicts_es1.jsonl` and `verdicts_es1_deep.jsonl`, one JSON
object per line, same shape as the Stage A verdicts:

```json
{"id":"D-001","result":"FAIL","L":0,"M":0,"N":1,"O":1,"P":1,"Q":null,"notes":"...","eval":"..."}
```

Score against the provision text reproduced in the scoring packet, not against the draft key. Build
the packet for the deep arm with `.venv/bin/python scripts/es_scoring_packet.py --arm es1_deep`.

**(c) Final comparison and the decision.**

```
.venv/bin/python scripts/es_compare.py --with-verdicts
```

That emits the PASS/FAIL comparison, the transition table, and the two lists the experiment exists to
produce: `evidence_now_present_and_correct` versus `evidence_now_present_but_still_wrong`. Then write
the results report and a SHIP / REFINE / REJECT call.

## 3. Mechanical result so far — control vs es1

Not a success verdict. Substantive correctness is unscored, and **a treatment that supplies better
evidence without improving substantive answers is not a successful fix.**

| Metric | control | es1 |
|---|---|---|
| **Governing section's text supplied** | **0 / 36** | **14 / 36** |
| Cites the governing section | 2 | 9 |
| Mean evidence blocks | 8.3 | 8.1 |
| Mean evidence tokens | 681.7 | 694.7 (+1.9%) |
| Mean prompt tokens | 1766.6 | **1733.9 (−1.9%)** |
| Mean latency | 33.4 s | 37.9 s (+13%) |
| Mean generated tokens | 252.0 | 310.4 (+23%) |
| Answers withheld | 10 | 12 |
| Hit the pinned token ceiling | 0 | 1 |
| Truncation notice | 0 | 0 |
| Errors | 0 | 0 |
| Evidence changed / answer changed | — | 20 / 18 |

By stratum — this is the part that matters, because it says which mechanism the fix actually reaches:

| Stratum | n | supplied, control → es1 | answers changed |
|---|---|---|---|
| A1a part listing ASCII-truncated | 12 | **0 → 12** | 12 |
| A1b trigram cut-off | 6 | 0 → 2 | 1 |
| A2 reachable at greater depth | 12 | 0 → 0 | 3 |
| B unreachable at any depth | 4 | 0 → 0 | 1 |
| C corpus gap / reserved | 2 | 0 → 0 | 1 |

Reading of this, to be confirmed or overturned by scoring:

- **E1 does exactly what it was designed to do: 12 of 12.** The part-listing mechanism is the one
  that is cleanly fixed, and it is fixed without growing the context — prompt tokens went *down*.
- **E2 reaches 2 of 6, not 6.** Predicted during the run and confirmed here: E2 only relaxes the
  trigram similarity cut-off, and on the other 4 rows the governing section had already passed
  `is_useful` (it was found by full text) and was cut by the **budget** instead. A-004 is the clean
  case: 558.6 retrieved at rank 6 by full text, identical evidence in both arms. Fixing those rows
  needs optional-evidence ordering, which ES-1 does not touch.
- **B and C correctly do not improve** — the negative control on the measurement holds. They do show
  1 changed answer each, which is candidate-set perturbation, not improvement; treat any apparent
  gain there as noise.
- **Watch items for the safety analysis:** withholding rose 10 → 12, and generated tokens rose 23%
  with one row hitting the pinned ceiling. Both need checking against the scored verdicts — if the
  extra withholding is suppressing newly-correct answers, that is a regression, not a neutral change.

## 4. The 18 es1 rows needing a fresh verdict

```
A-002 A-003 B-003 D-001 D-003 D-004 D-006 D-007 D-009
D-022 D-024 D-026 D-027 F-001 F-002 G-003 K-005 M-034
```

The other 18 produced an answer byte-identical to control and inherit their Stage A verdict.

## 5. Known defects in this harness — read before trusting a number

1. **The validator's own code stream was not captured.** `record()` in `scripts/es_experiment.py`
   reads `validation_initial`, `validation_initial_codes`, `validation_final`, `repair` and
   `stop_reason` from the wrong metadata nesting. They live under
   `metadata["validation"]["initial"]["status"]` / `["codes"]`, `metadata["validation"]["repair"]`
   and `metadata["generation"]["stop_reason"]` — see `scripts/run_acceptance_test.py:55-80` for the
   correct extraction. Those five fields are therefore `null` in **every** arm. They are null
   identically, so the arms stay comparable, and `es_compare.py` derives the safety signals from
   text that *was* captured in full (withholding from the fallback builder's wording, non-termination
   from hitting the pinned allowance). **It was left unfixed deliberately** so that `es1_deep` is
   captured the same way as control and es1. Fix it only after `es1_deep` has run — and if it is
   fixed, all three arms must be re-run together.
2. **`governing_in_prompt` in `run_control.jsonl` is the wrong metric** (it counts a section number
   appearing anywhere in the prompt, which includes question echo — A-003 and A-004 scored "supplied"
   with zero paragraphs present). Later rows carry `governing_text_supplied` instead. Do not read the
   field from the run files: `es_compare.py` derives supply for every arm from `governing_presence`,
   requiring the section's **text** in the selected evidence.
3. **Never run two arms at once on this machine.** Two model instances swap an 8 GB Mac and inflate
   latency roughly tenfold — A-001 measured 213 s against 22 s. The first `es1` attempt was
   contaminated this way, by a chained launch firing alongside a direct one; that output was
   discarded and the arm re-run as a single process. Check `ps aux | grep es_experiment` before
   starting, and do not chain arms in a background shell.

## 6. Constraints still in force

Model, prompt, decoding, post-processing, benchmark, rubric: unchanged. No H4, no CP-01, no
fine-tuning, no production edit. The generation allowance stays pinned to the control arm's own
per-question value, so extra evidence cannot buy extra tokens. The span-support validator is not a
success metric.
