# Apple M2 GPU (MPS) + float16: benchmark and equivalence evaluation

Performance Stage 2. Benchmark and validation only: the default is unchanged
(`device: auto` still resolves to CPU float32 on this Mac), and MPS is opt-in.
Baselines: [performance_baseline.md](performance_baseline.md), [streaming.md](streaming.md).

## Verdict

**Do not make MPS float16 the default.** It is 2.4× faster and deterministic,
but it does not produce the same answers as CPU float32. In 5 of 60 questions
(8 %) the answer text differs; in 3 of those the difference is material, and
in 2 the citations, validation outcome and repair differ. The cause is fully
explained and deterministic: float16 rounding flips near-tied next-token
choices. It is not a GPU defect. Under this stage's acceptance criteria (no
unacceptable answer, citation or validation differences), it does not qualify.

A secondary finding: **MPS float32 is answer-identical to CPU float32 (60/60,
every field) and 1.55× faster**, but it leaves as little as 0.4 GB of memory
free on this 8 GB machine. That makes it the better next candidate, subject to
a memory soak test.

## 1. Inference architecture (as found)

| Question | Finding |
|---|---|
| Where device/dtype are selected | `configs/model.yaml` → `model.device`, `model.dtype` (both `auto`), overridable by `REGULUS_DEVICE` / `REGULUS_DTYPE`; validated in `config/settings.py`, resolved in `model/device.py` |
| CPU configuration | `auto` → CPU (no CUDA); dtype `auto` on CPU → float32; torch uses 4 threads |
| Model loading | `model/loader.py:load_model`: `from_pretrained(dtype)` → `.to(device)` → `.eval()` |
| MPS support before this stage | none: `mps` was rejected by the config validator, and `auto` only knows CUDA/CPU |
| Reloaded between requests? | no: `serve_ui.Engine` loads one base model at start-up; each request wraps the same object |
| Instances in memory | one base model (plus any adapter the user explicitly switches to, cached) |

## 2. What changed (opt-in only)

* `config/settings.py`: `mps` is an accepted device value.
* `model/device.py`: `resolve_device("mps")` returns the Apple GPU. If MPS is
  unavailable it **raises**, never silently falls back, so the device in use is
  always the one requested. `auto` never selects MPS. dtype `auto` on MPS stays
  float32 (float16 must be asked for). `environment_info()` reports `mps_available`.
* `scripts/serve_ui.py`: `--device {auto,cpu,mps}` and `--dtype
  {auto,float32,float16,bfloat16}` override the config; `/api/config` and the
  page header show the dtype as well as the device.
* `configs/model.yaml`, `.env.example`: comments only, documenting `mps`.
  **Values unchanged** (`auto`/`auto`).
* `scripts/benchmark_latency.py`: `--device/--dtype`, `--ids all`,
  `--with-answer-shape`; records the prompt SHA-256, answer, citations,
  sources, both validations, repair, coverage action, citation support, MPS
  memory and GPU utilisation per question; writes `environment.json` first.
* `scripts/compare_inference_runs.py`: exact field-by-field comparison with a
  unified diff and first-divergence position for every mismatch.
* Tests: `tests/test_device.py` (+5), `tests/test_config.py` (+2),
  `tests/test_compare_inference_runs.py` (4).

Fallback to CPU is a configuration change: `device: cpu` (or `auto`), or
`--device cpu`. The `cpu_fp32_repeat` run, made after the MPS runs, reproduced
the first CPU run exactly.

## 3. Runs

All runs: the 51 questions of `stage5_v1.jsonl` plus the 9 of
`answer_shape_v1.jsonl` (60 in total), in the same order, through the production
pipeline (validation `repair`, greedy decoding: `do_sample=False`,
`enable_thinking=False`, no repetition penalty), same model files, same
database. Only device and dtype differ.

