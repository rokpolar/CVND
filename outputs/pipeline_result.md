# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-20 14:49:31`

## Analysis standard (hybrid)

- **Primary metric:** continuous `log_ratio = ln((y+0.0001)/(μ̂+0.0001))` rankings
- **Binary under-coverage:** `under_flag` when `log_ratio < 0` (observed &lt; expected)
- **Severe-neglect exploration pool:** `severity_tier == low` (bottom tertile ≤ P33)

## Summary

| Item | Value |
| --- | --- |
| Primary metric | `log_ratio = ln((y+0.0001)/(μ̂+0.0001))` |
| Model | Gaussian GLM (cluster-robust SE by state) |
| Monsoon flag | **Excluded** from GLM (metadata only; sensitivity branch) |
| GDELT volume offset | **None** (primary) |
| Media window (design) | onset + 14 days |
| Outcome | `MSS` from `mss_results.csv` (AHP-weighted primary score) |
| Article counts | `total_articles` retained as metadata (`n_articles_0_14`) |
| Severity proxy (AIC) | `log1p(population_exposed)` (`population_exposed`) |
| PSS definition | 0.5×MinMax(log1p area) + 0.5×MinMax(log1p pop) from `pss_results.csv` |
| Flood area source | `flood_combined.combined_km2` (district-level; via severity_raw) |
| Deaths handling | Option C: `log1p(deaths)` with `fillna(0)`; `deaths_missing` metadata only (not in GLM) |
| Deaths missing (metadata) | 23 / 132 |
| N events | 132 |
| GLM AIC | -234.8 |
| GLM log-likelihood | 130.4 |
| under_flag (log_ratio &lt; 0) | 71 (53.8%) |
| over_flag (log_ratio &gt; 0) | 61 (46.2%) |
| severity_tier | Tertiles (low ≤ P33, high ≥ P67; exploratory only) |

## MSS weight sensitivity (CP-09)

Primary `MSS` in `data/mss_results.csv` uses **AHP-derived** weights
(Saaty 1980; CR = 0.0000). Entropy weighting is computed on the same
scaled components for robustness (`MSS_entropy` column).

| Scheme | S_vol | S_sov | S_TTFR | S_CD |
| --- | --- | --- | --- | --- |
| AHP (primary) | 0.3750 | 0.3750 | 0.1250 | 0.1250 |
| Entropy | 0.0356 | 0.6364 | 0.0169 | 0.3111 |
| Equal | 0.2500 | 0.2500 | 0.2500 | 0.2500 |

| vs AHP MSS | Pearson r | max rank shift | mean rank shift |
| --- | --- | --- | --- |
| Entropy | 0.9381 | 66 | 8.69 |

- MSS events: 167
- Weight provenance: `data/mss_weight_provenance.csv`
- Rank stability: `data/mss_rank_stability.csv`

## Absolute under-coverage (`under_flag`)

| income_group | n_under | n | share |
| --- | --- | --- | --- |
| High | 12 | 28 | 42.9% |
| Middle | 12 | 26 | 46.2% |
| Low | 47 | 78 | 60.3% |

## Severe-neglect exploration pool (`severity_tier`)

| Tier | Meaning | n |
| --- | --- | --- |
| low | Bottom tertile (≤ 33rd pct) — severe under-coverage pool | 44 |
| mid | Middle tertile | 44 |
| high | Top tertile (≥ 67th pct) — over-coverage pool | 44 |

## Model coefficients (cluster-robust)

