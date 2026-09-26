#requires -Version 5.1
param(
    [string]$GDB = 'D:\STM32CubeIDE\App\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740\tools\bin\arm-none-eabi-gdb.exe'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$symbols = Join-Path $projectRoot 'MDK-ARM\Objects\GestureScreen.axf'
$commands = Join-Path $projectRoot 'Debug\gesture.gdb'
foreach ($path in @($GDB,$symbols,$commands)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing debug file: $path" }
}
Write-Output 'Connecting to the local fireDAP server. Start Tools/firedap.ps1 -Action Server first.'
& $GDB -x $commands $symbols
if ($LASTEXITCODE -ne 0) { throw 'GDB session failed; inspect the local server output.' }
