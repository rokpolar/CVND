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
| `events.csv` | `events` | `build_events_emdat.py` (manual) | All pipeline steps |
| `population.csv` | `population` | External (StatisticsTimes / Technical Group projections) | `compute_population.py` |
| `state_area.csv` | `state_area` | Survey of India area table (see `source` column) | `compute_population.py` |
| `emdat_raw.csv` | `emdat` | EM-DAT export | `compute_expected_coverage.py` |
| `gdelt_bq.json` | `gdelt_bq` | BigQuery export (manual) | `compute_mss.py` |
| `events_quarantine.csv` | `events_quarantine` | Manual QC | `compute_expected_coverage.py` |

### `cache/`

| File | Key | Producer | Consumers |
| --- | --- | --- | --- |
| `flood_extent.csv` | `flood_extent` | `satellite.py` | `merge_results.py` |
| `sits_scores/*.npz` | `sits_scores` | Colab / SITS scoring | `merge_results.py` |
| `satellite_checkpoint_*.json` | `satellite_checkpoint_*` | `satellite.py` | GEE resume |
| `ne_india_states.gpkg` | `ne_india_states` | `visualize.py` (optional) | Plot 9 choropleth |

### `intermediate/`

| File | Key | Producer | Consumers |
| --- | --- | --- | --- |
| `flood_combined.csv` | `flood_combined` | `merge_results.py` | `compute_population.py` |
| `district_area.csv` | `district_area` | `district_area.py` | `merge_results.py` |
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

## Expected row counts (approx.)

| Stage | Rows | Notes |
| --- | ---: | --- |
| `events.csv` | 168 | Master event list |
| `mss_results.csv` | 167 | E125 missing GDELT |
| `pss_results.csv` | ~136 | Drops events without flood/pop |
| `expected_coverage.csv` | ~132 | Quarantine + missing media/severity |

## Provenance

- **population.csv** — State/UT 2025 estimates; likely from [StatisticsTimes](https://statisticstimes.com/demographics/india/indian-states-population.php) derived from Technical Group on Population Projections.
- **state_area.csv** — State/UT areas (km²) from Survey of India reference table; used with uniform density for `population_exposed`.

## Legacy scripts

`src/archive/*`, `satellite.py`, `district_area.py`, and `post_cloud.py` still
reference the old flat `data/` paths until a follow-up update.
