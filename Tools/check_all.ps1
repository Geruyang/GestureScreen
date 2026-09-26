#requires -Version 5.1
<# 软件复验入口：编译、模块/采集/模型测试、静态分析和调试配置检查。
   不打开采集串口，不连接、暂停、复位或烧录目标芯片。 #>
param(
    [string]$Python = 'python',
    [string]$Node = 'node',
    [string]$UV4 = 'D:\Keil5\UV4\UV4.exe',
    [string]$VcVarsPath = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$results = Join-Path $projectRoot 'Build\usb-validation'
New-Item -ItemType Directory -Force -Path $results | Out-Null
& (Join-Path $PSScriptRoot 'build.ps1') -UV4 $UV4 -Rebuild
if (-not (Select-String -LiteralPath (Join-Path $projectRoot 'Build\keil-build.log') -Pattern '0 Error\(s\), 0 Warning\(s\)' -Quiet)) {
    throw 'Final build must have zero errors and warnings.'
}
& (Join-Path $PSScriptRoot 'test_host.ps1') -VcVarsPath $VcVarsPath
& (Join-Path $PSScriptRoot 'test_capture.ps1') -Python $Python -Node $Node
& (Join-Path $PSScriptRoot 'test_ethernet.ps1') -Python $Python -VcVarsPath $VcVarsPath
& (Join-Path $projectRoot 'Models\test.ps1') -Python $Python -VcVarsPath $VcVarsPath
$wire = Join-Path $results 'c-sender.bin'
& (Join-Path $projectRoot 'Build\host\test_usb_firmware.exe') $wire
if ($LASTEXITCODE -ne 0) { throw 'C wire fixture failed' }
& $Python (Join-Path $projectRoot 'Tests\check_usb_wire.py') $wire
if ($LASTEXITCODE -ne 0) { throw 'C/Python wire agreement failed' }
& $Python (Join-Path $PSScriptRoot 'analyze.py') --include-generated | Tee-Object -FilePath (Join-Path $results 'static-analysis.log')
if ($LASTEXITCODE -ne 0) { throw 'Static analysis failed' }
& (Join-Path $PSScriptRoot 'firedap.ps1') -Action Check -Python $Python
& $Python (Join-Path $PSScriptRoot 'record_usb_validation.py')
if ($LASTEXITCODE -ne 0) { throw 'Validation evidence could not be recorded' }
Write-Output "PASS: software checks complete. Report: $results\validation.json. Hardware was not contacted."
