# Скачивает все зависимости в api/wheels — затем Docker может собраться без HTTPS к PyPI.
# Запуск из корня репозитория:
#   powershell -ExecutionPolicy Bypass -File scripts\download_wheels.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$req = Join-Path $root "api\requirements.txt"
$out = Join-Path $root "api\wheels"

if (-not (Test-Path $req)) {
    Write-Error "Не найден $req"
}

New-Item -ItemType Directory -Force -Path $out | Out-Null

$py = $null
foreach ($c in @("py", "python3", "python")) {
    try {
        $ver = & $c -c "import sys; print(sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
    } catch { }
}
if (-not $py) {
    Write-Error "Нужен Python 3.11+ в PATH (py / python). Установите с python.org."
}

Write-Host "Используется: $py"
Write-Host "Качаем пакеты для Linux x86_64 + CPython 3.11 (как в образе python:3.11-slim)..."
& $py -m pip install --upgrade pip
# Колёса manylinux ставятся в контейнер; с Windows-хоста без --platform часто скачиваются win_amd64.
& $py -m pip download -r $req -d $out `
    --python-version 311 `
    --platform manylinux_2_17_x86_64 `
    --implementation cp `
    --abi cp311 `
    --only-binary=:all: 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "manylinux/only-binary не удался — пробуем без привязки к платформе (нужны py3-none-any / sdist)..."
    & $py -m pip download -r $req -d $out --python-version 311
}

Write-Host "Готово. Файлы в $out — запустите: docker compose build"
