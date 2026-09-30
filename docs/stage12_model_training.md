# Stage 12: First Working Qwen3-0.6B LoRA Fine-Tune

The first end-to-end fine-tuning pipeline for Regulus: the Stage 11 dataset
is loaded unchanged, rendered through the existing `to_messages()` chat
format, trained with LoRA on CPU, saved as a reloadable adapter, and
evaluated through the unchanged Stage 7 RAG pipeline.

The adapter works. It loads, generates, and runs inside the existing
retrieval pipeline. Its measured answer quality on the `baseline_v1`
benchmark is **lower** than the un-finetuned model in the same pipeline, and
it lost refusal behaviour on fictitious identifiers. Those numbers are
reported in full below; Stage 12 was not permitted to tune against them and
did not.

Code: `src/regulus/finetune/` (`config`, `data`, `lora`, `adapter`, `train`).
Scripts: `scripts/train_model.py`, `scripts/evaluate_stage12.py`.
Config: `configs/model_training.yaml`. Tests: `tests/test_finetune.py` (13),
`tests/test_finetune_slow.py` (2). Output: `models/qwen3-0.6b-lora/stage12_v1/`.

---

## 1. Model

| | |
|---|---|
| Base model | `Qwen/Qwen3-0.6B`, float32, CPU |
| Fine-tuning method | LoRA (PEFT 0.21.0), no quantisation, no full-parameter training |
| Base parameters | 596,049,920 |
| Total parameters with adapter | 606,142,464 |
| Trainable parameters | **10,092,544 (1.665 %)** |
| Base parameters frozen | yes, verified (every non-`lora_` parameter has `requires_grad = False`) |
| LoRA configuration | r = 16, alpha = 32, dropout = 0.05, bias = none, task = CAUSAL_LM |
| Target modules | `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj` |
| Adapter size on disk | 38.5 MB (`adapter_model.safetensors`) |

Target modules were not guessed. `regulus.finetune.lora.verify_target_modules`
walks the loaded model and counts `torch.nn.Linear` leaves by name, raising
`LoraTargetError` listing the available names if any requested target is
absent. On Qwen3-0.6B each of the seven targets resolves to 28 modules, one
per layer. `lm_head` exists but was deliberately not targeted.

## 2. Dataset

The Stage 11 artifact was used exactly as produced. Nothing was regenerated.

| | |
|---|---|
| Train / validation / test | 7,566 / 962 / 917 |
| Dataset SHA-256 | `bee32e320fc5c5072b040efc5b5a1caf707bce09c96affd05586a0f039e77a54` |
| Seed | 42 |
| eCFR snapshot behind the data | 2026-09-03 |

`regulus.finetune.data.verify_dataset` runs before anything is loaded and
refuses to train unless all of the following hold: each split file exists,
each file's SHA-256 matches `manifest_v1.json`, each line count matches both
the manifest and the config, and the combined hash matches the manifest and
the configured `expected_hash`. Any mismatch raises `DatasetIdentityError`
and the script exits with code 3 rather than training on different data.

**The test split was never opened.** It is hashed for identity verification
and otherwise untouched.

### Sequence length

Each example is rendered with `to_messages()` (the Stage 6 RAG system prompt,
a user turn containing the SOURCE blocks and the question, and the assistant
answer) and tokenised with Qwen's own chat template. The prompt is masked
with `-100`; only the assistant turn contributes to the loss.

| | Train | Validation subset |
|---|---|---|
| Max token length observed | 2,712 | 1,171 |
| Median | 558 | 462 |
| 95th percentile | 1,198 | 897 |
| Answer tokens, mean | 122.2 | 92.8 |
| **Selected max_seq_length** | **1,280** | 1,280 |
| Skipped as over-length | **260 of 7,566 (3.4 %)** | 0 of 64 |
| Truncated | **0** | 0 |

The policy is `skip`, not `truncate`: an over-length example is dropped whole
rather than cut mid-answer, which would teach the model to stop early. The
260 skipped examples are reported here and in `training_summary.json` rather
than being silently dropped.

## 3. Training

