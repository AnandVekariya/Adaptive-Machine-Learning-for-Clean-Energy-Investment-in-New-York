#!/usr/bin/env python3
"""Run notebooks 00–15 with the current Python. Works on Windows, macOS, Linux.

Default: local jupyter nbconvert. Pass --container or set USE_APPTAINER=1
only if you built clean-energy-ml.sif.

  python scripts/run_pipeline.py
  python scripts/run_pipeline.py --timeout 7200
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NOTEBOOKS = [
    "00_temporal_parity_qa.ipynb",
    "01_ingest_weather.ipynb",
    "01b_physics_hourly_yield.ipynb",
    "02_nlcd_zonal_stats.ipynb",
    "04_grid_transmission_distance.ipynb",
    "03_eia_cf_targets.ipynb",
    "05_build_master_table.ipynb",
    "06_gateway_filter.ipynb",
    "07_solar_resource_model.ipynb",
    "08_wind_resource_model.ipynb",
    "09_combine_resource_scores.ipynb",
    "10_yield_engine.ipynb",
    "11_hybrid_seasonal_suitability.ipynb",
    "12_risk_stress_p90.ipynb",
    "13_composite_score.ipynb",
    "14_export_gis_and_tables.ipynb",
    "15_pipeline_validation.ipynb",
]


def run(cmd: list[str]) -> None:
    print("=====", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute pipeline notebooks 00–15.")
    parser.add_argument("--timeout", type=int, default=7200, help="Seconds per notebook")
    parser.add_argument(
        "--container",
        action="store_true",
        help="Force Apptainer/Singularity even if local Python works",
    )
    args = parser.parse_args()

    (ROOT / "logs").mkdir(exist_ok=True)
    sif = ROOT / "clean-energy-ml.sif"
    runtime = shutil.which("apptainer") or shutil.which("singularity")
    use_sif = args.container or os.environ.get("USE_APPTAINER") == "1"

    for name in NOTEBOOKS:
        nb = ROOT / "src" / "pipeline" / name
        if not nb.exists():
            print(f"Missing {nb}", file=sys.stderr)
            return 1
        if use_sif and runtime and sif.exists():
            run(
                [
                    runtime,
                    "exec",
                    str(sif),
                    "jupyter",
                    "nbconvert",
                    "--to",
                    "notebook",
                    "--execute",
                    f"--ExecutePreprocessor.timeout={args.timeout}",
                    "--inplace",
                    str(nb.relative_to(ROOT)),
                ]
            )
        else:
            run(
                [
                    sys.executable,
                    "-m",
                    "jupyter",
                    "nbconvert",
                    "--to",
                    "notebook",
                    "--execute",
                    f"--ExecutePreprocessor.timeout={args.timeout}",
                    "--inplace",
                    str(nb),
                ]
            )

    geo = ROOT / "outputs" / "ny_composite_ranked.geojson"
    if geo.exists():
        print("Done.", geo)
    else:
        print("Done, but outputs/ny_composite_ranked.geojson is missing — check notebooks 13/14.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
