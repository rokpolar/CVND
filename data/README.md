# CVND data layout

Tiered folders under `data/`. Primary pipeline scripts resolve paths via
`data_path(key)` in [`src/cvnd_layout.py`](../src/cvnd_layout.py).

## Tiers

| Folder | Role |
| --- | --- |
| `raw/` | External inputs (events, population, EM-DAT, GDELT export) |
| `cache/` | Satellite / GEE artifacts (rebuild when `SKIP_GEE=0`) |
| `intermediate/` | Pipeline step outputs between severity and scores |
| `results/` | PSS, MSS, expected coverage, and weight metadata |
| `archive/` | Legacy fallbacks (not used by default) |

## Files by tier

### `raw/`

| File | Key | Producer | Consumers |
| --- | --- | --- | --- |
| `EM-DAT-BASE.xlsx` | `emdat_base` | Exact official portal export | `build_emdat_events.py`, `compute_expected_coverage.py` |
| `EM-DAT.xlsx` | `emdat_state` | `build_emdat_events.py` + workbook export | Audit-ready state-event data |
| `events.csv` | `events` | `build_emdat_events.py` | All pipeline steps |
| `population.csv` | `population` | External (StatisticsTimes / Technical Group projections) | `compute_population.py` |
| `state_area.csv` | `state_area` | Survey of India area table (see `source` column) | `compute_population.py` |
| `emdat_api_raw.csv` | `emdat_api_csv` | `collect_emdat.py` (optional API staging) | Manual comparison before promotion |
| `emdat_api_raw.meta.json` | `emdat_meta` | `collect_emdat.py` provenance | Audit / reproducibility |
| `gdelt_bq.json` | `gdelt_bq` | BigQuery export (manual) | `compute_mss.py` |
| `events_quarantine.csv` | `events_quarantine` | Manual QC | `compute_expected_coverage.py` |

### `cache/`

| File | Key | Producer | Consumers |
| --- | --- | --- | --- |
| `flood_extent.csv` | `flood_extent` | `satellite.py` | `merge_results.py` |
| `sits_scores/*.npz` | `sits_scores` | Colab / SITS scoring | `merge_results.py` |
| `sits_patches/*.h5` | `sits_patches` | `satellite.py` Track B | External SITS inference |
| `sits_patches_index.csv` | `sits_patches_index` | `satellite.py` Track B | Audit / resume |
| `satellite_checkpoint_*.json` | `satellite_checkpoint_*` | `satellite.py` | GEE resume |
| `ne_india_states.gpkg` | `ne_india_states` | `visualize.py` (optional) | Plot 9 choropleth |

### `intermediate/`

| File | Key | Producer | Consumers |
| --- | --- | --- | --- |
| `flood_combined.csv` | `flood_combined` | `merge_results.py` | `compute_population.py` |
| `event_aoi_area.csv` | `event_aoi_area` | `event_aoi_area.py` | `merge_results.py` |
| `post_cloud.csv` | `post_cloud` | `post_cloud.py` | `merge_results.py` |
| `severity_raw.csv` | `severity_raw` | `compute_population.py` | `compute_pss.py`, `compute_expected_coverage.py` |

### `results/`

| File | Key | Producer |
| --- | --- | --- |
| `pss_results.csv` | `pss_results` | `compute_pss.py` |
| `mss_results.csv` | `mss_results` | `compute_mss.py` |
| `expected_coverage.csv` | `expected_coverage` | `compute_expected_coverage.py` |
| `state_expected_coverage.csv` | `state_expected_coverage` | `compute_expected_coverage.py` |
| `mss_weight_sensitivity.json` | `mss_weight_meta` | `compute_mss.py` |
| `mss_weight_provenance.csv` | `mss_weight_provenance` | `compute_mss.py` |
| `mss_rank_stability.csv` | `mss_rank_stability` | `compute_mss.py` |

## Current source coverage

| Stage | Rows | Notes |
| --- | ---: | --- |
| `EM-DAT-BASE.xlsx` | 75 | Official source records |
| `events.csv` | 204 | Current unique `DisNo.` × state/UT result; not a fixed target |

## Provenance

- **EM-DAT-BASE.xlsx** — sole official event truth, preserved byte-for-byte.
- **EM-DAT.xlsx** — one row per unique official `DisNo.` and resolved Indian
  state/UT. All 47 original columns are retained; manual seeds and cross-event
  date merging are prohibited.
- **events.csv** — lean registry derived from the same rows. `source_record_id`
  is always the exact official `DisNo.` and `event_source` is
  `emdat_official_state`.
- **population.csv** — State/UT 2025 estimates; likely from [StatisticsTimes](https://statisticstimes.com/demographics/india/indian-states-population.php) derived from Technical Group on Population Projections.
- **state_area.csv** — State/UT areas (km²) from Survey of India reference table; used with uniform density for `population_exposed`.

## Legacy scripts

The event readers in legacy/optional scripts now use the canonical
`data/raw/events.csv`. Some optional scripts still write their outputs to the
old flat `data/` paths and are not part of the primary runner.
