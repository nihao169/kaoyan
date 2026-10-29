$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH='backend'
& .venv/Scripts/python.exe -c "from app.ai_services import configured; raise SystemExit(0 if configured() else 'Fill MODEL_API_KEY in .env before real acceptance.')"
if ($LASTEXITCODE -ne 0) { throw 'Real AI acceptance requires a configured server-side key.' }
$env:ZX_REAL_AI='1'
Push-Location frontend
try {
    & npx playwright test --config playwright.teaching.config.ts
    if ($LASTEXITCODE -ne 0) { throw 'Real AI acceptance failed. Do not push final delivery.' }
} finally {
    Pop-Location
    Remove-Item Env:ZX_REAL_AI -ErrorAction SilentlyContinue
}
Write-Host 'Automated real-AI checks finished. Review questions, answers, citations and .runtime/real-teaching-acceptance.json before final delivery.'
