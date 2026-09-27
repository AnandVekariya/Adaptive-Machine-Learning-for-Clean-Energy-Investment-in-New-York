# Data Dictionary — NY Clean Energy Grid Pipeline

**Purpose:** Standalone column reference for all pipeline features and scores  
**Source of truth:** `src/pipeline/*.ipynb` (notebooks 00–15)  
**Companion:** [`README.md`](README.md) (folder overview)  
**Last updated:** June 2026

---

## How to read this document

| Field | Meaning |
|-------|---------|
| **Column** | Name in Parquet / GeoJSON exports |
| **Units** | Physical units or dimensionless |
| **Stage** | Pipeline notebook that creates the column |
| **Used in ML** | Whether the column is a model feature or target |

Keys: `lat`/`lon` = `(latitude, longitude)` on the ~10 km NY grid (WGS84).

---

## 1. Raw hourly weather (10 km grid CSVs)

**Source:** Open-Meteo archive 2018–2025 · **Notebook:** `01_ingest_weather`

| Column | Units | Description |
|--------|-------|-------------|
| `date` | UTC datetime | Hourly timestamp |
| `latitude`, `longitude` | degrees | Cell centroid (~0.09° step) |
| `shortwave_radiation` | W/m² | Global horizontal irradiance (GHI) |
| `direct_radiation` | W/m² | Direct normal component |
| `diffuse_radiation` | W/m² | Diffuse horizontal |
| `wind_speed_10m` | m/s | 10 m wind speed (hub-height proxy) |
| `wind_direction_10m` | degrees | Wind direction |
| `temperature_2m` | °C | Air temperature |
| `surface_pressure` | hPa | Surface pressure |

---

## 2. Weather cell features (`weather_cell_features.parquet`)

**Notebook:** `01` · **Rows:** 4,401 cells · **84 columns**

### 2.1 Solar climatology

| Column | Units | Description | ML |
|--------|-------|-------------|-----|
| `shortwave_mean` | W/m² | Mean irradiance when shortwave > 0 (daytime only) | Target (solar) |
| `shortwave_mean_24h` | W/m² | All-hour mean (includes night zeros) | Reference |
| `shortwave_interannual_std` | W/m² | Std of annual `shortwave_mean` across years | Feature |
| `shortwave_intraseasonal_std_mean` | W/m² | Mean of monthly std within years | Feature |
| `direct_mean` | W/m² | Mean direct radiation | Feature |
| `diffuse_mean` | W/m² | Mean diffuse radiation | Feature |
| `shortwave_diurnal_amplitude` | W/m² | Daily max − min shortwave | Feature |
| `clear_sky_index` | 0–1 | Observed GHI / clear-sky GHI | Feature |
| `direct_diffuse_ratio` | ratio | Direct / (diffuse + ε) | Feature |
| `shortwave_mean_m01` … `m12` | W/m² | Monthly mean shortwave (Jan–Dec) | Feature |
| `shortwave_std_m01` … `m12` | W/m² | Monthly std shortwave | Feature |
| `shortwave_mean_DJF/MAM/JJA/SON` | W/m² | Seasonal mean shortwave | Feature |

### 2.2 Wind climatology

| Column | Units | Description | ML |
|--------|-------|-------------|-----|
| `wind_speed_mean` | m/s | Mean 10 m wind speed | Feature |
| `wind_speed_interannual_std` | m/s | Interannual variability | Feature |
| `wind_speed_intraseasonal_std_mean` | m/s | Mean monthly std | Feature |
| `wind_speed_p90` | m/s | 90th percentile 10 m speed | Feature |
| `wind_power_mean` | (m/s)³ | Mean wind³ proxy | Target (wind) |
| `wind_speed_hub_mean` | m/s | 10 m × hub factor (1.3) | Feature |
| `wind_speed_hub_std` | m/s | Hub-height std | Feature |
| `wind_hub_power_mean` | (m/s)³ | Hub-height wind³ | Feature |
| `wind_hub_speed_p50/p75/p90/p95` | m/s | Hub-height percentiles | Feature |
| `wind_ramp_p95` | m/s | 95th percentile hour-to-hour hub ramp | Feature |
| `weibull_k`, `weibull_A` | — | Weibull fit to hub wind | Feature |
| `wind_speed_mean_m01` … `m12` | m/s | Monthly mean wind | Feature |
| `wind_speed_mean_DJF/MAM/JJA/SON` | m/s | Seasonal mean wind | Feature |
| `wind_power_mean_DJF/MAM/JJA/SON` | (m/s)³ | Seasonal wind power | Feature |
| `wind_hub_speed_p50_DJF/JJA` | m/s | Seasonal hub percentiles | Feature |
| `wind_hub_speed_p90_DJF/JJA` | m/s | Seasonal hub percentiles | Feature |
| `wind_data_source` | text | Always `10km_grid_2018_2025` | Metadata |

