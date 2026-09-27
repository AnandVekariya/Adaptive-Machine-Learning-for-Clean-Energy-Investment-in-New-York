# Create the conda environment on Windows (PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (Get-Command mamba -ErrorAction SilentlyContinue) {
    mamba env create -f environment.yml --yes
    if ($LASTEXITCODE -ne 0) { mamba env update -f environment.yml --yes }
}
elseif (Get-Command conda -ErrorAction SilentlyContinue) {
    conda env create -f environment.yml
    if ($LASTEXITCODE -ne 0) { conda env update -f environment.yml }
}
else {
    Write-Host "Install Miniforge first: https://github.com/conda-forge/miniforge"
    Write-Host "Then re-run: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1"
    exit 1
}

Write-Host ""
Write-Host "Activate and check:"
Write-Host "  conda activate clean-energy-ny"
Write-Host "  python scripts/check_setup.py"
