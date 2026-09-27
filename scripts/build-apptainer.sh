#!/usr/bin/env bash
# Optional HPC image (Linux with Apptainer/Singularity).
# Desktop users should use environment.yml instead.
# Usage: bash scripts/build-apptainer.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OUT="${1:-clean-energy-ml.sif}"
DEF="apptainer/clean-energy-ml.def"

echo "Building Apptainer image: $OUT"
echo "Definition: $DEF"

if command -v apptainer >/dev/null 2>&1; then
  RUNTIME=apptainer
elif command -v singularity >/dev/null 2>&1; then
  RUNTIME=singularity
else
  echo "Error: apptainer or singularity not found." >&2
  exit 1
fi

# --fakeroot helps on shared HPC login nodes; drop it if your site disallows it.
$RUNTIME build --fakeroot "$OUT" "$DEF"

echo "Done. Run example:"
echo "  $RUNTIME exec -B \$PWD:\$PWD $OUT python scripts/check_setup.py"
echo "  $RUNTIME exec -B \$PWD:\$PWD $OUT python scripts/rebuild_v7_consistency_figures.py"