### 2.3 Meta

| Column | Units | Description |
|--------|-------|-------------|
| `temperature_mean` | °C | Mean 2 m temperature |
| `surface_pressure_mean` | hPa | Mean surface pressure |
| `n_years` | count | Years aggregated (8) |
| `year_start`, `year_end` | year | 2018, 2025 |

---

## 3. NLCD land cover (`grid_nlcd_fractional.parquet`)

**Notebook:** `02` · **Method:** 5 km radius zonal stats on NLCD 2024

| Column | Units | NLCD class | Description |
|--------|-------|------------|-------------|
| `frac_class_11` | 0–1 | Open water | Water fraction |
| `frac_class_12` | 0–1 | Perennial ice/snow | Ice/snow |
| `frac_class_21–24` | 0–1 | Developed open/med/low/high | Urban/developed |
| `frac_class_31` | 0–1 | Barren | Barren land |
| `frac_class_41–43` | 0–1 | Forest | Deciduous/evergreen/mixed |
| `frac_class_52` | 0–1 | Shrub/scrub | Shrubland |
| `frac_class_71` | 0–1 | Grassland | Grassland |
| `frac_class_81–82` | 0–1 | Pasture/crops | Agriculture |
| `frac_class_90`, `95` | 0–1 | Wetlands | Woody/emergent wetlands |
| `nlcd_pixel_count` | count | — | Pixels in buffer |
| `nlcd_code_centroid` | code | — | Dominant class at centroid |
| `nlcd_class_centroid` | text | — | Dominant class label |
| `nlcd_fraction_sum` | 0–1 | — | Sum of fractions (QA) |

---

## 4. Grid & master table

| Column | Units | Stage | Description |
|--------|-------|-------|-------------|
| `dist_to_transmission_km` | km | `04` | Nearest US transmission line (UTM 18N) |
| `in_ny_state` | bool | `05` | Point inside NY boundary |
| `modeling_master_cell` | — | `05` | Join of weather + NLCD + transmission (103 cols) |

---

## 5. Developability gateway (`06`)

| Column | Units | Description |
|--------|-------|-------------|
| `developability_raw` | score | Weighted NLCD mix before min-max |
| `developability_D` | 0–1 | Min-max normalized developability |
| `passes_gateway` | bool | True if cell passes all hard filters |
| `fail_water` | bool | Water > 50% |
| `fail_developed` | bool | Developed > 20% |
| `fail_wetland` | bool | Wetlands > 30% |
| `fail_ice` | bool | Ice/snow > 30% |
| `fail_low_D` | bool | D < 0.20 |

**Hard filter formula (D_raw):**

```
D_raw = 0.35·(frac_81 + frac_82) + 0.25·frac_31 + 0.20·frac_21
        − 0.15·(frac_41 + frac_42 + frac_43) − 0.20·(frac_90 + frac_95)
```

---

## 6. Resource scores (`cell_resource_scores.parquet`)

**Notebooks:** `07` solar, `08` wind, `09` combine · **Rows:** 1,089 scored NY cells

| Column | Units | Description |
|--------|-------|-------------|
| `solar_resource_observed` | W/m² | Measured `shortwave_mean` at cell |
| `solar_resource_observed_pct` | 0–100 | Statewide percentile |
| `solar_resource_land_adj_oof` | W/m² | Spatial-CV XGBoost OOF prediction |
| `solar_resource_opportunity_oof` | W/m² | observed − land_adj_oof |
| `solar_resource_screening_score` | 0–100 | **Primary solar rank** (observed percentile) |
| `wind_resource_observed` | (m/s)³ | Measured wind power proxy |
| `wind_resource_observed_pct` | 0–100 | Statewide percentile |
| `wind_resource_land_adj_oof` | (m/s)³ | Spatial-CV OOF |
| `wind_resource_opportunity_oof` | (m/s)³ | observed − land_adj_oof |
| `wind_resource_screening_score` | 0–100 | **Primary wind rank** |
| `hybrid_screening_score` | 0–100 | Mean of solar + wind screening percentiles |

---

## 7. Yield layer (`cell_p50_yield.parquet`)

**Notebook:** `10` · Directional only (negative spatial CV R²)

| Column | Units | Description |
|--------|-------|-------------|
| `solar_cf_p50` | 0–1 | Predicted solar capacity factor |
| `wind_cf_p50` | 0–1 | Predicted wind capacity factor |
| `hybrid_cf_p50` | 0–1 | Mean of solar + wind P50 |
| `physics_hybrid_cf_p50` | 0–1 | Physics hourly layer (`01b`) fallback |

