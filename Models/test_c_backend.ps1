#requires -Version 5.1
param(
    [string]$Python = '',
    [string]$VcVarsPath = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $projectRoot 'Build\model-training-venv\Scripts\python.exe' }
$modelBuildRoot = Join-Path $projectRoot 'Build\model-c-reference'
$modelPath = Join-Path (Split-Path -Parent $projectRoot) 'artifacts\model_audit\arm_openmv\model.tflite'
& $Python -X utf8 (Join-Path $PSScriptRoot 'export_c.py') $modelPath --output $modelBuildRoot --reference-five-class
if ($LASTEXITCODE -ne 0) { throw 'Reference C model export failed' }
$source = Join-Path $projectRoot 'Modules\Vision\Src\gs_ai_int8_backend.c'
$include = Join-Path $projectRoot 'Modules\Vision\Inc'
foreach ($path in @($source, $include, $VcVarsPath, $modelBuildRoot)) {
    if ($path -match '["%!^\r\n]') { throw "Cannot safely pass batch compiler path: $path" }
}
$commands = @(
    '@echo off', 'setlocal EnableExtensions DisableDelayedExpansion',
    ('call "{0}" > vcvars.log 2>&1' -f $VcVarsPath),
    'if errorlevel 1 exit /b 1', 'set "CL="', 'set "_CL_="',
    ('cl /nologo /LD /O2 /std:c11 /utf-8 /W4 /WX /I"{0}" "{1}" gs_model_weights.c /Fe:gs_model_reference.dll /link /EXPORT:gs_model_raw_run /EXPORT:gs_model_network /EXPORT:gs_int8_execute > c-backend-build.log 2>&1' -f $include, $source),
    'exit /b %errorlevel%'
)
[IO.File]::WriteAllLines((Join-Path $modelBuildRoot 'build_backend.cmd'), $commands, [Text.UTF8Encoding]::new($false))
Push-Location -LiteralPath $modelBuildRoot
try {
    & $env:ComSpec /d /c build_backend.cmd
    if ($LASTEXITCODE -ne 0) { Get-Content -LiteralPath 'c-backend-build.log'; throw 'C backend build failed' }
} finally { Pop-Location }
& $Python -X utf8 (Join-Path $PSScriptRoot 'tests\compare_c_backend.py') $modelPath (Join-Path $modelBuildRoot 'gs_model_reference.dll') --report (Join-Path $PSScriptRoot 'validation\c_backend_numeric.json')
if ($LASTEXITCODE -ne 0) { throw 'C backend numeric comparison failed' }
