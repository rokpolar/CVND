# Implementation validation

This file records the current 30-day-primary implementation contract. Historical state-level and 14-day-primary snapshots are intentionally removed.

## Implemented gates

- News windows are `PRIMARY_NEWS_WINDOW_DAYS=30` and `SENSITIVITY_NEWS_WINDOW_DAYS=14`; satellite remains `SATELLITE_POST_WINDOW_DAYS=14`.
- The article auto-resume state validates both count windows and provenance hashes. `complete` and `partial` are observations; `incomplete` is valid missingness.
- Track A runs S1 first, then S2 only for valid-AOI keys with missing S1 area. Finite S1 zero is observed, not failed.
- `build_emdat_events.py` writes only the event×district registry.
- Analysis labels derive from the input's single `window_days`; absent or mixed windows fail.
- Canonical outputs are split into `primary_30d/` and `sensitivity_14d/`; no legacy aliases are emitted.
- `requirements-lock.txt` pins the complete validated Python 3.13 environment.

## Required checks

```bash
venv/bin/python -m unittest discover -s tests
venv/bin/python -m compileall -q src tests scripts
bash -n scripts/run_pipeline.sh
git diff --check
bash scripts/run_pipeline.sh --dry-run
```

The final validation record must also verify primary/sensitivity input hashes, row counts and window values, and regenerate `outputs/primary_30d/analysis_manifest.json`, `key_results.csv`, and `final_results_figure.png` from the canonical joined inputs. External GEE, BigQuery and OpenAI operations remain mocked in automated tests.

## 2026-09-17 validation

- Full suite: 288 passed, 4 skipped.
- `compileall`, both shell syntax checks, `git diff --check`, and offline pipeline dry-run passed.
- Primary: 1,553 rows, 1,191 eligible, only `window_days=30`, input SHA-256 `3ff0313a2b8823528553124310c16b5ef272cd92f8a219087c088a626a2d8cc8`.
- Sensitivity: 1,553 rows, 1,069 eligible, only `window_days=14`, input SHA-256 `79281623bc814617ac6906f6c0c44168872f9bc45cc60212ada92810067d35bd`.
- Both H1/H2 analyses and both OOF scoring runs were regenerated locally without external service calls. The primary package records execution HEAD `c0c390f5a434911723e89d119dadebf1c05b4083` and the dirty source provenance.
