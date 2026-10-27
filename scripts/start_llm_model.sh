#!/bin/zsh
# Start the llm-model API (scripts/serve_llm_model.py) with Qwen3-4B-Instruct-2507 (MLX 4-bit) and the production
# pipeline. Every machine-specific value comes from configs/llm_model.env: copy configs/llm_model.env.example and fill
# it in. The model needs ~2.6 GB of free memory: close large apps first on an 8 GB Mac.
cd "$(dirname "$0")/.." || exit 1
PROFILE=${LLM_MODEL_PROFILE:-configs/llm_model.env}
if [ ! -f "$PROFILE" ]; then
  echo "missing $PROFILE: copy configs/llm_model.env.example to configs/llm_model.env and fill it in" >&2
  exit 1
fi
set -a; source "$PROFILE"; set +a
exec ./.venv/bin/python scripts/serve_llm_model.py --host "${LLM_MODEL_HOST:-127.0.0.1}" --port "${LLM_MODEL_PORT:-8100}" \
  ${LLM_MODEL_TLS_CERT:+--tls-cert "$LLM_MODEL_TLS_CERT"} ${LLM_MODEL_TLS_KEY:+--tls-key "$LLM_MODEL_TLS_KEY"} --offline "$@"
