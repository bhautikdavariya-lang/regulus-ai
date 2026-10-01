# Model-Ladder Handoff (after Stage 8)

Date: 2026-10-01. **Status: a proposal. It has not been executed.** No 4B/8B/14B/30B model has been run, and no
training was started.

The machine-readable baseline is [artifacts/baselines/post_stage8_baseline.json](../artifacts/baselines/post_stage8_baseline.json).
A ladder run is comparable with this baseline only if it matches every field there except the model.

## 1. Current baseline

| Item | Value |
|---|---|
| Code | commit `e0c3135` (Stages 7–8) |
| Model | Qwen/Qwen3-0.6B, revision `c1899de289a04d12100db370d81485cdf75e47ca` |
| Weights sha256 | `f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b` |
| Tokenizer sha256 | tokenizer.json `aeb13307…dae4`, tokenizer_config.json `d5d09f07…8101` (same snapshot) |
| Backend | transformers, local; an OpenAI-compatible backend seam exists (`model.backend`, `model.endpoint`) |
| Hardware | Apple M2, 8 GB; **CPU, float32** |
| Database | PostgreSQL, read-only. cfr_records 65,341, cfr_sections 7,906, cfr_parts 250, fda_guidance 1,836, fda_guidance_chunks 68,669; content md5s in the manifest |
| Benchmark workbook sha256 | `c009d5f9c649822097b02a6c6aba415715fb0929914ef452acb03c8c3ac4a110` (unchanged) |
| Diagnostic set (diagnostic_v1) sha256 | `f99b1106aba8e0532f9b6efa67437dc72d80c5ecf95d903b746ec107564bff50` |
| System prompt sha256 | `d39dc7bb9778d1a632a4863bd12718871f8653154853b0f180d1cf774afe8b79` |
| Pipeline fingerprint | version 6 |

### Inference configuration

- **Decoding:** greedy (`do_sample=false`), thinking off.
- **Token budget:** adaptive, minimum 256, ceiling 2,048.
- **Repetition stop:** at the 3rd normalised copy of a sentence.
- **Retrieval:** lexical, with semantic fallback.
  - Index: semantic_expanded_v1 (bge-small, 19% of the DB).
  - Settings: top 8, similarity floor 0.75, interleave merge.
  - The fallback runs for reference-target-only and no-result questions; general questions are off.
- **Scope policy:** general_knowledge.
- **Evidence consolidation:** on.
- **Answerability gate, claim validation and repair:** as in Stage 7.

### Tests

The default suite gives 1,266 passed, 1 skipped and 26 deselected. The slow tier has 3 failures, which predate
Stage 5.

## 2. Stage 8 metrics

| Metric | Value |
|---|---|
| 830.20 "address" question | **12–13 s, 138 tokens, no repetition** (was 173 s / 1,216 tokens) |
| 12-question targeted suite | highest repeat count in a final answer: 1; duplicate evidence: 0; 314.999 and Part 1400 declined |
| Final answers with a sentence repeated ≥3 times (79 + 12) | 0 |
| Evidence consolidation (379 questions) | 94 [Reserved] rows removed in 33 questions; 0 merges |
| Determinism | 10/10 identical |

### Answer length by scope

Median characters, from the diagnostic run:

| Scope | Questions | Median characters |
|---|---:|---:|
| Single paragraph | 19 | 231 |
| General | 12 | 596 |
| Multi-provision | 17 | 757 |
| Whole section | 4 | 1,692 |
| Whole Part | 10 | 518 (p90 2,735; max 3,246) |

Length follows the scope of the question. No "make it shorter" prompt was applied.

## 3. Diagnostic result (79 questions)

Run: `artifacts/diagnostics/stage8_freeze_20261001T051756Z`. It is live and byte-identical to `stage8_result_final`.

| | Reviewed (developer) | Automatic |
|---|---:|---:|
| PASS | 49 | 46 |
| FAIL | 12 | 15 |
| NEEDS_REVIEW | 2 | 2 |
| UNVERIFIED | 13 | 12 (+1 UNVERIFIED_NEEDS_REVIEW) |
| UNVERIFIED_WITH_FAILURES | 3 | 3 |

**Protected Stage 4 PASS set:** 38 of 39 pass. S5-101 has been FAIL since the Stage 6 review correction. No
protected answer changed from Stage 7.

The reviews are developer reviews, not SME reviews.

## 4. Failure taxonomy (12 FAIL + 3 UNVERIFIED_WITH_FAILURES)

| Cause | Questions | Notes |
|---|---|---|
| Model capacity | S5-006, S5-010, S5-012, S5-091, S5-101, AS-01, AS-06 | Fail under all 11 evidence and prompt representations tried in Stage 6 |
| Capacity / prompt trade | S5-100 | Fixed by some prompt variants, which break others |
| Capacity: omitted conditions | S5-007 | |
| Retrieval | S5-061 | The definition is not retrieved lexically |
| Generation after a retrieval fix | S5-090 | The reference lookup now retrieves 820.10(b)(3); the model echoes the prompt, and the answer is withheld |
| Scope-policy limit | S5-082 | "Boiling point of water" contains a domain term, so it is not declined as general knowledge |
| UNVERIFIED_WITH_FAILURES | BM-F-002 | Capacity; no key |
| UNVERIFIED_WITH_FAILURES | BM-S-001 | Degenerate generation on broad Part 111 evidence; withheld |
| UNVERIFIED_WITH_FAILURES | BM-NC-003 | False premise (a non-existent Subpart Z); withheld |

Roughly 10 of the 15 are attributed to model capacity. This attribution is the hypothesis the ladder tests; it has
not been proven.

