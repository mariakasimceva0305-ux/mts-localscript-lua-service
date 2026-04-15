#!/usr/bin/env bash
# LocalScript: быстрая диагностика Docker Compose, volumes и моделей Ollama.
# Запуск из корня репозитория:  bash scripts/compose_diagnostics.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== LocalScript compose diagnostics ==="
echo "Repo root: $ROOT"

if [[ ! -f docker-compose.yml ]]; then
  echo "error: docker-compose.yml not found; run from repo root" >&2
  exit 1
fi

echo "COMPOSE_PROJECT_NAME (env): ${COMPOSE_PROJECT_NAME:-<unset; expected localscript from compose name:>}"

echo ""
echo "--- docker version (short) ---"
docker version 2>&1 | head -n 6 || true

echo ""
echo "--- docker compose ls ---"
docker compose ls 2>&1 || true

echo ""
echo "--- docker compose ps ---"
docker compose ps 2>&1 || true

echo ""
echo "--- volumes (localscript / ollama) ---"
docker volume ls 2>&1 | grep -E 'localscript|ollama' || true

echo ""
echo "--- API /ready (host) ---"
if curl -sS -m 15 "http://127.0.0.1:8000/ready" 2>/dev/null; then
  echo ""
else
  echo "(unavailable or not ready)"
fi

echo ""
echo "--- ollama list (inside ollama container) ---"
if docker ps -q -f name=^ollama$ | grep -q .; then
  docker exec ollama ollama list 2>&1 || true
else
  echo "(ollama container not running)"
fi

echo ""
echo "--- last ollama-pull logs ---"
docker compose logs --tail 30 ollama-pull 2>&1 || true

echo ""
echo "=== Done. Runbook: docs/jury/MEMORY_AND_RUNTIME_CHECKS.md ==="