Hardware detected and reported at run time, no CUDA assumptions:

| | |
|---|---|
| Device / dtype | CPU / float32 (no GPU present) |
| CPU threads / RAM | 4 / 7.91 GB total, 2.53 GB free at start |
| Platform | Windows 10, Python 3.11.9 |
| torch / transformers / peft / accelerate | 2.14.0+cpu / 5.17.0 / 0.21.0 / 1.15.0 |

Configuration (`configs/model_training.yaml`):

| | |
|---|---|
| Learning rate / scheduler / warmup | 2e-4 / cosine / 4 steps |
| Batch size x gradient accumulation | 1 x 8 (effective batch 8) |
| Max steps | 40 (**320 examples, 0.044 epochs**) |
| Weight decay | 0.0 |
| Gradient checkpointing | enabled on the PEFT model |
| Eval / save strategy | every 20 steps, `save_total_limit` 2, best by `eval_loss` |
| Validation subset for selection | 64 examples, hash-ordered, seed 42 |
| Seed | 42 (Python, NumPy, torch, Trainer, data order) |

The step budget is a hardware limit, not a tuned choice: a CPU training step
costs about 5 minutes and a 64-example validation pass about 10 minutes, so
one full epoch over 7,306 examples would take roughly 40 days. The run was
sized to fit an afternoon.

### Results

| | Value |
|---|---|
| Steps completed | 40 of 40 |
| Examples seen | 320 |
| Epochs | 0.0438 |
| Wall-clock training | 204.0 min (12,239 s), 214.4 min including validation passes |
| Final training loss | 0.1411 |
| Mean training loss | 0.2772 |

Validation loss on the 64-example subset:

| Checkpoint | eval_loss |
|---|---|
| Base model, before training | 1.2076 |
| checkpoint-20 | 0.3765 |
| **checkpoint-40 (selected)** | **0.3014** |

Training loss by logged step: 1.048, 0.938, 0.532, 0.301, 0.393, 0.318,
0.250, 0.451, 0.218, 0.175, 0.181, 0.283, 0.199, 0.351, 0.169, 0.139, 0.111,
0.123, 0.104, 0.112, 0.141.

Validation loss was still falling when the budget ran out, so the run is
under-trained rather than over-trained. `checkpoint-40` was selected by
validation loss alone. The test split played no part in selection.

### Operational note on how the run ended

The Trainer completed all 40 steps, wrote `checkpoint-40` and logged
`train_runtime = 12239 s`. The process was then stopped deliberately during a
redundant second validation pass, at the user's request, to free the machine.
`scripts/train_model.py --finalize` reconstructs the run from
`trainer_state.json`: it selects the best checkpoint, copies its adapter,
writes all metadata, and runs the reload and inference check. No training
happens in that path. This is recorded in `training_summary.json` as
`mode: "full (finalized from checkpoints after a manual stop following the
last checkpoint)"`. The redundant pass has since been removed for future
runs: when the best checkpoint is the last evaluated one, its logged
`eval_loss` is reused instead of recomputed.

## 4. Inference check

The saved adapter is reloaded onto a freshly loaded base model and merged,
then asked one question. `adapter_config.json` records
`base_model_name_or_path`, and `attach_saved_adapter` refuses to attach an
adapter whose recorded base model differs from the loaded one.

```
Input question:   What does paragraph (b)(1)(vi) of 21 CFR 112.45 state?

Retrieved context (SOURCE 1, eCFR, 21 CFR 112.45(b)(1)(vi)):
  "(vi) Taking an alternative mitigation measure, provided that you satisfy
   the requirements of § 112.12."

Model output:
  "21 CFR 112.45(b)(1)(vi) [1], in the section on agricultural water,
   provides: Taking an alternative mitigation measure, provided that you
   satisfy the requirements of § 112.12."
```

347 prompt tokens, 51 generated tokens, 19.2 s. Saved to
`inference_check.json`. This verifies that the adapter loads and generates;
it does not establish that the answer is correct. The probe example comes
from the validation subset used for checkpoint selection, so it is not a
held-out demonstration.

