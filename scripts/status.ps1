$projectRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $projectRoot '.runtime\services.json'
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $manifest.services) {
        [PSCustomObject]@{Service=$entry.name;PID=$entry.pid;Running=[bool](Get-Process -Id $entry.pid -ErrorAction SilentlyContinue)}
    }
} else { Write-Host 'No recorded services.' }
try { Invoke-RestMethod 'http://127.0.0.1:8000/health/ready' -TimeoutSec 2 | Format-List } catch { Write-Host 'API not ready.' }
