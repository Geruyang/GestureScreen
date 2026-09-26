param(
  [string]$Python = 'python',
  [string]$Node = 'node'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $projectRoot 'Build\capture-tests'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
foreach ($runtime in @($Python, $Node)) {
  if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {
    throw "Runtime not found: $runtime. Pass -Python/-Node explicitly."
  }
}
& $Python -X utf8 (Join-Path $projectRoot 'Tests\test_capture_server.py') 2>&1 |
  Tee-Object -FilePath (Join-Path $logDir 'http.log')
if ($LASTEXITCODE -ne 0) { throw 'Capture HTTP regression failed.' }
& $Python -X utf8 (Join-Path $projectRoot 'Tests\test_usb_capture.py') 2>&1 |
  Tee-Object -FilePath (Join-Path $logDir 'usb.log')
if ($LASTEXITCODE -ne 0) { throw 'USB capture regression failed.' }
& $Node (Join-Path $projectRoot 'Tests\test_capture_ui.cjs') 2>&1 |
  Tee-Object -FilePath (Join-Path $logDir 'ui.log')
if ($LASTEXITCODE -ne 0) { throw 'Capture UI logic regression failed.' }
Write-Host 'Capture regression passed (synthetic frames / mock DOM, no hardware).'
