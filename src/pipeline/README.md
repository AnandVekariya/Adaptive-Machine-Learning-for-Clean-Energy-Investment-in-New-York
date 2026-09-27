# Pipeline notebooks (00–15)

Each notebook reads raw or intermediate data and writes Parquet/JSON under `data/processed/`. Notebooks resolve the repo root as `ROOT = Path('../..').resolve()` so they can see `config/paths.yaml`, `data/`, `maps/`, and `outputs/`.

Use the same environment on Windows, macOS, or Linux:

```bash
conda env create -f environment.yml
conda activate clean-energy-ny
python scripts/check_setup.py
```

Then either `python scripts/run_pipeline.py` or open `src/pipeline/` in JupyterLab. Apptainer is optional (Linux HPC only).

---

## Pipeline flow

```
00 (QA gate)
    ↓
01 (weather) ──┬──→ 02 (NLCD) ──┐
               ├──→ 04 (transmission) ──┼──→ 05 (master table) ──→ 06 (gateway filter)
               └──→ 03 (EIA targets)     │         [parallel branch]
                                         │
03 uses 01 only; does not feed into 05
```

**Unit of analysis:** ~4,401 grid cells at ~10 km spacing, keyed by `(latitude, longitude)`.

---

## Quick reference

| # | Notebook | Phase | Main output |
|---|----------|-------|-------------|
| 00 | `00_temporal_parity_qa.ipynb` | 0 | `temporal_parity_report.json` |
| 01 | `01_ingest_weather.ipynb` | 1 | `weather_cell_features.parquet` (~84 cols) |
| 01b | `01b_physics_hourly_yield.ipynb` | physics | `cell_physics_yield.parquet` (NY gateway cells only) |
| 02 | `02_nlcd_zonal_stats.ipynb` | 1 | `grid_nlcd_fractional.parquet` |
| 03 | `03_eia_cf_targets.ipynb` | 1 | `eia_facility_annual.parquet`, `eia_facility_features.parquet` |
| 04 | `04_grid_transmission_distance.ipynb` | 1 | `grid_transmission_distance.parquet` |
| 05 | `05_build_master_table.ipynb` | 1 | `modeling_master_cell.parquet` |
| 06 | `06_gateway_filter.ipynb` | 2 | `cells_passing_gateway.parquet`, `gateway_filter_report.json`, `maps/developability_ny.html` |
| 07 | `07_solar_resource_model.ipynb` | 3 | `models/solar_resource.joblib`, `solar_scores_by_cell.parquet`, `maps/solar_resource_ny.html` |
| 08 | `08_wind_resource_model.ipynb` | 3 | `models/wind_resource.joblib`, `wind_scores_by_cell.parquet`, `maps/wind_resource_ny.html` |
| 09 | `09_combine_resource_scores.ipynb` | 3 | `cell_resource_scores.parquet` |
| 10 | `10_yield_engine.ipynb` | 4 | `cell_p50_yield.parquet` |
| 11 | `11_hybrid_seasonal_suitability.ipynb` | 5 | `hybrid_suitability.parquet` |
| 12 | `12_risk_stress_p90.ipynb` | 6 | `cell_risk_spread.parquet` |
| 13 | `13_composite_score.ipynb` | 7 | `cell_composite_score.parquet`, `outputs/ny_composite_ranked.geojson` |
| 14 | `14_export_gis_and_tables.ipynb` | 8 | GIS GeoJSON, limitation notes on Plotly HTML, top-50 CSV / export summary in `results/tables/` |
| 15 | `15_pipeline_validation.ipynb` | QA | `pipeline_validation_report.json` |

**Run order:** `00 → 01 → 01b → (02, 04) → 03 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 13 → 14 → 15`. Run `03` after `01` for Phase 4 yield. `01b` can run after `06` if you only need gateway-scored physics before composite.

**Current scored set:** ~1,089 NY cells after gateway + resource scoring.

---

## 00 — `00_temporal_parity_qa.ipynb` (Phase 0)

**Purpose:** Audit year coverage across weather data layers **before** building features. Acts as a go/no-go gate for Phase 1.

**Inputs:**
- `data/raw_solar_wind_hourly_data/NY_State_10km_*.csv` (10 km grid)
- `data/ny_county_solar_hourly_API_Data/` (county solar)
- `data/ny-county_Wind_hourly_API_Data/` (county wind)
- `config/paths.yaml` (target years 2018–2025)

