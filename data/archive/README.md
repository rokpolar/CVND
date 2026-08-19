# Archived data artifacts

Unused or superseded outputs kept for reproducibility. Primary pipeline reads
from `data/` (not this folder), except optional fallbacks noted below.

| File | Notes |
| --- | --- |
| `state_covariates.csv` | From archived `build_covariates.py`; unread by models |
| `rainfall.csv` | From archived `rainfall.py`; unread downstream |
| `state_pi.csv` / `pi_results.csv` | Orphan PI covariates |
| `flood_area_results.csv` | Pre-`flood_combined` severity source; optional fallback in `compute_population.py` |
| `gdelt_bigquery_lang.json` | Input for archived `process_bigquery.py` |
| `sits_patches_index.csv` | Track B patch index (satellite prep); not needed for cached scoring |
| `emdat_raw.xlsx` | Original EM-DAT download; pipeline now uses `data/raw/emdat_raw.csv` |
