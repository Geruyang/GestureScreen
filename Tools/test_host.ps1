#requires -Version 5.1
<#
.SYNOPSIS
使用 MSVC 编译并运行十七组不依赖硬件的 C 测试。
.EXAMPLE
.\Tools\test_host.ps1
.EXAMPLE
.\Tools\test_host.ps1 -VcVarsPath 'C:\VS\VC\Auxiliary\Build\vcvars64.bat'
.NOTES
需要包含 C++ 工具链和 Windows SDK 的 Visual Studio Build Tools。
生成的命令、目标文件、可执行程序与日志均保存在 Build/host。
这些测试不执行烧录，不验证模型准确率或硬件时序。
#>
param(
    [string]$VcVarsPath = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat',
    [string[]]$SelectedSuites = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$hostBuildRoot = Join-Path $projectRoot 'Build\host'
New-Item -ItemType Directory -Force -Path $hostBuildRoot | Out-Null

function ConvertTo-BatchQuotedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    # cmd.exe 即使在引号内也会展开百分号；拒绝这类路径，避免 CALL 二次解析。
    # 普通空格路径仍然支持。
    if ($Path -match '["%!^\r\n]') {
        throw "This batch compiler wrapper cannot represent this path safely: $Path"
    }
    return '"' + $Path + '"'
}

if (-not (Test-Path -LiteralPath $VcVarsPath -PathType Leaf)) {
    throw "MSVC environment script missing: $VcVarsPath. Supply -VcVarsPath."
}
$VcVarsPath = (Resolve-Path -LiteralPath $VcVarsPath).Path
$vcVarsQuoted = ConvertTo-BatchQuotedPath $VcVarsPath
[void](ConvertTo-BatchQuotedPath $hostBuildRoot)

