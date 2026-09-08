# District analysis contract

The registry is authoritative: retain one deterministic key per parent event and district; retain unresolved rows for QC. `source_record_id` links districts and states belonging to the same official EM-DAT flood. Parent E### IDs preserve current ordering; adding source records can shift that ordering, so cache identity checks also use source, dates and geography.

District name matching uses Unicode normalization, case folding and whitespace compression. It does not infer that one renamed, split or merged administrative area equals another. Explicit crosswalk entries require external evidence; no default entries are supplied. Location-only district candidates are retained with lower confidence and excluded from the strict primary sample. This favors explicit missingness over false spatial matches.

## Spatial and observation consistency

A successful district polygon match is unique within India and the named state at GAUL level 2. Every flood measurement carries AOI provenance and a district key. The same existing flood algorithms run at that scale; the study is not a new flood detector. S1 and S2 observations use their existing temporal composites, which are not all identical: baseline Track A uses the first seven days, while the optional SITS post composite and cloud QA use fourteen days. News uses exactly fourteen days. This difference must be reported in a paper and cannot be interpreted as a fully time-matched flood maximum.

SITS scores are optional externally produced data. Score NPZs must include the district/source/date/geometry identity and `model_id`, `weights_sha256`, `patches_sha256`; unproven legacy score files are rejected. District optical quality routing uses post-event cloud QA; scores locate patches and NDWI quantifies water. The merge does not interpret flagged-patch extent as inundated area. The NDWI calibration is agreement with an internal optical signal, not ground-truth validation. Model provenance, boundary alignment, masked-pixel coverage, detector accuracy and partial optical observability remain scientific limitations.

Missing flood measurement is NA. An observed zero can be retained if the AOI, valid-pixel observation and statuses permit it. Counts are only observed when district collection and required relevance evidence are complete; zero candidates after a successful query is a true zero under this collection definition. Original page failures are represented separately from keyword-negative retrieved bodies.

## Article assignment

Use a fixed half-open fourteen-day window in UTC and no anticipation period. Structured location evidence must explicitly identify the district and disambiguate the state. Optional title evidence must explicitly mention the district and state and is recorded. State-only mentions are excluded. Match multiple districts only when each has explicit evidence. Deduplicate normalized URL/state/district and select nearest onset, with deterministic ties. Classification cannot re-expand a URL into every overlapping state event, unlike the legacy classifier.

The primary relevance decision is the existing multilingual flood-keyword heuristic on successfully retrieved text. It does not prove event-specific semantic relevance, and event onset proximity is a deterministic assignment rule rather than truth. Future human validation should estimate errors by district, language, time and urbanization before strong scientific conclusions.

## Exclusion and selection audit

`analysis_eligible` requires identified district, matched district AOI, finite nonnegative observed flood area no larger than AOI area, complete article observation with nonnegative integer counts, matched official 2011 covariates with valid totals, and valid onset date. Every failure has an `exclusion_reason`; no imputation or zero filling is used for these conditions. All primary models use the same eligible rows.

Report extraction, polygon matching, Census matching, satellite observation, collection success, missingness and final sample size. Selection terciles are defined from unique districts with known Census urbanization. Unknown Census matches cannot reveal whether excluded districts are more rural; the QC report states this limitation rather than treating unknown as low urbanization.

## Model interpretation

Model 2 is `article_count ~ log1p(flood_area_km2) + urban_population_share`, with a log-mean NB2 model estimating dispersion. Year fixed effects are robustness only. No population offset is used, so the estimand concerns absolute coverage rather than per-capita reporting. The urbanization coefficient is an association conditional on observed flood area, not a direct or causal urbanization effect.

A positive estimate with two-sided p < .05 supports the corresponding directional hypothesis under the specified model; reverse and uncertain results are described explicitly. State-clustered inference is used when its fixed sample gate is met, ordinary inference otherwise with warnings. This gate, fitting eligibility and report language are fixed in code, not chosen after seeing hypotheses. See the [statsmodels NB2 implementation](https://www.statsmodels.org/stable/generated/statsmodels.discrete.discrete_model.NegativeBinomial.html) for the likelihood used; this differs from a GLM family with fixed alpha.
