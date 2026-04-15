# Проверка наличия основных моделей в текущем демоне Ollama (volume проекта localscript).
# Запуск: powershell -ExecutionPolicy Bypass -File .\scripts\check_ollama_models.ps1

$Primary = if ($env:MODEL_NAME) { $env:MODEL_NAME } else { "qwen2.5-coder:7b" }
$Fallback = if ($env:FALLBACK_MODEL) { $env:FALLBACK_MODEL } else { "deepseek-coder:6.7b" }

Write-Host "Ожидаемые теги: $Primary , $Fallback" -ForegroundColor Cyan
$proj = $env:COMPOSE_PROJECT_NAME
if ([string]::IsNullOrWhiteSpace($proj)) { $proj = "<unset>" }
Write-Host "Имя compose-проекта (env): $proj"

$ollamaRunning = docker ps -q -f "name=^ollama$"
if (-not $ollamaRunning) {
    Write-Warning "Контейнер ollama не запущен. Сначала: docker compose up -d ollama (или полный стек)."
    exit 1
}

$output = docker exec ollama ollama list 2>&1 | Out-String
Write-Host $output

$missing = @()
if ($output -notmatch [regex]::Escape($Primary.Split(':')[0])) {
    $missing += $Primary
}
# deepseek tag may appear as deepseek-coder:6.7b
if ($output -notmatch "deepseek-coder") {
    $missing += $Fallback
}

if ($missing.Count -gt 0) {
    Write-Warning "Возможно отсутствуют модели: $($missing -join ', '). Проверьте логи: docker compose logs ollama-pull"
 exit 2
}

Write-Host "OK: в списке есть ожидаемые семейства моделей." -ForegroundColor Green
