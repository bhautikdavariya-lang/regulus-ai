#!/bin/zsh
# Start the Regulus UI with Qwen3-4B-Instruct-2507 (MLX 4-bit) and the production pipeline (scripts/serve_ui.py).
# The machine's paths (MLX interpreter, model snapshot, tokenizer cache) come from configs/ui.env: copy
# configs/ui.env.example and fill them in. Pipeline behaviour is the code's own defaults; the profile holds paths only.
# Open http://127.0.0.1:8000 when it prints "Serving". Stop with Ctrl+C. The model needs ~2.6 GB of free memory:
# close large apps first on an 8 GB Mac.
cd "$(dirname "$0")/.." || exit 1
PROFILE=${REGULUS_UI_PROFILE:-configs/ui.env}
if [ ! -f "$PROFILE" ]; then
  echo "missing $PROFILE: copy configs/ui.env.example to configs/ui.env and set the paths" >&2
  exit 1
fi
set -a; source "$PROFILE"; set +a
exec ./.venv/bin/python scripts/serve_ui.py --port "${REGULUS_UI_PORT:-8000}" --offline "$@"
