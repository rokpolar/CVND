# CVND project context

Snapshot date: 2026-09-12 (Asia/Seoul)
Repository root: `/home/home/CVND`
Remote: `origin` = `https://github.com/rokpolar/CVND.git`
Branch: `main`
HEAD at snapshot: `c94072b Add offline state article reuse pipeline`
Remote main at snapshot: `fa31a1a Merge pull request #8 from rokpolar/refactor/satellite2`

This file is a factual project inventory for a later pipeline review. It does
not define an analytical conclusion or choose a research policy.

## Project purpose

CVND is an India flood study. The primary observation key is event × district.
`event_id` is the parent EM-DAT event identifier, `source_record_id` is the
official EM-DAT DisNo., and `event_district_id` is the deterministic event ×
district key. The repository contains satellite flood-area processing, GDELT
article collection and body retrieval, Census 2011 covariates, joins, quality
checks, descriptive/statistical analysis and coverage scoring.

The supported runner is `scripts/run_pipeline.sh`. State-level files and
district-level files use separate paths. State satellite caches are not read as
district observations by the district runner.

## Current event registry

The official local source is `data/raw/EM-DAT-BASE.xlsx` (75 source records).
The generated parent event table is `data/raw/events.csv` and currently has
190 event rows. The generated district table is
`data/intermediate/event_districts.csv` and currently has 1,630 rows for the
same 190 events. The district table has no `district_missing` rows and no
district confidence column.

The following 14 parent event IDs were omitted because the maximal recovery
mapping supplied no district candidate:

`E006, E007, E011, E018, E043, E062, E063, E083, E102, E105, E123, E147, E149, E155`

The user-supplied recovery data was converted into two local files:

- `data/raw/district_recovery_mapping.csv`: 1,374 accepted maximal-evidence
  rows covering 154 event IDs. It stores event identity, canonical district,
  source metadata and evidence text. Recovery confidence and tier columns are
  not present.
- `data/raw/district_recovery_aliases.csv`: 33 spelling, compound-name and
  non-district actions used before event-district ID generation.

`src/district_recovery.py` merges the mapping with the generated registry,
deduplicates on `event_district_id`, keeps source provenance in
`district_resolution_evidence`, removes unresolved parent events and removes
the district confidence field from the returned table. The builder invokes it
from `src/build_emdat_events.py` on every non-dry run and dry run.

The event generation code still computes internal source confidence while
parsing EM-DAT. That internal value is removed before `events.csv` and
`event_districts.csv` are written. The final district join also drops that
field if an input table happens to contain it.

## Data files and current observations

### Raw inputs

- `data/raw/EM-DAT-BASE.xlsx`: official EM-DAT workbook.
- `data/raw/EM-DAT.xlsx`: existing EM-DAT state workbook.
- `data/raw/census_2011_district_urban_rural.xlsx`: Census 2011 population
  input; accompanying metadata is in the adjacent `.meta.json` file.
- `data/raw/events.csv`: current 190-row parent event registry.
- `data/raw/gdelt_bq.articles.jsonl`: 507,076 raw GDELT article metadata rows,
  approximately 280 MB.
- `data/raw/gdelt_bq.articles.jsonl.gz`: compressed copy of the same state
  article metadata, approximately 24 MB.
- `data/raw/gdelt_bq.articles.sqlite`: approximately 1.9 GB URL/body database.
- `data/raw/gdelt_bq.json` and `data/raw/gdelt_bq.meta.json`: earlier GDELT
  query output and collection metadata.
- `data/raw/district_name_crosswalk.csv`: existing Census crosswalk template.

The raw GDELT files remain state-event source data and include rows for the
omitted event IDs. The derived event article result files were filtered to the
current 190-event registry.

### Current article reuse state

`src/reuse_state_articles.py` reads the existing state JSONL and SQLite body
database without querying BigQuery or downloading article pages. Its latest
audit is `data/intermediate/state_article_reuse_audit.json`:

