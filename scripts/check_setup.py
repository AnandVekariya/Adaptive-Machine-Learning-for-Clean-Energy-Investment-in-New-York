#!/usr/bin/env python3
"""Check that this machine can run the paper scripts. Works on Windows, macOS, Linux.

Safe to run on old system Python: it prints a clear install hint instead of a
SyntaxError.
"""
import importlib
import platform
import sys

try:
    from pathlib import Path
except ImportError:
    Path = None


NEEDED = [
    "yaml",
    "pandas",
    "numpy",
    "pyarrow",
    "geopandas",
    "rasterio",
    "rasterstats",
    "pyproj",
    "shapely",
    "sklearn",
    "xgboost",
    "polars",
    "matplotlib",
    "seaborn",
    "plotly",
    "scipy",
    "joblib",
]


def _root():
    if Path is None:
        return None
    return Path(__file__).resolve().parents[1]


def main():
    print("Python %s  (%s)" % (sys.version.split()[0], sys.executable))
    print("OS     %s %s  %s" % (platform.system(), platform.release(), platform.machine()))
    root = _root()
    if root is not None:
        print("Repo   %s" % root)
    print("")

    if sys.version_info < (3, 11):
        print("Need Python 3.11 or newer (3.12 recommended).")
        print("Do not use the system Python. Install Miniforge and run:")
        print("  conda env create -f environment.yml")
        print("  conda activate clean-energy-ny")
        print("  python scripts/check_setup.py")
        return 1

    missing = []
    for name in NEEDED:
        try:
            mod = importlib.import_module(name)
            ver = getattr(mod, "__version__", "")
            print("  ok  %-14s %s" % (name, ver))
        except Exception as exc:
            missing.append(name)
            print("  --  %-14s %s" % (name, exc.__class__.__name__))

    processed = root / "data" / "processed" / "cell_composite_score.parquet"
    config = root / "config" / "config.yaml"
    print("")
    print("  config.yaml          %s" % ("ok" if config.exists() else "MISSING"))
    print("  processed composite  %s" % ("ok" if processed.exists() else "MISSING"))

    if missing:
        print("")
        print("Missing packages: %s" % ", ".join(missing))
        print("Install one of:")
        print("  conda env create -f environment.yml && conda activate clean-energy-ny")
        print("  python -m pip install -r requirements.txt")
        print("On Windows, conda-forge is the reliable way to get GDAL/geopandas.")
        return 1

    print("")
    print("Setup looks good. Next:")
    print("  python scripts/rebuild_v7_consistency_figures.py")
    print("  python scripts/run_pipeline.py          # full notebooks; needs raw data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
