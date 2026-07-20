# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-20 11:59:57`

## Analysis standard (hybrid)

- **Primary metric:** continuous `log_ratio = ln((y+0.5)/(μ̂+0.5))` rankings
- **Binary under-coverage:** `under_flag` when `log_ratio < 0` (observed &lt; expected)
- **Severe-neglect exploration pool:** `severity_tier == low` (bottom tertile ≤ P33)

## Summary

| Item | Value |
| --- | --- |
| Primary metric | `log_ratio = ln((y+0.5)/(μ̂+0.5))` |
| Model | Sparse Negative-Binomial (cluster-robust SE by state) |
| Monsoon flag | **Excluded** from NegBin (metadata only; sensitivity branch) |
| GDELT volume offset | **None** (primary) |
| Media window (design) | onset + 14 days |
| Outcome (interim) | `mss_results.total_articles` as `n_articles_0_14` proxy |
| Severity proxy (AIC) | `population_exposed` |
| Flood area source | `flood_combined.combined_km2` (district-level; via severity_raw) |
| Deaths handling | Option C: `log1p(deaths)` with `fillna(0)`; `deaths_missing` metadata only (not in NegBin) |
| Deaths missing (metadata) | 23 / 132 |
| N events | 132 |
| NegBin AIC | 2459.5 |
| NegBin log-likelihood | -1216.7 |
| under_flag (log_ratio &lt; 0) | 82 (62.1%) |
| over_flag (log_ratio &gt; 0) | 50 (37.9%) |
| severity_tier | Tertiles (low ≤ P33, high ≥ P67; exploratory only) |

## Legacy MSS weight sensitivity (CP-09)

Primary `MSS` in `data/mss_results.csv` uses **fixed** weights (0.3/0.3/0.2/0.2).
Entropy Weight Method (EWM) and PCA loadings are computed on the same scaled
components for sensitivity only (`MSS_ewm`, `MSS_pca` columns).

| Scheme | S_vol | S_sov | S_TTFR | S_CD |
| --- | --- | --- | --- | --- |
| Fixed (primary) | 0.3000 | 0.3000 | 0.2000 | 0.2000 |
| EWM | 0.0356 | 0.6364 | 0.0169 | 0.3111 |
| PCA loadings | 0.2619 | 0.2314 | 0.0623 | 0.4443 |

| vs fixed MSS | Pearson r | max rank shift | mean rank shift |
| --- | --- | --- | --- |
| EWM | 0.9413 | 48 | 4.65 |
| PCA | 0.9465 | 46 | 7.68 |

- MSS events: 167
- PCA PC1 explained variance: 0.5936
- Primary coverage metric remains NegBin `log_ratio` (not MSS).

## Absolute under-coverage (`under_flag`)

| income_group | n_under | n | share |
| --- | --- | --- | --- |
| High | 13 | 28 | 46.4% |
| Middle | 15 | 26 | 57.7% |
| Low | 54 | 78 | 69.2% |

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
Model:              GLM              AIC:            2459.4780
Link Function:      Log              BIC:            -431.7218
Dependent Variable: n_articles_0_14  Log-Likelihood: -1216.7  
Date:               2026-07-20 11:59 LL-Null:        -1259.3  
No. Observations:   132              Deviance:       149.33   
Df Model:           12               Pearson chi2:   153.     
Df Residuals:       119              Scale:          1.0000   
Method:             IRLS                                      
--------------------------------------------------------------
                 Coef.  Std.Err.    z    P>|z|   [0.025 0.975]
--------------------------------------------------------------
const            6.0885   0.4808 12.6619 0.0000  5.1460 7.0309
log1p_severity   0.1602   0.0484  3.3097 0.0009  0.0653 0.2550
log1p_deaths     0.1569   0.0227  6.9188 0.0000  0.1125 0.2014
year_2016        1.4293   0.6025  2.3722 0.0177  0.2484 2.6103
year_2017        0.6090   0.3875  1.5716 0.1161 -0.1505 1.3686
year_2018        0.3153   0.5022  0.6278 0.5301 -0.6690 1.2996
year_2019        0.6903   0.5363  1.2871 0.1980 -0.3609 1.7415
year_2020        0.1410   0.4860  0.2901 0.7718 -0.8116 1.0936
year_2021       -0.0566   0.5255 -0.1077 0.9142 -1.0866 0.9733
year_2022       -0.2663   0.4765 -0.5587 0.5763 -1.2002 0.6677
year_2023        0.5458   0.4176  1.3070 0.1912 -0.2727 1.3643
year_2024       -0.0066   0.5249 -0.0125 0.9900 -1.0354 1.0222
year_2025       -0.4109   0.6111 -0.6724 0.5013 -1.6087 0.7869
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | 0.0085 | 0.1534 | 0.8486 | 28 |
| Middle | -0.0682 | -0.0826 | 0.7058 | 26 |
| Low | -0.7733 | -0.6955 | 1.2515 | 78 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -0.7818 | [-1.5226, -0.0411] | 0.0386 | False |
| Middle | -0.0767 | [-0.6833, 0.5299] | 0.8043 | True |