## 5. Evaluation

Run through the existing Stage 7 RAG pipeline with no changes: same
`baseline_v1` benchmark, same `LexicalRetriever` with the Stage 7 OR
fallback, same prompt, same greedy decoding at 128 new tokens, same seed 42.
The only difference between the two runs is the generator.

Retrieval was byte-identical across the runs, which makes the comparison
clean: both show 930.30 average input tokens, 3,069.30 average context
characters, 2.81 sources per question, 9 fallback activations and 1
deterministic no-context refusal.

**Baseline used:** the saved Stage 7 result
`rag-stage7_20260915_180408_cd883ba7.json`, per the Stage 12 instruction to
reuse existing Stage 7/9/10 results rather than recreate them. A 3-question
control run with the base model through the modified script reproduced the
Stage 7 answers **byte for byte**, confirming the `--adapter` option did not
disturb the existing path. The only config field that differs between the
runs is `exclude_contextual_only`, added in Stage 9, which the lexical
retriever never triggers.

### Objective measurements

| | Raw model, no RAG | Stage 7 RAG (base model) | **Stage 12 RAG (LoRA)** |
|---|---|---|---|
| Completed / failed | 27 / 0 | 27 / 0 | 27 / 0 |
| Model calls / no-context refusals | 27 / n/a | 26 / 1 | 26 / 1 |
| Avg latency | 42.32 s | 32.24 s | 41.30 s |
| Avg input tokens | 25.74 | 930.30 | 930.30 |
| Avg output tokens | 117.41 | 60.44 | 78.07 |
| Median / max output tokens | | 68 / 128 | 91 / 128 |
| Answers hitting the 128-token cap | | 2 | 5 |
| Answers using `[n]` citation markers | | 1 | **14** |
| Answers containing a refusal phrase | | 17 | **5** |
| Answers with degenerate repetition | | 0 | **2** |
| Answers changed against Stage 7 | | | 25 of 27 |

### Reviewer scores (0-2, assistant judgments, not objective accuracy)

Scored against each question's `evaluation_notes`, by the same method and
scale used in Stages 6 to 10. These are reviewer opinions and should be
confirmed by a human reviewer.

| Category (n) | Raw model | Stage 7 RAG | **Stage 12 LoRA** |
|---|---|---|---|
| General knowledge (5) | 1.80 | 1.00 | **0.40** |
| Regulatory concepts (5) | 0.60 | 1.00 | **0.80** |
| FDA/eCFR-oriented (7) | 0.71 | 0.86 | **0.57** |
| Reasoning (5) | 1.40 | 1.00 | **0.20** |
| Unknown/hallucination (5) | 0.00 | 1.80 | **1.00** |
| **Mean, all 27** | **0.89** | **1.11** | **0.59** |

Improved: 1 question. Regressed: 13. Unchanged score: 13.

### What the fine-tune taught, and what it cost

**Learned.** Citation markers went from 1 answer to 14 of 27. The trained
answer shape, `<citation> [n] ... provides: <verbatim text>`, is reproduced
reliably, and the model now names guidance documents with their docket and
status. The one improvement, the New Drug Application question, scored 2
against Stage 7's 1.

**Lost: refusal on fictitious identifiers.** This is the most consequential
finding. The base model in the Stage 7 pipeline scored 1.80 on the
hallucination category; the fine-tuned model scores 1.00, and two of the five
answers are fabrications:

- **21 CFR 314.999** (nonexistent section). The model answered
  `"21 CFR 314.999 [1], in the section on sanitation requirements, provides:
  You must conduct all manufacturing operations in accordance with adequate
  sanitation principles."` The sentence is real text, but it came from
  21 CFR 111.360 or 1.360(a) in the retrieved context and was re-attributed
  to the fictitious section. Stage 7 refused. Score 2 to 0.
- **21 CFR Part 1400** (nonexistent part). The model invented the title
  `"Drug Labeling"` for it and then degenerated into a runaway citation list
  `[1], [2], ... [31` until the token cap. Stage 7 refused. Score 2 to 0.

