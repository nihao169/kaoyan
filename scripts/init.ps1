param([switch]$SkipInstall, [switch]$DownloadModel)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $projectRoot 'backend'
$env:UV_CACHE_DIR = Join-Path $projectRoot '.runtime\uv-cache'
New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot 'data'), (Join-Path $projectRoot '.runtime') | Out-Null
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Please install uv and Python 3.12, then run init.ps1 again.' }
    & uv venv --python 3.12 .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
if (-not $SkipInstall) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv pip install --python $pythonPath -r backend/requirements.txt
    } else {
        & $pythonPath -m pip install -r backend/requirements.txt
    }
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        & npm ci --cache (Join-Path $projectRoot '.runtime\npm-cache')
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    } finally { Pop-Location }
}
& $pythonPath -m alembic -c backend/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
& $pythonPath -m app.seed
if ($LASTEXITCODE -ne 0) { throw 'Demo initialization failed.' }
if ($DownloadModel) {
    & $pythonPath scripts/setup_models.py --download --reindex
    if ($LASTEXITCODE -ne 0) { throw 'Local embedding model setup failed. Content cannot be submitted until the model is ready.' }
}
Write-Host 'Initialized accounts and configuration. Upload your own teaching material through the platform.'
Write-Host 'Next: powershell -ExecutionPolicy Bypass -File scripts/start.ps1'
