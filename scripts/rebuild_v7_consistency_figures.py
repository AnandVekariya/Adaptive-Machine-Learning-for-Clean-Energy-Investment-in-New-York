#!/usr/bin/env python3
"""Rebuild the v7 journal figures from processed pipeline outputs.

Plot titles are stripped after save so captions live in the paper only.
Run (any OS, after conda activate clean-energy-ny):
  python scripts/rebuild_v7_consistency_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import yaml
from pyproj import Transformer
from scipy import stats
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config" / "config.yaml").read_text())
_P = CFG["paths"]

PROC = ROOT / _P["data"]["processed_dir"]
REF = ROOT / _P["data"]["ref_dir"]
FIG = ROOT / _P["results_figures"]
OUT_ANAL = ROOT / _P["results_analysis"]
OUT_TABLES = ROOT / _P["results_tables"]
RANDOM_STATE = int(CFG["random"]["seed"])
BOOT_N = int(CFG["bootstrap"]["n_boot"])
BOOT_SEED = int(CFG["bootstrap"]["seed"])
# Persona/ablation sensitivity table uses a fixed 800-draw CI (not BOOT_N).
SENS_BOOT = 800
CW = CFG["composite"]["weights"]

FIG.mkdir(parents=True, exist_ok=True)
OUT_ANAL.mkdir(parents=True, exist_ok=True)
OUT_TABLES.mkdir(parents=True, exist_ok=True)

# Caption-only figures: strip matplotlib titles after save helpers run.
NO_EMBEDDED_TITLES = True
DPI = 300

C_BLUE = "#1F4E79"
C_ACCENT = "#C45911"
C_TEAL = "#2A9D8F"
C_MUTED = "#8D99AE"
C_PASS = "#52B788"
C_FAIL = "#E76F51"
C_SOFT = "#F0F4F8"

sns.set_theme(style="whitegrid", context="paper")


def _strip_titles(fig: plt.Figure) -> None:
    """Drop embedded titles so LaTeX captions stand alone."""
    if not NO_EMBEDDED_TITLES:
        return
    try:
        fig.suptitle("")
    except Exception:
        pass
    for ax in fig.get_axes():
        ax.set_title("")


def save(fig: plt.Figure, name: str) -> Path:
    _strip_titles(fig)
    path = FIG / name
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {name}")
    return path


def load_json(name: str) -> dict:
    return json.loads((PROC / name).read_text())


def rank_pct(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True) * 100.0


def corridor_label(lat: float, lon: float) -> str:
    """Corridor labels from coordinates (deterministic)."""
    # Southern Tier / Steuben–Allegany cluster
    if 41.9 <= lat <= 42.35 and -78.1 <= lon <= -77.3:
        if lon <= -77.75:
            return "Hornell–west Steuben/Allegany"
        if lon <= -77.68:
            return "Hornell–Avoca corridor"
        if lon <= -77.60:
            return "Avoca–Bath mid corridor"
        if lon <= -77.50:
            return "Bath–Avoca corridor"
        return "Addison corridor"
    if 41.75 <= lat <= 42.05 and -75.2 <= lon <= -74.6:
        return "Grahamsville / Catskills"
    return f"Cell ({lat:.2f}, {lon:.2f})"


def attach_counties(pdf: pd.DataFrame, counties_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """County attribution for lat/lon points (vectorized + nearest fallback)."""
    g = gpd.GeoDataFrame(
        pdf.copy(),
        geometry=[Point(xy) for xy in zip(pdf.longitude, pdf.latitude)],
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(g, counties_gdf[["NAME", "geometry"]], how="left", predicate="within")
    if joined.index.duplicated().any():
        joined = joined[~joined.index.duplicated(keep="first")]
    missing = joined["NAME"].isna()
    if missing.any():
        counties_utm = counties_gdf.to_crs(32618)
        pts_utm = joined.loc[missing].to_crs(32618)
        names = []
        for geom in pts_utm.geometry:
            dists = counties_utm.distance(geom)
            names.append(str(counties_utm.loc[dists.idxmin(), "NAME"]))
        joined.loc[missing, "NAME"] = names
    out = pdf.copy()
    out["county"] = joined["NAME"].astype(str).values
    return out


def add_north_arrow(ax, x=0.92, y=0.88):
    ax.annotate(
        "N",
        xy=(x, y),
        xytext=(x, y - 0.08),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="center",
        fontsize=10,
        fontweight="bold",
        arrowprops=dict(arrowstyle="-|>", color="black", lw=1.2),
    )


def add_scale_bar(ax, length_km=50, location=(0.08, 0.08)):
    """Approximate scale bar in projected meters (UTM)."""
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    x0 = xlim[0] + (xlim[1] - xlim[0]) * location[0]
    y0 = ylim[0] + (ylim[1] - ylim[0]) * location[1]
    length_m = length_km * 1000
    ax.plot([x0, x0 + length_m], [y0, y0], color="black", lw=2.5, solid_capstyle="butt")
    ax.plot([x0, x0], [y0 - length_m * 0.02, y0 + length_m * 0.02], color="black", lw=1.5)
    ax.plot(
        [x0 + length_m, x0 + length_m],
        [y0 - length_m * 0.02, y0 + length_m * 0.02],
        color="black",
        lw=1.5,
    )
    ax.text(
        x0 + length_m / 2,
        y0 + length_m * 0.04,
        f"{length_km} km",
        ha="center",
        va="bottom",
        fontsize=8,
    )


def gateway_exclusion_items(fail_counts: dict) -> list:
    """Bar labels/values for gateway exclusion chart (report counts)."""
    return [
        ("Low developability (D)", fail_counts["fail_low_D"]),
        ("Missing NLCD", fail_counts["fail_no_nlcd"]),
        ("Too developed", fail_counts["fail_developed"]),
        ("Too much water", fail_counts["fail_water"]),
        ("Too much wetland", fail_counts["fail_wetland"]),
        ("Ice/snow", fail_counts["fail_ice"]),
    ]


def spearman_ci(x, y, n_boot=None, seed=None):
    n_boot = BOOT_N if n_boot is None else n_boot
    seed = BOOT_SEED if seed is None else seed
    rho = float(stats.spearmanr(x, y).correlation)
    rng = np.random.default_rng(seed)
    boots = []
    idx = np.arange(len(x))
    for _ in range(n_boot):
        b = rng.choice(idx, size=len(idx), replace=True)
        boots.append(stats.spearmanr(x.iloc[b], y.iloc[b]).correlation)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return rho, float(lo), float(hi)


def top10_coord_overlap(df: pd.DataFrame, col_a: str, col_b: str) -> int:
    """Count shared lat/lon pairs in the top-10 of two score columns."""
    a = set(df.nlargest(10, col_a)[["latitude", "longitude"]].apply(tuple, axis=1))
    b = set(df.nlargest(10, col_b)[["latitude", "longitude"]].apply(tuple, axis=1))
    return len(a & b)


def weight_table_row(scheme: str, w: dict, notes: str) -> dict:
    return {
        "scheme": scheme,
        "resource_R": w["resource"],
        "seasonal": w["seasonal"],
        "P50_yield": w["yield"],
        "risk": w["risk"],
        "land_D": w["land"],
        "notes": notes,
    }


def main() -> None:
    # ---------------------------------------------------------------------------
    # Data load
    # ---------------------------------------------------------------------------
    comp = pd.read_parquet(PROC / "cell_composite_score.parquet")
    res = pd.read_parquet(PROC / "cell_resource_scores.parquet")
    hyb = pd.read_parquet(PROC / "hybrid_suitability.parquet")
    risk = pd.read_parquet(PROC / "cell_risk_spread.parquet")
    gw_pass = pd.read_parquet(PROC / "cells_passing_gateway.parquet")
    master = pd.read_parquet(PROC / "modeling_master_cell.parquet")
    weather = pd.read_parquet(PROC / "weather_cell_features.parquet")
    eia = pd.read_parquet(PROC / "eia_facility_features.parquet")
    counties = gpd.read_file(REF / "ny_counties_2021.geojson")
    # Keep NY (STATE FIPS 36) when a national counties file is present
    if "STATE" in counties.columns:
        counties = counties[counties["STATE"].astype(str).str.zfill(2) == "36"].copy()
    ny_bound = gpd.read_file(REF / "ny_state_boundary.geojson")
    gw_report = load_json("gateway_filter_report.json")
    solar_cv = load_json("solar_resource_cv_report.json")
    wind_cv = load_json("wind_resource_cv_report.json")
    comp_report = load_json("composite_score_report.json")
    risk_report = load_json("risk_stress_report.json")

    df = comp.merge(
        res[
            [
                "latitude",
                "longitude",
                "solar_resource_observed_pct",
                "wind_resource_observed_pct",
                "hybrid_screening_score",
                "solar_resource_observed",
                "wind_resource_observed",
                "solar_resource_land_adj_oof",
                "wind_resource_land_adj_oof",
            ]
        ],
        on=["latitude", "longitude"],
        how="left",
        suffixes=("", "_r"),
    )
    df = df.merge(
        hyb[["latitude", "longitude", "summer_ghi_pct", "winter_wind_pct", "hybrid_seasonal_score"]],
        on=["latitude", "longitude"],
        how="left",
        suffixes=("", "_h"),
    )

    n_scored = len(df)

    # Counties + corridor labels for top ranks
    top = df.sort_values("composite_score", ascending=False).copy()
    top["rank"] = np.arange(1, len(top) + 1)
    top10 = top.head(10).copy()
    top10 = attach_counties(top10.drop(columns=["county"], errors="ignore"), counties)
    top10["corridor_label"] = [corridor_label(r.latitude, r.longitude) for _, r in top10.iterrows()]
    top10[
        [
            "rank",
            "corridor_label",
            "county",
            "latitude",
            "longitude",
            "composite_score",
            "jackpot_zone",
            "dist_to_transmission_km",
        ]
    ].to_csv(OUT_ANAL / "top10_reconciled.csv", index=False)
    (OUT_TABLES / "top10_reconciled.csv").write_text((OUT_ANAL / "top10_reconciled.csv").read_text())

    # ---------------------------------------------------------------------------
    # 1. Funnel: canonical 4401 -> 2223 -> 1089
    # ---------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    stages = [
        ("Weather grid\n(study extent)", gw_report["input_cells"]),
        ("Pass developability\ngateway", gw_report["cells_passing"]),
        ("NY cells fully\nscored (shortlist)", gw_report["cells_passing_in_ny"]),
    ]
    labels, vals = zip(*stages)
    colors = [C_BLUE, C_TEAL, C_ACCENT]
    bars = ax.barh(list(labels)[::-1], list(vals)[::-1], color=list(colors)[::-1], height=0.55, edgecolor="white")
    for bar, v in zip(bars, list(vals)[::-1]):
        ax.text(bar.get_width() + 50, bar.get_y() + bar.get_height() / 2, f"{v:,}", va="center", fontweight="bold", fontsize=11)
    ax.set_xlabel("Number of ~10 km cells", fontsize=11)
    ax.set_xlim(0, max(vals) * 1.18)
    note = (
        f"Context only (not an alternate funnel): {gw_report['cells_in_ny']:,} weather cells fall inside NY; "
        f"{gw_report['cells_passing_in_ny']:,} of them pass the gateway."
    )
    ax.text(0.0, -0.22, note, transform=ax.transAxes, fontsize=9, color="0.35")
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "01_cell_funnel.png")

    # ---------------------------------------------------------------------------
    # 2. Gateway exclusions with ice/snow + overlap numerics
    # ---------------------------------------------------------------------------
    # Reconstruct fail flags on full master (passing parquet has survivors only)
    thr = gw_report["thresholds"]
    wts = gw_report["weights"]
    m = master.copy()
    for code in [11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 81, 82, 90, 95]:
        col = f"frac_class_{code}"
        if col not in m.columns:
            m[col] = 0.0
    m["frac_agriculture"] = m[["frac_class_81", "frac_class_82"]].fillna(0).sum(axis=1)
    m["frac_barren"] = m["frac_class_31"].fillna(0)
    m["frac_dev_open"] = m["frac_class_21"].fillna(0)
    m["frac_forest"] = m[["frac_class_41", "frac_class_42", "frac_class_43"]].fillna(0).sum(axis=1)
    m["frac_wetland"] = m[["frac_class_90", "frac_class_95"]].fillna(0).sum(axis=1)
    m["frac_developed"] = m[[f"frac_class_{c}" for c in (21, 22, 23, 24)]].fillna(0).sum(axis=1)
    m["frac_water"] = m["frac_class_11"].fillna(0)
    m["frac_ice"] = m["frac_class_12"].fillna(0)
    raw = (
        wts["W_AG"] * m["frac_agriculture"]
        + wts["W_BARREN"] * m["frac_barren"]
        + wts["W_OPEN"] * m["frac_dev_open"]
        - wts["W_FOREST"] * m["frac_forest"]
        - wts["W_WET"] * m["frac_wetland"]
    )
    d_min, d_max = float(raw.min()), float(raw.max())
    m["developability_D"] = (raw - d_min) / (d_max - d_min if d_max != d_min else 1.0)
    fails = pd.DataFrame(
        {
            "fail_water": m["frac_water"] > thr["WATER_FRAC_MAX"],
            "fail_developed": m["frac_developed"] > thr["DEVELOPED_FRAC_MAX"],
            "fail_wetland": m["frac_wetland"] > thr["WETLAND_FRAC_MAX"],
            "fail_ice": m["frac_ice"] > thr["ICE_FRAC_MAX"],
            "fail_low_D": m["developability_D"] < thr["D_MIN"],
            "fail_no_nlcd": m["nlcd_pixel_count"].fillna(0) == 0,
        }
    )
    master = m
    overlap_summary = {}
    items = gateway_exclusion_items(gw_report["fail_counts"])
    if fails is not None and fails.shape[1] >= 4:
        rule_names = {
            "fail_water": "Water >50%",
            "fail_developed": "Developed >20%",
            "fail_wetland": "Wetland >30%",
            "fail_ice": "Ice/snow >30%",
            "fail_low_D": "Low D (<0.20)",
            "fail_no_nlcd": "Missing NLCD",
        }
        present = [c for c in rule_names if c in fails.columns]
        counts = fails[present].sum().astype(int)
        n_any = int(fails[present].any(axis=1).sum())
        n_multi = int((fails[present].sum(axis=1) >= 2).sum())
        exclusive = {}
        for c in present:
            mask = fails[c]
            others = fails[[x for x in present if x != c]].any(axis=1)
            exclusive[c] = int((mask & ~others).sum())
        overlap_summary = {
            "n_cells": int(len(fails)),
            "n_fail_any": n_any,
            "n_fail_multiple_rules": n_multi,
            "counts": {rule_names[c]: int(counts[c]) for c in present},
            "exclusive_counts": {rule_names[c]: exclusive[c] for c in present},
            "report_fail_counts": gw_report["fail_counts"],
        }
        fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6), gridspec_kw={"width_ratios": [1.35, 1]})
        labs, vs = zip(*items)
        axes[0].barh(list(labs)[::-1], list(vs)[::-1], color=C_FAIL, alpha=0.9, height=0.55)
        for y, v in enumerate(list(vs)[::-1]):
            axes[0].text(v + 8, y, f"{v:,}", va="center", fontsize=10)
        axes[0].set_xlabel("Cells triggering rule (rules may overlap)", fontsize=11)
        axes[0].spines[["top", "right"]].set_visible(False)

        axes[1].axis("off")
        txt = [
            f"Any-rule failures: {n_any:,}",
            f"Fail ≥2 rules: {n_multi:,} ({100*n_multi/max(n_any,1):.1f}% of failures)",
            "",
            "Exclusive failures (only this rule):",
        ]
        for c in present:
            txt.append(f"  • {rule_names[c]}: {exclusive[c]:,}")
        axes[1].text(
            0.02,
            0.95,
            "\n".join(txt),
            va="top",
            ha="left",
            fontsize=10,
            family="monospace",
            transform=axes[1].transAxes,
            bbox=dict(boxstyle="round", facecolor=C_SOFT, edgecolor=C_BLUE, alpha=0.95),
        )
        save(fig, "02_gateway_exclusions.png")
    else:
        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        labs, vs = zip(*items)
        ax.barh(list(labs)[::-1], list(vs)[::-1], color=C_FAIL, alpha=0.9, height=0.55)
        for y, v in enumerate(list(vs)[::-1]):
            ax.text(v + 8, y, f"{v:,}", va="center", fontsize=10)
        ax.set_xlabel("Cells triggering rule (may overlap)", fontsize=11)
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "02_gateway_exclusions.png")
        overlap_summary = {"report_fail_counts": gw_report["fail_counts"], "note": "overlap rebuild partial"}

    (OUT_ANAL / "gateway_overlap_summary.json").write_text(json.dumps(overlap_summary, indent=2))

    # ---------------------------------------------------------------------------
    # 3. Diverging bar weights — caption-only
    # ---------------------------------------------------------------------------
    weights = [
        ("Resource R", CW["resource"]),
        ("Exploratory P50", CW["yield"]),
        ("Seasonal", CW["seasonal"]),
        ("Developability D", CW["land"]),
        ("Risk spread", -CW["risk"]),
    ]
    fig, ax = plt.subplots(figsize=(7.8, 4.2))
    names, vals = zip(*weights)
    colors = [C_TEAL if v > 0 else C_FAIL for v in vals]
    ax.barh(names[::-1], vals[::-1], color=colors[::-1], edgecolor="white", height=0.55)
    ax.axvline(0, color="black", lw=1)
    for i, v in enumerate(vals[::-1]):
        ax.text(v + (0.01 if v >= 0 else -0.01), i, f"{v:+.2f}", va="center", ha="left" if v >= 0 else "right", fontsize=11)
    ax.set_xlabel("Heuristic weight in Eq. (S)", fontsize=11)
    ax.set_xlim(-0.2, 0.45)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "08_composite_weights.png")

    # ---------------------------------------------------------------------------
    # 4. Fold-level OOF R2
    # ---------------------------------------------------------------------------
    solar_folds = [f["r2"] for f in solar_cv["cv_folds"]]
    wind_folds = [f["r2"] for f in wind_cv["cv_folds"]]
    solar_pooled = float(solar_cv["cv_land_adjusted_oof"]["r2"])
    wind_pooled = float(wind_cv["cv_land_adjusted_oof"]["r2"])
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    data = [solar_folds, wind_folds]
    bp = ax.boxplot(data, labels=["Solar resource", "Wind resource"], patch_artist=True, widths=0.45)
    for patch, c in zip(bp["boxes"], [C_ACCENT, C_TEAL]):
        patch.set_facecolor(c)
        patch.set_alpha(0.55)
    rng = np.random.default_rng(RANDOM_STATE)
    for i, (folds, c, pooled, mean) in enumerate(
        zip(data, [C_ACCENT, C_TEAL], [solar_pooled, wind_pooled], [np.mean(solar_folds), np.mean(wind_folds)]),
        start=1,
    ):
        x = rng.normal(i, 0.04, size=len(folds))
        ax.scatter(x, folds, color=c, s=48, zorder=3, edgecolor="white", label="Fold $R^2$" if i == 1 else None)
        ax.hlines(mean, i - 0.18, i + 0.18, colors="black", lw=2.2, zorder=4)
        ax.annotate(
            f"fold mean={mean:.2f}",
            xy=(i + 0.22, mean),
            fontsize=8,
            va="center",
            color="0.15",
        )
        ax.scatter([i], [pooled], marker="D", s=55, color="black", zorder=5, label="Pooled OOF $R^2$" if i == 1 else None)
        ax.annotate(
            f"pooled={pooled:.2f}",
            xy=(i, pooled),
            xytext=(i - 0.42, pooled + 0.06 if i == 1 else pooled - 0.08),
            fontsize=8,
            ha="center",
            arrowprops=dict(arrowstyle="-", color="0.4", lw=0.8),
        )
    ax.set_ylabel("Out-of-fold $R^2$ (spatial-block folds)", fontsize=11)
    ax.set_ylim(0, 1.08)
    ax.legend(loc="lower left", fontsize=9, framealpha=0.95)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "03_model_performance_v1_v2.png")

    fold_stats = {
        "solar_oof_r2_pooled": solar_pooled,
        "solar_fold_mean": float(np.mean(solar_folds)),
        "solar_fold_sd": float(np.std(solar_folds, ddof=1)),
        "solar_folds": solar_folds,
        "wind_oof_r2_pooled": wind_pooled,
        "wind_fold_mean": float(np.mean(wind_folds)),
        "wind_fold_sd": float(np.std(wind_folds, ddof=1)),
        "wind_folds": wind_folds,
    }
    (OUT_ANAL / "fold_r2_stats.json").write_text(json.dumps(fold_stats, indent=2))

    # ---------------------------------------------------------------------------
    # 5. Risk spread — baseline_v1 parquet mean (~0.0013 CF), not truncated 0.001
    # ---------------------------------------------------------------------------
    v1_risk_path = PROC / "baseline_v1" / "cell_risk_spread.parquet"
    if v1_risk_path.exists():
        v1_mean = float(pd.read_parquet(v1_risk_path)["hybrid_risk_spread"].mean())
        try:
            source_v1 = str(v1_risk_path.relative_to(ROOT))
        except ValueError:
            source_v1 = str(v1_risk_path)
    else:
        # risk_stress_report may store truncated 0.001; manuscript uses ~0.0013 from v1 parquet
        _rep = float(risk_report.get("v1_baseline_mean_hybrid_risk_spread", 0.0013))
        v1_mean = 0.0013 if abs(_rep - 0.001) < 1e-9 else _rep
        source_v1 = "risk_stress_report"
    v2_mean = float(risk_report["mean_hybrid_risk_spread"])
    # Manuscript rounding: 0.0013 and 0.0059
    v1_disp, v2_disp = round(v1_mean, 4), round(v2_mean, 4)
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    ax.bar(
        ["Earlier baseline\n(narrow stress)", "Final shortlist\n(8-year p5 stress)"],
        [v1_mean, v2_mean],
        color=[C_MUTED, C_BLUE],
        width=0.55,
        edgecolor="white",
    )
    ax.set_ylabel("Mean hybrid risk spread (P50 − P90), CF units", fontsize=11)
    for i, (v, lab) in enumerate([(v1_mean, f"{v1_disp:.4f}"), (v2_mean, f"{v2_disp:.4f}")]):
        ax.text(i, v + max(v1_mean, v2_mean) * 0.04, lab, ha="center", fontsize=11, fontweight="bold")
    ax.set_ylim(0, max(v1_mean, v2_mean) * 1.35)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "10_risk_spread_v1_v2.png")
    (OUT_ANAL / "risk_spread_baseline.json").write_text(
        json.dumps(
            {
                "v1_mean_hybrid_risk_spread": v1_mean,
                "v1_display_rounded": v1_disp,
                "v2_mean_hybrid_risk_spread": v2_mean,
                "v2_display_rounded": v2_disp,
                "ratio_v2_over_v1": v2_mean / v1_mean,
                "source_v1": source_v1,
                "note": "Archived risk_stress_report.v1_baseline_mean_hybrid_risk_spread=0.001 was truncated; parquet mean≈0.00126→0.0013.",
            },
            indent=2,
        )
    )

    # ---------------------------------------------------------------------------
    # 6. Component correlation + variance decomposition of S
    # ---------------------------------------------------------------------------
    comp_cols = {
        "R (resource)": CW["resource"] * df["resource_norm"],
        "Seasonal": CW["seasonal"] * df["seasonal_norm"],
        "P50": CW["yield"] * df["P50_norm"],
        "Risk (−)": -CW["risk"] * df["R_norm"],
        "D (land blend)": CW["land"] * df["D_norm"],
    }
    contrib = pd.DataFrame(comp_cols)
    S_hat = contrib.sum(axis=1)
    recon_err = float(np.max(np.abs(S_hat - df["composite_score"])))

    base_vars = df[["resource_norm", "seasonal_norm", "P50_norm", "R_norm", "D_norm"]].rename(
        columns={
            "resource_norm": "R",
            "seasonal_norm": "Seasonal",
            "P50_norm": "P50",
            "R_norm": "Risk",
            "D_norm": "D",
        }
    )
    corr = base_vars.corr(method="spearman")
    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, vmin=-1, vmax=1, ax=ax, square=True)
    ax.set_title(f"Spearman correlation among S components (n={n_scored:,})")
    save(fig, "17_component_correlation.png")
    corr.to_csv(OUT_ANAL / "component_spearman_corr.csv")

    std_contrib = contrib.apply(lambda s: (s - s.mean()) / s.std(ddof=0))
    var_decomp = {}
    S = df["composite_score"]
    varS = float(S.var(ddof=0))
    for col in contrib.columns:
        var_decomp[col] = float(np.cov(contrib[col], S, ddof=0)[0, 1] / varS)
    rho_rp = float(stats.spearmanr(df["resource_norm"], df["P50_norm"]).correlation)
    var_report = {
        "reconstruction_max_abs_err": recon_err,
        "variance_shares_cov": var_decomp,
        "spearman_R_vs_P50": rho_rp,
        "spearman_R_vs_Seasonal": float(stats.spearmanr(df["resource_norm"], df["seasonal_norm"]).correlation),
        "note": "Variance shares are cov(component,S)/var(S); signed risk term included.",
    }
    (OUT_ANAL / "variance_decomposition.json").write_text(json.dumps(var_report, indent=2))

    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    names = list(var_decomp.keys())
    vals = [var_decomp[n] for n in names]
    colors = [C_FAIL if v < 0 else C_BLUE for v in vals]
    ax.barh(names[::-1], vals[::-1], color=colors[::-1], height=0.55)
    ax.axvline(0, color="black", lw=1)
    ax.set_xlabel("Share of var(S) via cov(component, S)/var(S)")
    ax.set_title(f"Variance decomposition of S  |  Spearman(R, P50) = {rho_rp:.2f}")
    save(fig, "18_variance_decomposition.png")

    # ---------------------------------------------------------------------------
    # 7. Observed vs predicted scatter + residual map
    # ---------------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6))
    for ax, obs, pred, title, c in [
        (
            axes[0],
            df["solar_resource_observed"],
            df["solar_resource_land_adj_oof"],
            "Solar",
            C_ACCENT,
        ),
        (
            axes[1],
            df["wind_resource_observed"],
            df["wind_resource_land_adj_oof"],
            "Wind",
            C_TEAL,
        ),
    ]:
        ax.scatter(obs, pred, s=8, alpha=0.45, color=c, edgecolors="none")
        lo = np.nanmin([obs.min(), pred.min()])
        hi = np.nanmax([obs.max(), pred.max()])
        ax.plot([lo, hi], [lo, hi], "k--", lw=1, label="1:1")
        r2 = 1 - np.nansum((obs - pred) ** 2) / np.nansum((obs - obs.mean()) ** 2)
        ax.set_xlabel(f"Observed {title.lower()}")
        ax.set_ylabel(f"OOF predicted {title.lower()}")
        ax.set_title(f"{title} resource (pooled OOF $R^2$≈{r2:.2f})")
        ax.legend(fontsize=8)
    save(fig, "19_obs_vs_pred_scatter.png")

    gdf = gpd.GeoDataFrame(
        df.copy(),
        geometry=[Point(xy) for xy in zip(df.longitude, df.latitude)],
        crs="EPSG:4326",
    ).to_crs(32618)
    ny_utm = ny_bound.to_crs(32618)
    counties_utm = counties.to_crs(32618)
    gdf["solar_resid"] = gdf["solar_resource_observed"] - gdf["solar_resource_land_adj_oof"]
    gdf["wind_resid"] = gdf["wind_resource_observed"] - gdf["wind_resource_land_adj_oof"]

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0))
    for ax, col, title, cmap in [
        (axes[0], "solar_resid", "Solar residual (obs − OOF)", "coolwarm"),
        (axes[1], "wind_resid", "Wind residual (obs − OOF)", "coolwarm"),
    ]:
        counties_utm.boundary.plot(ax=ax, color="0.75", lw=0.3)
        ny_utm.boundary.plot(ax=ax, color="black", lw=0.8)
        vmax = np.nanpercentile(np.abs(gdf[col]), 98)
        sc = ax.scatter(
            gdf.geometry.x,
            gdf.geometry.y,
            c=gdf[col],
            cmap=cmap,
            s=10,
            vmin=-vmax,
            vmax=vmax,
            alpha=0.85,
        )
        plt.colorbar(sc, ax=ax, shrink=0.72, label=title)
        ax.set_title(title)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        add_north_arrow(ax)
        add_scale_bar(ax, 50)
    save(fig, "20_residual_maps.png")

    # ---------------------------------------------------------------------------
    # 8. Projected maps 12, 13, 15 + study area
    # ---------------------------------------------------------------------------
    def plot_ny_points(ax, gdf_pts, column, cmap, title, top10_gdf=None, mark_jackpot=False):
        counties_utm.boundary.plot(ax=ax, color="0.7", lw=0.25)
        ny_utm.boundary.plot(ax=ax, color="black", lw=0.9)
        sc = ax.scatter(
            gdf_pts.geometry.x,
            gdf_pts.geometry.y,
            c=gdf_pts[column],
            cmap=cmap,
            s=11,
            alpha=0.9,
        )
        if top10_gdf is not None:
            ax.scatter(
                top10_gdf.geometry.x,
                top10_gdf.geometry.y,
                facecolors="none",
                edgecolors=C_ACCENT,
                s=90,
                linewidths=1.6,
                label="Top 10",
            )
        if mark_jackpot:
            jp = gdf_pts[gdf_pts["jackpot_zone"] == True]  # noqa: E712
            ax.scatter(jp.geometry.x, jp.geometry.y, s=18, facecolors="none", edgecolors=C_TEAL, linewidths=0.9)
        plt.colorbar(sc, ax=ax, shrink=0.75, label=column)
        ax.set_title(title)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        add_north_arrow(ax)
        add_scale_bar(ax, 50)
        inset = ax.inset_axes([0.02, 0.62, 0.28, 0.35])
        ny_bound.boundary.plot(ax=inset, color="black", lw=0.6)
        inset.scatter(df.longitude, df.latitude, s=0.3, color=C_BLUE, alpha=0.4)
        inset.set_xticks([])
        inset.set_yticks([])
        inset.set_title("Locator", fontsize=7)
        return sc

    top10_gdf = gpd.GeoDataFrame(
        top10,
        geometry=[Point(xy) for xy in zip(top10.longitude, top10.latitude)],
        crs="EPSG:4326",
    ).to_crs(32618)

    fig, ax = plt.subplots(figsize=(8.5, 7.2))
    plot_ny_points(ax, gdf, "composite_score", "viridis", "Composite shortlist score $S$ (UTM 18N)", top10_gdf)
    save(fig, "12_map_composite_score.png")

    fig, ax = plt.subplots(figsize=(8.5, 7.2))
    jp = gdf.copy()
    jp["jackpot_int"] = jp["jackpot_zone"].astype(int)
    counties_utm.boundary.plot(ax=ax, color="0.7", lw=0.25)
    ny_utm.boundary.plot(ax=ax, color="black", lw=0.9)
    ax.scatter(gdf.geometry.x, gdf.geometry.y, s=8, color="0.85", alpha=0.5, label="Scored cells")
    jp_pts = gdf[gdf["jackpot_zone"] == True]  # noqa: E712
    ax.scatter(jp_pts.geometry.x, jp_pts.geometry.y, s=22, color=C_TEAL, alpha=0.85, label=f"Jackpot n={len(jp_pts)}")
    ax.legend(loc="lower left", fontsize=8)
    ax.set_title("Seasonal co-occurrence (jackpot) cells")
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    add_north_arrow(ax)
    add_scale_bar(ax, 50)
    save(fig, "13_map_jackpot_cells.png")

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.6))
    plot_ny_points(axes[0], gdf, "composite_score", "viridis", "Composite $S$", top10_gdf)
    plot_ny_points(axes[1], gdf, "dist_to_transmission_km", "magma_r", "Distance to HIFLD line (km)", top10_gdf)
    fig.suptitle("Score vs transmission context (transmission not a separate Eq. S term)", fontsize=12, y=1.02)
    save(fig, "15_map_score_vs_transmission.png")

    fig, ax = plt.subplots(figsize=(8.0, 6.8))
    counties_utm.boundary.plot(ax=ax, color="0.75", lw=0.3)
    ny_utm.boundary.plot(ax=ax, color="black", lw=1.0)
    w_gdf = gpd.GeoDataFrame(
        weather,
        geometry=[Point(xy) for xy in zip(weather.longitude, weather.latitude)],
        crs="EPSG:4326",
    ).to_crs(32618)
    ax.scatter(w_gdf.geometry.x, w_gdf.geometry.y, s=3, color=C_MUTED, alpha=0.35, label="Weather grid 4,401")
    ax.scatter(gdf.geometry.x, gdf.geometry.y, s=6, color=C_BLUE, alpha=0.7, label=f"Scored NY {n_scored:,}")
    ax.legend(loc="lower left", fontsize=8)
    ax.set_title("Study area: ~0.09° (~10 km) grid, projected UTM zone 18N")
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    add_north_arrow(ax)
    add_scale_bar(ax, 50)
    save(fig, "21_study_area_map.png")

    # ---------------------------------------------------------------------------
    # 9. Top-10 bar chart with reconciled labels
    # ---------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    labels = [f"{int(r['rank'])}. {r['corridor_label']}" for _, r in top10.iterrows()]
    ax.barh(labels[::-1], top10["composite_score"].values[::-1], color=C_BLUE, height=0.6)
    for y, v in enumerate(top10["composite_score"].values[::-1]):
        ax.text(v + 0.3, y, f"{v:.1f}", va="center", fontsize=9)
    ax.set_xlabel("Composite score $S$")
    ax.set_title("Top-10 shortlist cells (corridor labels from coordinates)")
    ax.set_xlim(60, 80)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "05_top10_composite_sites.png")

    # ---------------------------------------------------------------------------
    # 10. Rank sensitivity scatter
    # ---------------------------------------------------------------------------
    _abl = CFG["composite"]["zero_p50_ablation"]
    df["S0"] = (
        _abl["resource"] * df["resource_norm"]
        + _abl["seasonal"] * df["seasonal_norm"]
        - _abl["risk"] * df["R_norm"]
        + _abl["land"] * df["D_norm"]
    )
    df["rank_default"] = df["composite_score"].rank(ascending=False, method="average")
    df["rank_S0"] = df["S0"].rank(ascending=False, method="average")
    fig, ax = plt.subplots(figsize=(5.8, 5.6))
    ax.scatter(df["rank_default"], df["rank_S0"], s=10, alpha=0.45, color=C_BLUE)
    ax.plot([1, n_scored], [1, n_scored], "k--", lw=1)
    ax.set_xlabel("Rank under default $S$ (1 = best)")
    ax.set_ylabel("Rank under zero-P50 ablation $S_0$")
    ax.set_title("Rank shuffle when exploratory P50 is removed")
    ax.set_aspect("equal")
    save(fig, "16_scatter_rank_sensitivity.png")

    persona_rank_cols = [
        c for c in df.columns if c.startswith("rank_persona_")
    ]
    if persona_rank_cols:
        ranks = df[persona_rank_cols]
        df["rank_sd_personas"] = ranks.std(axis=1)
        gdf2 = gdf.copy()
        gdf2["rank_sd_personas"] = df["rank_sd_personas"].values
        fig, ax = plt.subplots(figsize=(8.2, 7.0))
        counties_utm.boundary.plot(ax=ax, color="0.7", lw=0.25)
        ny_utm.boundary.plot(ax=ax, color="black", lw=0.9)
        sc = ax.scatter(
            gdf2.geometry.x,
            gdf2.geometry.y,
            c=gdf2["rank_sd_personas"],
            cmap="YlOrRd",
            s=11,
            alpha=0.9,
        )
        plt.colorbar(sc, ax=ax, shrink=0.75, label="SD of persona ranks")
        ax.set_title("Rank stability across weight personas (higher = less stable)")
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        add_north_arrow(ax)
        add_scale_bar(ax, 50)
        save(fig, "22_rank_stability_map.png")

    # ---------------------------------------------------------------------------
    # 11. Monthly climatology + complementarity index map
    # ---------------------------------------------------------------------------
    month_sw = [f"shortwave_mean_m{m:02d}" for m in range(1, 13)]
    month_ws = [f"wind_speed_mean_m{m:02d}" for m in range(1, 13)]
    have_sw = all(c in weather.columns for c in month_sw)
    have_ws = all(c in weather.columns for c in month_ws)
    if have_sw and have_ws:
        keyed = weather.merge(df[["latitude", "longitude"]], on=["latitude", "longitude"], how="inner")
        sw = keyed[month_sw].mean()
        ws = keyed[month_ws].mean()
        sw_n = (sw - sw.min()) / (sw.max() - sw.min() + 1e-12)
        ws_n = (ws - ws.min()) / (ws.max() - ws.min() + 1e-12)
        fig, ax = plt.subplots(figsize=(8.0, 4.4))
        months = np.arange(1, 13)
        ax.plot(months, sw_n, "-o", color=C_ACCENT, label="Solar (norm. mean shortwave)")
        ax.plot(months, ws_n, "-s", color=C_TEAL, label="Wind (norm. mean 10 m speed)")
        ax.set_xticks(months)
        ax.set_xlabel("Month")
        ax.set_ylabel("Min–max normalized climatology")
        ax.set_title("Statewide monthly solar–wind climatology (scored NY cells)")
        ax.legend(fontsize=8)
        save(fig, "04_seasonal_solar_wind.png")

        # Complementarity: 1 − corr of monthly profiles per cell
        sw_mat = keyed[month_sw].to_numpy()
        ws_mat = keyed[month_ws].to_numpy()
        comps = []
        for i in range(len(keyed)):
            a = sw_mat[i]
            b = ws_mat[i]
            if np.std(a) < 1e-9 or np.std(b) < 1e-9:
                comps.append(np.nan)
            else:
                rho = np.corrcoef(a, b)[0, 1]
                comps.append(1 - rho)
        keyed = keyed.copy()
        keyed["complementarity_index"] = comps
        cg = gpd.GeoDataFrame(
            keyed,
            geometry=[Point(xy) for xy in zip(keyed.longitude, keyed.latitude)],
            crs="EPSG:4326",
        ).to_crs(32618)
        fig, ax = plt.subplots(figsize=(8.2, 7.0))
        counties_utm.boundary.plot(ax=ax, color="0.7", lw=0.25)
        ny_utm.boundary.plot(ax=ax, color="black", lw=0.9)
        sc = ax.scatter(
            cg.geometry.x,
            cg.geometry.y,
            c=cg["complementarity_index"],
            cmap="plasma",
            s=11,
            alpha=0.9,
        )
        plt.colorbar(sc, ax=ax, shrink=0.75, label="Complementarity index (1 − corr)")
        ax.set_title("Monthly solar–wind complementarity index")
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        add_north_arrow(ax)
        add_scale_bar(ax, 50)
        save(fig, "23_complementarity_index_map.png")

    # ---------------------------------------------------------------------------
    # 12. External validation: EIA operating plants in S distribution
    # ---------------------------------------------------------------------------
    eia_ny = eia[(eia["State"] == "NY") | (eia.get("State") == "New York")].copy()
    tech = eia_ny["technology"].astype(str).str.lower()
    mask = tech.str.contains("solar") | tech.str.contains("wind") | eia_ny["fuel_code"].isin(["SUN", "WND"])
    eia_rw = eia_ny[mask].copy()
    eia_rw = eia_rw.sort_values("year").groupby("plant_id", as_index=False).tail(1)
    scored_keys = df.set_index(["latitude", "longitude"])
    recs = []
    for _, p in eia_rw.iterrows():
        glat, glon = p.get("grid_latitude"), p.get("grid_longitude")
        if pd.isna(glat) or pd.isna(glon):
            continue
        key = (float(glat), float(glon))
        hit = df[(np.isclose(df.latitude, glat)) & (np.isclose(df.longitude, glon))]
        if len(hit) == 0:
            d2 = (df.latitude - glat) ** 2 + (df.longitude - glon) ** 2
            hit = df.loc[[d2.idxmin()]]
            if d2.min() > (0.15**2):
                continue
        row = hit.iloc[0]
        recs.append(
            {
                "plant_id": int(p.plant_id),
                "plant_name": p.plant_name,
                "technology": p.technology,
                "nameplate_mw": float(p.nameplate_mw) if pd.notna(p.nameplate_mw) else np.nan,
                "cell_lat": float(row.latitude),
                "cell_lon": float(row.longitude),
                "composite_score": float(row.composite_score),
                "resource_norm": float(row.resource_norm),
                "S_percentile": float(rank_pct(df["composite_score"]).loc[row.name]),
            }
        )
    val_df = pd.DataFrame(recs)
    val_df.to_csv(OUT_ANAL / "eia_external_validation.csv", index=False)
    if len(val_df):
        fig, ax = plt.subplots(figsize=(7.5, 4.4))
        ax.hist(df["composite_score"], bins=30, color=C_MUTED, alpha=0.55, density=True, label="All scored cells")
        ax.hist(val_df["composite_score"], bins=20, color=C_ACCENT, alpha=0.65, density=True, label="EIA solar/wind cells")
        ax.axvline(df["composite_score"].median(), color=C_BLUE, ls="--", label="Median S (all)")
        ax.axvline(val_df["composite_score"].median(), color=C_ACCENT, ls="--", label="Median S (EIA cells)")
        ax.set_xlabel("Composite score $S$")
        ax.set_ylabel("Density")
        ax.set_title(
            f"External check: EIA-860 NY solar/wind snapped cells (n={len(val_df)})\n"
            f"median S percentile = {val_df['S_percentile'].median():.0f}th"
        )
        ax.legend(fontsize=8)
        save(fig, "24_eia_external_validation.png")
        eia_summary = {
            "n_plants_snapped": int(len(val_df)),
            "median_S": float(val_df["composite_score"].median()),
            "median_S_percentile": float(val_df["S_percentile"].median()),
            "frac_above_median_S": float((val_df["composite_score"] >= df["composite_score"].median()).mean()),
            "frac_top_quartile_S": float((val_df["S_percentile"] >= 75).mean()),
        }
    else:
        eia_summary = {"n_plants_snapped": 0}
    (OUT_ANAL / "eia_validation_summary.json").write_text(json.dumps(eia_summary, indent=2))

    # ---------------------------------------------------------------------------
    # 13. Lift / capture vs resource-only and random
    # ---------------------------------------------------------------------------
    queue_path = OUT_TABLES / "nyiso_queue_crosscheck_top25.csv"
    lift_summary = {}
    if queue_path.exists():
        q = pd.read_csv(queue_path)
        df_c = attach_counties(df.copy(), counties)
        q_unique = q.dropna(subset=["queue_mw"]).drop_duplicates(subset=["county", "nearest_queue_project"])
        county_mw = q_unique.groupby("county")["queue_mw"].sum().to_dict()
        df_c["queue_mw_county"] = df_c["county"].map(county_mw).fillna(0.0)
        # Distribute county MW equally across scored cells in that county
        counts = df_c.groupby("county")["latitude"].transform("count")
        df_c["queue_mw_cell"] = df_c["queue_mw_county"] / counts.replace(0, np.nan)
        df_c["queue_mw_cell"] = df_c["queue_mw_cell"].fillna(0.0)

        def capture_curve(score_col, n=200):
            ord_df = df_c.sort_values(score_col, ascending=False)
            cum = ord_df["queue_mw_cell"].cumsum().to_numpy()
            xs = np.arange(1, len(ord_df) + 1)
            return xs, cum

        x_s, y_s = capture_curve("composite_score")
        x_r, y_r = capture_curve("resource_norm")
        rng = np.random.default_rng(RANDOM_STATE)
        rand_order = rng.permutation(len(df_c))
        y_rand = df_c.iloc[rand_order]["queue_mw_cell"].cumsum().to_numpy()
        total = float(df_c["queue_mw_cell"].sum())
        fig, ax = plt.subplots(figsize=(7.2, 4.8))
        ax.plot(x_s, y_s / max(total, 1), label="Rank by $S$", color=C_BLUE, lw=2)
        ax.plot(x_r, y_r / max(total, 1), label="Rank by resource $R$ only", color=C_TEAL, lw=1.8)
        ax.plot(np.arange(1, len(y_rand) + 1), y_rand / max(total, 1), label="Random order", color=C_MUTED, lw=1.5)
        ax.set_xlabel("Number of cells screened (best-first)")
        ax.set_ylabel("Cumulative share of county-attributed queue MW")
        ax.set_title("Descriptive capture curve (county queue MW attributed to cells)")
        ax.legend(fontsize=8)
        ax.set_xlim(0, n_scored)
        ax.set_ylim(0, 1.05)
        save(fig, "25_lift_capture_curve.png")
        lift_summary = {
            "total_attributed_mw": total,
            "capture_at_100_S": float(y_s[99] / max(total, 1)),
            "capture_at_100_R": float(y_r[99] / max(total, 1)),
            "capture_at_100_random": float(y_rand[99] / max(total, 1)),
            "note": "County MW split equally across scored cells in county; descriptive only.",
        }
    (OUT_ANAL / "lift_capture_summary.json").write_text(json.dumps(lift_summary, indent=2))

    # ---------------------------------------------------------------------------
    # 14. Baseline comparison: S vs R vs equal-weight overlay
    # ---------------------------------------------------------------------------
    df["S_equal"] = (
        df["resource_norm"] + df["seasonal_norm"] + df["P50_norm"] - df["R_norm"] + df["D_norm"]
    ) / 5.0
    df["S_ahp_like"] = 0.5 * df["resource_norm"] + 0.5 * df["D_norm"]

    comparisons = {}
    for name, col in [
        ("resource_only", "resource_norm"),
        ("equal_weight", "S_equal"),
        ("ahp_like_R_D", "S_ahp_like"),
        ("zero_P50", "S0"),
    ]:
        rho, lo, hi = spearman_ci(df["composite_score"], df[col])
        comparisons[name] = {
            "spearman_rho": rho,
            "spearman_ci95": [lo, hi],
            "top10_overlap": top10_coord_overlap(df, "composite_score", col),
        }
    (OUT_ANAL / "baseline_comparison.json").write_text(json.dumps(comparisons, indent=2))

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    names = list(comparisons.keys())
    rhos = [comparisons[n]["spearman_rho"] for n in names]
    los = [comparisons[n]["spearman_ci95"][0] for n in names]
    his = [comparisons[n]["spearman_ci95"][1] for n in names]
    ax.barh(names[::-1], rhos[::-1], color=C_BLUE, height=0.55, xerr=np.array([
        np.array(rhos[::-1]) - np.array(los[::-1]),
        np.array(his[::-1]) - np.array(rhos[::-1]),
    ]), error_kw=dict(ecolor="black", lw=1, capsize=3))
    ax.set_xlabel(r"Spearman $\rho$ vs default $S$ (95% bootstrap CI)")
    ax.set_title("Baseline comparison against default composite $S$")
    ax.set_xlim(0.5, 1.05)
    save(fig, "26_baseline_comparison.png")

    # ---------------------------------------------------------------------------
    # 15. Resource vs D scatter; S distribution
    # ---------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 5.4))
    sc = ax.scatter(df["resource_norm"], df["D_norm"], c=df["composite_score"], cmap="viridis", s=12, alpha=0.85)
    ax.scatter(top10.resource_norm, top10.D_norm, facecolors="none", edgecolors=C_ACCENT, s=80, lw=1.5)
    plt.colorbar(sc, ax=ax, label="$S$")
    ax.set_xlabel("Hybrid resource percentile $R$")
    ax.set_ylabel("Developability blend percentile $D$")
    ax.set_title("Resource vs developability (top-10 outlined)")
    save(fig, "14_scatter_resource_vs_D.png")

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    ax.hist(df["composite_score"], bins=35, color=C_BLUE, alpha=0.85, edgecolor="white")
    ax.axvline(df["composite_score"].median(), color=C_ACCENT, ls="--", label=f"Median={df['composite_score'].median():.1f}")
    ax.set_xlabel("Composite score $S$")
    ax.set_ylabel("Cells")
    ax.set_title(f"Distribution of shortlist score $S$ (n={n_scored:,})")
    ax.legend(fontsize=8)
    save(fig, "07_composite_score_distribution.png")

    # ---------------------------------------------------------------------------
    # 16. Threshold sensitivity (gateway D cutoffs)
    # ---------------------------------------------------------------------------
    sens = {"D_cutoffs": {}, "note": ""}
    if "developability_D" in master.columns and "in_ny_state" in master.columns:
        m = master.copy()
        thr = gw_report["thresholds"]
        for code in [11, 12, 21, 22, 23, 24, 90, 95]:
            if f"frac_class_{code}" not in m.columns:
                m[f"frac_class_{code}"] = 0.0
        hard = (
            (m["frac_class_11"].fillna(0) <= thr["WATER_FRAC_MAX"])
            & ((m[[f"frac_class_{c}" for c in (21, 22, 23, 24)]].fillna(0).sum(axis=1)) <= thr["DEVELOPED_FRAC_MAX"])
            & ((m[["frac_class_90", "frac_class_95"]].fillna(0).sum(axis=1)) <= thr["WETLAND_FRAC_MAX"])
            & (m["frac_class_12"].fillna(0) <= thr["ICE_FRAC_MAX"])
        )
        if "nlcd_pixel_count" in m.columns:
            hard &= m["nlcd_pixel_count"] > 0
        for cut in [0.10, 0.15, 0.20, 0.25, 0.30]:
            n_pass = int(((m["developability_D"] >= cut) & hard).sum())
            n_pass_ny = int(((m["developability_D"] >= cut) & hard & m["in_ny_state"]).sum())
            sens["D_cutoffs"][str(cut)] = {"pass_all": n_pass, "pass_ny": n_pass_ny}
        sens["note"] = "Hard NLCD rules held fixed; only D_MIN varies. Buffer sensitivity: current run uses 7 km NLCD buffer; 5 km was an earlier baseline (v1 fail_no_nlcd=721 vs 703)."
        fig, ax = plt.subplots(figsize=(6.8, 4.0))
        cuts = [float(k) for k in sens["D_cutoffs"]]
        nys = [sens["D_cutoffs"][str(c)]["pass_ny"] for c in cuts]
        ax.plot(cuts, nys, "-o", color=C_BLUE)
        ax.axvline(0.20, color=C_ACCENT, ls="--", label="Default D_MIN=0.20")
        ax.set_xlabel("Developability gateway cutoff $D_{MIN}$")
        ax.set_ylabel("NY cells passing")
        ax.set_title("Gateway threshold sensitivity (NY pass count)")
        ax.legend(fontsize=8)
        save(fig, "27_gateway_threshold_sensitivity.png")
    sens["nlcd_buffer"] = {
        "current_m": gw_report.get("nlcd_r2", {}).get("cell_radius_m", 7000),
        "v1_baseline_fail_no_nlcd": gw_report.get("nlcd_r2", {}).get("v1_baseline_fail_no_nlcd"),
        "current_fail_no_nlcd": gw_report["fail_counts"]["fail_no_nlcd"],
    }
    (OUT_ANAL / "threshold_sensitivity.json").write_text(json.dumps(sens, indent=2))

    # ---------------------------------------------------------------------------
    # 17. Grid geometry stats
    # ---------------------------------------------------------------------------
    lats = np.sort(weather["latitude"].unique())
    lons = np.sort(weather["longitude"].unique())
    dlat = float(np.median(np.diff(lats)))
    transformer = Transformer.from_crs(4326, 32618, always_xy=True)
    x1, y1 = transformer.transform(-76.0, 42.5)
    x2, y2 = transformer.transform(-76.0, 42.5 + dlat)
    x3, y3 = transformer.transform(-76.0 + dlat, 42.5)
    km_ns = abs(y2 - y1) / 1000
    km_ew = abs(x3 - x1) / 1000
    grid_meta = {
        "degree_spacing_lat": dlat,
        "degree_spacing_lon_median": float(np.median(np.diff(lons))),
        "approx_cell_km_NS_at_42_5N": km_ns,
        "approx_cell_km_EW_at_42_5N_same_delta": km_ew,
        "approx_cell_area_km2": km_ns * km_ew,
        "crs_distances": "EPSG:32618 (UTM zone 18N)",
        "percentile_method": "rank(average)/n * 100 on the 1,089 scored NY cells",
        "hybrid_R_definition": "R = percentile of hybrid_screening_score; hybrid_screening_score = mean(solar_observed_pct, wind_observed_pct)",
        "P50_source": comp_report.get("roadmap2_p50_source"),
        "solar_yield_cv_r2": comp_report.get("solar_yield_cv_r2"),
        "stress_method": risk_report.get("method"),
        "stress_percentile": risk_report.get("stress_percentile"),
        "weather_2025_end": "2025-10-31 (partial year)",
        "D_norm_implementation": "Equal blend of developability percentile and inverted transmission-distance percentile (near-grid preference folded into land term)",
    }
    (OUT_ANAL / "methods_definitions.json").write_text(json.dumps(grid_meta, indent=2))

    sens_rows = []
    for name, col in [
        ("Balanced (default S)", "composite_score"),
        ("Risk +10%", "composite_persona_risk_plus_10pct"),
        ("Resource +10%", "composite_persona_resource_plus_10pct"),
        ("Resource-first", "composite_persona_resource_first"),
        ("Yield-focus", "composite_persona_yield_focus"),
        ("Conservative", "composite_persona_conservative"),
        ("Zero-P50 ablation", "S0"),
    ]:
        if col not in df.columns:
            continue
        rho, lo, hi = spearman_ci(df["composite_score"], df[col], n_boot=SENS_BOOT)
        sens_rows.append(
            {
                "scheme": name,
                "rho": rho,
                "rho_lo": lo,
                "rho_hi": hi,
                "top10_overlap": top10_coord_overlap(df, "composite_score", col),
            }
        )
    pd.DataFrame(sens_rows).to_csv(OUT_ANAL / "sensitivity_with_ci.csv", index=False)

    prior = pd.DataFrame(
        [
            {
                "Study": "Van Haaren & Fthenakis (2011)",
                "Region": "New York",
                "Resolution": "GIS SMCA (coarse)",
                "Criteria": "Wind + exclusions",
                "Weighting": "SMCA",
                "Validation": "Limited",
                "ML": "No",
            },
            {
                "Study": "Janke (2010)",
                "Region": "Colorado",
                "Resolution": "Raster GIS",
                "Criteria": "Solar/wind multi-criteria",
                "Weighting": "Weighted overlay",
                "Validation": "Limited",
                "ML": "No",
            },
            {
                "Study": "This study (Phase 1)",
                "Region": "New York",
                "Resolution": "~10 km / 0.09°",
                "Criteria": "Gateway, observed R, seasonal, P50, risk, D",
                "Weighting": "Heuristic + personas",
                "Validation": "Spatial CV; EIA/queue descriptive",
                "ML": "XGB diagnostics only",
            },
        ]
    )
    prior.to_csv(OUT_ANAL / "prior_work_comparison.csv", index=False)

    # ---------------------------------------------------------------------------
    # 18. Seasonal / jackpot clarification
    # ---------------------------------------------------------------------------
    seasonal_gap = load_json("seasonal_gap_report.json")
    seasonal_note = {
        "n_scored_cells_means": seasonal_gap["n_cells"],
        "n_jackpot_zones": seasonal_gap["n_jackpot_zones"],
        "mean_solar_seasonal_drop_frac_statewide_scored": seasonal_gap["mean_solar_seasonal_drop_frac"],
        "mean_wind_winter_lift_frac_statewide_scored": seasonal_gap["mean_wind_winter_lift_frac"],
        "interpretation": (
            "The −56% summer→winter solar drop and +69% winter vs summer wind lift are means "
            "over all 1,089 scored NY cells (seasonal_gap_report), not jackpot-only. "
            "Jackpot n=143 is the dual top-quartile co-occurrence count."
        ),
    }
    hyb_cols = [c for c in ["summer_ghi", "winter_ghi", "winter_wind", "summer_wind"] if c in hyb.columns]
    hyb_full = hyb[["latitude", "longitude"] + hyb_cols].merge(
        df[["latitude", "longitude", "jackpot_zone"]],
        on=["latitude", "longitude"],
        how="inner",
    )
    if set(hyb_cols) == {"summer_ghi", "winter_ghi", "winter_wind", "summer_wind"}:
        jp = hyb_full.loc[hyb_full["jackpot_zone"].astype(bool)]
        seasonal_note["jackpot_only_mean_solar_drop_frac"] = float(
            ((jp["summer_ghi"] - jp["winter_ghi"]) / jp["summer_ghi"]).mean()
        )
        seasonal_note["jackpot_only_mean_wind_lift_frac"] = float(
            ((jp["winter_wind"] - jp["summer_wind"]) / jp["summer_wind"]).mean()
        )
    (OUT_ANAL / "seasonal_jackpot_clarification.json").write_text(json.dumps(seasonal_note, indent=2))

    # ---------------------------------------------------------------------------
    # 19. Renamed archetypes (bar chart)
    # ---------------------------------------------------------------------------
    centroids = comp_report.get("cluster_centroids", [])
    # Old → new labels ordered by mean_composite descending
    # Old: A_prime_balanced (49.5), B_high_yield_risk (32.1), C_moderate_safe (54.7), D_lower_tier (33.9)
    RENAME = {
        "C_moderate_safe": "A_higher_S_safe",
        "A_prime_balanced": "B_mid_S_balanced",
        "D_lower_tier": "C_lower_S_tier",
        "B_high_yield_risk": "D_high_yield_risk",
    }
    DISPLAY = {
        "A_higher_S_safe": "A higher-S safe",
        "B_mid_S_balanced": "B mid-S balanced",
        "C_lower_S_tier": "C lower-S tier",
        "D_high_yield_risk": "D high-yield / higher-risk",
    }
    rows = []
    for c in centroids:
        old = c["label"]
        new = RENAME.get(old, old)
        rows.append(
            {
                "old_label": old,
                "new_label": new,
                "display": DISPLAY.get(new, new),
                "n_cells": c["n_cells"],
                "mean_composite": c["mean_composite"],
                "cluster_id": c["cluster_id"],
            }
        )
    arch = pd.DataFrame(rows).sort_values("mean_composite", ascending=False)
    arch.to_csv(OUT_ANAL / "archetype_labels_renamed.csv", index=False)

    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    y = np.arange(len(arch))
    ax.barh(y, arch["mean_composite"], color=[C_TEAL, C_BLUE, C_MUTED, C_FAIL][: len(arch)], height=0.55)
    ax.set_yticks(y)
    ax.set_yticklabels(
        [f"{r.display} (n={int(r.n_cells)})" for r in arch.itertuples()],
        fontsize=10,
    )
    for yi, v in zip(y, arch["mean_composite"]):
        ax.text(v + 0.6, yi, f"mean $S$={v:.1f}", va="center", fontsize=10)
    ax.set_xlabel("Mean composite score $S$", fontsize=11)
    ax.set_xlim(0, max(arch["mean_composite"]) * 1.22)
    ax.invert_yaxis()
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "06_cluster_typology.png")

    # ---------------------------------------------------------------------------
    # 20. County counts among top-N ranks
    # ---------------------------------------------------------------------------
    df_c = attach_counties(df.copy(), counties)
    df_c = df_c.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df_c["rank"] = np.arange(1, len(df_c) + 1)
    county_rows = []
    for n in [10, 25, 50, 100]:
        vc = df_c.head(n)["county"].value_counts()
        for county, cnt in vc.items():
            county_rows.append({"top_n": n, "county": county, "n_cells": int(cnt)})
    county_df = pd.DataFrame(county_rows)
    county_df.to_csv(OUT_ANAL / "topN_county_counts.csv", index=False)

    # ---------------------------------------------------------------------------
    # 21. Exact persona / ablation weights (appendix table)
    # ---------------------------------------------------------------------------
    _pers = CFG["composite"]["personas"]
    _pert = CFG["composite"]["perturbations"]
    _abl = CFG["composite"]["zero_p50_ablation"]
    weight_rows = [
        weight_table_row("Balanced (default S)", _pers["balanced"], "Eq. (S); risk enters with minus sign"),
        weight_table_row("Resource-first", _pers["resource_first"], "Persona"),
        weight_table_row("Conservative", _pers["conservative"], "Persona"),
        weight_table_row("Yield-focus", _pers["yield_focus"], "Persona"),
        weight_table_row("Risk +10%", _pert["risk_plus_10pct"], "Mild nudge"),
        weight_table_row("Resource +10%", _pert["resource_plus_10pct"], "Mild nudge"),
        weight_table_row("Zero-P50 ablation S0", _abl, "Eq. (S0)"),
    ]
    wdf = pd.DataFrame(weight_rows)
    wdf.to_csv(OUT_ANAL / "persona_weights_exact.csv", index=False)
    wdf.to_csv(OUT_TABLES / "persona_weights_exact.csv", index=False)

    print("\n=== KEY NUMBERS ===")
    print("Funnel:", gw_report["input_cells"], "->", gw_report["cells_passing"], "->", gw_report["cells_passing_in_ny"])
    print("Top10:\n", top10[["rank", "corridor_label", "county", "composite_score"]].to_string(index=False))
    print("Risk v1/v2:", v1_mean, v2_mean, "ratio", v2_mean / v1_mean)
    print("Archetypes:\n", arch.to_string(index=False))
    print("Seasonal note:", seasonal_note["interpretation"])
    print("DONE")


if __name__ == "__main__":
    main()