| Label | Device / dtype | Artifact | Status |
|---|---|---|---|
| cpu_fp32 | cpu / float32 | `artifacts/latency/cpu_fp32_20260929T045001Z` | complete, 60/60 |
| mps_fp16 | mps / float16 | `artifacts/latency/mps_fp16_20260929T050537Z` | complete, 60/60 |
| mps_fp16_repeat | mps / float16 | `artifacts/latency/mps_fp16_repeat_20260929T051144Z` | complete, 60/60 |
| mps_fp32 | mps / float32 | `artifacts/latency/mps_fp32_resume2_20260929T054005Z` | complete, 60/60 (**replacement**, see below) |
| cpu_fp32_repeat | cpu / float32 | `artifacts/latency/cpu_fp32_repeat_20260929T055007Z` | complete, 60/60 |

**Interruptions and replacements (originals preserved, nothing appended or overwritten):**

* The first three runs finished all 60 questions, but their summary step
  crashed on a field-name collision in the benchmark script (`sources` used
  for both a count and a list). Every per-question record is intact (verified:
  60 parseable lines, all fields present, expected order). Statistics for all
  runs were recomputed from the per-question records into
  `artifacts/latency/stage2_performance_summary.json`. The bug is fixed.
* `mps_fp32_20260929T051753Z`: 33/60, stopped by the unexpected shutdown.
* `mps_fp32_resume_20260929T052846Z`: 57/60, stopped when the working session ended.
* `mps_fp32_resume2_20260929T054005Z`: the complete replacement, launched
  detached. `cpu_fp32_repeat` ran after it in the same detached job.
* The two MPS float32 runs that stopped early agree with the complete one on
  every answer they reached.
* Timed runs started only after the post-reboot load average fell below 4 (it was 20).
* Model load time was measured separately (three fresh processes per
  configuration, `artifacts/latency/model_load_time_cpu_fp32_vs_mps_fp16.json`),
  because the first runs lost their environment record.

## 4. Performance (warm questions that called the model, n = 54)

| Metric | CPU float32 | MPS float16 | Change | MPS float32 |
|---|---:|---:|---:|---:|
| Model load (+ first forward pass), 3 loads | 1.57–2.64 s | 0.62–1.45 s | ≈ −50 % | — |
| First token, median (p90) | 1.86 s (2.84) | **0.82 s (1.28)** | **2.3× faster** | 1.00 s (1.59) |
| Prefill rate, median | 761 tok/s | 1,667 tok/s | 2.2× | 1,424 tok/s |
| Generation, median (p90) | 10.99 s (37.1) | **4.65 s (15.6)** | **2.4× faster** | 7.22 s (24.5) |
| Total per question, median (p90) | 11.29 s (37.5) | **4.70 s (15.8)** | **2.4× faster** | 7.28 s (24.8) |
| All 60 questions, wall time | 928 s | 361 s | 2.6× | 588 s |
| Decode tokens/s, median | 12.6 | **28.2** | 2.2× | 17.4 |
| Overall tokens/s (incl. prefill), median | 10.3 | 23.4 | 2.3× | 15.1 |
| First question after load (cold) | 7.25 s | 3.16 s | 2.3× | 4.70 s |
| Process RSS, max | 3,911 MB | 273 MB | — | 276 MB |
| MPS memory, driver-allocated max (tensors) | — | 2,227 MB (1,144) | — | **4,523 MB (2,288)** |
| Model + runtime memory, approx. | ≈ 3.9 GB | **≈ 2.5 GB** | ≈ −36 % | ≈ 4.8 GB |
| Lowest free memory during run | 1,357 MB | 1,188 MB | — | **421 MB** |
| Swap in use during run (min–max) | 1,175–1,647 MB | 1,297–1,345 MB | stable | 528–1,329 MB |
| GPU utilisation, median of per-question means | 0 % | 84.9 % | — | 90.6 % |
| Process CPU, median | 185 % | 23 % | — | 18 % |

The repeat runs agree closely: CPU median total 11.31 s, MPS float16 4.71 s.

Notes:

* MPS first-token times include one decode step (about 35 ms), because
  transformers streams one step behind on MPS. The true improvement is slightly
  larger than shown.
* RSS does not include MPS allocations. On MPS the weights live in unified
  memory, which the driver figure shows.
* Swap was already in use before these runs (after the reboot and the earlier
  runs). What matters is that no configuration made it grow materially while
  running: MPS float16 stayed within 1.30–1.35 GB.
