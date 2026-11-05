param([ValidatePattern('^[a-zA-Z0-9-]+$')][string]$RuntimeName='services')
$projectRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $projectRoot ('.runtime\'+$RuntimeName+'.json')
$apiPort=8000
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.api_port) { $apiPort=[int]$manifest.api_port }
    foreach ($entry in $manifest.services) {
        [PSCustomObject]@{Service=$entry.name;PID=$entry.pid;Running=[bool](Get-Process -Id $entry.pid -ErrorAction SilentlyContinue)}
    }
} else { Write-Host 'No recorded services.' }
try { Invoke-RestMethod ("http://127.0.0.1:$apiPort/health/ready") -TimeoutSec 2 | Format-List } catch { Write-Host 'API not ready.' }
