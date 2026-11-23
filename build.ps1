# Build a standalone MesaDock.exe with PyInstaller.
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1
#
# The build runs in its own virtual environment (.venv-build) holding only the
# project's runtime dependencies, so the exe does not pick up whatever else is
# installed in the global Python (numpy, requests, ...). Only the asset files
# tracked by git are bundled, never local scratch folders under assets\.
#
# Output: dist\MesaDock.exe and dist\MesaDock-<version>.zip (exe + README in PT and EN).
# The exe is built into build\out first and then copied over dist\MesaDock.exe;
# if MesaDock is running, that copy fails and the build stops with an error
# instead of reporting success on the old file.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$root = $PSScriptRoot

function Fail($message) {
    Write-Host "ERRO: $message" -ForegroundColor Red
    exit 1
}

# 1. Isolated build environment ------------------------------------------------
$venv = Join-Path $root ".venv-build"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Criando ambiente de build em .venv-build..." -ForegroundColor Cyan
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Fail "nao foi possivel criar o ambiente virtual." }
}
Write-Host "Instalando dependencias no ambiente de build..." -ForegroundColor Cyan
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r (Join-Path $root "requirements.txt") "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { Fail "falha ao instalar as dependencias." }

# 2. Tests ---------------------------------------------------------------------
Write-Host "Rodando os testes..." -ForegroundColor Yellow
& $py -m pytest -q tests
if ($LASTEXITCODE -ne 0) { Fail "os testes falharam; o exe nao foi gerado." }

# 3. Stage only the tracked asset files ---------------------------------------
$stage = Join-Path $root "build\assets_stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
$tracked = git -C $root ls-files "mesadock/assets"
if ($LASTEXITCODE -ne 0 -or -not $tracked) { Fail "nao foi possivel listar os assets pelo git." }
foreach ($file in $tracked) {
    Copy-Item (Join-Path $root $file) $stage
}
$icon = Join-Path $stage "mesadock.ico"
if (-not (Test-Path $icon)) { Fail "mesadock\assets\mesadock.ico nao encontrado." }

# 4. PyInstaller -----------------------------------------------------------------
# A fresh work path avoids the "Access denied" rmtree failure that --clean can hit.
$workPath = Join-Path $root ("build\wp_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$outDir = Join-Path $root "build\out"
$built = Join-Path $outDir "MesaDock.exe"
if (Test-Path $built) { Remove-Item $built -Force }

Write-Host "Gerando MesaDock.exe..." -ForegroundColor Cyan
& $py -m PyInstaller `
    --noconfirm --onefile --windowed `
    --name MesaDock `
    --icon $icon `
    --add-data "$stage;mesadock/assets" `
    --hidden-import PIL._tkinter_finder `
    --collect-all mesadock.core `
    --collect-all mesadock.ui `
    --collect-all mesadock.win32 `
    --distpath $outDir --workpath $workPath --specpath (Join-Path $root "build") `
    (Join-Path $root "launcher.py")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $built)) { Fail "o PyInstaller nao gerou o exe." }

# 5. Publish to dist -------------------------------------------------------------
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force $dist | Out-Null
$exe = Join-Path $dist "MesaDock.exe"
try {
    Copy-Item $built $exe -Force
} catch {
    Fail "nao foi possivel substituir dist\MesaDock.exe. Feche o MesaDock e rode de novo. O exe novo esta em build\out\MesaDock.exe."
}

$version = & $py -c "import mesadock; print(mesadock.__version__)"
$zip = Join-Path $dist ("MesaDock-" + $version + ".zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $exe, (Join-Path $root "README.md"), (Join-Path $root "README.en.md") -DestinationPath $zip

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "Pronto: dist\MesaDock.exe ($size MB), versao $version" -ForegroundColor Green
Write-Host "Para enviar: $zip" -ForegroundColor Green