---

## 8. Seasonal hybrid (`hybrid_suitability.parquet`)

**Notebook:** `11`

| Column | Units | Description |
|--------|-------|-------------|
| `summer_ghi` | W/m² | `shortwave_mean_JJA` |
| `winter_wind` | m/s | `wind_speed_mean_DJF` |
| `hybrid_seasonal_score` | 0–1 | percentile(JJA) × percentile(DJF) |
| `jackpot_zone` | bool | Both seasonal percentiles ≥ 75th |

---

## 9. Risk stress (`cell_risk_spread.parquet`)

**Notebook:** `12`

| Column | Units | Description |
|--------|-------|-------------|
| `solar_stress_ratio_std` | ratio | Worst 2-year solar / climatology |
| `wind_stress_ratio_std` | ratio | Worst 2-year wind / climatology |
| `hybrid_cf_p90` | 0–1 | P50 × stress ratio (downside) |
| `hybrid_risk_spread` | 0–1 | P50 − P90 |

---

## 10. Composite score (`cell_composite_score.parquet`)

**Notebook:** `13` · Default weights: resource 0.35, seasonal 0.15, yield 0.30, risk −0.10, land 0.10

### 10.1 Normalized components (0–100 percentile scale)

| Column | Source signal |
|--------|---------------|
| `resource_norm` | `hybrid_screening_score` |
| `seasonal_norm` | `hybrid_seasonal_score` |
| `P50_norm` | `P50_for_composite` (physics if XGB CV < 0) |
| `P50_norm_xgb` | `hybrid_cf_p50` |
| `R_norm` | `hybrid_risk_spread` (penalty) |
| `D_norm` | Blend of developability + inverted transmission distance |
| `transmission_pct` | Percentile of `dist_to_transmission_km` |
| `transmission_score` | 100 − transmission_pct |

### 10.2 Composite & clusters

| Column | Description |
|--------|-------------|
| `composite_score` | Weighted sum S (default persona) |
| `composite_rank_pct` | Percentile rank of S |
| `cluster_id` | K-Means k=4 on (D_norm, P50_norm, R_norm) |
| `cluster_label` | A_prime_balanced, B_high_yield_risk, C_moderate_safe, D_lower_tier |

### 10.3 Persona sensitivity columns

Recomputed in notebook `13`:

| Column | Persona weights (resource / seasonal / yield / risk / land) |
|--------|--------------------------------------------------------------|
| `composite_persona_balanced` | 0.35 / 0.15 / 0.30 / 0.10 / 0.10 |
| `composite_persona_resource_first` | 0.55 / 0.15 / 0.15 / 0.05 / 0.10 |
| `composite_persona_conservative` | 0.25 / 0.15 / 0.20 / 0.25 / 0.15 |
| `composite_persona_yield_focus` | 0.20 / 0.10 / 0.45 / 0.10 / 0.15 |
| `composite_persona_risk_plus_10pct` | 0.35 / 0.15 / 0.25 / 0.15 / 0.10 |
| `composite_persona_resource_plus_10pct` | 0.45 / 0.15 / 0.25 / 0.10 / 0.05 |
| `rank_persona_*` | Rank under each persona |
| `rank_delta_resource_first` | balanced rank − resource_first rank |
| `rank_delta_conservative` | balanced rank − conservative rank |

---

## 11. GIS exports

| File | Key properties |
|------|----------------|
| `outputs/ny_composite_ranked.geojson` | Full composite + persona columns |
| `outputs/ny_solar_screening.geojson` | Solar screening layers |
| `outputs/ny_wind_screening.geojson` | Wind screening layers |
| `outputs/ny_hybrid_suitability.geojson` | Seasonal hybrid + jackpot |

---

## 12. NYISO queue cross-check

| File | Description |
|------|-------------|
| `data/raw_data/nyiso_interconnection_queue.csv` | NYISO queue snapshot (gridstatus) |
| `results/tables/NYISO_QUEUE_CROSSCHECK.md` | Top-25 cells vs active county queue |
| `results/tables/nyiso_queue_crosscheck_top25.csv` | Machine-readable cross-check |

---

## 13. EIA plant targets (`03`)

| Column | Description |
|--------|-------------|
| `Net Generation (MWh)` | Annual generation |
| `Nameplate Capacity (MW)` | Installed capacity |
| `capacity_factor` | CF = MWh / (MW × 8760), flagged if > 1.2 |
| `fuel_type` | SUN (solar), WND (wind) |

---

*Figure rebuild and scoring constants: see `config/config.yaml` and `scripts/rebuild_v7_consistency_figures.py`.*
