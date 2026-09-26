#requires -Version 5.1
<# Rebuild actual production Ethernet state machine/parser against test mocks,
   then exchange real C wire bytes with localhost HTTP. Never accesses hardware. #>
param(
    [string]$Python = 'python',
    [string]$VcVarsPath = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat',
    [string]$OutputDir = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $projectRoot 'Build\ethernet-validation'
if ($OutputDir) { $outputRoot = [System.IO.Path]::GetFullPath($OutputDir) }
$testRoot = Join-Path $projectRoot 'Tests\ethernet'
function Quote-BatchPath([string]$Path) {
    if ($Path -match '["%!^\r\n]') { throw "Unsafe batch path: $Path" }
    return '"' + $Path + '"'
}
foreach ($runtime in @($Python, $VcVarsPath)) {
    if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) { throw "Runtime missing: $runtime" }
}
$Python = (Resolve-Path -LiteralPath $Python).Path
$VcVarsPath = (Resolve-Path -LiteralPath $VcVarsPath).Path
[void](Quote-BatchPath $outputRoot)
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('@echo off')
$lines.Add('chcp 65001 > nul')
$lines.Add('setlocal EnableExtensions DisableDelayedExpansion')
$lines.Add('pushd "%~dp0"')
$lines.Add('if errorlevel 1 exit /b 1')
$lines.Add(('call {0} > "vcvars.log" 2>&1' -f (Quote-BatchPath $VcVarsPath)))
$lines.Add('if errorlevel 1 (type "vcvars.log" & exit /b 1)')
$lines.Add('set "CL="')
$lines.Add('set "_CL_="')
$lines.Add('set "PYTHONOPTIMIZE="')
foreach ($suite in @('state_test', 'parser_bridge')) {
    $source = Join-Path $testRoot ($suite + '.c')
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Source missing: $source" }
    $compile = 'cl /nologo /std:c11 /utf-8 /W4 /WX /UNDEBUG /D_CRT_SECURE_NO_WARNINGS'
    # Production register/DMA pointers are 32-bit; the historical x64 mock
    # needs these two conversion diagnostics suppressed, never other warnings.
    if ($suite -eq 'state_test') { $compile += ' /wd4090 /wd4312' }
    $compile += ' /I' + (Quote-BatchPath (Join-Path $projectRoot 'BSP\Inc'))
    $compile += ' /I' + (Quote-BatchPath (Join-Path $testRoot 'mocks'))
    $compile += ' ' + (Quote-BatchPath $source)
    $compile += (' /Fo:"{0}.obj" /Fe:"{0}.exe" > "{0}-build.log" 2>&1' -f $suite)
    $lines.Add($compile)
    $lines.Add(('if errorlevel 1 (type "{0}-build.log" & exit /b 1)' -f $suite))
    $lines.Add(('type "{0}-build.log"' -f $suite))
}
$lines.Add('"state_test.exe" > "state_test-run.log" 2>&1')
$lines.Add('if errorlevel 1 (type "state_test-run.log" & exit /b 1)')
$lines.Add('type "state_test-run.log"')
$protocol = Join-Path $testRoot 'test_actual_protocol.py'
$lines.Add(('{0} -B -X utf8 {1} --build-dir "." > "protocol-run.log" 2>&1' -f
             (Quote-BatchPath $Python), (Quote-BatchPath $protocol)))
$lines.Add('if errorlevel 1 (type "protocol-run.log" & exit /b 1)')
$lines.Add('type "protocol-run.log"')
$lines.Add('popd')
$lines.Add('exit /b 0')
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$resultPath = Join-Path $outputRoot 'protocol-result.json'
if (Test-Path -LiteralPath $resultPath -PathType Leaf) { Remove-Item -LiteralPath $resultPath }
[System.IO.File]::WriteAllLines((Join-Path $outputRoot 'run_ethernet_tests.cmd'), $lines,
                              [System.Text.UTF8Encoding]::new($false))
Push-Location -LiteralPath $outputRoot
try {
    & $env:ComSpec /d /c run_ethernet_tests.cmd
    $testExitCode = $LASTEXITCODE
} finally { Pop-Location }
if ($testExitCode -ne 0) { throw "Ethernet regression failed (exit $testExitCode). Logs: $outputRoot" }
Write-Output "PASS: 8 Ethernet mock groups and localhost C/HTTP protocol exchange. Logs: $outputRoot"
