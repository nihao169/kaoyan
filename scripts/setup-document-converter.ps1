$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$runtimeDir=Join-Path $projectRoot '.runtime'
$converter=Join-Path $runtimeDir 'libreoffice/program/soffice.exe'
if (Test-Path -LiteralPath $converter) { Write-Output $converter; exit 0 }
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$installer=Join-Path $runtimeDir 'libreoffice.msi'
& curl.exe -sS -L --fail --retry 3 --ssl-no-revoke 'https://download.documentfoundation.org/libreoffice/stable/26.8.1/win/x86_64/LibreOffice_26.8.1_Win_x86-64.msi' -o $installer
if ($LASTEXITCODE -ne 0) { throw 'Download failed; no system configuration was changed.' }
$target=Join-Path $runtimeDir 'libreoffice'
$arguments=@('/a',('"'+$installer+'"'),'/qn',('TARGETDIR="'+$target+'"'))
$process=Start-Process msiexec.exe -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $converter)) { throw 'Portable converter extraction failed.' }
Write-Output $converter
