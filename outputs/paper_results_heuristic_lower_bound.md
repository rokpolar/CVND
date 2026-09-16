# PROVISIONAL HEURISTIC LOWER-BOUND REGRESSION

This is a supplementary, non-primary analysis. The article_count field is the local heuristic pass count, not LLM-QA; inaccessible article bodies remain excluded/NA in the primary output. Do not use this report as the final LLM-QA estimate or as evidence that missing articles are not relevant.

# Coverage disparity results

N = 1352 district-event observations; 474 districts; 166 parent events; 64 source floods.
Excluded: 201 of 1553 registry rows.
Spearman rho = -0.0274116392; p = 0.3138527562.

Primary model: log E[article_count] = intercept + beta_flood log(1 + flood_area_km2) + beta_urban urban_population_share. NB2 variance = mu + alpha * mu²; alpha is estimated.

M1/M2/M3 use the same complete-case sample. Fixed decision rule: positive coefficient and two-sided p < 0.05; prefer state-clustered inference when the prespecified cluster rule is met. No cutoff on urbanization enters the model.

| Model / SE | Term | Coefficient (SE) | 95% CI | p | IRR [95% CI] | 10pp IRR [95% CI] |
| --- | --- | --- | --- | --- | --- | --- |
| model_2 / ordinary | Intercept | -0.4682 (0.1152) | [-0.6941, -0.2423] | 4.848e-05 | 0.626 [0.500, 0.785] | — |
| model_2 / ordinary | log_flood_area | -0.2216 (0.0240) | [-0.2687, -0.1745] | 3.012e-20 | 0.801 [0.764, 0.840] | — |
| model_2 / ordinary | urban_population_share | 1.8205 (0.1496) | [1.5272, 2.1138] | 4.748e-34 | 6.175 [4.605, 8.280] | 1.200 [1.165, 1.235] |
| model_2 / state_clustered | Intercept | -0.4682 (0.9783) | [-2.4691, 1.5327] | 0.6358 | 0.626 [0.085, 4.631] | — |
| model_2 / state_clustered | log_flood_area | -0.2216 (0.1614) | [-0.5516, 0.1085] | 0.1803 | 0.801 [0.576, 1.115] | — |
| model_2 / state_clustered | urban_population_share | 1.8205 (1.1063) | [-0.4422, 4.0832] | 0.1107 | 6.175 [0.643, 59.334] | 1.200 [0.957, 1.504] |
| model_3 / ordinary | Intercept | -1.9849 (0.5526) | [-3.0680, -0.9018] | 0.0003285 | 0.137 [0.047, 0.406] | — |
| model_3 / ordinary | C(year)[T.2016] | 0.5453 (0.7522) | [-0.9290, 2.0195] | 0.4685 | 1.725 [0.395, 7.535] | — |
| model_3 / ordinary | C(year)[T.2017] | 0.4913 (0.6063) | [-0.6970, 1.6795] | 0.4178 | 1.634 [0.498, 5.363] | — |
| model_3 / ordinary | C(year)[T.2018] | 1.8764 (0.5731) | [0.7532, 2.9996] | 0.00106 | 6.530 [2.124, 20.077] | — |
| model_3 / ordinary | C(year)[T.2019] | 0.7301 (0.5556) | [-0.3588, 1.8190] | 0.1888 | 2.075 [0.699, 6.166] | — |
| model_3 / ordinary | C(year)[T.2020] | -0.7532 (0.6111) | [-1.9510, 0.4445] | 0.2177 | 0.471 [0.142, 1.560] | — |
| model_3 / ordinary | C(year)[T.2021] | 0.6302 (0.5878) | [-0.5218, 1.7823] | 0.2836 | 1.878 [0.593, 5.943] | — |
| model_3 / ordinary | C(year)[T.2022] | 1.3363 (0.6871) | [-0.0105, 2.6831] | 0.05181 | 3.805 [0.990, 14.630] | — |
| model_3 / ordinary | C(year)[T.2023] | 1.6283 (0.6047) | [0.4430, 2.8135] | 0.00709 | 5.095 [1.557, 16.668] | — |
| model_3 / ordinary | C(year)[T.2024] | 1.4634 (0.6165) | [0.2552, 2.6716] | 0.0176 | 4.321 [1.291, 14.464] | — |
| model_3 / ordinary | C(year)[T.2025] | 1.9826 (0.6301) | [0.7477, 3.2175] | 0.001651 | 7.262 [2.112, 24.967] | — |
| model_3 / ordinary | log_flood_area | -0.1491 (0.0606) | [-0.2679, -0.0304] | 0.01385 | 0.861 [0.765, 0.970] | — |
| model_3 / ordinary | urban_population_share | 2.4621 (0.5017) | [1.4788, 3.4455] | 9.226e-07 | 11.730 [4.388, 31.358] | 1.279 [1.159, 1.411] |
| model_3 / state_clustered | Intercept | -1.9849 (0.6410) | [-3.2959, -0.6739] | 0.004316 | 0.137 [0.037, 0.510] | — |
| model_3 / state_clustered | C(year)[T.2016] | 0.5453 (0.6397) | [-0.7630, 1.8535] | 0.401 | 1.725 [0.466, 6.382] | — |
| model_3 / state_clustered | C(year)[T.2017] | 0.4913 (0.7030) | [-0.9466, 1.9291] | 0.4903 | 1.634 [0.388, 6.884] | — |
| model_3 / state_clustered | C(year)[T.2018] | 1.8764 (0.7848) | [0.2712, 3.4815] | 0.02352 | 6.530 [1.312, 32.509] | — |
| model_3 / state_clustered | C(year)[T.2019] | 0.7301 (0.3696) | [-0.0257, 1.4860] | 0.05779 | 2.075 [0.975, 4.419] | — |
| model_3 / state_clustered | C(year)[T.2020] | -0.7532 (0.6732) | [-2.1301, 0.6236] | 0.2724 | 0.471 [0.119, 1.866] | — |
| model_3 / state_clustered | C(year)[T.2021] | 0.6302 (0.5417) | [-0.4776, 1.7381] | 0.2541 | 1.878 [0.620, 5.686] | — |
| model_3 / state_clustered | C(year)[T.2022] | 1.3363 (0.6952) | [-0.0856, 2.7582] | 0.06446 | 3.805 [0.918, 15.772] | — |
| model_3 / state_clustered | C(year)[T.2023] | 1.6283 (0.5879) | [0.4259, 2.8306] | 0.009684 | 5.095 [1.531, 16.956] | — |
| model_3 / state_clustered | C(year)[T.2024] | 1.4634 (0.4849) | [0.4717, 2.4551] | 0.005257 | 4.321 [1.603, 11.648] | — |
| model_3 / state_clustered | C(year)[T.2025] | 1.9826 (0.4400) | [1.0827, 2.8826] | 9.994e-05 | 7.262 [2.953, 17.860] | — |
| model_3 / state_clustered | log_flood_area | -0.1491 (0.1083) | [-0.3706, 0.0724] | 0.179 | 0.861 [0.690, 1.075] | — |
| model_3 / state_clustered | urban_population_share | 2.4621 (0.7543) | [0.9195, 4.0048] | 0.002815 | 11.730 [2.508, 54.860] | 1.279 [1.096, 1.493] |
| model_2_by_source_S1 / ordinary | Intercept | -0.4682 (0.1152) | [-0.6941, -0.2423] | 4.848e-05 | 0.626 [0.500, 0.785] | — |
| model_2_by_source_S1 / ordinary | log_flood_area | -0.2216 (0.0240) | [-0.2687, -0.1745] | 3.012e-20 | 0.801 [0.764, 0.840] | — |
| model_2_by_source_S1 / ordinary | urban_population_share | 1.8205 (0.1496) | [1.5272, 2.1138] | 4.748e-34 | 6.175 [4.605, 8.280] | 1.200 [1.165, 1.235] |
| model_2_by_source_S1 / state_clustered | Intercept | -0.4682 (0.9783) | [-2.4691, 1.5327] | 0.6358 | 0.626 [0.085, 4.631] | — |
| model_2_by_source_S1 / state_clustered | log_flood_area | -0.2216 (0.1614) | [-0.5516, 0.1085] | 0.1803 | 0.801 [0.576, 1.115] | — |
| model_2_by_source_S1 / state_clustered | urban_population_share | 1.8205 (1.1063) | [-0.4422, 4.0832] | 0.1107 | 6.175 [0.643, 59.334] | 1.200 [0.957, 1.504] |

