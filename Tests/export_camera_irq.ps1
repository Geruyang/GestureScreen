param(
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$Source = (Join-Path $PSScriptRoot '..\BSP\Src\gs_port_board.c')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$text = [IO.File]::ReadAllText($Source)
$parts = @('/* Extracted unchanged production C; do not edit this generated file. */')
foreach ($name in @('gs_board_dma_irq', 'HAL_DCMI_FrameEventCallback', 'HAL_DCMI_ErrorCallback',
                    'camera_quiesce', 'gs_port_camera_poll', 'gs_port_camera_release')) {
    $pattern = '(?ms)^\w[^\r\n]*\b' + [regex]::Escape($name) + '\([^\r\n]*\)\r?\n\{.*?^\}'
    $matches = [regex]::Matches($text, $pattern)
    if ($matches.Count -ne 1) { throw "Expected one complete production function: $name" }
    $parts += $matches[0].Value
}
$hal = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '..\Drivers\STM32F4xx_HAL_Driver\Inc\stm32f4xx_hal_dma.h'))
$macro = [regex]::Match($hal, '(?m)^#define __HAL_DMA_GET_IT_SOURCE[^\r\n]*\r?\n[^\r\n]*\r?\n[^\r\n]*')
if (-not $macro.Success) { throw 'Actual HAL interrupt-source macro missing' }
[IO.File]::WriteAllText($Output, ($macro.Value + "`n" + ($parts -join "`n`n") + "`n"), [Text.UTF8Encoding]::new($false))
