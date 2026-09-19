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

## 2026-09-19 offline repair scope

- Validation: 337 offline tests passed with no skips; `compileall`, shell syntax, `git diff --check`, dry-run, dependency checks, and input/source/lock/archive hash checks passed. Dry-run still reports unavailable live caches and registry drift; it is not an end-to-end collection test.
- Default and supervised launchers use Track A / `s1_then_s2`; Track B remains explicit opt-in. Sensor attempts are checkpointed independently; unqueried sensors have missing image counts, and legacy zero-image counters do not prove an attempt. Finite S1 zero skips S2; invalid AOIs do not enter fallback.
- QA reuse verifies candidate source/body/collection hashes, both count-file hashes, the parent QA manifest, result hash, and supplement ledger. Collection completeness is district-specific; completed empty queries are observed zero, while missing queries remain missing. Preflight uses the district source, district body DB and configured model.
- Cached SITS NPZ files repair absent/stale measurement CSV rows without loading the model. Inference locks follow the selected score directory.
- The lock now includes Torch, boto3 and their resolved transitive dependencies; installation and `pip check` are included in validation. Torch-dependent offline tests are no longer skipped in this environment.
- Packages reject stale analysis/scoring provenance. Staged and untracked source changes are fingerprinted; a deterministic source ZIP preserves their bytes.
- Existing joined inputs remain historical snapshots: 1,553 rows, with 1,191/1,069 eligible. The current registry builder yields 1,555 rows, adding two reviewed E189 Garo Hills districts. The read-only registry audit reports this difference in preflight and the package manifest. No observations for those additions are invented; authenticated collection is outside this offline repair.
- Refit results retain historical `interim_s1_only` routing labels. A successful offline refit is not a claim that the new satellite/news pipeline ran against external services.

## 2026-09-17 validation

- Full suite: 288 passed, 4 skipped.
- `compileall`, both shell syntax checks, `git diff --check`, and offline pipeline dry-run passed.
- Primary: 1,553 rows, 1,191 eligible, only `window_days=30`, input SHA-256 `3ff0313a2b8823528553124310c16b5ef272cd92f8a219087c088a626a2d8cc8`.
- Sensitivity: 1,553 rows, 1,069 eligible, only `window_days=14`, input SHA-256 `79281623bc814617ac6906f6c0c44168872f9bc45cc60212ada92810067d35bd`.
- Both H1/H2 analyses and both OOF scoring runs were regenerated locally without external service calls. The primary package records execution HEAD `c0c390f5a434911723e89d119dadebf1c05b4083` and the dirty source provenance.
