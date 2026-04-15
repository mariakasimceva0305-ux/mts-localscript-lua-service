param(
    [int]$MaxPullAttempts = 12,
    [int]$InitialDelaySeconds = 12,
    [int]$MaxDelaySeconds = 120
)

$ErrorActionPreference = "Stop"

if ($MaxPullAttempts -lt 1) {
    throw "MaxPullAttempts должен быть >= 1"
}
if ($InitialDelaySeconds -lt 1) {
    throw "InitialDelaySeconds должен быть >= 1"
}
if ($MaxDelaySeconds -lt $InitialDelaySeconds) {
    throw "MaxDelaySeconds должен быть >= InitialDelaySeconds"
}

function Invoke-ComposePullWithRetry {
    param(
        [string]$ServiceName
    )

    for ($attempt = 1; $attempt -le $MaxPullAttempts; $attempt++) {
        Write-Host "[compose-retry] Pull $ServiceName (attempt $attempt/$MaxPullAttempts)..."
        docker compose pull $ServiceName
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[compose-retry] Pull ${ServiceName}: OK"
            return
        }

        if ($attempt -lt $MaxPullAttempts) {
            # После short read/EOF локальные частичные слои иногда мешают следующей попытке.
            # Удаляем только тег целевого образа; это безопасно и не трогает другие образы.
            docker image rm "ollama/ollama:latest" 2>$null | Out-Null

            $delay = [Math]::Min($MaxDelaySeconds, $InitialDelaySeconds * [Math]::Pow(2, ($attempt - 1)))
            $delay = [int][Math]::Max(1, [Math]::Round($delay))
            Write-Warning "[compose-retry] Pull $ServiceName failed (exit $LASTEXITCODE). Retry in $delay sec..."
            Start-Sleep -Seconds $delay
        }
    }

    throw "[compose-retry] Pull $ServiceName failed after $MaxPullAttempts attempts."
}

Write-Host "[compose-retry] Starting resilient Docker Compose bootstrap..."
Invoke-ComposePullWithRetry -ServiceName "ollama"

Write-Host "[compose-retry] Running docker compose up --build --pull never"
docker compose up --build --pull never
exit $LASTEXITCODE
