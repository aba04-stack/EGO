# Run from the repository root in Windows PowerShell.
$ErrorActionPreference = "Stop"

python --version
if ($LASTEXITCODE -ne 0) { throw "Python 3 is required." }

python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

python -m pip install -e ".[package]"
if ($LASTEXITCODE -ne 0) { throw "Application dependency installation failed." }

python -m compileall -q src run_app.py
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed." }

python -m PyInstaller --noconfirm --clean --onefile --windowed --name EGO --paths src --collect-submodules keyring.backends --add-data "src/alterego_training_hub/assets/fonts;alterego_training_hub/assets/fonts" run_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

Write-Host ""
Write-Host "Build complete: dist\AlterEgoTrainingHub.exe"
