# Stage 12 LoRA adapter (full (finalized from checkpoints after a manual stop following the last checkpoint) run)

Base model: `Qwen/Qwen3-0.6B` | method: LoRA r=16 alpha=32 dropout=0.05 on q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj

Dataset: Stage 11 `v1` sha256 `bee32e320fc5c5072b040efc5b5a1caf707bce09c96affd05586a0f039e77a54` (train/validation/test 7566/962/917); test split never read.

Run: 40 optimizer steps (320 examples, 0.0438 epochs) on cpu (float32) in 214.4 min; validation loss base 1.2076 -> selected checkpoint 0.3014103174209595 (best 0.3014103174209595, checkpoint-40).

Files: `adapter/` (PEFT adapter weights + config), `tokenizer/`, `training_config.yaml`, `training_metrics.json` (log history), `training_summary.json`, `metadata.json`, `dataset_manifest.json` (copy of the Stage 11 manifest), `inference_check.json`, `checkpoints/`.

Load: `from regulus.finetune import load_adapter_model` or `python scripts/evaluate_stage12.py`.
