#requires -Version 5.1
param(
    [string]$Python = 'python',
    [string]$VcVarsPath = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$modelBuildRoot = Join-Path $projectRoot 'Build\model-tools'
New-Item -ItemType Directory -Force -Path $modelBuildRoot | Out-Null
$source = Join-Path $projectRoot 'Modules\Vision\Src\gs_preprocess.c'
$include = Join-Path $projectRoot 'Modules\Vision\Inc'
foreach ($path in @($source, $include, $VcVarsPath, $modelBuildRoot)) {
    if ($path -match '["%!^\r\n]') { throw "Cannot safely pass batch compiler path: $path" }
}
$commands = @(
    '@echo off', 'setlocal EnableExtensions DisableDelayedExpansion',
    ('call "{0}" > vcvars.log 2>&1' -f $VcVarsPath),
    'if errorlevel 1 exit /b 1', 'set "CL="', 'set "_CL_="',
    ('cl /nologo /LD /std:c11 /utf-8 /W4 /WX /I"{0}" "{1}" /Fe:gs_preprocess_test.dll /link /EXPORT:gs_preprocess_rgb565 > c-bridge-build.log 2>&1' -f $include, $source),
    'exit /b %errorlevel%'
)
[IO.File]::WriteAllLines((Join-Path $modelBuildRoot 'build_bridge.cmd'), $commands, [Text.UTF8Encoding]::new($false))
Push-Location -LiteralPath $modelBuildRoot
try {
    & $env:ComSpec /d /c build_bridge.cmd
    if ($LASTEXITCODE -ne 0) { Get-Content -LiteralPath 'c-bridge-build.log'; throw 'C preprocess bridge build failed' }
} finally { Pop-Location }
$previousDll = $env:GS_PREPROCESS_DLL
try {
    $env:GS_PREPROCESS_DLL = Join-Path $modelBuildRoot 'gs_preprocess_test.dll'
    & $Python -X utf8 (Join-Path $PSScriptRoot 'tests\test_tools.py') 2>&1 | Tee-Object -FilePath (Join-Path $modelBuildRoot 'tests.log')
    if ($LASTEXITCODE -ne 0) { throw 'Model tool tests failed' }
} finally { $env:GS_PREPROCESS_DLL = $previousDll }
