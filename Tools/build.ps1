param(
    [string]$UV4 = 'D:\Keil5\UV4\UV4.exe',
    [switch]$Rebuild
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectFile = Join-Path $projectRoot 'MDK-ARM\GestureScreen.uvprojx'
$logDir = Join-Path $projectRoot 'Build'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if (-not (Test-Path -LiteralPath $UV4)) { throw "Keil executable missing: $UV4" }
$log = Join-Path $logDir 'keil-build.log'
$buildFlag = if ($Rebuild) { '-r' } else { '-b' }
$keilProcess = Start-Process -FilePath $UV4 -ArgumentList @($buildFlag, ('"' + $projectFile + '"'), '-t', '"GestureScreen"', '-o', ('"' + $log + '"')) -WindowStyle Hidden -PassThru -Wait
if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log }
if ($keilProcess.ExitCode -ne 0) { throw "Keil build returned $($keilProcess.ExitCode). See $log" }
if (-not (Select-String -LiteralPath $log -Pattern '0 Error\(s\)' -Quiet)) { throw "No successful build summary in $log" }