**What it does:**
- Scans filenames for available years per layer
- Compares found years vs target years
- Records that **county wind 2021–2025 is incomplete** (Open-Meteo gap-fill deferred)
- Sets policy: Phase 1 wind features use **10 km grid** `wind_speed_10m` (aligned 2018–2025)

**Output:** `data/processed/temporal_parity_report.json`

**Gate:** `proceed_to_phase1: true` when all 8 grid years (2018–2025) exist on disk.

---

## 01 — `01_ingest_weather.ipynb` (Phase 1)

**Purpose:** Aggregate hourly 10 km weather CSVs into **one row per grid cell** with long-term climate statistics (2018–2025).

**Inputs:** `data/raw_solar_wind_hourly_data/NY_State_10km_YYYY.csv`

**What it does:**
- Reads hourly data with **Polars** (handles bad date lines, flexible datetime parsing)
- Derives `month`, `season` (DJF / MAM / JJA / SON)
- Per cell per year: means, std, P90 for:
  - **Solar:** `shortwave_radiation`, `direct_radiation`, `diffuse_radiation` (clipped ≥ 0)
  - **`shortwave_mean`** = daytime-only mean (`shortwave > 0`); **`shortwave_mean_24h`** = all-hour mean (night = 0)
  - **Wind:** `wind_speed_10m`, wind power proxy (∝ v³)
  - **Context:** `temperature_2m`, `surface_pressure`
- Monthly means (12 cols) and seasonal means (4 seasons × solar/wind)
- Combines all years → cell-level climatology; aligns schemas across years before concat
- Caches per-year scratch: `data/processed/scratch/weather_cell_year/weather_cell_YYYY.parquet`

**Output:** `data/processed/weather_cell_features.parquet` (~4,401 cells × ~54 columns)

**Settings:** `YEARS = None` (all years) or `[2025]` for a quick test; `USE_SCRATCH_CACHE = True` to skip recomputed years.

---

## 02 — `02_nlcd_zonal_stats.ipynb` (Phase 1)

**Purpose:** Attach **NLCD 2024 land-cover fractions** to each weather grid cell.

**Inputs:**
- Cell locations from `weather_cell_features.parquet`
- NLCD GeoTIFF: `data/Annual_NLCD_LndCov_2024/Annual_NLCD_LndCov_2024_CU_C1V1.tif`

**What it does:**
- For each `(latitude, longitude)`: builds a **5 km radius** buffer in NLCD projection
- Runs **`rasterstats`** categorical zonal stats (`nodata=250`)
- Converts pixel counts → fractions per NLCD class: `frac_class_11` (water), `frac_class_21`–`24` (developed), `frac_class_81`–`82` (agriculture), forest, wetlands, etc.
- Stores `nlcd_pixel_count`, centroid NLCD code/class, `nlcd_fraction_sum`

**Output:** `data/processed/grid_nlcd_fractional.parquet` (~4,401 × 22 cols)

**Runtime:** ~5–20 min for ~4,400 cells. ~721 edge cells have `nlcd_pixel_count = 0` (outside raster extent).

**Requires:** `01_ingest_weather.ipynb` completed first.

---

## 03 — `03_eia_cf_targets.ipynb` (Phase 1)

**Purpose:** Build **facility-level capacity factor (CF) targets** from real NY solar/wind plants (EIA). Used later in Phase 4 yield modeling — **not** merged into the grid master table.

**Inputs:**
- `data/model_data/NY_Greation_Data_with_nlcd.csv`
- `weather_cell_features.parquet` (for spatial join)

**What it does:**
- Filters to renewable fuels only: **SUN** (solar), **WND** (wind)
- Computes **capacity factor:**
  ```
  CF = Net Generation (MWh) / (Nameplate Capacity (MW) × 8760)
  ```
- Flags outliers where CF > 1.2
- **Spatial join:** each plant → nearest weather grid cell via `geopandas.sjoin_nearest` (EPSG:32618 UTM)

**Outputs:**
| File | Rows (approx.) | Description |
|------|----------------|-------------|
| `eia_facility_annual.parquet` | 2,794 | Facility × year with CF |
| `eia_facility_features.parquet` | 2,794 | Facilities + weather features at nearest cell |

**Requires:** `01_ingest_weather.ipynb` completed first.

---

## 04 — `04_grid_transmission_distance.ipynb` (Phase 1)

**Purpose:** Distance from each grid cell to the **nearest transmission line** (km).

**Inputs:**
- Cell lat/lon from `weather_cell_features.parquet`
- `data/US_Electric_Power_Transmission_Lin2es_*.geojson`

