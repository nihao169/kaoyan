param([ValidateRange(1024,65535)][int]$Port=5183)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$secrets=Get-Content -LiteralPath '.runtime\v2-secrets.json' -Raw | ConvertFrom-Json
$env:DATABASE_URL='postgresql+psycopg://zhixing:' + [Uri]::EscapeDataString($secrets.postgres_password) + '@127.0.0.1:55433/zhixing_v2_release'
$env:DATA_DIR=Join-Path $projectRoot 'data\v2-release'
$env:DEEPTUTOR_URL='http://127.0.0.1:18001'
$env:DEEPTUTOR_BRIDGE_SECRET=$secrets.bridge_secret
$env:LEGACY_RETRIEVAL_ENABLED='false'
$env:PYTHONPATH=Join-Path $projectRoot 'backend'
$env:PYTHONUTF8='1'
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
& $python -m alembic -c backend/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Release schema migration failed. No service was switched.' }
& $python -m app.v2.bootstrap
if ($LASTEXITCODE -ne 0) { throw 'Release catalog initialization failed. No service was switched.' }
& (Join-Path $PSScriptRoot 'start.ps1') -ApiPort $Port -FrontendPort $Port -RuntimeName 'services-v2-release' -StaticFrontend
