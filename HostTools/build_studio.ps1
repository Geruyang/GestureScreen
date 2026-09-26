[CmdletBinding()]
param(
    [switch]$Clean,
    [ValidateSet('reader-clean-exit-20260923','reader-portable-path-20260923','reader-capture-all-20260922','reader-selection-20260922','reader-direction-20260922','reader-polish-20260922')]
    [string]$ReleaseName='reader-clean-exit-20260923'
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$py=Join-Path $root 'Build/studio-venv/Scripts/python.exe'
if(-not(Test-Path $py)){throw "Missing project-local studio-venv: $py"}
$release=Join-Path $root (Join-Path 'Build' $ReleaseName)
$dist=Join-Path $release 'dist'
New-Item -ItemType Directory -Force -Path $release | Out-Null
$dist=(Resolve-Path (Split-Path $dist) -ErrorAction Stop).Path + '\dist'
$workspace=(Resolve-Path $root).Path
if($Clean -and (Test-Path $dist)){
    $resolved=(Resolve-Path $dist).Path
    if(-not $resolved.StartsWith(($workspace+'\'),[StringComparison]::OrdinalIgnoreCase)){throw "Refusing to clean outside workspace: $resolved"}
    if(-not ($resolved -eq ($workspace+'\Build\'+$ReleaseName+'\dist'))){throw "Refusing unexpected clean target: $resolved"}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
New-Item -ItemType Directory -Force $dist | Out-Null
Push-Location $PSScriptRoot
try { & $py -m PyInstaller --noconfirm --clean --distpath $dist --workpath (Join-Path $release 'pyinstaller-work') studio.spec; if($LASTEXITCODE -ne 0){throw "PyInstaller failed: $LASTEXITCODE"} }
finally { Pop-Location }
