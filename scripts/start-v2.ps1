$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$secretFile = Join-Path $projectRoot '.runtime\v2-secrets.json'
if (-not (Test-Path -LiteralPath $secretFile)) { throw 'Run scripts/setup-v2.ps1 first.' }
$secrets = Get-Content -LiteralPath $secretFile -Raw | ConvertFrom-Json
$env:DATABASE_URL = 'postgresql+psycopg://zhixing:' + [Uri]::EscapeDataString($secrets.postgres_password) + '@127.0.0.1:55433/zhixing_v2'
$env:DATA_DIR = Join-Path $projectRoot 'data\v2'
$env:DEEPTUTOR_URL = 'http://127.0.0.1:18001'
$env:DEEPTUTOR_BRIDGE_SECRET = $secrets.bridge_secret
$env:LEGACY_RETRIEVAL_ENABLED = 'false'
& (Join-Path $PSScriptRoot 'start.ps1') -ApiPort 8003 -FrontendPort 5184 -RuntimeName 'services-v2'