$suites = @(
    @{
        Name = 'test_reader_ui'
        Includes = @('Modules\Ui\Inc', 'Modules\Gesture\Inc', 'Modules\Preview\Inc',
                     'Modules\StaticRecognition\Inc', 'Modules\Vision\Inc', 'Modules\Content\Inc')
        Sources = @('Tests\test_reader_ui.c', 'Modules\Ui\Src\gs_ui_render.c',
                    'Modules\Ui\Src\gs_ui.c', 'Modules\Content\Src\gs_content_builtin.c')
    },
    @{
        Name = 'test_timing_trace'
        Includes = @('Tests\startup_mocks', 'App\Inc')
        Sources = @('Tests\test_timing_trace.c', 'App\Src\gs_timing_trace.c')
    },
    @{
        Name = 'test_preview_pixels'
        Includes = @('Modules\Preview\Inc', 'Modules\Vision\Inc')
        Sources = @('Tests\test_preview_pixels.c', 'Modules\Preview\Src\gs_preview.c', 'Modules\Vision\Src\gs_preprocess.c')
    },
    @{
        Name = 'test_preview_camera'
        Includes = @('Tests\startup_mocks', 'App\Inc', 'BSP\Inc', 'Modules\StaticRecognition\Inc',
                     'Modules\Gesture\Inc', 'Modules\Ui\Inc', 'Modules\Preview\Inc', 'Modules\Vision\Inc',
                     'Modules\Content\Inc')
        Sources = @('Tests\test_preview_camera.c', 'Modules\Preview\Src\gs_preview.c',
                    'Modules\Ui\Src\gs_ui_render.c',
                    'App\Src\gs_timing_trace.c',
                    'Modules\Gesture\Src\gs_gesture.c', 'Modules\Ui\Src\gs_ui.c',
                    'Modules\Vision\Src\gs_preprocess.c', 'Modules\Vision\Src\gs_ai.c',
                    'Modules\StaticRecognition\Src\gs_static_recognition.c', 'Modules\StaticRecognition\Src\gs_static_weights.c',
                    'Modules\Vision\Src\gs_ai_int8_backend.c')
    },
    @{
        Name = 'test_preview_display'
        Includes = @('Build\host', 'BSP\Inc', 'Modules\Display\Inc', 'Modules\Gesture\Inc', 'Modules\Ui\Inc',
                     'Modules\Preview\Inc', 'Modules\Vision\Inc', 'Modules\StaticRecognition\Inc')
        Sources = @('Tests\test_preview_display.c')
    },
    @{
        Name = 'test_int8_optimized'
        Includes = @('Modules\StaticRecognition\Inc', 'Modules\Vision\Inc')
        Sources = @('Tests\test_int8_optimized.c', 'Tests\int8_round8_oracle.c', 'Tests\int8_round9_probe.c',
                    'Modules\StaticRecognition\Src\gs_static_weights.c', 'Modules\Vision\Src\gs_ai_int8_backend.c')
    },
    @{
        Name = 'test_static_model'
        Includes = @('Modules\StaticRecognition\Inc', 'Modules\Vision\Inc')
        Sources = @('Tests\test_static_model.c', 'Modules\StaticRecognition\Src\gs_static_recognition.c')
    },
    @{
        Name = 'test_static_app'
        Defines = @('GS_STATIC_TEST_BACKEND=1')
        Includes = @('Tests\startup_mocks', 'App\Inc', 'BSP\Inc', 'Modules\StaticRecognition\Inc',
                     'Modules\Gesture\Inc', 'Modules\Ui\Inc', 'Modules\Preview\Inc', 'Modules\Vision\Inc',
                     'Modules\Content\Inc')
        Sources = @('Tests\test_static_app.c', 'Modules\Gesture\Src\gs_gesture.c',
                    'Modules\Ui\Src\gs_ui_render.c',
                    'App\Src\gs_timing_trace.c',
                    'Modules\Ui\Src\gs_ui.c', 'Modules\Vision\Src\gs_preprocess.c', 'Modules\Vision\Src\gs_ai.c',
                    'Modules\StaticRecognition\Src\gs_static_recognition.c')
    },
    @{
        Name = 'test_ui_render'
        Includes = @('Modules\Ui\Inc', 'Modules\Gesture\Inc', 'Modules\Preview\Inc',
                     'Modules\StaticRecognition\Inc', 'Modules\Vision\Inc')
        Sources = @('Tests\test_ui_render.c', 'Modules\Ui\Src\gs_ui_render.c', 'Modules\Ui\Src\gs_ui.c',
                    'Modules\StaticRecognition\Src\gs_static_recognition.c', 'Modules\StaticRecognition\Src\gs_static_weights.c',
                    'Modules\Vision\Src\gs_ai_int8_backend.c')
    },
    @{
        Name = 'test_incremental_render'
        Includes = @('Modules\Ui\Inc', 'Modules\Gesture\Inc', 'Modules\Preview\Inc',
                     'Modules\StaticRecognition\Inc', 'Modules\Vision\Inc')
        Sources = @('Tests\test_incremental_render.c',
                    'Modules\Ui\Src\gs_ui_render.c', 'Modules\Ui\Src\gs_ui.c',
                    'Modules\StaticRecognition\Src\gs_static_recognition.c',
                    'Modules\StaticRecognition\Src\gs_static_weights.c',
                    'Modules\Vision\Src\gs_ai_int8_backend.c')
    },
    @{
        Name = 'test_camera_irq'
        Includes = @('Build\host', 'Tests', 'BSP\Inc', 'Modules\Camera\Inc', 'Modules\Gesture\Inc', 'Modules\StaticRecognition\Inc',
                     'Modules\Vision\Inc', 'Modules\Preview\Inc', 'Modules\Ui\Inc')
        Sources = @('Tests\test_camera_irq.c', 'Modules\Camera\Src\gs_camera_pool.c')
    },
    @{
        Name = 'test_startup'
        Includes = @('Tests\startup_mocks', 'App\Inc', 'BSP\Inc', 'Modules\StaticRecognition\Inc',
                     'Modules\Gesture\Inc', 'Modules\Ui\Inc', 'Modules\Preview\Inc', 'Modules\Vision\Inc',
                     'Modules\Content\Inc')
        Sources = @('Tests\test_startup.c', 'Modules\Gesture\Src\gs_gesture.c',
                    'Modules\Ui\Src\gs_ui_render.c',
                    'App\Src\gs_timing_trace.c',
                    'Modules\Ui\Src\gs_ui.c', 'Modules\Vision\Src\gs_preprocess.c',
                    'Modules\Vision\Src\gs_ai.c', 'Modules\StaticRecognition\Src\gs_static_recognition.c',
                    'Modules\StaticRecognition\Src\gs_static_weights.c', 'Modules\Vision\Src\gs_ai_int8_backend.c')
    },
    @{
        Name = 'test_usb_firmware'
        Includes = @('Tests\usb_mocks', 'BSP\Inc', 'Modules\UsbCapture\Inc')
        Sources = @('Modules\UsbCapture\Src\gs_usb_protocol.c', 'Tests\test_usb_firmware.c')
    },
    @{
        Name = 'test_buffers'
        Includes = @('Modules\Camera\Inc', 'Modules\Display\Inc')
        Sources = @('Modules\Camera\Src\gs_camera_pool.c',
                    'Modules\Display\Src\gs_display_swap.c',
                    'Tests\test_buffers.c')
    },
    @{
        Name = 'test_gesture_ui'
        Includes = @('Modules\Gesture\Inc', 'Modules\Ui\Inc')
        Sources = @('Modules\Gesture\Src\gs_gesture.c',
                    'Modules\Ui\Src\gs_ui.c',
                    'Tests\test_gesture_ui.c')
    },
    @{
        Name = 'test_vision'
        Includes = @('Modules\Vision\Inc')
        Sources = @('Modules\Vision\Src\gs_preprocess.c',
                    'Modules\Vision\Src\gs_ai.c',
                    'Tests\test_vision.c')
    },
    @{
        Name = 'test_end_to_end'
        Includes = @('Modules\Camera\Inc', 'Modules\Display\Inc',
                     'Modules\Gesture\Inc', 'Modules\Preview\Inc', 'Modules\Ui\Inc',
                     'Modules\Vision\Inc', 'Modules\StaticRecognition\Inc')
        Sources = @('Modules\Camera\Src\gs_camera_pool.c',
                    'Modules\Display\Src\gs_display_swap.c',
                    'Modules\Gesture\Src\gs_gesture.c',
                    'Modules\Preview\Src\gs_preview.c',
                    'Modules\Ui\Src\gs_ui.c',
                    'Modules\Ui\Src\gs_ui_render.c',
                    'Modules\Vision\Src\gs_preprocess.c',
                    'Modules\Vision\Src\gs_ai.c', 'Modules\StaticRecognition\Src\gs_static_recognition.c',
                    'Modules\StaticRecognition\Src\gs_static_weights.c', 'Modules\Vision\Src\gs_ai_int8_backend.c',
                    'Tests\test_end_to_end.c')
    }
)
if ($SelectedSuites.Count -gt 0) {
    $SelectedSuites = @($SelectedSuites | ForEach-Object { $_ -split ',' })
    $unknown = @($SelectedSuites | Where-Object { $_ -notin $suites.Name })
    if ($unknown.Count -gt 0) { throw "Unknown host suite: $($unknown -join ', ')" }
    $suites = @($suites | Where-Object { $_.Name -in $SelectedSuites })
}

