# Stage 12 LoRA adapter (full run)

Base model: `Qwen/Qwen3-0.6B` | method: LoRA r=16 alpha=32 dropout=0.05 on q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj

Dataset: Stage 11 `v2` sha256 `656d69b284db62bf945ffd100a4f52b36a1652b06d43b03239e7facba8c4a71b` (train/validation/test 7958/1058/947); test split never read.

Run: 90 optimizer steps (720 examples, 0.0928 epochs) on cpu (float32) in 359.5 min; validation loss base 1.0956313610076904 -> selected checkpoint 0.07227404415607452 (best 0.07227404415607452, checkpoint-90).

Files: `adapter/` (PEFT adapter weights + config), `tokenizer/`, `training_config.yaml`, `training_metrics.json` (log history), `training_summary.json`, `metadata.json`, `dataset_manifest.json` (copy of the Stage 11 manifest), `inference_check.json`, `checkpoints/`.

Load: `from regulus.finetune import load_adapter_model` or `python scripts/evaluate_stage12.py`.
