# CVND: flood extent and district news visibility

CVND measures whether disaster news visibility differs across urban and rural areas after accounting for satellite-observed flood extent. It tests whether larger inundated areas receive more news coverage (H1), and whether district urban population share is associated with additional coverage after accounting for observed extent (H2). Opposite or inconclusive findings are reported without changing the specification.

**PRIMARY: flood event × district. SECONDARY/LEGACY: event × state.** `event_id` remains the parent EM-DAT state-event ID; `source_record_id` is the official DisNo.; `event_district_id` is the deterministic district key. State flood areas and article counts are never expanded into district observations. PSS/MSS and other composite scores are not used.

## Data and methods

1. `build_emdat_events.py` reads the official `EM-DAT-BASE.xlsx`, preserves the legacy parent registry and expands credible affected districts. Structured GADM/Admin Units are preferred. Conservatively parsed Location evidence remains separately identifiable; unresolved districts remain audit rows. No capital or fuzzy district replacement is invented.
2. `build_district_covariates.py` reads official Census of India 2011 district population counts. `urban_population_share = urban_population / total_population` remains continuous. Missing inputs fail with an actionable schema message. An explicit, documented crosswalk is required for district name/history changes; the supplied template has no invented mappings.
3. `src/event_aoi_area.py` resolves a unique India/state/district FAO GAUL 2015 level-2 polygon and records its identifier, source, area and match status. Unmatched districts have no primary flood measurement.
4. `satellite.py` measures new flood water on that AOI with S1 (Otsu) and S2 NDWI, plus post-window cloud QA (Track A). Optional Track B prepares district SITS patches with per-pixel measurement layers. `merge_results.py` routes the comparable S1/NDWI/SITS-NDWI candidates by SITS quality and cloud cover, and records the chosen `satellite_source` and `route_reason`. Missing observations remain missing, including empty reductions; observed zero is distinct.
5. `district_articles.py` uses historical GKG BigQuery metadata with a fixed window **start_date ≤ article_date < start_date + 14 days (UTC)**. Explicit district location evidence is required, with state disambiguation. A state mention alone cannot create district coverage. Within a district, one URL is assigned to its nearest eligible event onset; the same URL can count for multiple explicitly mentioned districts.
6. `download_articles.py` retrieves accessible article text. `district_articles.py --counts-only` reuses the existing multilingual flood keyword heuristic, keeps district assignments, and preserves collection/text incompleteness. Query success with no matching candidates yields zero; unexecuted/failed/incomplete observation yields missing. Counts represent confirmed, accessible, heuristic-positive GDELT articles, not all reporting.
7. `join_district_flood_articles.py` checks identities and one-to-one keys, joins Census covariates many-to-one, retains every registry row, and writes exclusion reasons and stage QC.
8. `analyze_coverage_disparity.py` produces descriptive statistics, Spearman correlation, NB2 models, figures, and a conditional numeric report.

## Statistical specification

The primary model is **Model 2**:

```text
Y_ed ~ NegativeBinomial2(mu_ed, alpha)
log(mu_ed) = beta_0 + beta_flood * log(1 + flood_area_km2_ed)
                      + beta_urban * urban_population_share_d
Var(Y_ed) = mu_ed + alpha * mu_ed^2
```

Dispersion `alpha` is estimated by maximum likelihood, not fixed to 1. Model 1 omits urbanization; Model 3 adds year fixed effects. All three use the same eligible complete-case sample. Population density, income groups and synthetic exposure do not enter the models. The population share effect is reported as `exp(0.1 * beta_urban)` per 10 percentage points, with SE, p-value, coefficient CI, IRR and IRR CI. No arbitrary urban/rural cutoff enters the primary model.

Ordinary SE are always reported for estimable models. State-clustered covariance with a finite-sample correction and t(G−1) inference is added when G ≥ 20 and N > 2G; otherwise the independence limitation is explicit. Models require N ≥ 20 and ≥5 observations per estimated parameter, a full-rank design and stable convergence. These fixed numerical safeguards do not depend on result direction. Secondary source-flood fixed effects require at least 10 multi-district floods and sufficient rows; otherwise `insufficient sample` is reported. Exposed-population robustness is omitted until a verified flood-mask × gridded-population input contract exists.

Figure 1 plots `log1p(area)` against `log1p(count)`. Figure 2 shows the Model 2 expected count over the observed urbanization range with flood area fixed at its median and a 95% confidence interval for the expected mean. It is not an individual-observation prediction interval. Terciles are used only for selection QC, based on unique districts, with the cutpoints reported.

## Run

```bash
# Offline command plan and input/cache schema audit; no external calls.
bash scripts/run_pipeline.sh --dry-run

# Tests and syntax checks.
venv/bin/python -m unittest discover -s tests
venv/bin/python -m compileall -q src tests

# First real district run, after checking Census input and authenticating services.
SETUP_DEPS=1 SKIP_GEE=0 SKIP_ARTICLES=0 bash scripts/run_pipeline.sh

# Reuse district caches and downloaded article text.
SKIP_GEE=1 SKIP_ARTICLES=1 SKIP_COVARIATES=1 bash scripts/run_pipeline.sh
```

