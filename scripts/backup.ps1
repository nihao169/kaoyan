param([string]$Destination)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$manifestPath = Join-Path $projectRoot '.runtime\services.json'
$wasRunning = Test-Path -LiteralPath $manifestPath
if (-not $Destination) { $Destination = Join-Path $projectRoot ('.runtime\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')) }
if ($wasRunning) { & (Join-Path $PSScriptRoot 'stop.ps1') }
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'backend'
    $env:PYTHONUTF8 = '1'
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') -m app.backup create $Destination
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed. The live data was not overwritten.' }
} finally {
    if ($wasRunning) { & (Join-Path $PSScriptRoot 'start.ps1') }
}