```
              Results: Generalized linear model
==============================================================
Model:              GLM              AIC:            -234.8026
Link Function:      Identity         BIC:            -579.9818
Dependent Variable: MSS              Log-Likelihood: 130.40   
Date:               2026-07-20 14:49 LL-Null:        69.930   
No. Observations:   132              Deviance:       1.0716   
Df Model:           12               Pearson chi2:   1.07     
Df Residuals:       119              Scale:          0.0090050
Method:             IRLS                                      
--------------------------------------------------------------
                Coef.  Std.Err.    z    P>|z|   [0.025  0.975]
--------------------------------------------------------------
const           0.2225   0.0456  4.8779 0.0000  0.1331  0.3119
log1p_severity  0.0178   0.0041  4.3391 0.0000  0.0097  0.0258
log1p_deaths    0.0235   0.0031  7.6415 0.0000  0.0175  0.0295
year_2016       0.1452   0.0787  1.8446 0.0651 -0.0091  0.2994
year_2017       0.0613   0.0379  1.6165 0.1060 -0.0130  0.1356
year_2018       0.0064   0.0451  0.1410 0.8879 -0.0820  0.0947
year_2019       0.0594   0.0505  1.1769 0.2392 -0.0396  0.1585
year_2020      -0.0048   0.0439 -0.1095 0.9128 -0.0909  0.0813
year_2021      -0.0107   0.0441 -0.2422 0.8086 -0.0972  0.0758
year_2022      -0.0010   0.0442 -0.0232 0.9815 -0.0877  0.0856
year_2023       0.0444   0.0412  1.0785 0.2808 -0.0363  0.1252
year_2024      -0.0143   0.0467 -0.3070 0.7588 -0.1059  0.0772
year_2025      -0.0989   0.0459 -2.1537 0.0313 -0.1889 -0.0089
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | 0.0441 | 0.0499 | 0.1797 | 28 |
| Middle | 0.0299 | 0.0105 | 0.1729 | 26 |
| Low | -0.0559 | -0.0632 | 0.2167 | 78 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -0.1000 | [-0.2334, 0.0333] | 0.1416 | True |
| Middle | -0.0142 | [-0.1373, 0.1089] | 0.8216 | True |

**Verdict:** No detectable income gradient in this GDELT system (all income CIs cover 0) — do not claim bias.  
R² = 0.0507

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E127 | Sikkim | Low | 0.1250 | 0.3372 | -0.9919 | True | low |
| E160 | Uttarakhand | Low | 0.2383 | 0.3778 | -0.4607 | True | low |
| E18 | Arunachal Pradesh | Low | 0.2295 | 0.3548 | -0.4354 | True | low |
| E19 | Arunachal Pradesh | Low | 0.3383 | 0.5208 | -0.4314 | True | low |
| E135 | Telangana | High | 0.3787 | 0.5278 | -0.3318 | True | low |
| E28 | Assam | Low | 0.2839 | 0.3952 | -0.3307 | True | low |
| E104 | Meghalaya | Low | 0.2668 | 0.3689 | -0.3239 | True | low |
| E102 | Meghalaya | Low | 0.3664 | 0.4977 | -0.3063 | True | low |
| E123 | Rajasthan | Low | 0.3784 | 0.5062 | -0.2909 | True | low |
| E69 | Jharkhand | Low | 0.3482 | 0.4649 | -0.2890 | True | low |
| E159 | Uttarakhand | Low | 0.3267 | 0.4288 | -0.2719 | True | low |
| E155 | Uttarakhand | Low | 0.4814 | 0.6185 | -0.2506 | True | low |
| E61 | Himachal Pradesh | Low | 0.3932 | 0.5043 | -0.2488 | True | low |
| E136 | Tripura | Low | 0.3308 | 0.4186 | -0.2353 | True | low |
| E103 | Meghalaya | Low | 0.3184 | 0.4004 | -0.2292 | True | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 0.6272 | 0.3568 | 0.5641 | False | high |
| E94 | Maharashtra | High | 0.9504 | 0.5943 | 0.4695 | False | high |
| E88 | Madhya Pradesh | Low | 0.3819 | 0.2441 | 0.4474 | False | high |
| E01 | Kerala | Middle | 0.8501 | 0.5562 | 0.4241 | False | high |
| E112 | Odisha | Low | 0.4366 | 0.2893 | 0.4113 | False | high |
| E65 | Himachal Pradesh | Low | 0.4476 | 0.3109 | 0.3642 | False | high |
| E06 | Uttarakhand | Low | 0.4678 | 0.3329 | 0.3402 | False | high |
| E42 | Delhi | High | 0.8797 | 0.6455 | 0.3095 | False | high |
| E05 | Maharashtra | High | 0.4715 | 0.3578 | 0.2760 | False | high |
| E92 | Maharashtra | High | 0.5838 | 0.4622 | 0.2336 | False | high |
| E95 | Maharashtra | High | 0.7200 | 0.5703 | 0.2330 | False | high |
| E13 | Andhra Pradesh | Middle | 0.6650 | 0.5341 | 0.2192 | False | high |
| E145 | Uttar Pradesh | Low | 0.4454 | 0.3586 | 0.2167 | False | high |
| E97 | Maharashtra | High | 0.7361 | 0.5987 | 0.2065 | False | high |
| E83 | Madhya Pradesh | Low | 0.5212 | 0.4327 | 0.1861 | False | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -0.9919 | -0.9919 | 1 |
| Arunachal Pradesh | Low | -0.2711 | -0.4314 | 3 |
| Meghalaya | Low | -0.2584 | -0.2677 | 4 |
| Telangana | High | -0.2579 | -0.2579 | 2 |
| Jharkhand | Low | -0.2330 | -0.2056 | 3 |
| Chhattisgarh | Low | -0.1320 | -0.1334 | 3 |
| Nagaland | Low | -0.1204 | -0.1204 | 2 |
| Haryana | High | -0.1099 | -0.1099 | 2 |
| Assam | Low | -0.1034 | -0.1086 | 6 |
| Uttarakhand | Low | -0.1017 | -0.0942 | 11 |
| Rajasthan | Low | -0.0813 | -0.0791 | 3 |
| Mizoram | Low | -0.0625 | -0.0625 | 1 |
| Goa | High | -0.0457 | -0.0457 | 2 |
| Gujarat | High | -0.0377 | -0.0509 | 7 |
| Bihar | Low | -0.0329 | -0.0354 | 5 |
| Tripura | Low | -0.0320 | -0.0095 | 4 |
| Odisha | Low | -0.0290 | -0.1211 | 5 |
| Andhra Pradesh | Middle | -0.0254 | -0.0528 | 5 |
| West Bengal | Middle | -0.0185 | -0.0042 | 6 |
| Tamil Nadu | Middle | 0.0085 | 0.0510 | 6 |
| Himachal Pradesh | Low | 0.0110 | 0.0277 | 9 |
| Karnataka | High | 0.0704 | 0.0935 | 6 |
| Uttar Pradesh | Low | 0.0946 | 0.0950 | 11 |
| Kerala | Middle | 0.1014 | 0.0369 | 5 |
| Jammu and Kashmir | Low | 0.1071 | 0.1071 | 1 |
| Punjab | Middle | 0.1144 | -0.0087 | 4 |
| Madhya Pradesh | Low | 0.1749 | 0.1670 | 6 |
| Maharashtra | High | 0.1992 | 0.2198 | 8 |
| Delhi | High | 0.3095 | 0.3095 | 1 |

## Figures

- [Observed vs expected calibration](plot5_observed_vs_expected.png)
- [log_ratio residual histogram](plot6_log_ratio_histogram.png)
- [Coverage imbalance ranking (extremes)](plot7_log_ratio_ranking.png)
- [log_ratio by income group](plot8_log_ratio_by_income.png)
- [Coverage imbalance choropleth map](plot9_coverage_map.png)

## Output files

- `data/expected_coverage.csv` (primary)
- `data/state_expected_coverage.csv`
- `data/events_quarantine.csv`
- `outputs/pipeline_result.md`