The mechanism is visible in the numbers: refusal phrases fell from 17 answers
to 5. Stage 11 taught the model to apply a citation template to retrieved
text, and it now applies that template to whatever retrieval returned, even
when the requested identifier does not exist. The 500 abstention examples
(5.3 % of the dataset) did not counteract this, and the two remaining
identifier defences are the retrieval layer's, not the model's: the fake
docket was caught because retrieval returned nothing at all, and the fiscal
year 2031 fee question was refused correctly.

**Lost: general knowledge and reasoning.** General knowledge fell to 0.40 and
reasoning to 0.20. Two general-knowledge questions now receive a bare refusal
where the base model gave a usable partial definition, and several reasoning
answers quote an irrelevant retrieved passage instead of answering. Three
answers contain fabricated citations to provisions that do not exist
(`21 CFR Part 311`, `21 CFR 311.101`), and one mislabels an eCFR regulation
as non-binding guidance.

These are the expected failure modes of 320 training examples at a high
learning rate on templated targets: strong format acquisition, degraded
general ability. Stage 12 deliberately did not react to them.

## 6. Safety

| | |
|---|---|
| Database writes | **0** |
| Evaluation dataset modifications | **0** |
| Training dataset modifications | **0** |
| Benchmark modifications | **0** |
| Model weights modified | **0** (base weights frozen; only the adapter was written) |
| External FDA/eCFR downloads | **0** |

Training never connects to the database. `tests/test_finetune.py` asserts
that no module under `src/regulus/finetune/` mentions `regulus.retrieval` or
`psycopg`. Evaluation uses the database read-only through the Stage 5 layer.

The database was checked after all Stage 12 work: `default_transaction_read_only`
and `transaction_read_only` both `on`, 0 writes and 85,298 reads recorded
since the server started, 65,341 eCFR records with 65,264 embeddings, 68,669
guidance chunks with 68,669 embeddings, 241 indexes and 322 relations, all
matching the Stage 11 values. The cumulative write counter reads 0 rather
than the 293,083 recorded at the end of Stage 11 because the PostgreSQL
server restarted on 2026-09-21 at 09:25, which resets `pg_stat_user_tables`;
the counter covers only the current server session.

Protected files, SHA-256 recorded before training and re-checked after
(training aborts if they change):

| File | SHA-256 prefix |
|---|---|
| `baseline_v1.jsonl` | `28363d860c50d64f` |
| `retrieval_v1.jsonl` | `63f0a0863cfbc42e` |
| `retrieval_v2.jsonl` | `db73c6fa7bb934f3` |
| `training_v1.jsonl` | `b424d69cc435429b` |
| `validation_v1.jsonl` | `5927d767187703f7` |
| `test_v1.jsonl` | `d8140c0b1c935352` |

All Stage 7, 9 and 10 result files retain their original dates and contents.
Stage 12 results were written only to `data/evaluation/results/stage12_v1/`.

## 7. Reproducibility

Seed 42 is set for Python, NumPy, torch, the Trainer and the data order.
Recorded in `metadata.json` and `training_summary.json`: the dataset hash and
per-split hashes, the base model id, the full LoRA and training
configuration, the hardware, and the exact versions of Python, torch,
transformers, peft, accelerate, safetensors, tokenizers and NumPy.

Known nondeterminism: CPU floating-point reduction order in PyTorch is not
guaranteed bit-identical across runs, and `full_determinism` was not enabled
because it slows CPU training further. The configuration reproduces exactly;
the resulting weights may differ in the last bits. Evaluation is greedy and
reproduced byte-identical answers in the control run.

## 8. Output structure

```
models/qwen3-0.6b-lora/stage12_v1/
  adapter/              adapter_config.json, adapter_model.safetensors (38.5 MB), README.md
  tokenizer/            tokenizer + chat template as used in training
  checkpoints/          checkpoint-20, checkpoint-40 (weights, optimizer, scheduler, trainer state)
  training_config.yaml  the full resolved Stage 12 configuration
  training_metrics.json complete log history, base and final evaluation
  training_summary.json hardware, dependencies, tokenisation stats, losses, LoRA info
  metadata.json         machine-readable summary (stage, model, dataset hash, LoRA, training, checkpoint, device, timestamp)
  dataset_manifest.json verbatim copy of the Stage 11 manifest
  inference_check.json  the reload-and-generate artifact
  README.md             human-readable summary
  train.log             the run log
```

