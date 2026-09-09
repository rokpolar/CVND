# District refactor: implementation and validation

Validated on 2026-09-08 in the local `rokpolar/CVND` checkout. State-only entry points are removed; the district pipeline is the supported execution path.

## A. What changed

| Files | Change |
| --- | --- |
| `src/build_emdat_events.py`, `src/district_keys.py` | Preserve 204 parent state events from 75 official source floods; create 495 deterministic district/audit rows, with source/date/administrative evidence. Unicode/case/space normalization only; unresolved districts remain explicit. |
| `src/build_district_covariates.py`, `data/raw/district_name_crosswalk.csv` | Parse actual official Census PCA workbook, validate population counts and district keys, match Census to registry districts, and preserve crosswalk evidence/source hashes. Empty crosswalk template only. |
| `src/satellite.py`, `event_aoi_area.py`, `post_cloud.py`, `src/gee_config.py` | Strict unique GAUL2 India/state/district AOIs; provenance and missing statuses; district cache and H5 identities; no import-time Earth Engine initialization. Preserve existing detection stack. |
| `src/merge_results.py`, `src/build_flood_area_table.py` | District score/area routing and table with missing versus observed zero. External SITS archives require source/model provenance. |
| `src/gdelt_backend.py`, `src/district_articles.py` | District-only CLI, half-open 14-day SQL, same-block district/state evidence, explicit title sensitivity, URL/district nearest-onset deduplication, collection manifests with registry/payload hashes, and the district-local multilingual relevance heuristic. Missing/weak text cannot manufacture zero. |
| `src/join_district_flood_articles.py` | One-to-one district observation join and many-to-one Census lookup; stale identities/duplicate keys rejected; excluded rows retained. Optional `--audit-missing` records absent stages as NA. |
| `src/analyze_coverage_disparity.py` | NB2 Models 1–3, estimated alpha, ordinary/eligible state-clustered inference, IRRs including 10pp, conditional conclusions, selection audit and two 300 dpi figures. |
| `src/cvnd_layout.py`, `src/cvnd_config.py`, `scripts/run_pipeline.sh`, `src/pipeline_preflight.py` | Central district paths, explicit primary window, runnable district sequence, skip flags and offline audit. |
| `README.md`, `data/README.md`, `docs/district_methodology.md` | Research question, methods, actual input schemas, district-only run instructions, output contracts and limitations. |
| `tests/test_district_*.py`, `tests/test_coverage_disparity.py` | Registry, Census, AOI, cache, article attribution/missingness, join and statistical regression tests. |

The remote branch added `src/run_sits_inference.py` and the vendor model implementation after the district refactor. The scorer now writes district-keyed, provenance-bearing NPZ files when the verified local checkpoint is present. Default execution still uses the existing Track A S1/S2 stack; Track B is optional and requires the local upstream checkpoint.

## B. Final pipeline

1. Official EM-DAT → legacy parent events + district registry.
2. Official Census workbook → district covariates (documented explicit crosswalk only).
3. Unique district GAUL2 AOIs → area/provenance.
4. Existing satellite Track A (optional Track B patch preparation).
5. District post-cloud QA → merge S1/S2/optional proven SITS → district flood-area table.
6. District GKG query over `[onset, onset+14 days)` → collection manifest and article metadata.
7. Original-site text retrieval → district heuristic counts, preserving zero versus incomplete.
8. Strict flood/articles/Census join → all rows, exclusions, stage QC.
9. NB2 analysis → model tables, adjusted predictions, two figures and `paper_results.md`.

`bash scripts/run_pipeline.sh --dry-run` is offline. A real run uses `SKIP_GEE=0 SKIP_ARTICLES=0`; default skip mode requires district caches. `SKIP_COVARIATES`, `SKIP_ANALYSIS`, `SETUP_DEPS` and `PYTHON` are supported. Nothing copies legacy state caches into district values.

## C. Artifacts actually generated