* GPU utilisation is read from the IOAccelerator registry (`ioreg`) every 0.5 s.

## 5. Answer equivalence

Compared exactly, with no similarity threshold, on: prompt SHA-256, retrieval
sources, final answer, citations, initial validation, final validation,
repair, coverage action, citation support, generated tokens, prompt tokens,
model_called. Reports: `artifacts/latency/compare_*.md`.

| Comparison | Identical in every field | Differing questions |
|---|---:|---|
| CPU fp32 vs CPU fp32 repeat | **60 / 60** | none |
| MPS fp16 vs MPS fp16 repeat | **60 / 60** | none |
| CPU fp32 vs MPS fp32 | **60 / 60** | none |
| CPU fp32 vs **MPS fp16** | **55 / 60** | S5-005, S5-010, S5-061, S5-083, AS-05 |
| MPS fp32 vs MPS fp16 | 55 / 60 | the same five |

In all 60 questions the prompt (SHA-256), sources, prompt token count,
`model_called` and coverage action are identical under every configuration:
the model always received exactly the same input.

| Quality check (CPU fp32 → MPS fp16) | Result |
|---|---|
| Byte-identical answers | **55 / 60** (5 differ) |
| Materially different answers | **3** (S5-061, S5-083, AS-05); 1 one-word (S5-005); 1 whitespace-only (S5-010) |
| Citation differences | **2** (S5-061, S5-083) |
| Source differences | 0 |
| Validation differences | **4** (initial and final; all but S5-005) |
| Repair differences | **2** (S5-061: `safe_message` → none; S5-083: `invalid_citations_removed` → none) |
| Generated-token differences | 5 (e.g. S5-061: 384 → 95) |
| Determinism (MPS fp16 run vs repeat) | 60 / 60 identical in every field |
| Test regressions | none |

### The five differences, exactly

Full unified diffs: `artifacts/latency/compare_cpu_fp32_vs_mps_fp16.md`.

| Q | First divergence | CPU float32 → MPS float16 | Validation / repair / citations |
|---|---|---|---|
| S5-005 `What does § 211.132(a) say?` | token 15, after "requires that OTC" | " drug" → " human" ("OTC **human** drug products"); otherwise identical | both valid, same citation. Cosmetic |
| S5-010 `What does 21 CFR 820.10(b) require manufacturers to comply with?` | token 44, after "part 830 of this chapter [1]." | line break → " The": the same four sentences, one paragraph instead of four lines | identical codes and citations. Whitespace only |
| S5-061 `What is a unique device identifier required to contain?` | token 26, after "…required to contain. [2] The" | " unique" → " exception". CPU then loops to 384 tokens (degenerate, truncated) and is replaced by the safe message. MPS writes a 95-token answer that echoes the question and says "A unique device identifier is required to contain." | CPU: degenerate → `safe_message`, no citations. MPS: **valid**, 3 citations, no repair. **Material**: the outcome flips from a refusal to a weak answer that passes validation |
| S5-083 `What does the EU Medical Device Regulation require for UDI?` (out of domain; should be refused) | token 20, after "…must be assigned to a device" | " under" → " that". Both answer when they should refuse; different wording | CPU: invalid citation, repaired. MPS: valid as generated. **Material** (different text and repair); both wrong |
| AS-05 `Compare 21 CFR 820.10(c) and 820.10(d).` | token 68, after "…ISO 13485. The" | " class" → " requirement". MPS then states (c) "applies only to devices that are automated with computer software", which is wrong; CPU's text has a different slip | both evidence-mismatched → repaired the same way, same citations. **Material** wording; both flawed |

## 6. Why they differ (nondeterminism investigation)

* **Sampling / randomness: excluded.** Decoding is greedy (`do_sample=False`)
  in every run; no seed is involved. Each configuration reproduced itself
  exactly (CPU 60/60, MPS float16 60/60).
* **Generation configuration: excluded.** Same settings object, same prompts
  (SHA-256 equal on all 60), same token budget per question.
* **MPS implementation: excluded.** MPS float32 is identical to CPU float32 on
  60/60 in every field.
