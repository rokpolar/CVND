# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-19 02:14:45`

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
| Deaths included | True |
| N events | 114 |
| NegBin AIC | 2123.4 |
| NegBin log-likelihood | -1047.7 |
| under_flag (log_ratio &lt; 0) | 70 (61.4%) |
| over_flag (log_ratio &gt; 0) | 44 (38.6%) |
| severity_tier | Tertiles (low ≤ P33, high ≥ P67; exploratory only) |

## Absolute under-coverage (`under_flag`)

| income_group | n_under | n | share |
| --- | --- | --- | --- |
| High | 13 | 27 | 48.1% |
| Middle | 9 | 21 | 42.9% |
| Low | 48 | 66 | 72.7% |

## Severe-neglect exploration pool (`severity_tier`)

| Tier | Meaning | n |
| --- | --- | --- |
| low | Bottom tertile (≤ 33rd pct) — severe under-coverage pool | 38 |
| mid | Middle tertile | 38 |
| high | Top tertile (≥ 67th pct) — over-coverage pool | 38 |

## Model coefficients (cluster-robust)

```
              Results: Generalized linear model
==============================================================
Model:              GLM              AIC:            2123.4222
Link Function:      Log              BIC:            -345.7635
Dependent Variable: n_articles_0_14  Log-Likelihood: -1047.7  
Date:               2026-07-19 02:14 LL-Null:        -1098.4  
No. Observations:   114              Deviance:       127.86   
Df Model:           13               Pearson chi2:   136.     
Df Residuals:       100              Scale:          1.0000   
Method:             IRLS                                      
--------------------------------------------------------------
                 Coef.  Std.Err.    z    P>|z|   [0.025 0.975]
--------------------------------------------------------------
const            5.0838   0.6617  7.6824 0.0000  3.7868 6.3807
log1p_severity   0.1235   0.0350  3.5243 0.0004  0.0548 0.1921
log1p_deaths     0.2786   0.0978  2.8491 0.0044  0.0869 0.4702
monsoon_flag     0.3161   0.3630  0.8709 0.3838 -0.3953 1.0275
year_2016       -0.4124   0.6028 -0.6841 0.4939 -1.5939 0.7691
year_2017        1.1197   0.4849  2.3092 0.0209  0.1693 2.0701
year_2018        0.6327   0.5661  1.1176 0.2637 -0.4768 1.7422
year_2019        0.6769   0.7437  0.9102 0.3627 -0.7807 2.1346
year_2020       -0.2022   0.5534 -0.3653 0.7149 -1.2869 0.8825
year_2021        0.0473   0.4715  0.1003 0.9201 -0.8769 0.9715
year_2022       -0.3053   0.7365 -0.4145 0.6785 -1.7489 1.1383
year_2023        0.9144   0.5994  1.5254 0.1272 -0.2605 2.0892
year_2024        0.3001   0.5303  0.5660 0.5714 -0.7392 1.3394
year_2025       -0.2755   0.6122 -0.4501 0.6527 -1.4753 0.9243
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | -0.0023 | 0.0731 | 0.8308 | 27 |
| Middle | 0.1271 | 0.1340 | 0.7433 | 21 |
| Low | -0.7723 | -0.6577 | 1.1273 | 66 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -0.7700 | [-1.4463, -0.0936] | 0.0257 | False |
| Middle | 0.1294 | [-0.5285, 0.7874] | 0.6998 | True |

**Verdict:** Detectable income gradient in this GDELT-monitored system (at least one CI excludes 0).  
R² = 0.1467

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E127 | Sikkim | Low | 2 | 1445.8 | -6.3605 | True | low |
| E18 | Arunachal Pradesh | Low | 33 | 808.1 | -3.1837 | True | low |
| E69 | Jharkhand | Low | 536 | 7139.6 | -2.5884 | True | low |
| E104 | Meghalaya | Low | 81 | 916.5 | -2.4205 | True | low |
| E21 | Arunachal Pradesh | Low | 186 | 1890.2 | -2.3163 | True | low |
| E57 | Haryana | High | 746 | 5760.6 | -2.0435 | True | low |
| E105 | Meghalaya | Low | 109 | 819.0 | -2.0128 | True | low |
| E155 | Uttarakhand | Low | 2580 | 14814.6 | -1.7477 | True | low |
| E70 | Jharkhand | Low | 951 | 5448.9 | -1.7452 | True | low |
| E103 | Meghalaya | Low | 170 | 953.8 | -1.7222 | True | low |
| E106 | Mizoram | Low | 124 | 663.6 | -1.6742 | True | low |
| E71 | Jharkhand | Low | 399 | 2079.9 | -1.6501 | True | low |
| E61 | Himachal Pradesh | Low | 1187 | 5793.9 | -1.5850 | True | low |
| E135 | Telangana | High | 1002 | 4883.1 | -1.5834 | True | low |
| E102 | Meghalaya | Low | 340 | 1632.5 | -1.5678 | True | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 13938 | 2167.9 | 1.8607 | False | high |
| E94 | Maharashtra | High | 39317 | 9117.9 | 1.4614 | False | high |
| E01 | Kerala | Middle | 34918 | 8313.2 | 1.4351 | False | high |
| E92 | Maharashtra | High | 11788 | 3333.3 | 1.2630 | False | high |
| E133 | Tamil Nadu | Middle | 3065 | 1072.5 | 1.0497 | False | high |
| E95 | Maharashtra | High | 19382 | 8284.8 | 0.8499 | False | high |
| E134 | Tamil Nadu | Middle | 3361 | 1458.0 | 0.8350 | False | high |
| E148 | Uttar Pradesh | Low | 11906 | 5410.5 | 0.7887 | False | high |
| E64 | Himachal Pradesh | Low | 3988 | 1861.3 | 0.7619 | False | high |
| E98 | Maharashtra | High | 2766 | 1303.0 | 0.7525 | False | high |
| E73 | Karnataka | High | 8391 | 4037.5 | 0.7315 | False | high |
| E91 | Maharashtra | High | 7701 | 3772.3 | 0.7136 | False | high |
| E141 | Uttar Pradesh | Low | 3005 | 1481.9 | 0.7068 | False | high |
| E149 | Uttar Pradesh | Low | 3475 | 1758.8 | 0.6808 | False | high |
| E72 | Karnataka | High | 18118 | 9580.7 | 0.6371 | False | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -6.3605 | -6.3605 | 1 |
| Jharkhand | Low | -1.9946 | -1.7452 | 3 |
| Meghalaya | Low | -1.9308 | -1.8675 | 4 |
| Arunachal Pradesh | Low | -1.6944 | -1.7970 | 4 |
| Mizoram | Low | -1.6742 | -1.6742 | 1 |
| Haryana | High | -1.2055 | -1.2055 | 2 |
| Odisha | Low | -1.1762 | -1.1347 | 3 |
| Nagaland | Low | -1.1589 | -1.1589 | 2 |
| Telangana | High | -0.9292 | -0.9292 | 2 |
| Tripura | Low | -0.8643 | -1.1433 | 4 |
| Chhattisgarh | Low | -0.7871 | -0.8494 | 3 |
| Rajasthan | Low | -0.6608 | -0.9358 | 3 |
| Uttarakhand | Low | -0.6071 | -0.4479 | 7 |
| Goa | High | -0.6031 | -0.6031 | 2 |
| Assam | Low | -0.4246 | -0.6380 | 6 |
| Bihar | Low | -0.3894 | -0.2853 | 6 |
| West Bengal | Middle | -0.3513 | -0.3885 | 6 |
| Manipur | Low | -0.2963 | -0.2963 | 1 |
| Gujarat | High | -0.2864 | -0.3231 | 8 |
| Himachal Pradesh | Low | -0.2118 | -0.1036 | 8 |
| Madhya Pradesh | Low | -0.0599 | -0.0599 | 2 |
| Punjab | Middle | -0.0367 | -0.6177 | 4 |
| Delhi | High | 0.0731 | 0.0731 | 1 |
| Kerala | Middle | 0.2758 | 0.1340 | 5 |
| Uttar Pradesh | Low | 0.2879 | 0.3451 | 7 |
| Karnataka | High | 0.3546 | 0.4740 | 5 |
| Andhra Pradesh | Middle | 0.3587 | 0.3587 | 2 |
| Jammu and Kashmir | Low | 0.4233 | 0.4233 | 1 |
| Tamil Nadu | Middle | 0.7069 | 0.6551 | 4 |
| Maharashtra | High | 0.8367 | 0.7525 | 7 |

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
