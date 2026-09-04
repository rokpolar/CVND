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
