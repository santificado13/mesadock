# Build a standalone MesaDock.exe with PyInstaller.
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1
#
# The build runs from launcher.py, a two-line wrapper around mesadock.__main__, so
# the frozen bundle never re-enters the package's __main__ guard. Asset and icon
# paths are absolute: PyInstaller resolves relative --add-data paths against
# --specpath, not against the current directory.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Installing PyInstaller..." -ForegroundColor Cyan
    python -m pip install --upgrade pyinstaller
}

Write-Host "A executar Testes (pytest) antes do build..." -ForegroundColor Yellow
python -m pytest tests/
if ($LASTEXITCODE -ne 0) {
    Write-Error "Testes falharam! Executável nao será gerado para evitar regressões."
    exit $LASTEXITCODE
}
Write-Host "Testes validados com sucesso!" -ForegroundColor Green

$root = $PSScriptRoot
$assets = Join-Path $root "mesadock\assets"
$icon = Join-Path $assets "mesadock.ico"
# path avoids the "Access denied" rmtree failure that --clean can hit.
$workPath = Join-Path $root ("build\wp_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

Write-Host "Building MesaDock.exe..." -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm --onefile --windowed `
    --name MesaDock `
    --icon $icon `
    --add-data "$assets;mesadock/assets" `
    --hidden-import PIL._tkinter_finder `
    --collect-all mesadock.core `
    --collect-all mesadock.ui `
    --collect-all mesadock.win32 `
    --distpath (Join-Path $root "dist") --workpath $workPath --specpath (Join-Path $root "build") `
    (Join-Path $root "launcher.py")

$exe = Join-Path $root "dist\MesaDock.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "Built dist\MesaDock.exe ($size MB)" -ForegroundColor Green
} else {
    Write-Error "Build failed - dist\MesaDock.exe was not produced."
}