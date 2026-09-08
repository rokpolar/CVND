# Primary district data artifacts

All paths are registered in `src/cvnd_layout.py`. Primary satellite caches live under `data/cache/district/`, and primary article/covariate tables use district-specific names. An `event_id`-only state table is never an acceptable district input.

## Required Census input

Supply the official Census of India 2011 district urban/rural population file at `data/raw/census_2011_district_urban_rural.xlsx` (or pass `--input`). The verified input is ORGI [Basic Population Figures of India/State/District/Sub-District/Village, 2011](https://censusindia.gov.in/nada/index.php/catalog/42557), file `2011-IndiaStateDist-0000.xlsx`. Its actual `Data` and `Record Structure` sheets were inspected; 2,028 input rows include 1,920 district/residence rows representing 640 districts. The parser recognizes:

- PCA SD machine columns: `State`, `District`, `Level`, `Name`, `TRU`, `TOT_P`. State/district are location codes; district names come from `Name`, residence from `TRU` (`Total`, `Rural`, `Urban`), and person counts from `TOT_P`.
- Named-geography long format: `state`, `district`, `Residence` (`Total/Rural/Urban`), `Population - Persons`; optional district code.
- A transparent wide extraction of the official source: `state`, `district`, `total_population`, `urban_population`, `rural_population`; optional `census_district_code`, `census_year` (must be 2011).

Counts must be nonnegative and consistent (`total = urban + rural`). Zero denominators remain invalid rather than generating urbanization zero. The builder never infers a missing urban count from a district's reputation. Unsupported headers or missing required population rows fail explicitly. The original official file should be preserved, with any extraction or header conversion recorded. The exact official workbook was downloaded on 2026-09-08 and is present locally at the configured input path. `census_2011_district_urban_rural.meta.json` records its download URL and SHA-256 (`acb01ddb965be41cf22a20f0e641fdbcc1f4a16e6b7bc9cf91478ce289f853e8`). No header conversion was needed. The default projected lookup contains 261 registry geographies: 166 matched, 64 unmatched, 31 unresolved placeholders; this is not 261 independent measured observations.

`district_name_crosswalk.csv` is an empty template. Its keys are `registry_state,registry_district,census_state,census_district` with evidence fields. Only documented geographic equivalences belong here; modern split districts cannot simply inherit an entire old district's Census counts. Telangana has no separate 2011 Census state code; correct boundary matching requires evidence rather than silently substituting Andhra Pradesh.

## Primary artifacts and schemas

| Artifact | Key columns / contract |
| --- | --- |
| `intermediate/event_districts.csv` | `event_district_id` PK; parent `event_id`, `source_record_id`, state, district, start/end dates, district source/confidence/evidence, AOI level/status |
| `intermediate/district_covariates.csv` | one state/district row; Census code, total/urban/rural population, continuous urban share, Census year/source, match status |
| `intermediate/district_aoi.csv` | district PK, parent/source/geography, AOI level/source/match status, geometry ID, `aoi_area_km2`; failed matches retained |
| `cache/district/flood_extent.csv` | district PK with identity/provenance, S1/S2 areas, image counts and detection status |
| `cache/district/sits_patches/` | optional H5 patches with district and source/date identity; never state patches |
| `cache/district/sits_scores/` | optional external NPZ SITS scores for those district patches; requires valid provenance |
| `intermediate/district_post_cloud.csv` | district PK, post-image count, clear/cloud percentage, query status |
| `intermediate/district_flood_combined.csv` | district PK, combined pixel flood area/source, AOI area, flood ratio, provenance |
| `intermediate/district_flood_area.csv` | district PK, parent/source/geography/date, `flood_area_km2`, `flood_ratio`, `aoi_area_km2`, `satellite_source`, `satellite_status`, `aoi_match_status` |
| `intermediate/district_gdelt.sql` | reproducible 14-day query and district assignment logic |
| `intermediate/district_gdelt.articles.jsonl.gz` | district PK, parent/source/geography, URL, publication date, location evidence and GKG metadata |
| `intermediate/district_gdelt.manifest.json` | spatial/window contract, collection completeness and provenance; needed to distinguish missing from zero |
| `cache/district/articles.sqlite` | original URL documents, retrieved title/body and retrieval status; district metadata remains authoritative in JSONL |
| `results/district_article_counts.heuristic.csv` | district PK, parent/geography, candidate/pass/final counts, count source, collection status and text missingness |
| `results/district_flood_articles.csv` | district PK; parent/source/state/district/date; flood area/ratio; article count; urban share/populations; satellite/collection/district/Census statuses; `analysis_eligible`, `exclusion_reason` |
| `results/district_analysis_exclusions.csv` | same schema as joined table, restricted to excluded rows; multiple reasons separated by semicolons |
| `results/district_qc.json` | stage success numerator, denominator, fraction and final analyzable N |
| `results/district_selection_bias.csv` | known urbanization tercile/unknown, number of rows/exclusions and exclusion rate |
| `results/coverage_model_results.csv` | model/term/SE type, coefficient, SE, p-value, coefficient CI, IRR CI, urban 10pp IRR CI, N, estimated alpha |
| `results/coverage_predictions.csv` | Model 2 urbanization grid, fixed median flood extent, expected count and mean CI |
| `../outputs/paper_results.md` | numeric results, model availability, exclusions, quality warnings and conditional conclusion |
| `../outputs/coverage_summary.json` | machine-readable descriptive/model/QC results; unavailable values are JSON null |
| `../outputs/flood_area_vs_articles.png` | 300 dpi observed log1p scatter |
| `../outputs/urbanization_adjusted_coverage.png` | 300 dpi Model 2 adjusted mean and 95% CI |

## Legacy state artifacts (retained)

The following previous layout remains for compatibility. Its references to “primary” describe the former state workflow, not the current runner. Do not reuse its state flood/count caches as district values.

# CVND data layout

Tiered folders under `data/`. Primary pipeline scripts resolve paths via
`data_path(key)` in [`src/cvnd_layout.py`](../src/cvnd_layout.py).

## Tiers

| Folder | Role |
| --- | --- |
| `raw/` | External inputs (events, EM-DAT, GDELT export) |
| `cache/` | Satellite / GEE artifacts (rebuild when `SKIP_GEE=0`) |
| `intermediate/` | Flood area, article classification, retrieval QC |
| `results/` | Heuristic article counts and joined flood + article tables |
| `archive/` | Legacy fallbacks (not used by default) |

## Files by tier

### `raw/`

| File | Key | Producer | Consumers |
| --- | --- | --- | --- |
| `EM-DAT-BASE.xlsx` | `emdat_base` | Exact official portal export | `build_emdat_events.py` |
| `EM-DAT.xlsx` | `emdat_state` | `build_emdat_events.py` + workbook export | Audit-ready state-event data |
| `events.csv` | `events` | `build_emdat_events.py` | All pipeline steps |
| `population.csv` | `population` | External reference | Not used by primary flood stack |
| `state_area.csv` | `state_area` | Survey of India area table | `compute_population.py` |
| `emdat_api_raw.csv` | `emdat_api_csv` | `collect_emdat.py` (optional API staging) | Manual comparison before promotion |
| `emdat_api_raw.meta.json` | `emdat_meta` | `collect_emdat.py` provenance | Audit / reproducibility |
| `gdelt_emdat_query.sql` | `gdelt_sql` | `collect_gdelt.py` | Reviewable historical GKG query |
| `gdelt_bq.articles.jsonl.gz` | `gdelt_articles` | `collect_gdelt.py --execute` | Article-level GDELT URL metadata |
| `gdelt_bq.articles.sqlite` | — | `download_articles.py` | Resumable original-site article text and fetch status |
| `gdelt_bq.json` | `gdelt_bq` | `collect_gdelt.py --execute` | Optional language-level GDELT summaries |
| `gdelt_bq.meta.json` | `gdelt_meta` | `collect_gdelt.py --execute` | Query provenance and cost audit |
| `events_quarantine.csv` | `events_quarantine` | Manual QC | Optional downstream filtering |

### `cache/`

| File | Key | Producer | Consumers |
| --- | --- | --- | --- |
| `flood_extent.csv` | `flood_extent` | `satellite.py` | `merge_results.py` |
| `sits_scores/*.npz` | `sits_scores` | `run_sits_inference.py` | `merge_results.py` |
| `sits_patches/*.h5` | `sits_patches` | `satellite.py` Track B | Local SITS inference; retained after scoring |
| `sits_patches_index.csv` | `sits_patches_index` | `satellite.py` Track B | Audit / resume |
| `satellite_checkpoint_*.json` | `satellite_checkpoint_*` | `satellite.py` | GEE resume |
| `ne_india_states.gpkg` | `ne_india_states` | Optional map tooling | Choropleth exports |

The local SITS model checkpoint is loaded from
`SITS-ExtremeEvents-main/checkpoints/ravaen/`, outside the data cache.

### `intermediate/`

| File | Key | Producer | Consumers |
| --- | --- | --- | --- |
| `flood_combined.csv` | `flood_combined` | `merge_results.py` | `compute_population.py` |
| `event_aoi_area.csv` | `event_aoi_area` | `event_aoi_area.py` | `merge_results.py` |
| `post_cloud.csv` | `post_cloud` | `post_cloud.py` | `merge_results.py` |
| `severity_raw.csv` | `severity_raw` | `compute_population.py` | `join_flood_articles.py` |
| `article_retrieval_qc_by_event.csv` | `article_retrieval_event_qc` | `audit_article_retrieval.py` | Pre-LLM retrieval-bias audit |
| `article_retrieval_qc_by_year.csv` | `article_retrieval_year_qc` | `audit_article_retrieval.py` | Historical URL-survival audit |
| `article_retrieval_unresolved.csv.gz` | `article_retrieval_unresolved` | `audit_article_retrieval.py` | Retry/archive/access review queue |
| `gdelt_event_relevance.sqlite` | `event_relevance_database` | `classify_event_articles.py` | Resumable article/event classification and audit |
| `gdelt_event_relevance_pilot.csv` | `event_relevance_pilot_manifest` | `classify_event_articles.py pilot-create` | Stratified LLM/human validation sample |
| `gdelt_event_relevance_pilot_evaluation.json` | `event_relevance_pilot_evaluation` | `classify_event_articles.py pilot-evaluate` | Production submission gate and validation metrics |
| `gdelt_event_relevance_pilot_evaluated.csv` | `event_relevance_pilot_annotated` | `classify_event_articles.py pilot-evaluate` | Human and LLM labels joined for review |
| `gdelt_event_relevance_batches/` | — | `classify_event_articles.py submit/collect` | OpenAI Batch JSONL inputs and outputs |

### `results/`

| File | Key | Producer |
| --- | --- | --- |
| `event_article_counts.csv` | `event_article_counts` | `classify_event_articles.py export --count-source llm` |
| `event_articles.csv.gz` | `event_articles` | `classify_event_articles.py export --count-source llm` |
| `event_article_counts.heuristic.csv` | `event_article_counts_heuristic` | `classify_event_articles.py export` (default heuristic) |
| `event_articles.heuristic.csv.gz` | `event_articles_heuristic` | `classify_event_articles.py export` (default heuristic) |
| `event_flood_articles.csv` | `event_flood_articles` | `join_flood_articles.py` |
| `state_flood_articles.csv` | `state_flood_articles` | `join_flood_articles.py` |

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
- **population.csv** — retained as reference data only (not used by the
  primary flood-area stack).
- **state_area.csv** — State/UT areas (km²) from Survey of India reference table.

## Legacy scripts

The event readers in legacy/optional scripts now use the canonical
`data/raw/events.csv`. Some optional scripts still write their outputs to the
old flat `data/` paths and are not part of the primary runner.
