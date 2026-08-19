# Legacy / optional source scripts

Scripts here are **not** on the primary analysis path
(`compute_population` → `compute_pss` → `compute_mss` → `compute_expected_coverage` → `visualize`).

| Script | Role |
| --- | --- |
| `population.py` | Legacy WorldPop GEE overlay; pipeline uses `../compute_population.py` |
| `news.py` | GDELT Doc API collector; primary MSS reads `data/gdelt_bq.json` |
| `process_bigquery.py` | Early BigQuery JSON processor (12-event era) |
| `build_covariates.py` | Wrote `state_covariates.csv` (unused by scoring/models) |
| `rainfall.py` | Event rainfall (unused downstream) |
| `build_events.py` / `build_events_emdat.py` | Validate or regenerate the canonical `data/raw/events.csv`; seed rows are read from that registry |
| `fix_districts.py` | One-shot district geocode fix |
| `test_gee.py` | GEE connectivity smoke test |

To re-run an archived script from repo root:

```bash
python src/archive/<script>.py
```

`build_events.py` no longer contains an embedded event list. The EM-DAT
builder reads rows marked `event_source=manual_seed` from `data/raw/events.csv`
and appends regenerated rows marked `event_source=emdat_derived`.
