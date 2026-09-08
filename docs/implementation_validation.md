# District refactor: implementation and validation

Validated on 2026-09-08 in the local `rokpolar/CVND` checkout. The pre-existing local changes to `classify_event_articles.py` were preserved.

## A. What changed

| Files | Change |
| --- | --- |
| `src/build_emdat_events.py`, `src/district_keys.py` | Preserve 204 parent state events from 75 official source floods; create 495 deterministic district/audit rows, with source/date/administrative evidence. Unicode/case/space normalization only; unresolved districts remain explicit. |
| `src/build_district_covariates.py`, `data/raw/district_name_crosswalk.csv` | Parse actual official Census PCA workbook, validate population counts and district keys, match Census to registry districts, and preserve crosswalk evidence/source hashes. Empty crosswalk template only. |
| `src/satellite.py`, `event_aoi_area.py`, `post_cloud.py`, `src/gee_config.py` | Strict unique GAUL2 India/state/district AOIs; provenance and missing statuses; district cache and H5 identities; no import-time Earth Engine initialization. Preserve existing detection stack. |
| `src/merge_results.py`, `src/build_flood_area_table.py`, `src/compute_population.py` | District score/area routing and table with missing versus observed zero. External SITS archives require source/model provenance. Legacy area utility remains available. |
| `src/collect_gdelt.py`, `src/district_articles.py` | District CLI, half-open 14-day SQL, same-block district/state evidence, explicit title sensitivity, URL/district nearest-onset deduplication, collection manifests with registry/payload hashes, and existing multilingual relevance heuristic. Missing/weak text cannot manufacture zero. |
| `src/join_district_flood_articles.py` | One-to-one district observation join and many-to-one Census lookup; stale identities/duplicate keys rejected; excluded rows retained. Optional `--audit-missing` records absent stages as NA. |
| `src/analyze_coverage_disparity.py` | NB2 Models 1–3, estimated alpha, ordinary/eligible state-clustered inference, IRRs including 10pp, conditional conclusions, selection audit and two 300 dpi figures. |
| `src/cvnd_layout.py`, `src/cvnd_config.py`, `scripts/run_pipeline.sh`, `src/pipeline_preflight.py` | Central district paths, explicit primary window, runnable district sequence, skip flags and offline audit. |
| `README.md`, `data/README.md`, `docs/district_methodology.md` | Research question, methods, actual input schemas, run instructions, output contracts and limitations. Prior state docs clearly labeled legacy. |
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
