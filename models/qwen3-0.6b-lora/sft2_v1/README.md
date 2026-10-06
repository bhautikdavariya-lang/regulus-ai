# Stage 12 LoRA adapter (full run)

Base model: `Qwen/Qwen3-0.6B` | method: LoRA r=16 alpha=32 dropout=0.05 on q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj

Dataset: Stage 11 `sft2-v2.0` sha256 `782c5740f6fd80d87ea388fbf33987376966b5bc4e661926010c101fb0e672ee` (train/validation/test 129/23/23); test split never read.

Run: 48 optimizer steps (384 examples, 3.0 epochs) on cpu (float32) in 112.0 min; validation loss base 1.768721342086792 -> selected checkpoint 1.2239422798156738 (best 1.2239422798156738, checkpoint-48).

Files: `adapter/` (PEFT adapter weights + config), `tokenizer/`, `training_config.yaml`, `training_metrics.json` (log history), `training_summary.json`, `metadata.json`, `dataset_manifest.json` (copy of the Stage 11 manifest), `inference_check.json`, `checkpoints/`.

Load: `from regulus.finetune import load_adapter_model` or `python scripts/evaluate_stage12.py`.
