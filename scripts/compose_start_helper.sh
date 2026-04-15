#!/usr/bin/env bash
# LocalScript: first-run vs repeat-run hints (no architecture changes).
# Usage: bash scripts/compose_start_helper.sh
#        bash scripts/compose_start_helper.sh --start   # runs docker compose up -d

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cat <<'EOF'
=== LocalScript — operational quick path ===

Compose project name: localscript (see docker-compose.yml and COMPOSE_PROJECT_NAME in .env.example).
Model volume: localscript_ollama_data — stable across folder renames if project name unchanged.

--- First run (slow: images, api build, model pull) ---
  cp .env.example .env
  docker compose up --build

--- Repeat run (models in volume; ollama-pull mostly no-op) ---
  docker compose up -d
  # rebuild api only when Dockerfile/deps changed:
  docker compose up -d --build

--- Restart API after Python changes ---
  docker compose up -d --build api

--- DANGER: deletes volumes (models, whoosh) ---
  docker compose down -v

--- Diagnostics ---
  bash scripts/compose_diagnostics.sh
  bash scripts/check_ollama_models.sh

Details: docs/jury/MEMORY_AND_RUNTIME_CHECKS.md
EOF

if [[ "${1:-}" == "--start" ]]; then
  echo "Running: docker compose up -d"
  docker compose up -d
fi