* **float16 precision: the cause.** The same five questions differ in MPS
  float16 vs MPS float32 as in MPS float16 vs CPU float32. At each first
  divergence, CPU float32's top two next-token logits are a near-tie
  (`artifacts/latency/divergence_probe_cpu_fp32_vs_mps_fp16.json`):

| Q | CPU fp32 top-2 (margin) | MPS fp16 top-2 (margin) |
|---|---|---|
| S5-005 | " drug" 24.7994, " human" 24.7938 (0.0056) | tie at 24.7812 (0.0) → " human" |
| S5-010 | "  \n" 22.2454, " The" 22.2436 (0.0018) | tie at 22.2656 (0.0) → " The" |
| S5-061 | " unique" 18.5407, " exception" 18.5331 (0.0076) | " exception" 18.5469, " unique" 18.5312 (flipped) |
| S5-083 | " under" 18.5836, " that" 18.5781 (0.0055) | tie at 18.5781 (0.0) → " that" |
| AS-05 | " class" 20.3340, " requirement" 20.3314 (0.0026) | " requirement" 20.3594, " class" 20.3438 (flipped) |

float16 represents numbers near 16–32 in steps of 1/64 ≈ 0.0156. Margins of
0.002–0.008 are below that resolution, so they collapse into exact ties or
reverse, and greedy decoding follows the other branch from then on. The
behaviour is deterministic and would recur on every run; 55/60 questions have
no such near-tie on their path.

## 7. Regression testing

| Suite | Result |
|---|---|
| Full suite (`pytest`) | **1047 passed, 1 skipped** (the known Stage 12 dashboard skip) |
| Integration (read-only PostgreSQL) | **20 / 20** |
| Slow tier (loads the model) | 3 passed, 3 failed: the same three that fail on code predating all performance work (pre-existing) |
| CPU default path | `auto` resolves to `cpu`; CPU fp32 answers identical to those recorded 2026-09-24 (9/9) and token counts to the Stage 0 latency baseline (15/15) |
| CPU after MPS runs | `cpu_fp32_repeat` identical to `cpu_fp32` (60/60) |

## 8. Acceptance criteria

| Criterion | MPS float16 | MPS float32 (for reference) |
|---|---|---|
| 1. Substantial speed improvement | **yes**: 2.4× total, 2.3× first token | moderate: 1.55× total |
| 2. No unacceptable answer/citation differences | **no**: 3 material answer differences, 2 citation differences | yes: 60/60 identical |
| 3. Validation remains correct | validation *runs* correctly, but its outcome differs on 4/60 (one flips from safe message to a weak answer that passes) | identical |
| 4. Existing tests healthy | yes | yes |
| 5. Memory/swap stable | yes: about 2.5 GB, swap flat | **tight**: 4.5 GB driver memory, 0.4 GB free at the lowest |
| 6. Clean fallback to CPU | yes (config switch; verified) | yes |

## 9. Recommendation

1. **Keep CPU float32 as the default.** MPS float16 fails criterion 2. Its
   differences are not random and not a GPU bug, but they change answers,
   citations and validation outcomes on 8 % of the benchmark. In one case a
   question the current system declines is instead answered weakly, and that
   answer passes validation.
2. **MPS float16 stays available opt-in** (`--device mps --dtype float16`)
   for speed-sensitive use where exact equivalence with the verified CPU
   answers is not required. Not for evaluation or benchmark runs.
3. **Before any default change, evaluate MPS float32**, which is
   answer-identical to CPU on all 60 questions and 1.55× faster (median 7.3 s
   vs 11.3 s). Its risk is memory, not quality: about 4.5 GB of GPU-side
   allocation on an 8 GB machine. It needs a soak test under the answering UI
   with realistic background apps before it could be recommended.
4. Whether MPS float16's differences are *acceptable* is a product decision
   this evaluation cannot make on byte-equality alone. A full Stage 5
   correctness run under float16 would show whether the net quality effect is
   neutral. The differing answers here are no worse *on average*, but they
   are different, and the S5-061 outcome flip is the kind of change the
   verified-answer policy exists to prevent.

Not done in this stage, by design: no default change, no quantisation, no
model, prompt, retrieval, context or generation-parameter change.
