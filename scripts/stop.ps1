$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$manifestPath = Join-Path $projectRoot '.runtime\services.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { Write-Host 'No recorded services.'; return }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($manifest.root) -ne $projectRoot) { throw 'Service manifest belongs to a different workspace.' }
function Stop-OwnedTree([int]$processId) {
    $processInfo = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $processId) -ErrorAction SilentlyContinue
    if (-not $processInfo) { return }
    if (-not $processInfo.CommandLine -or $processInfo.CommandLine.IndexOf($projectRoot,[StringComparison]::OrdinalIgnoreCase) -lt 0) { throw ('PID identity changed; refusing to stop ' + $processId) }
    if ($processInfo.CreationDate.ToUniversalTime() -lt [DateTime]::Parse($manifest.started_at).ToUniversalTime().AddSeconds(-5)) { throw 'Process predates this start operation; refusing to stop it.' }
    foreach ($child in @(Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $processId))) {
        $systemConsole = Join-Path ([Environment]::GetFolderPath('System')) 'conhost.exe'
        if ($child.Name -eq 'conhost.exe' -and $child.ExecutablePath -and [IO.Path]::GetFullPath($child.ExecutablePath) -eq [IO.Path]::GetFullPath($systemConsole)) {
            continue # Windows owns this console helper; it exits when its clients stop.
        }
        Stop-OwnedTree -processId ([int]$child.ProcessId)
    }
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
    Wait-Process -Id $processId -Timeout 5 -ErrorAction SilentlyContinue
}
foreach ($entry in $manifest.services) {
    Stop-OwnedTree -processId ([int]$entry.pid)
    Write-Host ('Stopped ' + $entry.name)
}
Remove-Item -LiteralPath $manifestPath
