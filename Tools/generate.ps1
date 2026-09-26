param(
    [string]$CubeMX = 'D:\STM32CubeMX\App',
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $projectRoot 'Build'
$mxHome = Join-Path $buildDir 'cubemx-home'
New-Item -ItemType Directory -Force -Path $mxHome | Out-Null
$scriptFile = Join-Path $buildDir 'generate.mx'
@(
    ('config load "' + (Join-Path $projectRoot 'GestureScreen.ioc') + '"'),
    ('project path "' + $projectRoot + '"'),
    'project generate',
    ('config save "' + (Join-Path $projectRoot 'GestureScreen.ioc') + '"'),
    'exit'
) | Set-Content -LiteralPath $scriptFile -Encoding ascii
$log = Join-Path $buildDir 'cubemx-generate.log'
& (Join-Path $CubeMX 'jre\bin\java.exe') "-Duser.home=$mxHome" -jar (Join-Path $CubeMX 'STM32CubeMX.exe') -q $scriptFile *> $log
if ($LASTEXITCODE -ne 0) { throw "CubeMX failed; see $log" }
if (-not (Select-String -LiteralPath $log -Pattern 'Time for Generating toolchain IDE Files' -Quiet)) {
    throw "CubeMX did not confirm generation success; inspect $log before integration."
}
& $Python (Join-Path $PSScriptRoot 'integrate.py')
if ($LASTEXITCODE -ne 0) { throw 'Module integration failed' }
Write-Output "Generated and integrated. Log: $log"