**Measurement specification.** Every satellite area is produced under one frozen `MeasurementSpec` in `src/flood_spec.py`: post window `[onset, onset + 14 d)` (the news window), pre window `[onset − 30 d, onset)` median, a max-water post composite, one eligibility mask (JRC permanent water, slope < 5°, India LSIB) on every sensor path, `ee.Image.pixelArea()` sums at 10 m, and the same new-water definition for S1, S2 NDWI and SITS tiles. Its hash, `spec_version`, is printed by `src/pipeline_preflight.py` and stored on every Track A row, H5 patch, score archive, merged row and area-table row. Changing `flood_spec.SPEC` invalidates all satellite caches by design; stale rows are discarded, never reused. `analyze_coverage_disparity.py` additionally reports `model_2_source_fe` (Model 2 + `C(satellite_source)`) and by-source Model 2 subsamples as sensitivity analyses. They never enter the conclusion.

`PYTHON` may select an existing environment. `SETUP_DEPS=0` is the default. `SKIP_GEE=1` and `SKIP_ARTICLES=1` are the defaults, requiring previously generated **district** artifacts. `SKIP_COVARIATES=1` reuses district covariates; `SKIP_ANALYSIS=1` stops after joining. Missing required files fail; skipping does not manufacture observations. `SATELLITE_TRACK=A` is the explicit default; `both` also prepares SITS patches.

Track B stores completed HDF5 patches under `data/cache/district/sits_patches/`. When the local upstream checkpoint is available, `src/run_sits_inference.py` scores those patches on CPU or GPU and writes provenance-bearing NPZ files under `data/cache/district/sits_scores/`; HDF5 inputs are retained. The checkpoint is checksum-verified and is never downloaded by the pipeline. Baseline S1/S2 remains usable without SITS, and old state score files are incompatible with the district cache.

```bash
# Prepare or resume district SITS patches.
venv/bin/python src/satellite.py --track B

# Score completed patches with the local CPU/GPU model.
venv/bin/python src/run_sits_inference.py
```

Required external inputs/services:

- Official `data/raw/EM-DAT-BASE.xlsx`, already supplied locally, including `EM-DAT Data` and `EM-DAT Info` sheets.
- Official Census 2011 district urban/rural population workbook at `data/raw/census_2011_district_urban_rural.xlsx`; see [input schema](data/README.md). The official workbook has been downloaded and verified locally (640 districts); its original bytes and source SHA-256 are retained in the adjacent metadata JSON. No values are fabricated.
- Earth Engine access, Google credentials and `GEE_PROJECT_ID` for new satellite measurements. All district satellite artifacts must be regenerated; the old state cache is not compatible.
- BigQuery ADC and `GDELT_BILLING_PROJECT` for district article collection. The collector retains a maximum billed-bytes guard. New district queries are required; state counts cannot substitute.
- Article bodies available from original sites, subject to robots, access rules and historical URL survival. Missing bodies are recorded.

## Outputs and interpretation

[Artifact schemas](data/README.md) and [district methodology](docs/district_methodology.md) describe each output. Key outputs are:

- `data/results/district_flood_articles.csv`: one row per event-district, including excluded rows.
- `data/results/district_analysis_exclusions.csv`, `district_qc.json`, `district_selection_bias.csv`.
- `data/results/coverage_model_results.csv`, `coverage_predictions.csv`.
- `outputs/flood_area_vs_articles.png`, `urbanization_adjusted_coverage.png` (300 dpi).
- `outputs/paper_results.md`, `coverage_summary.json`.

The report only supports statements about **similar observed flood extent**. It cannot establish intentional neglect, causal discrimination, or equal total damage. Census 2011 predates many floods, GAUL 2015 boundaries can differ from Census/GADM, EM-DAT onset dates may be month-imputed, and news/satellite completeness can depend on geography. Selection QC reports excluded proportions by known urbanization tercile; districts without Census matches have unknown urbanization and cannot enter that comparison. Population size is deliberately not controlled in the short primary specification; it remains a potential explanation for the association.

State-only area, article-classification, and join entry points were removed. The primary workflow is district-only: `district_articles.py` applies the multilingual heuristic and `join_district_flood_articles.py --audit-missing` records absent satellite/article artifacts as NA, never zero. An analysis report on this audit states N=0 and unavailable models.

## Relative coverage candidates (separate from H1/H2)

`src/score_coverage.py` predicts observed article counts using source-group five-fold OOF NB2 with estimated alpha:
`article_count ~ log1p(flood_area_km2) + log(total_population / 1_000_000) + (year - 2020)`.
Population has an estimated coefficient; no offset is used. A globally single-year sample omits the year term. Existing H1/H2 formulas and adjusted-mean predictions are unchanged.

```bash
python src/score_coverage.py --input data/results/district_flood_articles.csv \
  --results-dir /tmp/cvnd-scoring-audit/results \
  --output-dir /tmp/cvnd-scoring-audit/outputs
# Optional separate NB2 population sensitivity:
python src/score_coverage.py --sensitivity-no-population
```

The pipeline runs the scorer after H1/H2 analysis; `SKIP_ANALYSIS=1` skips both. Offline `--dry-run` only prints its command. Outputs are `coverage_scores.csv`, `coverage_oof_diagnostics.csv` in results, and `coverage_scoring_summary.json`, `coverage_scoring_report.md`, `coverage_scoring_actual_vs_expected.png`, `coverage_scoring_calibration.png` in outputs. All input rows and exclusion reasons are retained. No-data runs produce `insufficient_data` and missing scores, never invented observations.

Relative under/over candidates use inclusive NB2 lower/upper tail probabilities and observed-minus-expected direction. These are exploratory alerts about measured GDELT coverage, not deserved coverage or causal/intentional neglect. The central 90% count prediction interval is a plug-in approximation excluding parameter uncertainty. Poisson is diagnostic only. See [scoring methodology](docs/coverage_scoring_methodology.md) for gates, contracts, diagnostics, sensitivity and interpretation limits.
