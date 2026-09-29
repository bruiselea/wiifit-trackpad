[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$spec = Join-Path $workspace 'packaging\WiiFitGiantTrackpad.spec'
$dist = Join-Path $workspace 'dist'
$work = Join-Path $workspace 'build\pyinstaller'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment was not found: $python"
}

Push-Location $workspace
try {
    & $python -m pip install -r (Join-Path $workspace 'requirements-release.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Release dependencies failed to install.' }

    & $python -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed.' }

    & $python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $work $spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

    Write-Host "Application: $(Join-Path $dist 'WiiFitGiantTrackpad\WiiFitGiantTrackpad.exe')"
} finally {
    Pop-Location
}