- Official Census original: `data/raw/census_2011_district_urban_rural.xlsx`; exact 1,381,659-byte download. [Official source](https://censusindia.gov.in/nada/index.php/catalog/42557/download/46183/2011-IndiaStateDist-0000.xlsx). Its original `Data` and `Record Structure` sheets were inspected.
- `data/raw/census_2011_district_urban_rural.meta.json`: source URL/time/hash. SHA-256: `acb01ddb965be41cf22a20f0e641fdbcc1f4a16e6b7bc9cf91478ce289f853e8`.
- `data/intermediate/event_districts.csv`: 495 rows, 251 high-confidence / 92 Location-derived medium-confidence / 152 unresolved. The original `data/raw/events.csv` is unchanged.
- `data/intermediate/district_covariates.csv`: 261 registry geographies, including 166 matched, 64 unmatched and 31 unresolved placeholders. The source workbook contains 640 districts / 1,920 district-residence rows; district totals sum to 1,210,854,977 persons. Matched Census values cover 268 registry observations, including 213 high-confidence district rows.
- `data/intermediate/district_gdelt.sql`: generated primary SQL. No paid BigQuery query ran.
- `data/results/district_flood_articles.csv`, `district_analysis_exclusions.csv`, `district_qc.json`, `district_selection_bias.csv`: **explicit missing-input audit**, 495 retained rows and 495 excluded rows. Flood/article observations are NA. Current analyzable N = 0.
- `data/results/coverage_model_results.csv`, `coverage_predictions.csv`: valid empty schemas because models are unavailable.
- `outputs/paper_results.md`, `coverage_summary.json`: actual missingness/availability report, no empirical H1/H2 claim.
- Both named PNGs: explicit “no observations / model unavailable” panels for this real-data audit. Populated figure rendering was separately tested on synthetic fixtures in `/tmp`, not promoted as research results.

Full per-artifact schemas are in `data/README.md`.

## D. Statistical model

Primary Model 2:

```text
log E[article_count_ed] = beta_0 + beta_flood log(1 + flood_area_km2_ed)
                                + beta_urban urban_population_share_d
Var(Y_ed) = mu_ed + alpha mu_ed²
IRR_10pp = exp(0.1 beta_urban)
```

Alpha is estimated. M1 omits urbanization, M3 adds year fixed effects. Ordinary SE and (when eligible) state-clustered SE are both reported. Fixed sample/convergence checks can mark models unavailable. No income score, PSS/MSS, urban cutoff or area×density proxy enters the model.

## E. Validation

- Full suite: **122 tests passed**, including the existing 77 baseline tests.
- Syntax: `python -m compileall -q src tests event_aoi_area.py post_cloud.py` passed.
- Imports: 15 pipeline modules imported successfully without initiating external services.
- Shell syntax: `bash -n scripts/run_pipeline.sh` passed.
- Whitespace/errors: `git diff --check` passed.
- Offline runner dry-run passed and reported present/missing district artifacts.
- Cached runner reached the expected explicit “Missing district flood merge” error; it did not consume state caches. This is an absent external-data dependency, not a syntax/import/test failure.
- Actual Census parsing: verified 640 districts, valid population sums/shares, code leading zeros preserved.
- Synthetic NB2 fixture: positive flood and urbanization effects recovered, estimated overdispersion, zero counts handled, IRR/CI computations tested. Both figures rendered and visually inspected.
- Real missing-data audit: 495-row schema, NaN observations, exclusion/QC/model/report outputs verified. No synthetic data entered its outputs.
- An existing SQLite ResourceWarning also appeared in the baseline test run; it does not fail the tests.

## F. Remaining external requirements

The official Census file is now available; it is no longer a missing requirement.

- **BigQuery:** a live dry-run could not refresh ADC: `invalid_grant: Account has been deleted`. Reauthenticate an active authorized account with `gcloud auth application-default login`, and confirm `GDELT_BILLING_PROJECT`. Server-side SQL validation and collection remain pending.
- **Earth Engine:** live initialization failed because `.env` still specifies the template `your-gee-project-id`, which is not usable by the caller. Set an actual Earth Engine-enabled project with service usage permission and valid authentication. The configuration helper now rejects the template early.
- Regenerate district AOI, satellite, cloud and GDELT/text artifacts after authentication is corrected. Existing state caches cannot be substituted.
- Optional SITS inference requires a separately supplied verified model/weights and district score provenance. The baseline S1/S2 path does not require it.

## G. Scientific limitations

No empirical H1/H2 conclusion is available yet. Matching excludes ambiguous and medium-confidence location candidates; spelling/history crosswalks remain intentionally empty. Census 2011, GAUL 2015 and event-year district boundaries may differ even when labels match; exact names are not proof of stable boundaries. Unmatched districts' urbanization is unknown. Current exclusion rates are all 100% because external observation stages have not run, so they do not yet diagnose differential matching bias.

GDELT language/location extraction, original-page survival, incomplete body retrieval, event-window assignment and keyword relevance can introduce selection/measurement error. A single inaccessible candidate makes the strict final article observation incomplete; this conservative rule may materially reduce the sample and should be reported. The seven-day baseline satellite composite and fourteen-day news/SITS windows differ. Satellite detections are not ground-truth damage measures. The model controls observed flood area, not total damage or population size; it cannot establish intent or causality. State clustering does not fully resolve source-event/repeated-district dependence.

## H. Relative coverage scorer implementation and validation (2026-09-10)

Implemented directly without sub-agents. Actual starting HEAD matched the requested review commit `52ac4b5f328949ac74cf942b1738c273eed26aed`; the working tree was initially clean. Prior sections describe the earlier refactor and its historical test environment. The results below describe this implementation's separate local run.

Changed files:

- Added `src/score_coverage.py`: strict input validation, deterministic source GroupKFold OOF NB2, inclusive discrete-tail candidates, prediction intervals, diagnostics-only Poisson, optional no-population NB2, stale-output invalidation and CLI.
- Added `tests/test_coverage_scoring.py`: 23 synthetic/mechanical and CLI tests, including coefficient/alpha recovery, held-out outcome isolation, all-row preservation, train gates, rank/convergence/covariance/nonfinite-prediction failures, common-success metrics, source macro averaging, sensitivity, extrapolation and zero-count tails.
- Added `docs/coverage_scoring_methodology.md`; updated `README.md`, this validation record, `src/cvnd_layout.py` and `scripts/run_pipeline.sh`.
- Constrained `requirements.txt` to `statsmodels>=0.14.6,<0.15`: installing unconstrained 0.15.0 switched the default formula backend and broke the existing H1/H2 `design_info`/patsy adjusted-prediction interface. Existing analysis code, formulas and prediction meaning were preserved; the validated environment uses 0.14.6.

The host default Python lacked NumPy. A temporary environment was created at `/tmp/cvnd-scoring-venv`; public Python dependencies were installed there. No paid query, research-data download or authentication was performed. Validated numerical environment: Python 3.14.7, NumPy 2.5.3, pandas 3.0.5, SciPy 1.18.1, statsmodels 0.14.6, scikit-learn 1.9.0 and matplotlib 3.11.1. The exact installed scoring library versions are recorded in the real-input summary.

Commands executed (use `PATH=/tmp/cvnd-scoring-venv/bin:$PATH` and `MPLCONFIGDIR=/tmp/cvnd-matplotlib` for this local environment):

```bash
python -m unittest discover -s tests
python -m compileall -q src tests
bash -n scripts/run_pipeline.sh
PYTHON=/tmp/cvnd-scoring-venv/bin/python bash scripts/run_pipeline.sh --dry-run
git diff --check
python src/score_coverage.py --input data/results/district_flood_articles.csv \
  --results-dir /tmp/cvnd-scoring-audit/results \
  --output-dir /tmp/cvnd-scoring-audit/outputs --sensitivity-no-population
```

Full suite: **104 discovered test cases, 103 passed, 1 skipped**. The skipped module is the existing optional SITS test module because torch is absent from the temporary environment; its underlying tests were not executed. An intentional invalid-date fixture triggers pandas' date-format warning; it does not fail the test. Compilation, shell syntax, offline dry-run and whitespace checks passed. Dry-run and `SKIP_ANALYSIS=1` behavior are also asserted by the scorer tests. The downloader tests use mocked/local fixtures; no live article collection was run. Initial failures were resolved before the successful final run; the older 122-test count above is historical and is not claimed for this environment.

Actual input was re-read and hashed, not inferred from an old report:

- `data/results/district_flood_articles.csv`: **495 total rows, 75 source IDs, 0 eligible rows, 0 eligible sources**.
- `article_count` and `flood_area_km2`: each missing on all 495 rows.
- SHA-256: `a78ef32ec942501c5b38c644b58edaec74e8de7b245386645aba37e387f28fcc`.
- Actual scorer run returned `insufficient_data`, 0 scored rows. Both default main scoring and requested sensitivity use no fabricated data. No fit, empirical performance, coefficient, or regional ranking was produced.
- The output CSV was compared against all original input columns using `pandas.testing.assert_frame_equal`: every row, value and exclusion reason was preserved. All classes are `not_scored`; numerical scores are missing. JSON is valid with null metrics. The output hash matches the input bytes.
- Six real-input artifacts were generated only under `/tmp/cvnd-scoring-audit/{results,outputs}`. Existing H1/H2 outputs and raw/intermediate files were unchanged.
- Empty-data and populated synthetic figure generation were tested; an actual empty-data panel and a synthetic calibration panel were visually inspected. Populated synthetic QA files live separately under `/tmp/cvnd-scoring-synthetic-qa` and are not research results.

Remaining external dependencies are measured district AOI/satellite observations and completed district GDELT/article-body collection under the existing matching, provenance and quality rules. Census is available locally. New authentication/collection was not attempted, so prior credential failures in section F were not revalidated. Missing data cannot be repaired by changing the score model or inserting zeros.

Relative candidate labels remain exploratory under observed GDELT/body/heuristic coverage. They estimate neither socially deserved reporting nor causal discrimination or intent. Plug-in prediction intervals omit beta/alpha uncertainty, repeated districts and shared sources limit independence assumptions, and candidate labels are not multiplicity-adjusted discoveries.