$batchLines = [System.Collections.Generic.List[string]]::new()
$batchLines.Add('@echo off')
$batchLines.Add('chcp 65001 > nul')
$batchLines.Add('setlocal EnableExtensions DisableDelayedExpansion')
$batchLines.Add('pushd "%~dp0"')
$batchLines.Add('if errorlevel 1 exit /b 1')
$batchLines.Add(('call {0} > "vcvars.log" 2>&1' -f $vcVarsQuoted))
$batchLines.Add('if errorlevel 1 (')
$batchLines.Add('  type "vcvars.log"')
$batchLines.Add('  exit /b 1')
$batchLines.Add(')')
# 清除继承的编译选项，防止 assert() 被关闭或混入额外参数。
# 只影响生成的批处理子进程，不修改调用者环境。
$batchLines.Add('set "CL="')
$batchLines.Add('set "_CL_="')

foreach ($suite in $suites) {
    $compilerArgs = [System.Collections.Generic.List[string]]::new()
    $compilerArgs.Add('cl /nologo /std:c11 /utf-8 /W4 /WX /UNDEBUG')
    if ($suite.Name -in @('test_int8_optimized','test_preview_pixels','test_ui_pixels')) { $compilerArgs.Add('/O2') }
    foreach ($include in $suite.Includes) {
        $includePath = Join-Path $projectRoot $include
        if (-not (Test-Path -LiteralPath $includePath -PathType Container)) {
            throw "Test include directory missing: $includePath"
        }
        $compilerArgs.Add('/I' + (ConvertTo-BatchQuotedPath $includePath))
    }
    if ($suite.ContainsKey('Defines')) {
        foreach ($define in $suite.Defines) { $compilerArgs.Add('/D' + $define) }
    }
    foreach ($source in $suite.Sources) {
        $sourcePath = Join-Path $projectRoot $source
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Test source missing: $sourcePath"
        }
        $compilerArgs.Add((ConvertTo-BatchQuotedPath $sourcePath))
    }
    $compilerArgs.Add(('/Fe:"{0}.exe"' -f $suite.Name))
    $buildLog = $suite.Name + '-build.log'
    $runLog = $suite.Name + '-run.log'
    $batchLines.Add(('echo Building {0}' -f $suite.Name))
    $batchLines.Add((($compilerArgs -join ' ') + ' > "' + $buildLog + '" 2>&1'))
    $batchLines.Add('if not "%errorlevel%"=="0" (')
    $batchLines.Add(('  type "{0}"' -f $buildLog))
    $batchLines.Add('  exit /b 1')
    $batchLines.Add(')')
    $batchLines.Add(('type "{0}"' -f $buildLog))
    $batchLines.Add(('"{0}.exe" > "{1}" 2>&1' -f $suite.Name, $runLog))
    $batchLines.Add('if not "%errorlevel%"=="0" (')
    $batchLines.Add(('  type "{0}"' -f $runLog))
    $batchLines.Add('  exit /b 1')
    $batchLines.Add(')')
    $batchLines.Add(('type "{0}"' -f $runLog))
}

$batchLines.Add(('echo All {0} selected host test suites passed.' -f $suites.Count))
$batchLines.Add('popd')
$batchLines.Add('exit /b 0')

New-Item -ItemType Directory -Force -Path $hostBuildRoot | Out-Null
& (Join-Path $projectRoot 'Tests\export_camera_irq.ps1') -Output (Join-Path $hostBuildRoot 'camera_irq_actual.inc')
& (Join-Path $projectRoot 'Tests\export_preview_display.ps1') -Output (Join-Path $hostBuildRoot 'preview_display_actual.inc')
$commandPath = Join-Path $hostBuildRoot 'run_host_tests.cmd'
[System.IO.File]::WriteAllLines($commandPath, $batchLines,
    [System.Text.UTF8Encoding]::new($false))

# 在构建目录调用固定文件名，无需将工程路径拼入命令字符串，
# 因此工程路径包含空格时也能使用。
Push-Location -LiteralPath $hostBuildRoot
try {
    & $env:ComSpec /d /c run_host_tests.cmd
    $testExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($testExitCode -ne 0) {
    throw "Host tests failed (exit $testExitCode). Logs: $hostBuildRoot"
}
Write-Host "Host test logs: $hostBuildRoot"
