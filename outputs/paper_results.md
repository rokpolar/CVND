# Coverage disparity results

N = 0 district-event observations; 0 districts; 0 parent events; 0 source floods.
Excluded: 1630 of 1630 registry rows.
Spearman rho = None; p = None.

Primary model: log E[article_count] = intercept + beta_flood log(1 + flood_area_km2) + beta_urban urban_population_share. NB2 variance = mu + alpha * mu²; alpha is estimated.

M1/M2/M3 use the same complete-case sample. Fixed decision rule: positive coefficient and two-sided p < 0.05; prefer state-clustered inference when the prespecified cluster rule is met. No cutoff on urbanization enters the model.

| Model / SE | Term | Coefficient (SE) | 95% CI | p | IRR [95% CI] | 10pp IRR [95% CI] |
| --- | --- | --- | --- | --- | --- | --- |

Flood IRR is per one-unit increase in log(1 + km²); the urbanization IRR is per 0→1 change, with 10 percentage points reported separately.

## Model availability

- model_1: insufficient sample: N=0 < 20
- model_2: insufficient sample: N=0 < 20
- model_3: insufficient sample: fewer than two years
- model_2_source_fe: insufficient source variation: fewer than two satellite sources
- source_event_robustness: insufficient sample: 0 multi-district source events, 0 rows; require >= 10 groups and >= 5*(groups+3) rows
- exposed_population_robustness: not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used

## Descriptive distributions and missingness

```json
{
  "distributions": {
    "flood_area_km2": {
      "count": 0.0,
      "mean": null,
      "std": null,
      "min": null,
      "25%": null,
      "50%": null,
      "75%": null,
      "max": null
    },
    "article_count": {
      "count": 0.0,
      "mean": null,
      "std": null,
      "min": null,
      "25%": null,
      "50%": null,
      "75%": null,
      "max": null
    },
    "urban_population_share": {
      "count": 0.0,
      "mean": null,
      "std": null,
      "min": null,
      "25%": null,
      "50%": null,
      "75%": null,
      "max": null
    }
  },
  "available_input_distributions": {
    "flood_area_km2": {
      "count": 0.0,
      "mean": null,
      "std": null,
      "min": null,
      "25%": null,
      "50%": null,
      "75%": null,
      "max": null
    },
    "article_count": {
      "count": 0.0,
      "mean": null,
      "std": null,
      "min": null,
      "25%": null,
      "50%": null,
      "75%": null,
      "max": null
    },
    "urban_population_share": {
      "count": 1502.0,
      "mean": 0.22142008,
      "std": 0.1976369929,
      "min": 0.0,
      "25%": 0.0891629483,
      "50%": 0.1502277735,
      "75%": 0.2863400338,
      "max": 1.0
    }
  },
  "missing_counts": {
    "flood_area_km2": 1630,
    "article_count": 1630,
    "urban_population_share": 128
  },
  "exclusion_counts": {
    "district_aoi_unmatched": 1630,
    "satellite_missing_or_invalid": 1630,
    "aoi_area_invalid": 1630,
    "article_collection_incomplete": 1630,
    "article_count_missing_or_invalid": 1630,
    "census_unmatched": 142,
    "census_invalid": 128,
    "census_population_inconsistent": 128,
    "ambiguous_duplicate_census_district_code": 14
  },
  "stage_qc": {
    "district_extraction": {
      "success": 1630,
      "total": 1630,
      "rate": 1.0
    },
    "district_aoi_match": {
      "success": 0,
      "total": 1630,
      "rate": 0.0
    },
    "census_match": {
      "success": 1488,
      "total": 1630,
      "rate": 0.9128834356
    },
    "satellite_observation": {
      "success": 0,
      "total": 1630,
      "rate": 0.0
    },
    "gdelt_collection": {
      "success": 0,
      "total": 1630,
      "rate": 0.0
    },
    "article_observation": {
      "success": 0,
      "total": 1630,
      "rate": 0.0
    },
    "final_analyzable": {
      "success": 0,
      "total": 1630,
      "rate": 0.0
    },
    "satellite_source_counts": {}
  },
  "estimated_dispersion": {},
  "article_count_variance": null,
  "article_count_mean": null
}
```

## Selection check

```
urbanization_group  rows  excluded  exclusion_rate
              high   411       411             1.0
               low   692       692             1.0
            medium   399       399             1.0
           unknown   128       128             1.0
```

## Conclusion candidate

Insufficient valid data or stable model fits to assess H1 and H2. No empirical conclusion is available.

These results describe associations at similar observed flood extent; they do not establish intent or causation.

## Data-quality warnings

- Associational analysis: flood extent does not control all disaster impacts, outlet availability, population size, or media access.
- Census 2011 and GAUL 2015 may not represent event-year district boundaries or urbanization.
- GDELT-indexed district-explicit coverage is not all disaster reporting; location extraction and language coverage can affect selection.
- District rows within a source flood and repeated districts may be dependent; state clustering is only a partial correction.
- 244 registry onset dates are month-imputed; their 14-day news windows have timing uncertainty.
- Flood area is Sentinel-1 new water over the eligible AOI for every district under the interim routing (satellite_source S1), or, under sits_primary routing, SITS-NDWI on the retained clear tiles with Sentinel-1 converted to the SITS-NDWI scale (S1_TO_SITS) where SITS cannot measure the district; the satellite-source fixed effect, by-source and SITS-only subsamples are sensitivity analyses, not a correction.
- district-based urbanization tercile cutpoints: [0.137698725534157, 0.26867594352309243]; unknown Census matches cannot be assigned an urbanization level
