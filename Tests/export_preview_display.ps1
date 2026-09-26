param([Parameter(Mandatory=$true)][string]$Output)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$text = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '..\BSP\Src\gs_port_board.c'))
$start = $text.IndexOf('/* GS_GUI_INCREMENTAL_BEGIN:', [StringComparison]::Ordinal)
$end = $text.IndexOf('gs_port_status_t gs_port_storage_step(', [StringComparison]::Ordinal)
if ($start -lt 0 -or $end -le $start) { throw 'Expected exactly one complete actual BSP GUI renderer block' }
$actual = $text.Substring($start, $end - $start)
[IO.File]::WriteAllText($Output, ("/* Actual production renderer, extracted unchanged. */`n" + $actual + "`n"), [Text.UTF8Encoding]::new($false))
