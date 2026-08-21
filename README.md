# CVND

 A research pipeline that measures whether Indian
flood disasters receive media attention proportional to their physical severity.

## What this project is

When floods hit, some events dominate the news while equally (or more) severe
disasters elsewhere get little coverage. CVND builds an analaysis of
floods in India and compares what happened on the ground(Satellite vision) with how much the
media reported(Media coverage), so under- and over-coverage can be quantified rather than guessed.

The pipeline has four linked pieces:

1. **Physical Severity Score (PSS)**
   flood extent from Sentinel-1/2 imagery (SITS + NDWI/SAR fallback) combined with exposed population. 
3. **Media Salience Score (MSS)**
   multilingual GDELT coverage aggregated into volume, share-of-voice, time-to-first-report, and coverage duration (AHP weights kept for sensitivity).
5. **Expected coverage**
   A sparse Negative Binomial model predicts how many articles a disaster should attract given severity, deaths, and onset year. This replaces naïve Min-Max discrepancy scores that outliers can distort.
7. **Discrepancy Index (`log_ratio`)**
   continuous residual \(\ln((y+a)/(\hat\mu+0.5))\). `log_ratio < 0` → under-covered; `log_ratio > 0` → over-covered.

## Event registry

`data/raw/events.csv` is the single event registry consumed by the pipeline.
Its `event_source` column records whether a row is a curated seed
(`manual_seed`) or an EM-DAT-derived row; `source_record_id` stores the EM-DAT
`DisNo.` when available. The archived event builders read this registry and do
not embed a separate seed-event list.

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

# India flood records, 2015–2026. Replaces the existing canonical raw export.
python src/collect_emdat.py --from-year 2015 --to-year 2026 \
  --iso IND --classif 'nat-hyd-flo-*' --overwrite
```

The collector uses the official `https://api.emdat.be/v1` GraphQL endpoint,
paginates in batches of 500, preserves the existing portal-export CSV schema,
and records API/dataset versions, filters, retrieval time, and SHA-256 in
`data/raw/emdat_raw.meta.json`. Omit `--overwrite` or choose a separate
`--output` while validating a new extract.

Optional Earth Engine auth (only when `SKIP_GEE=0`):

```bash
earthengine authenticate
```

## Run pipeline

Default (**cached** rebuild — skips GEE and GDELT Doc API):

```bash
./scripts/run_pipeline.sh
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `SKIP_GEE` | `1` | Skip `satellite.py`; use cached `flood_extent` / `sits_scores` / `flood_combined` |
| `SKIP_ARTICLES` | `1` | Skip archived Doc API collector; **MSS always reads `data/raw/gdelt_bq.json`** |
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
| Cached (`SKIP_GEE=1`) | `data/intermediate/flood_combined.csv` or (`data/cache/flood_extent.csv` + `data/cache/sits_scores/`), `data/raw/gdelt_bq.json` | Default; no network GEE/GDELT Doc |
| Full GEE (`SKIP_GEE=0`) | EE credentials, district AOIs | Writes flood extent / sits patches; Colab inference → `sits_scores/` |

SITS scores are produced outside the runner (Colab notebook after Track B patches),
then `merge_results.py` builds `data/intermediate/flood_combined.csv`.

## Media data truth

| Stage | Status |
| --- | --- |
| `data/raw/gdelt_bq.json` → `compute_mss.py` | **Primary** |
| `src/archive/news.py` (Doc API → `raw_gdelt.csv`) | Optional / legacy; does not feed current MSS |
| `src/archive/process_bigquery.py` | Orphan (early 12-event era) |

Column `n_articles_0_14` in expected-coverage outputs is a **proxy alias** for
`mss_results.total_articles` (design window onset+14d; counts are not guaranteed
day-filtered).

## Shared config

Paths: [`src/cvnd_layout.py`](src/cvnd_layout.py) (`data_path(key)` registry).  
Constants: [`src/cvnd_config.py`](src/cvnd_config.py) (`LOG_RATIO_EPS`, PSS weights, plot palette).  
Data catalog: [`data/README.md`](data/README.md).

## Figures

Active: **plot1**, **plot5–plot9** (plot2–4 retired with legacy DI; IDs kept for paper links).  
Report: `outputs/pipeline_result.md`.
