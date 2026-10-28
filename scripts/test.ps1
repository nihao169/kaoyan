$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot 'backend'
$env:PYTHONUTF8 = '1'
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    & npm run test:e2e
    if ($LASTEXITCODE -ne 0) { throw 'Browser tests failed.' }
    & npx playwright test --config playwright.extensions.config.ts
    if ($LASTEXITCODE -ne 0) { throw 'Document and AI-state browser tests failed.' }
} finally { Pop-Location }
