# Legacy / optional source scripts

Scripts here are **not** on the primary analysis path
(`compute_population` → `compute_pss` → `compute_mss` → `compute_expected_coverage` → `visualize`).

| Script | Role |
| --- | --- |
| `population.py` | Legacy WorldPop GEE overlay; pipeline uses `../compute_population.py` |
| `news.py` | Recent-only GDELT DOC API experiment; historical collection uses `../collect_gdelt.py` |
| `process_bigquery.py` | Early BigQuery JSON processor (12-event era) |
| `build_covariates.py` | Wrote `state_covariates.csv` (unused by scoring/models) |
| `rainfall.py` | Event rainfall (unused downstream) |
| `build_events.py` / `build_events_emdat.py` | Validate or regenerate `events.csv` from official `EM-DAT-BASE.xlsx`; no seed rows |
| `fix_districts.py` | Legacy district geocode audit; never overwrites canonical events |
| `test_gee.py` | GEE connectivity smoke test |

To re-run an archived script from repo root:

```bash
python src/archive/<script>.py
```

`build_events.py` no longer contains an embedded event list. The compatibility
builder delegates to `src/build_emdat_events.py`. Different
official `DisNo.` records are never merged and manual event seeds are not used.
