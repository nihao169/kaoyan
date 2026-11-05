param([string]$Destination,[switch]$Release)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $Destination) { $Destination=Join-Path $projectRoot ('.runtime\backups-v2\'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')) }
$runtimeName=if ($Release) { 'services-v2-release' } else { 'services-v2' }
$manifestPath=Join-Path $projectRoot ('.runtime\'+$runtimeName+'.json')
$port=5183
$wasRunning=Test-Path -LiteralPath $manifestPath
if ($wasRunning -and $Release) { $port=[int](Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).frontend_port }
$otherRuntime=if ($Release) { 'services-v2' } else { 'services-v2-release' }
if (Test-Path -LiteralPath (Join-Path $projectRoot ('.runtime\'+$otherRuntime+'.json'))) {
    throw 'Stop the other V2 application first because DeepTutor is shared.'
}
$tutorWasRunning=(& docker inspect -f '{{.State.Running}}' zhixing-v2-deeptutor-1) -eq 'true'
if ($LASTEXITCODE -ne 0) { throw 'Cannot determine isolated DeepTutor state.' }
if ($wasRunning) { & (Join-Path $PSScriptRoot 'stop.ps1') -RuntimeName $runtimeName }
try {
    if ($tutorWasRunning) {
        & docker stop zhixing-v2-deeptutor-1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Cannot stop DeepTutor writers.' }
    }
    [string[]]$releaseFlag=@()
    if ($Release) { $releaseFlag+= '--release' }
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'snapshot-v2.py') create $Destination @releaseFlag
    if ($LASTEXITCODE -ne 0) { throw 'V2 backup failed; existing database was not overwritten.' }
} finally {
    if ($tutorWasRunning) { & docker start zhixing-v2-deeptutor-1 | Out-Null }
    if ($wasRunning -and $Release) { & (Join-Path $PSScriptRoot 'start-release-v2.ps1') -Port $port }
    elseif ($wasRunning) { & (Join-Path $PSScriptRoot 'start-v2.ps1') }
}
