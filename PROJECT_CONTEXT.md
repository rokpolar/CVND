# CVND project context

## Current analysis definition

- Unit: EM-DAT flood event × explicit district.
- Primary response: district-explicit flood news in `[onset,onset+30d)`.
- Sensitivity response: the nested `[onset,onset+14d)` count.
- Exposure: satellite flood extent observed in `[onset,onset+14d)`.
- Default routing: `s1_then_s2`; S1 for all valid AOIs, S2 only where S1 is missing.
- Default track: A. Track B/SITS requires explicit opt-in, including the supervised launcher.
- Main model: NB2 `article_count ~ log1p(flood_area_km2) + urban_population_share`.

## Authoritative paths

- Registry: `data/intermediate/event_districts.csv`
- Article QA: `data/intermediate/article_qa/`
- Primary data/results: `data/results/primary_30d/`
- Sensitivity data/results: `data/results/sensitivity_14d/`
- Primary report/package: `outputs/primary_30d/`
- Sensitivity report: `outputs/sensitivity_14d/`
- Reproducible environment: `requirements-lock.txt`

Legacy `data/raw/events.csv`, flat analysis outputs, `sensitivity_30d/`, and `final_30d_primary/` are unsupported and must not be recreated.

## Pipeline state rules

`ARTICLE_PIPELINE_MODE=auto` verifies registry/source/prompt/model/request/result hashes. Valid 30d+14d counts skip heuristic and LLM-QA; valid heuristic-only state resumes at LLM-QA; missing or stale state restarts heuristic preparation. `complete` and lower-bound `partial` are observations. `incomplete` is missing data.

The standard sequence is registry → covariates/AOI → S1 → S2 fallback → merge → article auto resume → 30d primary join/analysis/scoring → 14d sensitivity join/analysis/scoring → primary package. Paid/authenticated calls are not part of automated tests.

## Reproducibility

`outputs/primary_30d/analysis_manifest.json` records both input hashes and row counts, Git HEAD/dirty state, source diff hash, and lock-file hash. The package must be regenerated from the current canonical joined inputs after code or dependency changes.

Offline refits preserve the existing 1,553-row joined snapshots (1,191 primary / 1,069 sensitivity eligible). Their recorded satellite routing is historical `interim_s1_only`, not evidence of a fresh S1/S2 run. Current registry derivation yields 1,555 rows: `E189::south%20garo%20hills` and `E189::west%20garo%20hills` are additional reviewed recoveries in `data/review/reviewed_district_recoveries.json`. They have not been newly measured/QA-reviewed during offline validation. Preflight reports this drift and package manifests record both registry fingerprints. Do not fill these districts with zero or silently relabel the frozen inputs as current end-to-end results. The authenticated pipeline rebuilds the registry before collection.

Analysis and scoring summaries bind their input hash to the current source-tree hash. Packaging rejects stale summaries/model tables. `source.patch` includes staged changes; `source_snapshot.zip` also preserves untracked implementation files.

Use `bash scripts/run_pipeline.sh --dry-run`, `python -m unittest discover -s tests`, `python -m compileall -q src tests scripts`, `bash -n scripts/run_pipeline.sh`, and `git diff --check` before publication.
