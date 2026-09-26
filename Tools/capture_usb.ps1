#requires -Version 5.1
param(
    [string]$Port,
    [switch]$ListPorts,
    [string]$Python = '',
    [string]$Output = '',
    [ValidateRange(1,65535)][int]$HttpPort = 8765
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $projectRoot 'Build\studio-venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'USB runtime missing. See HostTools/README.md setup instructions or pass -Python.' }
$captureArgs = @((Join-Path $projectRoot 'HostTools\capture_server.py'))
if ($ListPorts) {
    $captureArgs += '--list-usb'
} else {
    if (-not $Port) { $Port = 'auto' }
    $captureArgs += @('--usb-port',$Port,'--port',"$HttpPort")
    if ($Output) { $captureArgs += @('--output',$Output) }
}
& $Python -X utf8 @captureArgs
if ($LASTEXITCODE -ne 0) { throw 'USB capture service failed' }