- input rows: 507,076
- rows passing event identity/state/window selection: 126,885 QA candidates
- rows provisionally assigned to a district from available evidence: 750
- rows without a resolved district assignment: 126,202
- outside-window or unmatched identity rows: 380,191
- LLM status in the generated QA candidate records: `not_submitted`

The district collection manifest at
`data/intermediate/district_gdelt.manifest.json` has spatial unit `district`,
window length 14 days and collection status `incomplete`. Article bodies are
reused by URL from the existing SQLite database. No LLM-QA request has been
submitted by the current local workflow. The current district article count
path is the multilingual keyword heuristic in `src/district_heuristics.py`.

### Satellite and model files

- `data/cache/models/sits_extreme/checkpoint_vae_contrastive_42.pth`: local
  SITS model checkpoint, approximately 234 MB.
- `data/cache/sits_patches/E043.h5`: existing state-level SITS HDF5 patch,
  approximately 1.37 GB, with a `.blocks.json` checkpoint.
- `data/cache/district/` is the configured primary district cache namespace.
- `data/cache/flood_extent.csv`, satellite checkpoints and other existing files
  are retained in the repository data tree.

Track B HDF5 inputs are retained after local inference. The district runner
uses percent-encoded district event keys for portable cache filenames.

## Pipeline execution

`scripts/run_pipeline.sh` loads `.env` when present and chooses a Python
interpreter with NumPy and pandas. Defaults are:

- `SETUP_DEPS=0`
- `SKIP_GEE=1`
- `SKIP_ARTICLES=1`
- `SKIP_COVARIATES=0`
- `SKIP_ANALYSIS=0`
- `SATELLITE_TRACK=A`
- `SATELLITE_ROUTING=s1_interim`
- `REUSE_STATE_ARTICLES=0`

The runner executes these stages in order:

1. `src/build_emdat_events.py`
2. `src/build_district_covariates.py` unless `SKIP_COVARIATES=1`
3. `src/event_aoi_area.py` and `src/satellite.py --track ...` unless
   `SKIP_GEE=1`
4. `src/run_sits_inference.py` when the track is `B` or `both`
5. `src/compare_tracks.py` when `SATELLITE_ROUTING=sits_primary`
6. `src/merge_results.py`
7. `src/build_flood_area_table.py`
8. Article stage: local reuse when `REUSE_STATE_ARTICLES=1`; otherwise
   district BigQuery collection and article body download when
   `SKIP_ARTICLES!=1`
9. `src/district_articles.py --counts-only` unless the local reuse stage was
   used
10. `src/join_district_flood_articles.py`
11. `src/analyze_coverage_disparity.py` and `src/score_coverage.py` unless
    `SKIP_ANALYSIS=1`

Offline commands in the repository are:

```bash
bash scripts/run_pipeline.sh --dry-run
venv/bin/python -m unittest discover -s tests
venv/bin/python -m compileall -q src tests
```

The local-only article reuse invocation is:

```bash
REUSE_STATE_ARTICLES=1 SKIP_GEE=1 SKIP_ARTICLES=1 bash scripts/run_pipeline.sh
```

## Environment and external services

`.env.example` names these settings:

- `GEE_PROJECT_ID` for Earth Engine.
- `GDELT_BILLING_PROJECT` for BigQuery billing.
- `OPENAI_API_KEY` for any OpenAI-based article workflow.
- `EMDAT_API_KEY` for the optional EM-DAT API collector.

The repository's Earth Engine setup is in `src/gee_config.py`. The GDELT SQL
and client logic are in `src/gdelt_backend.py` and `src/district_articles.py`.
The article body retrieval and repair logic are in `src/download_articles.py`,
`src/article_fetcher.py`, `src/article_extractor.py` and
`src/repair_article_database.py`.

## Source modules

- `build_emdat_events.py`: EM-DAT parent registry and event × district registry.
- `build_district_covariates.py`: Census 2011 total/urban/rural population and
  urban share.
