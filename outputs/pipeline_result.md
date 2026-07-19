# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-20 00:56:22`

## Analysis standard (hybrid)

- **Primary metric:** continuous `log_ratio = ln((y+0.5)/(μ̂+0.5))` rankings
- **Binary under-coverage:** `under_flag` when `log_ratio < 0` (observed &lt; expected)
- **Severe-neglect exploration pool:** `severity_tier == low` (bottom tertile ≤ P33)
- **Legacy Min-Max DI:** not primary (opt-in via `LEGACY_DI=1` only)

## Summary

| Item | Value |
| --- | --- |
| Primary metric | `log_ratio = ln((y+0.5)/(μ̂+0.5))` |
| Model | Sparse Negative-Binomial (cluster-robust SE by state) |
| GDELT volume offset | **None** (primary) |
| Media window (design) | onset + 14 days |
| Outcome (interim) | `mss_results.total_articles` as `n_articles_0_14` proxy |
| Severity proxy (AIC) | `population_exposed` |
| Flood area source | `flood_combined.combined_km2` (district-level; via severity_raw) |
| Deaths handling | Option C: `log1p(deaths)` with `fillna(0)`; `deaths_missing` metadata only (not in NegBin) |
| Deaths missing (metadata) | 24 / 138 |
| N events | 138 |
| NegBin AIC | 2571.7 |
| NegBin log-likelihood | -1271.9 |
| under_flag (log_ratio &lt; 0) | 82 (59.4%) |
| over_flag (log_ratio &gt; 0) | 56 (40.6%) |
| severity_tier | Tertiles (low ≤ P33, high ≥ P67; exploratory only) |

## Absolute under-coverage (`under_flag`)

| income_group | n_under | n | share |
| --- | --- | --- | --- |
| High | 13 | 29 | 44.8% |
| Middle | 10 | 26 | 38.5% |
| Low | 59 | 83 | 71.1% |

## Severe-neglect exploration pool (`severity_tier`)

| Tier | Meaning | n |
| --- | --- | --- |
| low | Bottom tertile (≤ 33rd pct) — severe under-coverage pool | 46 |
| mid | Middle tertile | 46 |
| high | Top tertile (≥ 67th pct) — over-coverage pool | 46 |

## Model coefficients (cluster-robust)

