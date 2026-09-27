# Raw inputs used in the paper (not shipped)

Set these under `config/config.yaml` → `paths.data.raw` (same keys in `config/paths.yaml`). Paths are relative to the repo root.

| Config key | Expected path | Role |
|------------|---------------|------|
| `grid_weather_dir` | `data/raw_solar_wind_hourly_data/` | Open-Meteo 10 km hourly weather CSVs (2018–2025) |
| `county_solar_dir` | `data/ny_county_solar_hourly_API_Data/` | County solar hourly CSVs |
| `county_wind_dir` | `data/ny-county_Wind_hourly_API_Data/` | County wind hourly CSVs |
| `nlcd_ny_csv` | `data/model_data/Annual_NLCD_LndCov_2024_NY_only.csv` | NLCD 2024 NY extract (notebook 02 may also use a GeoTIFF) |
| `eia_generation_csv` | `data/model_data/NY_Greation_Data_with_nlcd.csv` | EIA generation / CF targets |
| `transmission_geojson` | `data/US_Electric_Power_Transmission_Lin2es_-6976209181916424225.geojson` | HIFLD / EIA transmission lines |

Journal figures can be rebuilt from the shipped `data/processed/` tree (`scripts/rebuild_v7_consistency_figures.py`). Re-running notebooks 00–15 needs the files above.