- `event_aoi_area.py`: district AOI lookup and area metadata.
- `satellite.py`: Track A Sentinel-1/Sentinel-2 measurements and Track B SITS
  HDF5 patch preparation.
- `run_sits_inference.py`: local SITS checkpoint inference.
- `sits_feasibility.py`: SITS availability/feasibility checks.
- `merge_results.py`: satellite candidate routing.
- `build_flood_area_table.py`: final district flood-area table.
- `gdelt_backend.py`: BigQuery SQL and GDELT query helpers.
- `district_articles.py`: district article metadata query, body-aware heuristic
  counts and manifests.
- `district_heuristics.py`: multilingual flood keyword classifier.
- `reuse_state_articles.py`: offline state-article to district candidate reuse.
- `download_articles.py`, `article_fetcher.py`, `article_extractor.py`:
  article body retrieval, extraction and storage.
- `join_district_flood_articles.py`: identity checks, flood/article/Census join,
  exclusions and QC.
- `analyze_coverage_disparity.py`: descriptive analysis, Spearman association,
  NB2 models, figures and report output.
- `score_coverage.py`: source-group OOF NB2 article-count scoring.
- `pipeline_preflight.py`: artifact and specification checks.
- `cvnd_layout.py`: logical data and output paths.
- `flood_spec.py`: frozen satellite measurement specification and hash.
- `district_keys.py`: conservative geography normalization and key generation.

## Key output paths

- `data/intermediate/event_districts.csv`
- `data/intermediate/district_covariates.csv`
- `data/intermediate/district_aoi.csv`
- `data/cache/district/flood_extent.csv`
- `data/cache/district/sits_patches/`
- `data/cache/district/sits_scores/`
- `data/intermediate/district_flood_area.csv`
- `data/intermediate/district_gdelt.articles.jsonl.gz`
- `data/intermediate/district_gdelt.manifest.json`
- `data/results/district_article_counts.heuristic.csv`
- `data/results/district_flood_articles.csv`
- `data/results/district_analysis_exclusions.csv`
- `data/results/district_qc.json`
- `data/results/coverage_model_results.csv`
- `data/results/coverage_predictions.csv`
- `outputs/paper_results.md`
- `outputs/coverage_summary.json`
- `outputs/flood_area_vs_articles.png`
- `outputs/urbanization_adjusted_coverage.png`

## Git working state at snapshot

The local branch is one commit ahead of `origin/main` and has uncommitted
changes from district recovery, article reuse, generated registry/result files,
documentation and tests. The current uncommitted paths include:

- `data/raw/events.csv`
- `data/raw/district_recovery_mapping.csv`
- `data/raw/district_recovery_aliases.csv`
- `data/intermediate/event_districts.csv`
- `src/build_emdat_events.py`
- `src/district_recovery.py`
- `src/district_articles.py`
- `src/district_keys.py`
- `src/join_district_flood_articles.py`
- `tests/test_district_recovery.py`
- generated article/result files and `docs/district_recovery.md`

## Test snapshot

The full local command `venv/bin/python -m unittest discover -s tests` discovers
218 tests. At the snapshot it reports 215 passing tests and 3 errors in
`tests/test_coverage_disparity.py`. The errors occur in
`src/analyze_coverage_disparity.py` at the access
`result.model.data.design_info`; the installed statsmodels version reports no
such attribute. The repository requirements specify `statsmodels>=0.14.6,<0.15`.

The district recovery, EM-DAT builder, district article and district join test
groups pass. `git diff --check` passes.

## Current data state boundaries

The 190-event geography registry has been regenerated. Satellite AOI and flood
measurements are separate artifacts and are not regenerated by the event
builder. Article manifests contain a registry fingerprint and must correspond
to the current 190-event registry. The raw state GDELT corpus is preserved;
derived article outputs were regenerated or filtered for the current registry.
