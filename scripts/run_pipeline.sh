#!/usr/bin/env bash
# Run notebooks 00–15. Prefers local Python; uses Apptainer if --container
# or clean-energy-ml.sif + apptainer are present and USE_APPTAINER=1.
#
#   bash scripts/run_pipeline.sh
#   python scripts/run_pipeline.py
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
if command -v python >/dev/null 2>&1; then
  exec python scripts/run_pipeline.py "$@"
fi
exec python3 scripts/run_pipeline.py "$@"
