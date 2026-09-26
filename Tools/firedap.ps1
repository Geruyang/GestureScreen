#requires -Version 5.1
param(
    [ValidateSet('Check','Server','Flash')][string]$Action = 'Check',
    [string]$OpenOCD = 'D:\STM32CubeIDE\App\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.openocd.win32_2.4.500.202604080855\tools\bin\openocd.exe',
    [string]$Scripts = 'D:\STM32CubeIDE\App\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.debug.openocd_2.3.400.202606220929\resources\openocd\st_scripts',
    [string]$ProbeSerial = '',
    [ValidateRange(100,4000)][int]$SpeedKHz = 1000,
    [switch]$UnderReset,
    [string]$Python = 'python'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Join-Path $projectRoot 'Debug\firedap.cfg'
foreach ($path in @($OpenOCD,$config,(Join-Path $Scripts 'interface\cmsis-dap.cfg'),(Join-Path $Scripts 'target\stm32f4x.cfg'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing debugger file: $path" }
}
if ($ProbeSerial -notmatch '^[A-Za-z0-9_-]+$') { throw 'Supply the exact fireDAP serial using -ProbeSerial.' }
$ocdArgs = @('-s',$Scripts,'-c',"set GS_DAP_SERIAL {$ProbeSerial}",'-c',"set GS_SWD_KHZ $SpeedKHz")
if ($UnderReset) { $ocdArgs += @('-c','set GS_UNDER_RESET 1') }
$ocdArgs += @('-f',$config)
if ($Action -eq 'Check') {
    # Shutdown during configuration stage: no init, USB open, target halt or erase.
    & $OpenOCD @ocdArgs -c 'adapter speed' -c 'echo {PASS: fireDAP config parsed; target not contacted}' -c shutdown
    if ($LASTEXITCODE -ne 0) { throw 'OpenOCD configuration check failed' }
    & $Python (Join-Path $PSScriptRoot 'verify.py') --with-build
    if ($LASTEXITCODE -ne 0) { throw 'Firmware structural/build check failed' }
    Write-Output "Prepared fireDAP $ProbeSerial, SWD ${SpeedKHz}kHz. Check did not contact target."
    return
}
if ($Action -eq 'Flash') {
    & (Join-Path $PSScriptRoot 'build.ps1') -Rebuild
    & $Python (Join-Path $PSScriptRoot 'verify.py') --with-build
    if ($LASTEXITCODE -ne 0) { throw 'Firmware check failed; not flashing' }
    $firmware = (Join-Path $projectRoot 'MDK-ARM\Objects\GestureScreen.hex').Replace('\','/')
    if ($firmware -match '[{}\r\n]') { throw 'Firmware path cannot be safely represented in Tcl' }
    & $OpenOCD @ocdArgs -c 'init; reset halt; gs_verify_chip' -c "program {$firmware} verify reset exit"
} else {
    Write-Output 'Starting local fireDAP server; this connects to the wired target. Ctrl+C to stop.'
    & $OpenOCD @ocdArgs
}
if ($LASTEXITCODE -ne 0) { throw "OpenOCD $Action failed; inspect probe, target power and SWD wiring." }