**What it does:**
- Projects cells and lines to **EPSG:32618** (UTM 18N) for meter-accurate distances
- Clips national transmission lines to NY extent + **50 km buffer** (performance)
- `gpd.sjoin_nearest` → distance in meters → `dist_to_transmission_km`
- Deduplicates when multiple lines are equidistant (keeps minimum distance per cell)

**Output:** `data/processed/grid_transmission_distance.parquet` (4,401 cells; median ~5 km to lines)

**Requires:** `01_ingest_weather.ipynb` completed first.

---

## 05 — `05_build_master_table.ipynb` (Phase 1)

**Purpose:** Merge all **cell-level** features into one modeling table for Phase 2+.

**Join key:** `(latitude, longitude)`

**Inputs:**
| Layer | File |
|-------|------|
| Weather | `weather_cell_features.parquet` |
| NLCD | `grid_nlcd_fractional.parquet` |
| Transmission | `grid_transmission_distance.parquet` |

**What it does:**
- Left-joins weather + NLCD fractions + transmission distance (1:1 per cell)
- Drops rows with null lat/lon

**Output:** `data/processed/modeling_master_cell.parquet` (4,401 × **72 columns**)

**Requires:** `01`, `02`, and `04` completed first.

---

## 06 — `06_gateway_filter.ipynb` (Phase 2)

**Purpose:** Remove grid cells that are **not developable** before resource/yield ML (siting MCDA gateway).

**Input:** `modeling_master_cell.parquet`

**What it does:**

### Developability score `D`

```
D_raw = w_ag·(frac_81 + frac_82) + w_barren·frac_31 + w_open·frac_21
        − w_forest·(frac_41 + frac_42 + frac_43) − w_wet·(frac_90 + frac_95)
```

Default weights: `W_AG=1.0`, `W_BARREN=0.8`, `W_OPEN=0.3`, `W_FOREST=0.4`, `W_WET=1.0`.  
Normalized to **[0, 1]** via min–max across all cells.

### Hard filters (exclude cell if)

| Rule | Threshold |
|------|-----------|
| Water dominance | `frac_class_11` > 0.50 |
| Developed land | sum `frac_21`–`24` > 0.20 |
| Wetlands | sum `frac_90` + `frac_95` > 0.30 |
| Ice/snow | `frac_class_12` > 0.30 |
| Low developability | `D` < 0.20 |
| Missing NLCD | `nlcd_pixel_count == 0` |

**Outputs:**
| File | Description |
|------|-------------|
| `cells_passing_gateway.parquet` | ~1,992 cells that pass all filters |
| `gateway_filter_report.json` | Counts, thresholds, pass rate |
| `maps/developability_ny.html` | Plotly map: green = pass, red = excluded |

**Requires:** `05_build_master_table.ipynb` completed first.

**Map:** `maps/developability_ny.html` — cells clipped with `gpd.sjoin(..., predicate='within')` on the NY state polygon, Plotly mapbox (center 42.9°N, 75.8°W, zoom 5.5), NY outline trace.

---

## Configuration

Notebooks load **`config/paths.yaml`** (path/weather keys). Scripts and hyperparameters use **`config/config.yaml`** (same paths plus seed and composite weights).

- Raw grid weather dir, county solar/wind dirs
- NLCD and EIA paths
- Transmission GeoJSON
- Target years and wind source policy (`grid_10km`)

---

## Processed artifacts summary

After running 00–06, expect these under `data/processed/`:

```
temporal_parity_report.json
weather_cell_features.parquet
grid_nlcd_fractional.parquet
eia_facility_annual.parquet
eia_facility_features.parquet
grid_transmission_distance.parquet
modeling_master_cell.parquet
cells_passing_gateway.parquet
gateway_filter_report.json
```

Plus `maps/developability_ny.html` at repo root.

---

## 07 — `07_solar_resource_model.ipynb` (Phase 3)

**Requires:** `06` + `in_ny_state` from `05`.

**Outputs:** `solar_scores_by_cell.parquet`, `maps/solar_resource_ny.html`, `models/solar_resource.joblib`

**Scoring (no seasonal leakage):**
- `resource_observed` — measured `shortwave_mean` (daytime-only after `01` re-run; current parquet may still be all-hour ~134–167 W/m²)
- `resource_land_adj_oof` — spatial-block CV, features = lat/lon + NLCD + met only
- `resource_screening_score` — percentile rank of observed (**primary map layer**)
- `resource_opportunity_oof` — observed − land-adjusted OOF

