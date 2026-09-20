# CVND project context

## Current analysis definition

- Unit: EM-DAT flood event × explicit district.
- Primary response: district-explicit flood news in `[onset,onset+30d)`.
- Sensitivity response: the nested `[onset,onset+14d)` count.
- Exposure: satellite flood extent observed in `[onset,onset+14d)`.
- Default routing: `s1_then_s2`; S1 for all valid AOIs, S2 only where S1 is missing.
- Production pipeline: Track A only (`s1_then_s2`). Track B/SITS is retained only as non-production research code.
- Main model: NB2 `article_count ~ log1p(flood_area_km2) + urban_population_share`.

## Authoritative paths

- Registry: `data/intermediate/event_districts.csv`
- Article QA: `data/intermediate/article_qa/`
- Primary data/results: `data/results/primary_30d/`
- Sensitivity data/results: `data/results/sensitivity_14d/`
- Primary report/package: `outputs/primary_30d/`
- Sensitivity report: `outputs/sensitivity_14d/`
- Opt-in Track B 35-district data: `data/results/track_b_35_sensitivity/`
- Opt-in Track B report: `outputs/track_b_35_sensitivity/`
- Reproducible environment: `requirements-lock.txt`

Legacy `data/raw/events.csv`, flat analysis outputs, `sensitivity_30d/`, and `final_30d_primary/` are unsupported and must not be recreated.

## Pipeline state rules

`ARTICLE_PIPELINE_MODE=frozen` is the default and verifies registry/source/prompt/model/request/result hashes. It proceeds only for validated `llm_complete` 30d+14d counts and never mutates article, body, heuristic, or LLM artifacts. `complete` and lower-bound `partial` are observations; `incomplete` is missing data.

The standard sequence is registry → covariates/AOI → S1 → S2 fallback → merge → frozen article validation → 30d primary join/analysis/scoring → 14d sensitivity join/analysis/scoring → primary package. Paid/authenticated calls are not part of automated tests.

## Reproducibility

`outputs/primary_30d/analysis_manifest.json` records both input hashes and row counts, Git HEAD/dirty state, source diff hash, and lock-file hash. The package must be regenerated from the current canonical joined inputs after code or dependency changes.

The current canonical Track-A joined inputs contain 1,548 rows: 1,198 are eligible in the 30-day primary analysis and 1,074 in the 14-day sensitivity. Article counts are the frozen lower-bound QA observations. The separate 35-district Track-B package is an opt-in measurement sensitivity, selected for optical feasibility; it must not be treated as a representative replacement for production Track A.

Analysis and scoring summaries bind their input hash to the current source-tree hash. Packaging rejects stale summaries/model tables. `source.patch` includes staged changes; `source_snapshot.zip` also preserves untracked implementation files.

Use `bash scripts/run_pipeline.sh --dry-run`, `python -m unittest discover -s tests`, `python -m compileall -q src tests scripts`, `bash -n scripts/run_pipeline.sh`, and `git diff --check` before publication.
