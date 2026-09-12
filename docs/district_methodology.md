# District analysis contract

The registry is authoritative: retain one deterministic key per parent event and district; retain unresolved rows for QC. `source_record_id` links districts and states belonging to the same official EM-DAT flood. Parent E### IDs preserve current ordering; adding source records can shift that ordering, so cache identity checks also use source, dates and geography.

District name matching uses Unicode normalization, case folding and whitespace compression. It does not infer that one renamed, split or merged administrative area equals another. Explicit crosswalk entries require external evidence; no default entries are supplied. Location-only district candidates are retained with lower confidence and excluded from the strict primary sample. This favors explicit missingness over false spatial matches.

## Spatial and observation consistency

A successful district polygon match is unique within India and the named state at GAUL level 2. Every flood measurement carries AOI provenance and a district key. The study is not a new flood detector; it applies one measurement specification (`src/flood_spec.py`, hashed as `spec_version`) to every sensor:

- **Windows.** Post `[onset, onset + 14 d)`, identical to the news window; pre `[onset − 30 d, onset)`. Satellite cloud QA uses the same post window.
- **Composites.** Pre is a per-pixel median. Post is a max-water composite: the per-pixel minimum of speckle-filtered S1 VV and the per-pixel maximum of S2 NDWI. The estimand is the maximum flood extent seen in the news window. Cloud shadows can survive a maximum composite, so the S2 scene-classification cloud mask stays on, and a `median` post composite is available as a spec sensitivity.
- **Flood definition.** `water(post) AND NOT water(pre) AND eligible` for S1 (both orbit directions, Otsu threshold clamped to [−20, −13] dB with a recorded fallback flag), S2 NDWI > 0, and NDWI on SITS tiles.
- **Eligibility.** Not JRC permanent water (occurrence ≥ 50%), slope < 5°, inside India's LSIB boundary, on every path.
- **Grid.** One pixel grid per district: the UTM zone of the AOI centroid, square 10 m pixels snapped to the 640 m SITS tile grid. Track A reductions (`crs` + `crsTransform`) and Track B downloads (`crs_transform` + `dimensions`) use it, so a Track A pixel and a Track B pixel are the same pixel and tiles are exactly 64 px with unique coordinates at every latitude.
- **Area.** Unweighted sum of `ee.Image.pixelArea()` on that grid. Unweighted matters: reprojected JRC/LSIB masks carry fractional mask weights on ~19% of pixels along historically wet areas, and a weighted sum counted those pixels partially (Darbhanga S1 new water 385 km² weighted vs 760 km² counted; the downloaded Track B pixels agree with the unweighted count to 0.15%). No reduction uses `bestEffort`; a whole-AOI reduction that exceeds Earth Engine limits is summed over grid-aligned sub-rectangles (same pixels, same scale), and a persistent failure is recorded with `error_kind`.
- **Footprints.** Track A records `eligible_km2`, `optical_observed_km2` (eligible and seen by S2 in both composites — the only pixels where NDWI new water can be nonzero), S1 new water on that footprint (`s1_on_optical_km2`), their overlap, WorldCover built-up and cropland strata, and the first post acquisition date per sensor. `flood_ratio_eligible` uses the eligible area as denominator next to the AOI-based `flood_ratio`.

**Interim routing (current default, `SATELLITE_ROUTING=s1_interim`).** Until Track B covers every district and the converter is decided, every district is measured by Track A Sentinel-1 new water over the eligible AOI alone (`satellite_source = S1`, `route_reason = interim_s1_only`, `routing_mode` recorded). One sensor for every district means no sensor mixing and no dependence on how far Track B got; districts without S1 pre and post imagery are NA (`no_s1`). SITS columns are still filled where Track B exists, for reference only. Setting `SATELLITE_ROUTING=sits_primary` (with `SATELLITE_TRACK=both`) switches to the design below.

**SITS is the primary measurement** under `sits_primary`, and Track B then runs for every district. Each district gets a `sits_status`: `pending` (Track B not run, incomplete — a `.blocks.json` marker exists from H5 creation until the last block — or not inferred) leaves the area NA (`sits_pending`), never a silent S1 value; `unavailable` (no pre/post imagery, no clear baseline, no retained tile) is a data condition; `ok` routes through the SITS gate. Scores locate patches and NDWI quantifies water; flagged-patch extent is never an area. When the gate passes, NDWI inside flagged tiles is used, restored to all retained tiles only when gating kept less than half of the water and S1 *on the same usable pixels* confirms the larger extent; when it fails, NDWI on all retained tiles is used. The NDWI calibration is agreement with an internal optical signal, not ground-truth validation.

Districts SITS cannot measure (`unavailable`, or usable pixels below `sits_usable_min_frac` of the eligible AOI) get Sentinel-1 new water converted to the SITS-NDWI scale (`satellite_source = S1_TO_SITS`). The converter is decided by `src/compare_tracks.py` under pre-registered rules (`flood_spec.ConverterRules`, hashed as `rules_version`) on the paired footprint C — eligible, inside the AOI, clear in all SITS timesteps, NDWI observed pre and post, on retained tiles:

