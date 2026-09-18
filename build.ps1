# Build a lightweight standalone exe into dist\ (single file, no torch).
# Run from the repo root:  .\build.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
}
& $py -m PyInstaller --clean --noconfirm (Join-Path $root "build.spec")
Write-Host "Done. See dist\DataMatrixVerifier.exe"
