#!/bin/zsh
# OLD configuration (production before 22 Oct): Qwen3-1.7B MLX 4-bit, restating format, no section promotion.
cd "/Users/sensussoftsoftware/Desktop/Prachi Patel/Regulus AI.nosync"
set -a; source /Users/sensussoftsoftware/regulus_eval_runs/q17_feasibility/qwen3_1.7b_mlx_4bit.env; set +a
export REGULUS_SECTION_PROMOTION=off REGULUS_ANSWER_STYLE=restate
exec .venv/bin/python scripts/run_cosmetics_eval.py --selection $1 --out $2
