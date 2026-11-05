param([switch]$SkipTutor,[switch]$SkipSeed,[switch]$Release)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Force $runtimeDir | Out-Null
$secretFile = Join-Path $runtimeDir 'v2-secrets.json'
if (-not (Test-Path -LiteralPath $secretFile)) {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $password = [Convert]::ToBase64String($bytes)
    $rng.GetBytes($bytes)
    @{postgres_password=$password;bridge_secret=[Convert]::ToBase64String($bytes)} | ConvertTo-Json | Set-Content -LiteralPath $secretFile -Encoding UTF8
    $rng.Dispose()
}
$secrets = Get-Content -LiteralPath $secretFile -Raw | ConvertFrom-Json
$env:V2_POSTGRES_PASSWORD = $secrets.postgres_password
$env:DEEPTUTOR_BRIDGE_SECRET = $secrets.bridge_secret
& docker compose -f compose.v2.yaml up -d postgres
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed.' }
$database = if ($Release) { 'zhixing_v2_release' } else { 'zhixing_v2' }
$env:DATABASE_URL = 'postgresql+psycopg://zhixing:' + [Uri]::EscapeDataString($secrets.postgres_password) + '@127.0.0.1:55433/' + $database
$env:DATA_DIR = Join-Path $projectRoot $(if ($Release) { 'data\v2-release' } else { 'data\v2' })
$env:PYTHONPATH = Join-Path $projectRoot 'backend'
$env:PYTHONUTF8 = '1'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$ready = $false
for ($attempt=0; $attempt -lt 90; $attempt++) {
    & docker compose -f compose.v2.yaml exec -T postgres pg_isready -h 127.0.0.1 -U zhixing -d zhixing_v2 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready=$true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'PostgreSQL did not become ready.' }
if ($Release) {
    $exists=& docker compose -f compose.v2.yaml exec -T postgres psql -U zhixing -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='zhixing_v2_release'"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect release database.' }
    if ($exists -ne '1') {
        & docker compose -f compose.v2.yaml exec -T postgres createdb -U zhixing zhixing_v2_release
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create fresh release database.' }
    }
}
& $pythonPath -m alembic -c backend/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'V2 migration failed.' }
if ($Release) {
    & $pythonPath -m app.v2.bootstrap
    if ($LASTEXITCODE -ne 0) { throw 'Release catalog initialization failed.' }
} elseif (-not $SkipSeed) {
    & $pythonPath -m app.seed
    if ($LASTEXITCODE -ne 0) { throw 'Account initialization failed.' }
}
if (-not $SkipTutor) {
    New-Item -ItemType Directory -Force 'data\v2-deeptutor' | Out-Null
    & docker compose -f compose.v2.yaml run --rm --no-deps --entrypoint python deeptutor -m deeptutor_cli init --non-interactive
    if ($LASTEXITCODE -ne 0) { throw 'DeepTutor initialization failed.' }
    $authPath = Join-Path $projectRoot 'data\v2-deeptutor\user\settings\auth.json'
    $authConfig = Get-Content -LiteralPath $authPath -Raw | ConvertFrom-Json
    $authConfig.enabled = $true
    [IO.File]::WriteAllText($authPath, ($authConfig | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
    $env:DEEPTUTOR_SETUP_LLM_KEY = $env:DEEPSEEK_API_KEY
    if ([string]::IsNullOrWhiteSpace($env:DEEPTUTOR_SETUP_LLM_KEY)) {
        $env:DEEPTUTOR_SETUP_LLM_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
    }
    if (-not [string]::IsNullOrWhiteSpace($env:DEEPTUTOR_SETUP_LLM_KEY)) {
        try {
            & docker compose -f compose.v2.yaml run --rm --no-deps -e DEEPTUTOR_SETUP_LLM_KEY --entrypoint python deeptutor -m deeptutor_cli config apply /integration/setup.json
            if ($LASTEXITCODE -ne 0) { throw 'DeepTutor provider setup failed.' }
        } finally { Remove-Item Env:DEEPTUTOR_SETUP_LLM_KEY -ErrorAction SilentlyContinue }
    } else { Write-Warning 'DeepSeek key not found. Configure the isolated DeepTutor API-key provider before using AI.' }
    & docker compose -f compose.v2.yaml up -d deeptutor
    if ($LASTEXITCODE -ne 0) { throw 'DeepTutor startup failed.' }
}
Write-Host 'V2 infrastructure initialized. Existing SQLite data was not modified.'
if ($Release) { Write-Host 'Run scripts/start-release-v2.ps1 for the release at http://127.0.0.1:5183.' }
else { Write-Host 'Run scripts/start-v2.ps1 to start the V2 preview application.' }
