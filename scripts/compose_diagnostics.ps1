# LocalScript: быстрая диагностика Docker Compose, volumes и моделей Ollama.
# Запуск из корня репозитория: powershell -ExecutionPolicy Bypass -File .\scripts\compose_diagnostics.ps1

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "=== LocalScript compose diagnostics ===" -ForegroundColor Cyan
Write-Host "Repo root: $Root"

if (-not (Test-Path ".\docker-compose.yml")) {
    Write-Error "docker-compose.yml не найден. Запускайте скрипт из корня репозитория или не перемещайте scripts/."
    exit 1
}

$composeName = $env:COMPOSE_PROJECT_NAME
if ([string]::IsNullOrWhiteSpace($composeName)) {
    $composeName = "(не задан; Compose возьмёт имя из docker-compose.yml, ожидается localscript)"
}
Write-Host "COMPOSE_PROJECT_NAME (env): $composeName"

Write-Host "`n--- docker version (кратко) ---"
docker version 2>&1 | Select-Object -First 8

Write-Host "`n--- docker compose ls ---"
docker compose ls 2>&1

Write-Host "`n--- docker compose ps ---"
docker compose ps 2>&1

Write-Host "`n--- volumes (localscript / ollama) ---"
docker volume ls 2>&1 | Select-String -Pattern "localscript|ollama"

Write-Host "`n--- API /ready (хост) ---"
try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/ready" -TimeoutSec 15
    $r | ConvertTo-Json -Compress
} catch {
    Write-Warning "API недоступен или не готов: $_"
}

Write-Host "`n--- ollama list (внутри контейнера ollama) ---"
$ollamaId = docker ps -q -f "name=^ollama$" 2>$null
if ($ollamaId) {
    docker exec ollama ollama list 2>&1
} else {
    Write-Warning "Контейнер ollama не запущен (имя ^ollama$)."
}

Write-Host "`n--- последние строки ollama-pull ---"
docker compose logs --tail 30 ollama-pull 2>&1

Write-Host "`n=== Конец. Полный runbook: docs/jury/MEMORY_AND_RUNTIME_CHECKS.md ===" -ForegroundColor Cyan
