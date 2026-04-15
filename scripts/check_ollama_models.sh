#!/usr/bin/env bash
# Проверка наличия основных моделей в демоне Ollama.
# Запуск из корня: bash scripts/check_ollama_models.sh

set -euo pipefail
PRIMARY="${MODEL_NAME:-qwen2.5-coder:7b}"
FALLBACK="${FALLBACK_MODEL:-deepseek-coder:6.7b}"

echo "Expected tags: $PRIMARY , $FALLBACK"
echo "COMPOSE_PROJECT_NAME: ${COMPOSE_PROJECT_NAME:-<unset>}"

if ! docker ps -q -f name=^ollama$ | grep -q .; then
  echo "error: ollama container not running" >&2
  exit 1
fi

out=$(docker exec ollama ollama list 2>&1 || true)
echo "$out"

if ! echo "$out" | grep -qF "${PRIMARY%%:*}"; then
  echo "warning: primary model family may be missing: $PRIMARY" >&2
  exit 2
fi
if ! echo "$out" | grep -q "deepseek-coder"; then
  echo "warning: fallback may be missing: $FALLBACK" >&2
  exit 2
fi

echo "OK: expected model families present in ollama list."
