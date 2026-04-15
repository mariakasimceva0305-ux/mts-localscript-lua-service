#Requires -Version 5.1
<#
.SYNOPSIS
  Перенос проекта GitLab в другой namespace (группу) через API — эквивалент Settings → Transfer project.

  Нужны права Owner у текущего пользователя на проект и права на создание проектов в целевой группе.

  Перед запуском в GitLab: User Settings → Access Tokens — scope: api (или project + read_api по политике инстанса).

.EXAMPLE
  $env:GITLAB_TOKEN = "glpat-xxxxxxxx"
  $env:GITLAB_HOST = "https://git.truetecharena.ru"
  $env:GITLAB_SOURCE_PATH = "mariakasimceva/mts-localscript-lua-service"
  $env:GITLAB_TARGET_NAMESPACE = "tta/true-tech-hack2026-localscript/dsc"   # родительский namespace; имя репо задаётся отдельно при создании/переименовании
  powershell -ExecutionPolicy Bypass -File .\scripts\transfer_gitlab_to_group.ps1
#>

$ErrorActionPreference = "Stop"

$hostUrl = $(if ($env:GITLAB_HOST) { $env:GITLAB_HOST } else { "https://git.truetecharena.ru" }).TrimEnd("/")
$token = $env:GITLAB_TOKEN
$sourcePath = $(if ($env:GITLAB_SOURCE_PATH) { $env:GITLAB_SOURCE_PATH } else { "mariakasimceva/mts-localscript-lua-service" })
$targetNs = $env:GITLAB_TARGET_NAMESPACE

if ([string]::IsNullOrWhiteSpace($token)) {
  Write-Error "Задайте GITLAB_TOKEN (Personal Access Token с правом api)."
}
if ([string]::IsNullOrWhiteSpace($targetNs)) {
  Write-Error "Задайте GITLAB_TARGET_NAMESPACE — путь группы на $hostUrl (например my-team), куда переносим проект."
}

$encPath = [uri]::EscapeDataString($sourcePath)
$headers = @{
  "PRIVATE-TOKEN" = $token
}

function Invoke-GitLabGet([string]$Uri) {
  $r = Invoke-RestMethod -Uri $Uri -Headers $headers -Method Get
  return $r
}

# 1) ID проекта
$projUrl = "$hostUrl/api/v4/projects/$encPath"
Write-Host "GET project: $projUrl"
$project = Invoke-GitLabGet -Uri $projUrl
$projectId = $project.id
Write-Host "  project_id = $projectId  path_with_namespace = $($project.path_with_namespace)"

# 2) ID целевого namespace (группа или пользователь)
$search = [uri]::EscapeDataString($targetNs)
$nsUrl = "$hostUrl/api/v4/namespaces?search=$search"
Write-Host "GET namespaces: $nsUrl"
$list = Invoke-GitLabGet -Uri $nsUrl
$match = $list | Where-Object { $_.path -eq $targetNs -or $_.full_path -eq $targetNs } | Select-Object -First 1
if (-not $match) {
  Write-Host "Доступные совпадения по search:" 
  $list | ForEach-Object { Write-Host "  id=$($_.id) path=$($_.path) full_path=$($_.full_path)" }
  Write-Error "Не найден namespace с path/full_path равным '$targetNs'. Уточните GITLAB_TARGET_NAMESPACE."
}
$namespaceId = $match.id
Write-Host "  target namespace_id = $namespaceId  full_path = $($match.full_path)"

# 3) Transfer
$transferUrl = "$hostUrl/api/v4/projects/$projectId/transfer"
$body = @{ namespace_id = $namespaceId } | ConvertTo-Json
Write-Host "POST transfer: $transferUrl"
$response = Invoke-RestMethod -Uri $transferUrl -Headers $headers -Method Post -Body $body -ContentType "application/json"

$newPath = $response.path_with_namespace
Write-Host ""
Write-Host "OK: проект перенесён в $newPath"
Write-Host "Обновите remote:"
Write-Host "  git remote set-url gitlab $hostUrl/$newPath.git"
