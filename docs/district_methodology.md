# District analysis contract

The registry is authoritative: retain one deterministic key per parent event and district; retain unresolved rows for QC. `source_record_id` links districts and states belonging to the same official EM-DAT flood. Parent E### IDs preserve current ordering; adding source records can shift that ordering, so cache identity checks also use source, dates and geography.

District name matching uses Unicode normalization, case folding and whitespace compression. It does not infer that one renamed, split or merged administrative area equals another. Explicit crosswalk entries require external evidence; no default entries are supplied. Location-only district candidates are retained with lower confidence and excluded from the strict primary sample. This favors explicit missingness over false spatial matches.

## Spatial and observation consistency

A successful district polygon match is unique within India and the named state at GAUL level 2. Every flood measurement carries AOI provenance and a district key. The study is not a new flood detector; it applies one measurement specification (`src/flood_spec.py`, hashed as `spec_version`) to every sensor:

- **Windows.** Post `[onset, onset + 14 d)`, identical to the news window; pre `[onset − 30 d, onset)`. Satellite cloud QA uses the same post window.
- **Composites.** Pre is a per-pixel median. Post is a max-water composite: the per-pixel minimum of speckle-filtered S1 VV and the per-pixel maximum of S2 NDWI. The estimand is the maximum flood extent seen in the news window. Cloud shadows can survive a maximum composite, so the S2 scene-classification cloud mask stays on, and a `median` post composite is available as a spec sensitivity.
- **Flood definition.** `water(post) AND NOT water(pre) AND eligible` for S1 (both orbit directions, Otsu threshold clamped to [−20, −13] dB with a recorded fallback flag), S2 NDWI > 0, and NDWI on SITS tiles.
- **Eligibility.** Not JRC permanent water (occurrence ≥ 50%), slope < 5°, inside India's LSIB boundary, on every path.
- **Area.** Sum of `ee.Image.pixelArea()` at 10 m, the native S2/S1 GRD resolution and the SITS grid. SITS tiles store their mean pixel area, so tile pixel counts convert to the same km². No reduction uses `bestEffort`; a reduction too large for 10 m fails and is retried rather than silently coarsened.

SITS scores are optional externally produced data. Score NPZs must include the district/source/date/geometry identity, `model_id`, `weights_sha256`, `patches_sha256` and the current `spec_version`; unproven or stale score files are rejected. Scores use the encoder mean, so they do not depend on batch size or device. Scores locate patches and NDWI quantifies water; the merge does not interpret flagged-patch extent as inundated area. SITS-NDWI is measured only on retained tiles that are clear in every timestep (`sits_footprint_km2` reports that footprint), so it is a subset of the AOI. When the SITS quality gate fails, the AOI-wide Track A NDWI is used instead. The NDWI calibration is agreement with an internal optical signal, not ground-truth validation.

The routed value (`satellite_source` ∈ S1, NDWI, SITS_NDWI, SITS_NDWI_RESTORED; `route_reason` records why) still differs by sensor: SAR misses water under vegetation and wind-roughened water, and NDWI confuses turbid water and shadows. Source choice also follows cloud cover, and therefore monsoon intensity. The satellite-source fixed effect and by-source subsamples are sensitivity analyses, not a correction. Model provenance, boundary alignment, detector accuracy and partial optical observability remain scientific limitations.

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
