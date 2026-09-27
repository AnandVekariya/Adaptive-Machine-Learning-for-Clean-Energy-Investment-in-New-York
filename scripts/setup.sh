#!/usr/bin/env bash
# Create the conda environment on Linux or macOS.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

if command -v mamba >/dev/null 2>&1; then
  mamba env create -f environment.yml --yes || mamba env update -f environment.yml --yes
elif command -v conda >/dev/null 2>&1; then
  conda env create -f environment.yml || conda env update -f environment.yml
else
  echo "Install Miniforge first: https://github.com/conda-forge/miniforge"
  echo "Then re-run: bash scripts/setup.sh"
  exit 1
fi

echo
echo "Activate and check:"
echo "  conda activate clean-energy-ny"
echo "  python scripts/check_setup.py"
