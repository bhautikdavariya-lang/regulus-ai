#!/bin/zsh
# NEW configuration: Qwen3-4B-Instruct-2507 MLX 4-bit, answer-first format, section promotion + picker (defaults).
cd "/Users/sensussoftsoftware/Desktop/Prachi Patel/Regulus AI.nosync"
set -a; source /Users/sensussoftsoftware/regulus_eval_runs/q17_feasibility/qwen3_4b_2507_mlx_4bit.env; set +a
exec .venv/bin/python scripts/run_cosmetics_eval.py --selection $1 --out $2