Flood IRR is per one-unit increase in log(1 + km²); the urbanization IRR is per 0→1 change, with 10 percentage points reported separately.

## Model availability

- model_1: NB2 covariance or coefficient estimates are not reliable
- model_2: estimated
- model_3: estimated
- model_2_source_fe: insufficient source variation: fewer than two satellite sources
- model_2_by_source_S1: estimated (sensitivity)
- source_event_robustness: NB2 maximum likelihood did not converge
- exposed_population_robustness: not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used

## Descriptive distributions and missingness

```json
{
  "distributions": {
    "flood_area_km2": {
      "count": 1352.0,
      "mean": 184.1541023669,
      "std": 361.0563197359,
      "min": 0.0147,
      "25%": 15.9498,
      "50%": 68.09295,
      "75%": 206.271075,
      "max": 5894.8599
    },
    "article_count": {
      "count": 1352.0,
      "mean": 0.4622781065,
      "std": 2.5000482872,
      "min": 0.0,
      "25%": 0.0,
      "50%": 0.0,
      "75%": 0.0,
      "max": 64.0
    },
    "urban_population_share": {
      "count": 1352.0,
      "mean": 0.2156432607,
      "std": 0.1920844032,
      "min": 0.0,
      "25%": 0.0876401087,
      "50%": 0.1474607884,
      "75%": 0.2796231495,
      "max": 1.0
    }
  },
  "available_input_distributions": {
    "flood_area_km2": {
      "count": 1470.0,
      "mean": 176.6781806803,
      "std": 352.4582836914,
      "min": 0.0028,
      "25%": 14.6394,
      "50%": 62.67275,
      "75%": 190.43805,
      "max": 5894.8599
    },
    "article_count": {
      "count": 1551.0,
      "mean": 0.4448742747,
      "std": 2.4103321616,
      "min": 0.0,
      "25%": 0.0,
      "50%": 0.0,
      "75%": 0.0,
      "max": 64.0
    },
    "urban_population_share": {
      "count": 1429.0,
      "mean": 0.2167205578,
      "std": 0.1918490889,
      "min": 0.0,
      "25%": 0.0876401087,
      "50%": 0.1486321135,
      "75%": 0.2804554824,
      "max": 1.0
    }
  },
  "missing_counts": {
    "flood_area_km2": 83,
    "article_count": 2,
    "urban_population_share": 124
  },
  "exclusion_counts": {
    "article_collection_incomplete": 201,
    "article_count_missing_or_invalid": 201,
    "census_unmatched": 124,
    "census_invalid": 124,
    "census_population_inconsistent": 124,
    "satellite_missing_or_invalid": 83,
    "district_aoi_unmatched": 5,
    "aoi_area_invalid": 5
  },
  "stage_qc": {
    "district_extraction": {
      "success": 1553,
      "total": 1553,
      "rate": 1.0
    },
    "district_aoi_match": {
      "success": 1548,
      "total": 1553,
      "rate": 0.996780425
    },
    "census_match": {
      "success": 1429,
      "total": 1553,
      "rate": 0.9201545396
    },
    "satellite_observation": {
      "success": 1470,
      "total": 1553,
      "rate": 0.9465550547
    },
    "gdelt_collection": {
      "success": 1553,
      "total": 1553,
      "rate": 1.0
    },
    "article_observation": {
      "success": 0,
      "total": 1553,
      "rate": 0.0
    },
    "final_analyzable": {
      "success": 1352,
      "total": 1553,
      "rate": 0.8705730844
    },
    "satellite_source_counts": {
      "S1": 1352
    }
  },
  "estimated_dispersion": {
    "model_2": 2.1e-09,
    "model_3": 11.0637741782
  },
  "article_count_variance": 6.2502414385,
  "article_count_mean": 0.4622781065
}
```

## Selection check

```
urbanization_group  rows  excluded  exclusion_rate
              high   387        22        0.056848
               low   660        28        0.042424
            medium   382        27        0.070681
           unknown   124       124        1.000000
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
- district-based urbanization tercile cutpoints: [0.1369414084546159, 0.2557930624760398]; unknown Census matches cannot be assigned an urbanization level
