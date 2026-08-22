# CVND

A research pipeline that measures whether Indian
flood disasters receive media attention proportional to their physical severity.

## What this project is

When floods hit, some events dominate the news while equally (or more) severe
disasters elsewhere get little coverage. CVND builds an analysis of floods in
India and compares what happened on the ground (satellite vision) with how much
the media reported (media coverage), so under- and over-coverage can be quantified rather than guessed.

The pipeline has four linked pieces:

1. **Physical Severity Score (PSS)**
   flood extent from Sentinel-1/2 imagery (SITS + NDWI/SAR fallback) combined with exposed population. 
2. **Media Salience Score (MSS)**
   multilingual GDELT coverage aggregated into volume, share-of-voice, time-to-first-report, and coverage duration (AHP weights kept for sensitivity).
3. **Expected coverage**
   A sparse Negative Binomial model predicts how many articles a disaster should attract given severity, deaths, and onset year. This replaces naïve Min-Max discrepancy scores that outliers can distort.
4. **Discrepancy Index (`log_ratio`)**
   continuous residual \(\ln((y+a)/(\hat\mu+0.5))\). `log_ratio < 0` → under-covered; `log_ratio > 0` → over-covered.

## Event registry

`data/raw/events.csv` is the single event registry consumed by the pipeline.
`data/raw/EM-DAT-BASE.xlsx` is the byte-identical official portal export and the
only event source. `src/build_emdat_events.py` expands each `DisNo.` into one row
per explicitly identified Indian state/UT without merging different `DisNo.`
records or adding manual seeds. `data/raw/EM-DAT.xlsx` preserves all 47 source
columns alongside the derived state-event fields, while `events.csv` is the
lean pipeline registry.

## First-time setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # set GEE_PROJECT_ID if using Earth Engine
```

### EM-DAT API input

Create an EM-DAT account at [public.emdat.be/register](https://public.emdat.be/register),
then [sign in](https://public.emdat.be/login) and add the API key associated
with your account to `.env` as `EMDAT_API_KEY`. The API can be explored in the
official [GraphiQL interface](https://api.emdat.be/). Then run:

```bash
# Inspect the exact GraphQL query; no key or network request is used.
python src/collect_emdat.py --dry-run

# India flood records, 2015–2026. Writes a staging CSV for comparison.
python src/collect_emdat.py --from-year 2015 --to-year 2026 \
  --iso IND --classif 'nat-hyd-flo-*' --overwrite
```

The collector uses the official `https://api.emdat.be/v1` GraphQL endpoint,
paginates in batches of 500 and writes `data/raw/emdat_api_raw.csv` plus query
metadata. API output is staging data only; it does not replace
`EM-DAT-BASE.xlsx` until it has been reviewed and explicitly promoted.

Regenerate the state workbook inputs and canonical registry with:

```bash
python src/build_emdat_events.py
```

Optional Earth Engine auth (only when `SKIP_GEE=0`):

```bash
earthengine authenticate
```

## Run pipeline

Cached rebuild (only after caches have been regenerated for the current registry):

```bash
./scripts/run_pipeline.sh
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `SKIP_GEE` | `1` | Skip `satellite.py`; use cached `flood_extent` / `sits_scores` / `flood_combined` |
| `SKIP_ARTICLES` | `1` | Reuse `gdelt_bq.json`; set `0` to execute the historical BigQuery collector |
| `SETUP_DEPS` | `0` | Set to `1` to reinstall `requirements.txt` into `venv/` |

Examples:

```bash
# Full satellite re-pull (needs GEE auth + .env)
SKIP_GEE=0 ./scripts/run_pipeline.sh

