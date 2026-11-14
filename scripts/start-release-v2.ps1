param([ValidateRange(1024,65535)][int]$Port=5183,[switch]$MasteryReviews)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$secrets=Get-Content -LiteralPath '.runtime\v2-secrets.json' -Raw | ConvertFrom-Json
$env:DATABASE_URL='postgresql+psycopg://zhixing:' + [Uri]::EscapeDataString($secrets.postgres_password) + '@127.0.0.1:55433/zhixing_v2_release'
$env:DATA_DIR=Join-Path $projectRoot 'data\v2-release'
$env:DEEPTUTOR_URL='http://127.0.0.1:18001'
$env:DEEPTUTOR_BRIDGE_SECRET=$secrets.bridge_secret
$reviewMarker=Join-Path $projectRoot '.runtime/mastery-reviews-release.enabled'
if ($MasteryReviews -or (Test-Path -LiteralPath $reviewMarker)) {
    $env:DEEPTUTOR_MASTERY_REVIEWS='true'
}
if ([string]::IsNullOrWhiteSpace($env:DEEPTUTOR_UNIFIED_EXECUTION)) {
    $env:DEEPTUTOR_UNIFIED_EXECUTION='true'
}
$nativeFlags = @('DEEPTUTOR_NATIVE_KNOWLEDGE', 'DEEPTUTOR_NATIVE_QUESTIONS', 'DEEPTUTOR_NATIVE_LESSONS',
    'DEEPTUTOR_NATIVE_TEACHER_QUESTIONS', 'DEEPTUTOR_STRUCTURED_TEACHER')
foreach ($name in $nativeFlags) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))) {
        [Environment]::SetEnvironmentVariable($name, 'true', 'Process')
    }
}
if (!$env:DEEPTUTOR_TIMEOUT) { $env:DEEPTUTOR_TIMEOUT='240' }
$env:LEGACY_RETRIEVAL_ENABLED='false'
$env:PYTHONPATH=Join-Path $projectRoot 'backend'
$env:PYTHONUTF8='1'
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
Write-Host 'Checking PostgreSQL readiness before starting the platform...'
@'
import os
import time

import psycopg

dsn = os.environ['DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://', 1)
deadline = time.monotonic() + 900
waiting = False
while True:
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            break
    except psycopg.OperationalError as error:
        detail = str(error).lower()
        retryable = error.sqlstate in {'57P03', '57P01'} or any(
            message in detail for message in (
                'the database system is starting up', 'connection refused',
                'timeout expired', 'server closed the connection unexpectedly',
            )
        )
        if not retryable:
            raise SystemExit('PostgreSQL connection failed. Check the release database and local credentials.')
        if time.monotonic() >= deadline:
            raise SystemExit('PostgreSQL did not become ready within 15 minutes. Check: docker logs --tail 50 zhixing-v2-postgres-1')
        if not waiting:
            print('Waiting for PostgreSQL on 127.0.0.1:55433. Check Docker Desktop if this persists.', flush=True)
            waiting = True
        time.sleep(5)
'@ | & $python -
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL readiness check failed. Migration was not started.' }
& $python -m alembic -c backend/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Release schema migration failed. No service was switched.' }
& $python -m app.v2.bootstrap
if ($LASTEXITCODE -ne 0) { throw 'Release catalog initialization failed. No service was switched.' }
& (Join-Path $PSScriptRoot 'start.ps1') -ApiPort $Port -FrontendPort $Port -RuntimeName 'services-v2-release' -StaticFrontend
if ($MasteryReviews -and -not (Test-Path -LiteralPath $reviewMarker)) {
    New-Item -ItemType File -Path $reviewMarker -ErrorAction Stop | Out-Null
}