**Verdict:** Detectable income gradient in this GDELT-monitored system (at least one CI excludes 0).  
R² = 0.1044

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E127 | Sikkim | Low | 2 | 1615.6 | -6.4715 | True | low |
| E18 | Arunachal Pradesh | Low | 33 | 1214.4 | -3.5909 | True | low |
| E104 | Meghalaya | Low | 81 | 1601.5 | -2.9784 | True | low |
| E28 | Assam | Low | 120 | 2175.4 | -2.8935 | True | low |
| E19 | Arunachal Pradesh | Low | 435 | 6229.5 | -2.6606 | True | low |
| E105 | Meghalaya | Low | 109 | 1538.1 | -2.6427 | True | low |
| E103 | Meghalaya | Low | 170 | 2002.0 | -2.4634 | True | low |
| E159 | Uttarakhand | Low | 327 | 3273.5 | -2.3023 | True | low |
| E106 | Mizoram | Low | 124 | 1170.7 | -2.2415 | True | low |
| E136 | Tripura | Low | 360 | 2870.2 | -2.0748 | True | low |
| E102 | Meghalaya | Low | 340 | 2683.9 | -2.0648 | True | low |
| E10 | Odisha | Low | 173 | 1245.6 | -1.9716 | True | low |
| E69 | Jharkhand | Low | 536 | 3728.9 | -1.9389 | True | low |
| E135 | Telangana | High | 1002 | 6711.3 | -1.9014 | True | low |
| E70 | Jharkhand | Low | 951 | 5783.1 | -1.8047 | True | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 13938 | 1923.1 | 1.9804 | False | high |
| E01 | Kerala | Middle | 34918 | 8216.1 | 1.4469 | False | high |
| E94 | Maharashtra | High | 39317 | 9704.6 | 1.3990 | False | high |
| E06 | Uttarakhand | Low | 4378 | 1240.3 | 1.2609 | False | high |
| E65 | Himachal Pradesh | Low | 2726 | 895.3 | 1.1131 | False | high |
| E92 | Maharashtra | High | 11788 | 3980.7 | 1.0855 | False | high |
| E05 | Maharashtra | High | 4504 | 1552.3 | 1.0650 | False | high |
| E112 | Odisha | Low | 1999 | 805.0 | 0.9091 | False | high |
| E95 | Maharashtra | High | 19382 | 8054.4 | 0.8781 | False | high |
| E86 | Madhya Pradesh | Low | 8173 | 3655.8 | 0.8044 | False | high |
| E42 | Delhi | High | 33940 | 15444.9 | 0.7873 | False | high |
| E53 | Gujarat | High | 7654 | 3664.3 | 0.7365 | False | high |
| E97 | Maharashtra | High | 20891 | 10133.6 | 0.7234 | False | high |
| E140 | Uttar Pradesh | Low | 3681 | 1812.8 | 0.7082 | False | high |
| E78 | Kerala | Middle | 8045 | 4182.0 | 0.6542 | False | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -6.4715 | -6.4715 | 1 |
| Arunachal Pradesh | Low | -2.6816 | -2.6606 | 3 |
| Meghalaya | Low | -2.5373 | -2.5530 | 4 |
| Mizoram | Low | -2.2415 | -2.2415 | 1 |
| Jharkhand | Low | -1.7332 | -1.8047 | 3 |
| Telangana | High | -1.5719 | -1.5719 | 2 |
| Nagaland | Low | -1.1952 | -1.1952 | 2 |
| Tripura | Low | -1.0853 | -1.2143 | 4 |
| Assam | Low | -1.0060 | -0.7938 | 6 |
| Chhattisgarh | Low | -0.9645 | -0.8867 | 3 |
| Uttarakhand | Low | -0.8916 | -1.0478 | 11 |
| Odisha | Low | -0.7799 | -0.9453 | 5 |
| Haryana | High | -0.7488 | -0.7488 | 2 |
| Rajasthan | Low | -0.5811 | -0.4651 | 3 |
| Goa | High | -0.5140 | -0.5140 | 2 |
| Bihar | Low | -0.3648 | -0.4906 | 5 |
| Andhra Pradesh | Middle | -0.3624 | -0.3102 | 5 |
| West Bengal | Middle | -0.3440 | -0.1894 | 6 |
| Gujarat | High | -0.3429 | -0.3680 | 7 |
| Himachal Pradesh | Low | -0.0855 | -0.0676 | 9 |
| Tamil Nadu | Middle | -0.0459 | 0.1200 | 6 |
| Karnataka | High | 0.2038 | 0.3786 | 6 |
| Punjab | Middle | 0.2165 | -0.1295 | 4 |
| Madhya Pradesh | Low | 0.2830 | 0.2400 | 6 |
| Kerala | Middle | 0.3024 | 0.0261 | 5 |
| Uttar Pradesh | Low | 0.3142 | 0.3313 | 11 |
| Jammu and Kashmir | Low | 0.3370 | 0.3370 | 1 |
| Maharashtra | High | 0.7872 | 0.8008 | 8 |
| Delhi | High | 0.7873 | 0.7873 | 1 |

## Figures

- [Observed vs expected calibration](plot5_observed_vs_expected.png)
- [log_ratio residual histogram](plot6_log_ratio_histogram.png)
- [Coverage imbalance ranking (extremes)](plot7_log_ratio_ranking.png)
- [log_ratio by income group](plot8_log_ratio_by_income.png)

## Output files

- `data/expected_coverage.csv` (primary)
- `data/state_expected_coverage.csv`
- `data/events_quarantine.csv`
- `outputs/pipeline_result.md`
