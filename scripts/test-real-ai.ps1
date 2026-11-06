param([string]$NativePreview)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH='backend'
$changes=@{ZX_REAL_AI='1'}
if ($NativePreview) {
    $preview=(Resolve-Path -LiteralPath $NativePreview).Path
    if ((Split-Path -Parent $preview) -ne (Join-Path $projectRoot '.runtime') -or
        (Split-Path -Leaf $preview) -notmatch '^tutor-native-preview-[a-z0-9-]+$') {
        throw 'Pass an isolated .runtime/tutor-native-preview-* directory.'
    }
    $key=(Get-Content -LiteralPath (Join-Path $preview 'bridge.key') -Raw).Trim()
    if ($key.Length -lt 32) { throw 'The isolated bridge key is missing or invalid.' }
    $secrets=Get-Content -LiteralPath '.runtime/v2-secrets.json' -Raw | ConvertFrom-Json
    $database='zhixing_tutor_native_teach_'+([Guid]::NewGuid().ToString('N').Substring(0,12))
    & docker exec zhixing-v2-postgres-1 createdb -U zhixing $database
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the isolated teacher acceptance database.' }
    $changes+=@{
        ZX_E2E_ISOLATED_DATABASE_URL='postgresql+psycopg://zhixing:'+[Uri]::EscapeDataString($secrets.postgres_password)+'@127.0.0.1:55433/'+$database
        ZX_NATIVE_TEACHING_E2E='1'; DEEPTUTOR_URL='http://127.0.0.1:18012'; DEEPTUTOR_BRIDGE_SECRET=$key
        DEEPTUTOR_NATIVE_KNOWLEDGE='true'; DEEPTUTOR_NATIVE_TEACHER_QUESTIONS='true'; DEEPTUTOR_STRUCTURED_TEACHER='true'
        DEEPTUTOR_TIMEOUT='240'; LEGACY_RETRIEVAL_ENABLED='false'; NO_PROXY='127.0.0.1,localhost'
    }
} else {
    & .venv/Scripts/python.exe -c "from app.ai_services import configured; raise SystemExit(0 if configured() else 'Fill MODEL_API_KEY in .env before real acceptance.')"
    if ($LASTEXITCODE -ne 0) { throw 'Real AI acceptance requires a configured server-side key.' }
}
$previous=@{}
try {
    foreach ($name in $changes.Keys) {
        $previous[$name]=[Environment]::GetEnvironmentVariable($name,'Process')
        [Environment]::SetEnvironmentVariable($name,$changes[$name],'Process')
    }
    & npm --prefix frontend run test:e2e
    if ($LASTEXITCODE -ne 0) { throw 'Real AI acceptance failed. Do not push final delivery.' }
} finally {
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name,$previous[$name],'Process') }
}
Write-Host 'Automated real-AI checks finished. Review questions, answers, citations and .runtime/real-teaching-acceptance.json before final delivery.'