| Decision | Rule | Effect |
| --- | --- | --- |
| `insufficient` | < 30 paired districts (A_ndwi(C) ≥ 1 km²) or < 5 states | S1_TO_SITS rows NA |
| `identity` | TOST: 90% state-cluster bootstrap CI of the median log ratio within ±log 1.2; heterogeneity p > 0.10; pooled IoU ≥ 0.5 | converted = S1, label kept |
| `linear` | not equivalent, homogeneous, Deming slope 95% CI width ≤ 0.5 | log-log Deming; LOSO-CV error reported |
| `stratified` | otherwise, if a log-linear model with built-up/cropland shares has LOSO-CV median error ≤ 1.25× | stratified conversion |
| `excluded` | otherwise | S1_TO_SITS rows NA; S1 results are sensitivity only |

Heterogeneity is a joint test of the log ratio on built-up and cropland share (on C), S1 post-image count, orbit, year ≥ 2022, cloud share and Otsu fallback, using HC3 covariance with an F reference (state-clustered CR1-F from 20 states); HC1 with χ² was rejected because it rejects pure noise 20–37% of the time at nominal 10% in samples of this size. Before any conversion, the identity check rebuilds Track A's AOI-wide NDWI new water from the downloaded Track B block pixels (`block_stats`); a relative difference above 1%, duplicate tiles or duplicate blocks mark a bug and remove the district from the converter fit.

The pre-refactor routing (S1 whenever SITS was not run, a 60% cloud cut) is kept as `legacy_*` columns. `data/results/routing_comparison.json` fits Model 2 under (a) the legacy routing, (b) the primary routing, (c) SITS sources only and (d) the Track A spec variants (`pre_same_season_3y`, `jrc_seasonal_10`, `mndwi`) applied as the routed sensor's relative change; the legacy result is called robust when the urbanization coefficients differ by less than half the width of (b)'s 95% CI. Sensor differences remain: SAR misses water under vegetation and in built-up areas (double bounce), McFeeters NDWI flags some built-up surfaces; the source fixed effect and by-source/SITS-only subsamples are sensitivity analyses.

Sentinel-2 availability bounds SITS. The Phase −1 probe (`src/sits_feasibility.py`, Earth Engine queries only) found SITS unavailable for 64% of AOI-matched rows with S2 SR and 40% with L1C, almost entirely in 2015–2018 (S2 barely imaged India in 2015–2016, and SR is sparse before late 2018), so most early events are measured as `S1_TO_SITS` or not at all.

Missing flood measurement is NA. An observed zero can be retained if the AOI, valid-pixel observation and statuses permit it. Counts are only observed when district collection and required relevance evidence are complete; zero candidates after a successful query is a true zero under this collection definition. Original page failures are represented separately from keyword-negative retrieved bodies.

## Article assignment

Use a fixed half-open fourteen-day window in UTC and no anticipation period. Structured location evidence must explicitly identify the district and disambiguate the state. Optional title evidence must explicitly mention the district and state and is recorded. State-only mentions are excluded. Match multiple districts only when each has explicit evidence. Deduplicate normalized URL/state/district and select nearest onset, with deterministic ties. Classification remains attached to the district observation and cannot re-expand a URL into overlapping parent events.

The primary relevance decision is the existing multilingual flood-keyword heuristic on successfully retrieved text. It does not prove event-specific semantic relevance, and event onset proximity is a deterministic assignment rule rather than truth. Future human validation should estimate errors by district, language, time and urbanization before strong scientific conclusions.

## Exclusion and selection audit

`analysis_eligible` requires identified district, matched district AOI, finite nonnegative observed flood area no larger than AOI area, complete article observation with nonnegative integer counts, matched official 2011 covariates with valid totals, and valid onset date. Every failure has an `exclusion_reason`; no imputation or zero filling is used for these conditions. All primary models use the same eligible rows.

Report extraction, polygon matching, Census matching, satellite observation, collection success, missingness and final sample size. Selection terciles are defined from unique districts with known Census urbanization. Unknown Census matches cannot reveal whether excluded districts are more rural; the QC report states this limitation rather than treating unknown as low urbanization.

## Model interpretation

Model 2 is `article_count ~ log1p(flood_area_km2) + urban_population_share`, with a log-mean NB2 model estimating dispersion. Year fixed effects are robustness only. No population offset is used, so the estimand concerns absolute coverage rather than per-capita reporting. The urbanization coefficient is an association conditional on observed flood area, not a direct or causal urbanization effect.

A positive estimate with two-sided p < .05 supports the corresponding directional hypothesis under the specified model; reverse and uncertain results are described explicitly. State-clustered inference is used when its fixed sample gate is met, ordinary inference otherwise with warnings. This gate, fitting eligibility and report language are fixed in code, not chosen after seeing hypotheses. See the [statsmodels NB2 implementation](https://www.statsmodels.org/stable/generated/statsmodels.discrete.discrete_model.NegativeBinomial.html) for the likelihood used; this differs from a GLM family with fixed alpha.
