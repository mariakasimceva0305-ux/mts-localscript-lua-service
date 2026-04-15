# LocalScript: подсказки по запуску (первый / повторный), без изменения архитектуры.
# Запуск: powershell -ExecutionPolicy Bypass -File .\scripts\compose_start_helper.ps1
# Старт стека: добавьте -Start   (выполнит docker compose up -d)

param([switch]$Start)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host @"

=== LocalScript — операционный путь ===

Имя проекта Docker Compose: localscript (см. docker-compose.yml и COMPOSE_PROJECT_NAME в .env.example).
Volumes моделей: localscript_ollama_data — общие для любой папки с кодом, пока не меняете имя проекта.

--- Первый запуск (долго: образы, сборка api, pull моделей) ---
  cp .env.example .env
  docker compose up --build
  # Windows / нестабильный pull образа ollama:
  # powershell -ExecutionPolicy Bypass -File .\scripts\compose_up_retry.ps1

--- Повторный запуск (модели уже в volume — ollama-pull почти не качает) ---
  docker compose up -d
  # или с пересборкой только при смене Dockerfile/зависимостей api:
  docker compose up -d --build

--- Только перезапуск API после смены кода Python ---
  docker compose up -d --build api

--- Полная пересборка api (редко) ---
  docker compose build --no-cache api
  docker compose up -d api

--- ОПАСНО: удаляет volumes с моделями и индексами ---
  docker compose down -v
 (-v удаляет именованные volumes проекта; следующий up снова скачает модели)

--- Диагностика ---
  powershell -ExecutionPolicy Bypass -File .\scripts\compose_diagnostics.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\check_ollama_models.ps1

Подробнее: docs/jury/MEMORY_AND_RUNTIME_CHECKS.md, README.md (раздел операционного запуска).

"@ -ForegroundColor Cyan

if ($Start) {
    Write-Host "Запуск: docker compose up -d" -ForegroundColor Yellow
    docker compose up -d
}