**Current result:** 1,024 cells; land-adjusted **OOF R² ≈ 0.78**.

---

## 08 — `08_wind_resource_model.ipynb` (Phase 3)

Same as `07`, target = `wind_power_mean`.

**Outputs:** `wind_scores_by_cell.parquet`, `maps/wind_resource_ny.html`

**Current result:** 1,024 cells; land-adjusted **OOF R² ≈ 0.48**.

---

## 09 — `09_combine_resource_scores.ipynb` (Phase 3)

Joins solar + wind → `cell_resource_scores.parquet` (1,024 rows) + `hybrid_screening_score` = mean of solar/wind screening percentiles.

**Top hybrid site (current):** (42.39°N, −79.44°W).

---

## 01b — `01b_physics_hourly_yield.ipynb` (physics layer)

**Requires:** `01` (raw hourly CSVs), `06` (gateway NY cells), `03` (EIA validation).

Hourly simplified solar (GHI × PR × temp derate) + generic 2.5 MW wind power curve on 80 m hub speed. **NY gateway cells only** (~1,089). Cached per year in `scratch/physics_cell_year/`.

**Outputs:** `cell_physics_yield.parquet` (`physics_*_cf_p50/p90`), `physics_validation_report.json`

**Settings:** `YEARS = [2025]` for a quick test; `INVALIDATE_SCRATCH = True` after formula changes.

---

## 10 — `10_yield_engine.ipynb` (Phase 4)

**Requires:** `01`, `03`, `06`.

**Plant × year** XGBoost on EIA capacity factor (2018–2023), ≤ 5 km snap, spatial-block CV. Composite P50 may use `01b` physics when solar CV < 0 (see `13`).

**Outputs:** `cell_p50_yield.parquet`, `yield_*_cv_report.json`, yield maps.

---

## 11 — `11_hybrid_seasonal_suitability.ipynb` (Phase 5)

**Requires:** `01`, `06`; optional `09`, `10`.

Summer JJA GHI × winter **hub-height DJF** wind percentile (`wind_hub_speed_p50_DJF`); **jackpot** = top quartile both.

**Outputs:** `hybrid_suitability.parquet`, `seasonal_gap_report.json`, `maps/hybrid_seasonal_suitability_ny.html`

---

## 12 — `12_risk_stress_p90.ipynb` (Phase 6)

**Requires:** `01` scratch years, `06`, `10` (P50).

P90 = P50 × **5th percentile** of year-level stress ratios (full 8-year distribution). **Risk spread** = P50 − P90. Extra: `solar_stress_ratio_std`, `wind_stress_ratio_std`.

**Outputs:** `cell_p90_yield.parquet`, `cell_risk_spread.parquet`, `maps/risk_spread_ny.html`

---

## 13 — `13_composite_score.ipynb` (Phase 7)

Weighted score: resource + seasonal + P50 − risk + developability. Uses `physics_hybrid_cf_p50` for P50_norm when solar yield CV R² < 0. K-Means (k=4) on D, P50, R.

**Outputs:** `cell_composite_score.parquet`, `outputs/ny_composite_ranked.geojson`, `maps/composite_score_ny.html`

---

## 14 — `14_export_gis_and_tables.ipynb` (Phase 8)

Writes screening GeoJSON to `outputs/`, adds limitation notes on `maps/*.html`, and writes summary CSV/JSON to `results/tables/`.

**Requires:** `13` completed.

---

## 15 — `15_pipeline_validation.ipynb` (QA)

Checks artifacts exist, **≥ 1,024** scored cells (1,089 in current release), weather cols ≥ 80, physics yield, yield CV warnings, risk spread vs the earlier 1,024-cell baseline, P90 ≤ P50, composite P50 source documented.

**Output:** `data/processed/pipeline_validation_report.json` — aim for `all_passed: true` before sharing results.

---

## Batch run

```bash
python scripts/run_pipeline.py
```

Same command on Windows, macOS, and Linux. `scripts/run_pipeline.sh` just calls that Python runner. Use `--container` only if you built `clean-energy-ml.sif`.

---

## Re-run chains

| After changing… | Re-run |
|-----------------|--------|
| Weather features (`01`) | `01 → 05 → 06 → 07–15` |
| NLCD only (`02`) | `02 → 05 → 06 → 07–15` |
| Yield only (`03`, `10`) | `03 → 10 → 12 → 13 → 14 → 15` |
| Physics only (`01b`) | `01b → 13 → 14 → 15` |
| Full pipeline | `python scripts/run_pipeline.py` |
