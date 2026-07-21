# CVND

**Coverage vs Need Discrepancy** — a research pipeline that measures whether Indian
flood disasters receive media attention proportional to their physical severity.

## What this project is

When floods hit, some events dominate the news while equally (or more) severe
disasters elsewhere get little coverage. CVND builds an event-level dataset of
floods in India and compares **what happened on the ground** with **how much the
media reported**, so under- and over-coverage can be quantified rather than guessed.

The pipeline has four linked pieces:

1. **Physical Severity Score (PSS)** — flood extent from Sentinel-1/2 imagery
   (SITS + NDWI/SAR fallback) combined with exposed population. Area and
   population are `log1p`-transformed, MinMax-scaled, then averaged (0.5 / 0.5).
2. **Media Salience Score (MSS)** — multilingual GDELT coverage aggregated into
   volume, share-of-voice, time-to-first-report, and coverage duration (AHP weights;
   Entropy weights kept for sensitivity).
3. **Expected coverage** — a sparse Negative Binomial model predicts how many
   articles a disaster *should* attract given severity, deaths, and onset year
   (cluster-robust SE by state). This replaces naïve Min-Max discrepancy scores
   that outliers can distort.
4. **Discrepancy Index (`log_ratio`)** — continuous residual
   \(\ln((y+0.5)/(\hat\mu+0.5))\).  
   `log_ratio < 0` → under-covered; `log_ratio > 0` → over-covered.

Primary unit of analysis is the **flood event** (not a continuous location panel).
Outputs live in `data/` (scores, expected coverage) and `outputs/` (figures +
`pipeline_result.md`).

## First-time setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # set GEE_PROJECT_ID if using Earth Engine
```

Optional Earth Engine auth (only when `SKIP_GEE=0`):

```bash
earthengine authenticate
```

## Primary analysis DAG

```text
data/flood_combined.csv (+ events, population)
        → compute_population.py → severity_raw.csv
        → compute_pss.py        → pss_results.csv
data/gdelt_bq_part*.json
        → compute_mss.py        → mss_results.csv
        → compute_expected_coverage.py  → expected_coverage.csv + log_ratio
        → visualize.py          → outputs/plot{1,5–9}_*.png
```

**Primary model:** sparse Negative Binomial on article counts  
`log_ratio = ln((y + 0.5) / (μ̂ + 0.5))`  
PSS uses equal weights `0.5/0.5` after `MinMax(log1p(·))`.  
MSS primary weights are AHP (Entropy/Equal for sensitivity only).

## Run pipeline

Default (**cached** rebuild — skips GEE and GDELT Doc API):

```bash
./scripts/run_pipeline.sh
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `SKIP_GEE` | `1` | Skip `satellite.py`; use cached `flood_extent` / `sits_scores` / `flood_combined` |
| `SKIP_ARTICLES` | `1` | Skip archived Doc API collector; **MSS always reads `gdelt_bq_part*.json`** |
| `SETUP_DEPS` | `0` | Set to `1` to reinstall `requirements.txt` into `venv/` |

Examples:

```bash
# Full satellite re-pull (needs GEE auth + .env)
SKIP_GEE=0 ./scripts/run_pipeline.sh

# Reinstall deps then cached scoring
SETUP_DEPS=1 ./scripts/run_pipeline.sh
```

Windows: use Git Bash / WSL, or run the same `src/*.py` steps with
`venv\Scripts\python.exe`. The runner picks `venv/bin/python` or
`venv/Scripts/python.exe` automatically.

### Cached vs full rebuild

| Mode | Needs | Notes |
| --- | --- | --- |
| Cached (`SKIP_GEE=1`) | `data/flood_combined.csv` or (`flood_extent.csv` + `sits_scores/`), `gdelt_bq_part*.json` | Default; no network GEE/GDELT Doc |
| Full GEE (`SKIP_GEE=0`) | EE credentials, district AOIs | Writes flood extent / sits patches; Colab inference → `sits_scores/` |

SITS scores are produced outside the runner (Colab notebook after Track B patches),
then `merge_results.py` builds `flood_combined.csv`.

## Media data truth

| Stage | Status |
| --- | --- |
| `data/gdelt_bq_part*.json` → `compute_mss.py` | **Primary** |
| `src/archive/news.py` (Doc API → `raw_gdelt.csv`) | Optional / legacy; does not feed current MSS |
| `src/archive/process_bigquery.py` | Orphan (early 12-event era) |

Column `n_articles_0_14` in expected-coverage outputs is a **proxy alias** for
`mss_results.total_articles` (design window onset+14d; counts are not guaranteed
day-filtered).

## Legacy archives

Unused modules and orphan CSVs live under:

- [`src/archive/`](src/archive/README.md) — e.g. `population.py` (WorldPop), `build_covariates.py`, `news.py`
- [`data/archive/`](data/archive/README.md) — e.g. `state_covariates.csv`, `rainfall.csv`, `pi_results.csv`

Pipeline population path is **`compute_population.py`**, not archived `population.py`.

## Shared config

Canonical paths and constants: [`src/cvnd_paths.py`](src/cvnd_paths.py)
(`LOG_RATIO_EPS`, PSS weights, plot palette, figure list).

## Figures

Active: **plot1**, **plot5–plot9** (plot2–4 retired with legacy DI; IDs kept for paper links).  
Report: `outputs/pipeline_result.md`.