## 5. Retrieval findings

These are **retrieval-level measurements only, not end-to-end results.**

| Question | Finding |
|---|---|
| S5-090 | Semantic search ranks 820.10(b)(3) #1; lexical search never retrieves it. Now resolved by the reference lookup. |
| S5-061 | Semantic search ranks 830.20 #1 and 801.3 about #3; lexical search finds neither. The semantic fallback does not trigger, because the question names no provision and lexical returns results. |
| S5-091 | Semantic retrieval does not help; the failure is in generation. |
| Benchmark draft targets | Selected-evidence recall is 31.6% (lexical), measured against unverified draft keys. |

A general-question semantic fallback was measured at net +2 of 266 questions and left opt-in.

## 6. Model-capacity findings

- **Stage 6:** 11 evidence and prompt representations were tried on the 0.6B model. Each fixes some questions and
  breaks others, so the model "trades" properties.
- **Stage 8:** a "state each requirement once" prompt rule improved degeneracy (4 → 1) and citations (8 → 4).
  It also failed 3 protected PASS questions, so it was reverted.
- **Stage 8:** for this model, the text before a loop is not a reliable answer, so loops are rejected rather than
  trimmed.
- **Remaining 12-question errors:** an incomplete enumeration, a misread paragraph, a garbled sentence and a
  dropped qualifier. These are capability errors, not pipeline defects.

## 7. Training findings

| Stage | Result |
|---|---|
| 12 (LoRA, 0.6B) | 1 improved, 13 regressed (of 27) |
| 13 | Reviewer mean 0.556 vs base 1.11 (worse) |
| 14 | Stalled; no verdict. One epoch takes 45.7 h on this machine |

**Conclusion: training the 0.6B model is not justified.** Any fine-tuning decision waits until the ladder has
chosen a model.

## 8. Evaluation limitations

The 300-question benchmark has not yet been expert-verified and therefore does not provide a validated end-to-end accuracy number.

- **Key status:** 300 total / 0 expert verified / 300 pending / 0 disputed. The promotion gate is closed.
- **Diagnostic set:** 79 questions, developer-reviewed, with no SME review. It is a regression and diagnosis
  instrument, not an accuracy estimate.
- **Retrieval recall figures:** they use draft targets.

## 9. Ladder proposal (not executed)

| Rung | Model | Purpose |
|---|---|---|
| 0 | Qwen3-0.6B (current) | Control. It must reproduce this baseline on the ladder hardware |
| 1 | ~4B (e.g. Qwen3-4B) | Smallest candidate |
| 2 | ~8B (e.g. Qwen3-8B) | Main candidate |
| 3 | ~14B (e.g. Qwen3-14B) | Upper candidate |
| 4 | 30B-class (e.g. Qwen3-30B-A3B) | Reference ceiling, not a deployment candidate |

### Design requirements: the model is the only variable

The following must be identical on every rung:
- **Questions:** the diagnostic_v1 hash above. Optionally also the 300 benchmark questions, reported as
  unverified.
- **Evidence:** frozen retrieved evidence per question (replay the prompts), with the same DB content md5s and
  semantic index.
- **Prompts:** the same system prompt sha and the same prompt builder. No per-model prompt tuning.
- **Decoding:** greedy, thinking off, the same budget policy and the same repetition stop.
- **Validation, repair, scoring and evaluator:** unchanged. The protected set and the developer reviews stay as
  they are.
- **Tokenizer:** each model's own, recorded by hash.

Two further rules:
- **Rung 0 reruns first.** If it does not reproduce 49/12/2/13/3 (allowing for documented device or dtype
  numeric drift), stop and investigate before comparing.
- **Record per rung:**
  - the status distribution;
  - the protected-set result;
  - per-question changes against rung 0;
  - degenerate and withheld counts;
  - citation failures;
  - latency and tokens;
  - peak memory.

**Decision rule:**
1. Choose the smallest model that fixes the capacity-class failures without protected regressions.
2. Then consider fine-tuning that model.
3. Expert verification of the benchmark key is still needed before anyone can claim an accuracy number.

## 10. Hardware handoff

This 8 GB M2 cannot run rungs 2–4, and only rung 1 at reduced precision. The ladder needs **CUDA, preferably
rented cloud GPUs**.

**These are estimates, not measurements.** They come from parameter counts at the stated precision and include
headroom for a ~4k-token context; actual peak memory must be measured on rung 0/1.

| Model | Weights (bf16) | Suggested GPU |
|---|---|---|
| 4B | ~8 GB | 16–24 GB (e.g. L4, A10G) |
| 8B | ~16 GB | 24 GB (L4 / A10G class) |
| 14B | ~28–30 GB | 48 GB (L40S / A6000 class), or 24 GB at 8-bit or 4-bit |
| 30B-class | ~60–64 GB | 80 GB (A100/H100 80 GB) or 2 × 48 GB |

Precision rules:
- **Primary comparison:** bf16 on every rung.
- **Quantisation:** if used, it is a separate, labelled variable, never mixed into the primary comparison.
- **Rung 0 baseline:** CPU float32, so rung 0 must be rerun on the GPU in bf16 to separate hardware/dtype effects
  from model effects.

The database and the evidence can stay local or be exported as frozen prompt files. The replay
(`run_diagnostics.py --replay-from`, prompt-hash verified) means the GPU host does not need DB credentials.
Credentials and API keys are supplied only through environment variables (`REGULUS_MODEL_API_KEY`) and are never
recorded.

**Runtime and cost:** unknown until rung 0/1 are timed on the chosen GPU. No figure is given here.

## Next stage

**Model Ladder Evaluation: not started.** It needs approval and a GPU host.
