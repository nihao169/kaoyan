$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
$manifestPath = Join-Path $runtimeDir 'services.json'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$vitePath = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath $vitePath)) { throw 'Run scripts/init.ps1 first.' }
if (Test-Path -LiteralPath $manifestPath) {
    $previous = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $previous.services) {
        if (Get-Process -Id $entry.pid -ErrorAction SilentlyContinue) { throw 'A recorded service is running. Use scripts/status.ps1 or scripts/stop.ps1 first.' }
    }
}
foreach ($port in @(5173,8000)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is occupied. No existing process was stopped." }
}
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$env:PYTHONPATH = Join-Path $projectRoot 'backend'
$env:PYTHONUTF8 = '1'
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
}
$services = @()
$startedAt = [DateTime]::UtcNow.ToString('o')
try {
    $apiProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','app.main:app','--app-dir', ('"' + (Join-Path $projectRoot 'backend') + '"'),'--host','127.0.0.1','--port','8000') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'api.out.log') -RedirectStandardError (Join-Path $runtimeDir 'api.err.log') -PassThru
    $services += @{name='api';pid=$apiProcess.Id}
    $workerProcess = Start-Process -FilePath $pythonPath -ArgumentList @(('"' + (Join-Path $projectRoot 'scripts\run_worker.py') + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'worker.out.log') -RedirectStandardError (Join-Path $runtimeDir 'worker.err.log') -PassThru
    $services += @{name='worker';pid=$workerProcess.Id}
    $nodePath = (Get-Command node -ErrorAction Stop).Source
    $frontProcess = Start-Process -FilePath $nodePath -ArgumentList @(('"' + $vitePath + '"'),'--host','127.0.0.1','--port','5173','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.out.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.err.log') -PassThru
    $services += @{name='frontend';pid=$frontProcess.Id}
    @{root=$projectRoot;started_at=$startedAt;services=$services} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $ready = $false
    # Local embedding-model cold starts can exceed the old ~30 second window.
    $readyDeadline = [DateTime]::UtcNow.AddSeconds(180)
    while ([DateTime]::UtcNow -lt $readyDeadline) {
        foreach ($entry in $services) {
            if (-not (Get-Process -Id $entry.pid -ErrorAction SilentlyContinue)) { throw ('Service exited during startup: ' + $entry.name) }
        }
        try {
            $apiReady = Invoke-RestMethod 'http://127.0.0.1:8000/health/ready' -TimeoutSec 1
            $frontReady = Invoke-WebRequest 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 1
            if ($apiReady.status -eq 'ready' -and $frontReady.StatusCode -eq 200) { $ready=$true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Readiness check failed. Inspect .runtime/*.err.log.' }
    foreach ($entry in $services) {
        if (-not (Get-Process -Id $entry.pid -ErrorAction SilentlyContinue)) { throw ('Service exited: ' + $entry.name) }
    }
    Write-Host 'Platform: http://127.0.0.1:5173'
    Write-Host 'API docs: http://127.0.0.1:8000/docs'
    Write-Host ('AI capability: ' + $apiReady.ai)
} catch {
    if (Test-Path -LiteralPath $manifestPath) { & (Join-Path $PSScriptRoot 'stop.ps1') }
    else { foreach ($entry in $services) { Stop-Process -Id $entry.pid -ErrorAction SilentlyContinue } }
    throw
}