# Reinstall deps then cached scoring
SETUP_DEPS=1 ./scripts/run_pipeline.sh
```

### Cached vs full rebuild

| Mode | Needs | Notes |
| --- | --- | --- |
| Cached (`SKIP_GEE=1`) | `data/intermediate/flood_combined.csv` or satellite caches, `data/raw/gdelt_bq.json` | Default; no network GEE/GDELT |
| Full GEE (`SKIP_GEE=0`) | EE credentials, state AOIs | Writes flood extent, AOI/cloud QA, and SITS patches; Colab inference → `sits_scores/` |

SITS scores are produced outside the runner (Colab notebook after Track B patches),
then `merge_results.py` builds `data/intermediate/flood_combined.csv`.

## Media data truth

Historical collection uses the partitioned GDELT 2.0 GKG BigQuery table. The
DOC API is retained only for recent exploration because it searches a rolling
three-month window and caps Article List results at 250 per request.

```bash
# Generate SQL for review; no credentials or query charge.
python src/collect_gdelt.py --overwrite

# Execute after: gcloud auth application-default login
GDELT_BILLING_PROJECT=your-project \
python src/collect_gdelt.py --estimate --overwrite

GDELT_BILLING_PROJECT=your-project \
python src/collect_gdelt.py --execute --overwrite

# Plan resumable batches capped below 1 TiB, execute one batch in each intended
# billing period, then merge only after every batch is complete.
GDELT_BILLING_PROJECT=your-project \
python src/collect_gdelt.py --plan-batches --max-batch-tib 0.95 --overwrite

# Optional: richer GKG metadata, with a new dry-run plan because extra columns
# increase bytes processed.
python src/collect_gdelt.py --plan-batches \
  --article-metadata-profile rich --overwrite

GDELT_BILLING_PROJECT=your-project \
python src/collect_gdelt.py --execute-batch B001

# Download accessible article bodies from the GDELT URL metadata. The SQLite
# file is both the output and the restart checkpoint.
python src/download_articles.py \
  data/raw/gdelt_batches/B001.articles.jsonl.gz \
  --output data/raw/gdelt_batches/B001.articles.sqlite \
  --delay 1.0

python src/collect_gdelt.py --merge-batches --overwrite

# Examples: language subset, all GKG languages, broader themes, or domain exclusion.
python src/collect_gdelt.py --languages en,hin,tam --overwrite
python src/collect_gdelt.py --languages all --overwrite
python src/collect_gdelt.py --topic-profile broad --exclude-domain example.com --overwrite
```

The default is a fixed onset-to-onset+93-day window (94 calendar dates,
including onset) and strict flood themes.
Source languages default to the 16-language intersection of India's nationwide
Census C-16 categories and GDELT Translingual 2.0 support.
Candidates must mention India plus the event state/UT (or its linked district).
Exact GDELT document identifiers are assigned to only the nearest overlapping
event within the same state, preventing duplicate coverage counts.
Batch planning preserves that rule by keeping overlapping windows from the
same state together. BigQuery's `maximum_bytes_billed` guard enforces the
planned per-batch ceiling at execution time, and completed batch files allow
later runs to resume without repeating successful queries.
Each batch execution writes article-level GDELT URL metadata to compressed
JSONL and derives the existing MSS summary locally. GDELT does not contain the
full article body; `download_articles.py` follows the original URLs, respects
robots.txt, and stores accessible extracted text in a resumable SQLite file.
See [`docs/gdelt_collection.md`](docs/gdelt_collection.md) for all selectors,
assignment rules, limitations and recommended sensitivity runs.

| Stage | Status |
| --- | --- |
| `collect_gdelt.py` → `Bxxx.articles.jsonl.gz` / `gdelt_bq.json` | **Primary metadata + MSS summary** |
| `download_articles.py` → `Bxxx.articles.sqlite` | **Original-site article text where accessible** |
| `src/archive/news.py` (DOC API) | Recent exploratory legacy only |
| `src/archive/process_bigquery.py` | Orphan (early 12-event era) |

Expected-coverage models use `n_articles_window`, the collector's fixed
onset-through-onset+93-day article count.

## Shared config

Paths: [`src/cvnd_layout.py`](src/cvnd_layout.py) (`data_path(key)` registry).  
Constants: [`src/cvnd_config.py`](src/cvnd_config.py) (`LOG_RATIO_EPS`, PSS weights, plot palette).  
Data catalog: [`data/README.md`](data/README.md).

## Figures

Active: **plot1**, **plot5–plot9** (plot2–4 retired with legacy DI; IDs kept for paper links).  
Report: `outputs/pipeline_result.md`.
