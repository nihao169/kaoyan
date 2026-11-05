param([ValidatePattern('^zhixing_v2_test(?:_[a-z0-9]{1,24})?$')][string]$Database='zhixing_v2_test')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$secrets=Get-Content (Join-Path $projectRoot '.runtime\v2-secrets.json') -Raw | ConvertFrom-Json
$exists=& docker exec zhixing-v2-postgres-1 psql -U zhixing -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$Database'"
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect test database.' }
if ($exists -ne '1') {
    & docker exec zhixing-v2-postgres-1 createdb -U zhixing $Database
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create isolated test database.' }
}
$previous=$env:V2_TEST_DATABASE_URL
try {
    $env:V2_TEST_DATABASE_URL='postgresql+psycopg://zhixing:'+[Uri]::EscapeDataString($secrets.postgres_password)+'@127.0.0.1:55433/'+$Database
    $env:PYTHONUTF8='1'
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') -m pytest backend/tests/test_v2.py -q --basetemp=.runtime/pytest-v2-postgres
    if ($LASTEXITCODE -ne 0) { throw 'V2 PostgreSQL tests failed.' }
} finally { $env:V2_TEST_DATABASE_URL=$previous }
