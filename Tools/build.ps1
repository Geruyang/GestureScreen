param(
    [string]$UV4 = $env:KEIL_UV4,
    [switch]$Rebuild
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectFile = Join-Path $projectRoot 'MDK-ARM\GestureScreen.uvprojx'
$logDir = Join-Path $projectRoot 'Build'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if (-not $UV4) {
    $found = Get-Command UV4.exe -ErrorAction SilentlyContinue
    if ($found) { $UV4 = $found.Source }
}
if (-not $UV4 -or -not (Test-Path -LiteralPath $UV4)) {
    throw 'Keil UV4.exe not found. Pass -UV4 <path>, set KEIL_UV4, or add UV4.exe to PATH.'
}
$log = Join-Path $logDir 'keil-build.log'
$buildFlag = if ($Rebuild) { '-r' } else { '-b' }
$keilProcess = Start-Process -FilePath $UV4 -ArgumentList @($buildFlag, ('"' + $projectFile + '"'), '-t', '"GestureScreen"', '-o', ('"' + $log + '"')) -WindowStyle Hidden -PassThru -Wait
if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log }
if ($keilProcess.ExitCode -ne 0) { throw "Keil build returned $($keilProcess.ExitCode). See $log" }
if (-not (Select-String -LiteralPath $log -Pattern '0 Error\(s\)' -Quiet)) { throw "No successful build summary in $log" }