```
              Results: Generalized linear model
==============================================================
Model:              GLM              AIC:            2571.7364
Link Function:      Log              BIC:            -453.0772
Dependent Variable: n_articles_0_14  Log-Likelihood: -1271.9  
Date:               2026-07-20 00:56 LL-Null:        -1310.2  
No. Observations:   138              Deviance:       157.90   
Df Model:           13               Pearson chi2:   148.     
Df Residuals:       124              Scale:          1.0000   
Method:             IRLS                                      
--------------------------------------------------------------
                 Coef.  Std.Err.    z    P>|z|   [0.025 0.975]
--------------------------------------------------------------
const            6.3260   0.6323 10.0044 0.0000  5.0867 7.5654
log1p_severity   0.0864   0.0434  1.9897 0.0466  0.0013 0.1715
log1p_deaths     0.1581   0.0302  5.2338 0.0000  0.0989 0.2173
monsoon_flag     0.4017   0.2985  1.3456 0.1784 -0.1834 0.9868
year_2016        1.5191   0.5796  2.6211 0.0088  0.3832 2.6551
year_2017        0.5889   0.3802  1.5487 0.1214 -0.1564 1.3341
year_2018        0.3460   0.4831  0.7162 0.4739 -0.6009 1.2929
year_2019        0.5864   0.5358  1.0943 0.2738 -0.4638 1.6366
year_2020       -0.1162   0.5108 -0.2275 0.8201 -1.1173 0.8849
year_2021        0.0158   0.5475  0.0289 0.9770 -1.0574 1.0890
year_2022       -0.2074   0.5788 -0.3584 0.7200 -1.3418 0.9269
year_2023        0.5790   0.4701  1.2319 0.2180 -0.3422 1.5003
year_2024       -0.2387   0.5183 -0.4605 0.6451 -1.2545 0.7771
year_2025       -0.6610   0.5712 -1.1573 0.2471 -1.7805 0.4584
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | -0.0009 | 0.3687 | 0.9531 | 29 |
| Middle | 0.0420 | 0.0538 | 0.6498 | 26 |
| Low | -0.8888 | -0.7658 | 1.4095 | 83 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -0.8878 | [-1.7072, -0.0685] | 0.0337 | False |
| Middle | 0.0429 | [-0.6022, 0.6879] | 0.8963 | True |

**Verdict:** Detectable income gradient in this GDELT-monitored system (at least one CI excludes 0).  
R² = 0.1207

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E126 | Sikkim | Low | 2 | 3728.7 | -7.3077 | True | low |
| E127 | Sikkim | Low | 2 | 1404.0 | -6.3311 | True | low |
| E18 | Arunachal Pradesh | Low | 33 | 1832.8 | -4.0023 | True | low |
| E28 | Assam | Low | 120 | 2013.6 | -2.8163 | True | low |
| E21 | Arunachal Pradesh | Low | 186 | 2907.2 | -2.7467 | True | low |
| E19 | Arunachal Pradesh | Low | 435 | 6118.0 | -2.6426 | True | low |
| E104 | Meghalaya | Low | 81 | 1086.1 | -2.5902 | True | low |
| E10 | Odisha | Low | 173 | 2078.0 | -2.4832 | True | low |
| E159 | Uttarakhand | Low | 327 | 2982.4 | -2.2092 | True | low |
| E57 | Haryana | High | 746 | 6575.7 | -2.1758 | True | low |
| E71 | Jharkhand | Low | 399 | 3456.6 | -2.1580 | True | low |
| E105 | Meghalaya | Low | 109 | 943.3 | -2.1540 | True | low |
| E69 | Jharkhand | Low | 536 | 3993.6 | -2.0075 | True | low |
| E137 | Tripura | Low | 299 | 2022.9 | -1.9104 | True | low |
| E106 | Mizoram | Low | 124 | 814.2 | -1.8785 | True | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 13938 | 2229.5 | 1.8327 | False | high |
| E05 | Maharashtra | High | 4504 | 848.5 | 1.6687 | False | high |
| E01 | Kerala | Middle | 34918 | 7620.0 | 1.5222 | False | high |
| E94 | Maharashtra | High | 39317 | 9545.3 | 1.4156 | False | high |
| E95 | Maharashtra | High | 19382 | 5858.9 | 1.1963 | False | high |
| E140 | Uttar Pradesh | Low | 3681 | 1198.4 | 1.1219 | False | high |
| E86 | Madhya Pradesh | Low | 8173 | 2939.1 | 1.0226 | False | high |
| E92 | Maharashtra | High | 11788 | 4368.5 | 0.9926 | False | high |
| E06 | Uttarakhand | Low | 4378 | 1722.8 | 0.9325 | False | high |
| E42 | Delhi | High | 33940 | 13364.3 | 0.9320 | False | high |
| E148 | Uttar Pradesh | Low | 11906 | 5065.3 | 0.8546 | False | high |
| E145 | Uttar Pradesh | Low | 3255 | 1484.5 | 0.7850 | False | high |
| E97 | Maharashtra | High | 20891 | 10319.3 | 0.7053 | False | high |
| E31 | Assam | Low | 3690 | 1853.1 | 0.6887 | False | high |
| E144 | Uttar Pradesh | Low | 16660 | 8820.6 | 0.6359 | False | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -6.8194 | -6.8194 | 2 |
| Arunachal Pradesh | Low | -2.7315 | -2.6946 | 4 |
| Meghalaya | Low | -2.1059 | -1.9973 | 4 |
| Jharkhand | Low | -1.9985 | -2.0075 | 3 |
| Mizoram | Low | -1.8785 | -1.8785 | 1 |
| Nagaland | Low | -1.3429 | -1.3429 | 2 |
| Telangana | High | -1.2834 | -1.2834 | 2 |
| Haryana | High | -1.2751 | -1.2751 | 2 |
| Tripura | Low | -1.1663 | -1.4077 | 4 |
| Odisha | Low | -1.1405 | -1.2271 | 5 |
| Chhattisgarh | Low | -0.9536 | -0.7881 | 3 |
| Uttarakhand | Low | -0.9104 | -1.0400 | 11 |
| Assam | Low | -0.7344 | -0.5592 | 7 |
| Goa | High | -0.7269 | -0.7269 | 2 |
| Rajasthan | Low | -0.6967 | -1.0193 | 3 |
| Gujarat | High | -0.3908 | -0.4336 | 8 |
| Bihar | Low | -0.3657 | -0.4397 | 6 |
| Himachal Pradesh | Low | -0.3644 | -0.2839 | 9 |
| Manipur | Low | -0.3478 | -0.3478 | 1 |
| West Bengal | Middle | -0.3210 | -0.3444 | 6 |
| Andhra Pradesh | Middle | 0.0105 | 0.1231 | 5 |
| Punjab | Middle | 0.1701 | -0.0567 | 4 |
| Kerala | Middle | 0.1714 | 0.0983 | 5 |
| Tamil Nadu | Middle | 0.2379 | 0.3120 | 6 |
| Madhya Pradesh | Low | 0.2760 | 0.1233 | 6 |
| Karnataka | High | 0.2841 | 0.4446 | 6 |
| Uttar Pradesh | Low | 0.3521 | 0.1437 | 11 |
| Jammu and Kashmir | Low | 0.5478 | 0.5478 | 1 |
| Maharashtra | High | 0.8791 | 0.8489 | 8 |
| Delhi | High | 0.9320 | 0.9320 | 1 |

## Figures

- [Observed vs expected calibration](plot5_observed_vs_expected.png)
- [log_ratio residual histogram](plot6_log_ratio_histogram.png)
- [Coverage imbalance ranking (extremes)](plot7_log_ratio_ranking.png)
- [log_ratio by income group](plot8_log_ratio_by_income.png)
- [LEGACY (not primary): PSS vs MSS scatter](plot1_pss_vs_mss_scatter.png)
- [LEGACY (not primary): DI by income group](plot2_di_by_income_group.png)
- [LEGACY (not primary): DI per event](plot3_di_per_event.png)
- [LEGACY (not primary): Spatial DI map](plot4_spatial_di_map.png)

## Output files

- `data/expected_coverage.csv` (primary)
- `data/state_expected_coverage.csv`
- `data/di_results.csv` (legacy; only if `LEGACY_DI=1`)
- `data/events_quarantine.csv`
- `outputs/pipeline_result.md`