## 9. Dependencies

One package added: **`peft==0.21.0`**, installed with `--no-deps` because
every one of its requirements (torch, transformers, accelerate, safetensors,
numpy, pyyaml, tqdm, psutil, huggingface_hub) was already pinned in
`requirements.txt` at a compatible version. `pip check` reports no broken
requirements. No dependency was upgraded or removed. TRL was not installed:
the Trainer in transformers 5.17.0 provides supervised fine-tuning directly
with a custom collator, and adding TRL would have risked the pinned
transformers version.

Compatibility note: transformers 5.17.0 renamed `evaluation_strategy` to
`eval_strategy` and dropped `warmup_ratio` in favour of `warmup_steps`. Both
were verified against the installed signature before use rather than assumed.

## 10. Tests

| Suite | Result |
|---|---|
| Fast (no model, no database, no GPU) | **272 passed** |
| Slow (real Qwen3-0.6B, `-m slow`) | **6 passed** |
| Integration (read-only database, `-m integration`) | **21 passed** |
| Failures | **0** |

Stage 12 adds 13 fast tests and 2 slow tests covering: configuration loading
and rejection of invalid configuration; dataset identity verification
including tamper and count mismatch; deterministic evaluation subsets;
`to_messages()` output and prompt masking; tokenisation statistics,
skip and truncate behaviour, and padded collation; target-module verification
and its failure mode; LoRA attachment, trainable-parameter count and base
freezing; that one optimisation step changes only LoRA weights; adapter save,
reload and merge equivalence to the unmerged model; refusal to attach an
adapter trained on a different base model; the inference-check artifact; and
that the finetune package never touches evaluation datasets or the database.

## 11. Limitations

- **320 training examples, 0.044 epochs.** The model saw 4 % of one pass over
  the data. Validation loss was still falling. Every quality number here
  describes a deliberately under-trained adapter.
- **The adapter is not usable as a default.** On this benchmark it is worse
  than the un-finetuned model in the same pipeline, and it fabricates content
  for nonexistent identifiers. It remains opt-in via `--adapter`; no default
  path loads it.
- **Reviewer scores are assistant judgments** on 27 questions. Differences
  below roughly 0.1 are within their noise, but the 0.52 gap and the two
  fabrications are well outside it.
- **Checkpoint selection used 64 of 962 validation examples**, chosen for
  cost. A full validation pass costs about 10 minutes per evaluation on this
  CPU.
- **3.4 % of training examples were skipped** as longer than 1,280 tokens,
  which biases training slightly toward shorter contexts.
- **CPU-only.** A GPU would make a full epoch and a proper hyperparameter
  choice practical; the code detects and uses CUDA if present but was never
  exercised on one.
- The inference-check probe is from the validation subset used for selection,
  not a held-out example.

## 12. Recommended next stage

Stage 13 should decide what to change based on these measurements, not
extend this run blindly. The evidence points at three separate questions:

1. **Refusal behaviour is the blocking problem.** The fabrications on
   314.999 and Part 1400 are worse than anything the base model did. Options
   include raising the abstention share well above 5 %, adding training
   examples where the retrieved context is real but does not match the
   requested identifier, or moving identifier verification into the pipeline
   so the model is never asked to answer about an unverified identifier.
2. **Training volume.** A meaningful epoch needs a GPU or a much smaller
   model; the current budget cannot distinguish "LoRA does not help" from
   "40 steps do not help".
3. **The dataset's templated answers** taught format but not judgment.
   Whether to add paraphrased or human-reviewed targets is a dataset
   question, to be decided before another training run.

Nothing in this stage was tuned against the benchmark, and the adapter should
not be promoted to default until the refusal regression is resolved.
