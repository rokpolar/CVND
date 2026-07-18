# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-18 23:03:29`

## Summary

| Item | Value |
| --- | --- |
| Primary metric | `log_ratio = ln((y+0.5)/(μ̂+0.5))` |
| Model | Sparse Negative-Binomial (cluster-robust SE by state) |
| GDELT volume offset | **None** (primary) |
| Media window (design) | onset + 14 days |
| Outcome (interim) | `mss_results.total_articles` as `n_articles_0_14` proxy |
| Severity proxy (AIC) | `population_exposed` |
| Deaths included | True |
| N events | 133 |
| NegBin AIC | 2458.2 |
| NegBin log-likelihood | -1215.1 |
| Exploratory tiers | Tertiles on `log_ratio` (low ≤ P33, high ≥ P67; not significance tests) |

Legacy Min-Max DI is demoted; see `data/di_results.csv` for continuity only.

## Exploratory tertile pool

| Tier | Meaning | n |
| --- | --- | --- |
| low | Bottom tertile (≤ 33rd pct) — under-covered pool | 45 |
| mid | Middle tertile | 43 |
| high | Top tertile (≥ 67th pct) — over-covered pool | 45 |

## Model coefficients (cluster-robust)

```
              Results: Generalized linear model
==============================================================
Model:              GLM              AIC:            2458.2111
Link Function:      Log              BIC:            -433.8006
Dependent Variable: n_articles_0_14  Log-Likelihood: -1215.1  
Date:               2026-07-18 23:03 LL-Null:        -1286.6  
No. Observations:   133              Deviance:       148.15   
Df Model:           13               Pearson chi2:   154.     
Df Residuals:       119              Scale:          1.0000   
Method:             IRLS                                      
--------------------------------------------------------------
                Coef.  Std.Err.    z    P>|z|   [0.025  0.975]
--------------------------------------------------------------
const           3.1687   0.6587  4.8105 0.0000  1.8777  4.4598
log1p_severity  0.2378   0.0447  5.3161 0.0000  0.1501  0.3255
log1p_deaths    0.2491   0.0771  3.2301 0.0012  0.0979  0.4002
monsoon_flag    0.4252   0.3037  1.4000 0.1615 -0.1701  1.0205
year_2016       0.7847   0.2999  2.6161 0.0089  0.1968  1.3725
year_2017       0.3806   0.3509  1.0846 0.2781 -0.3071  1.0683
year_2018      -0.3626   0.4345 -0.8345 0.4040 -1.2143  0.4890
year_2019      -0.2528   0.4063 -0.6222 0.5338 -1.0491  0.5435
year_2020      -0.5088   0.3537 -1.4385 0.1503 -1.2021  0.1844
year_2021      -0.6596   0.2673 -2.4679 0.0136 -1.1835 -0.1358
year_2022      -0.6378   0.5589 -1.1412 0.2538 -1.7333  0.4577
year_2023       0.2478   0.3391  0.7309 0.4648 -0.4168  0.9124
year_2024      -0.3295   0.4192 -0.7861 0.4318 -1.1511  0.4921
year_2025      -0.5757   0.3976 -1.4479 0.1476 -1.3551  0.2036
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | -0.0092 | 0.0599 | 0.6522 | 31 |
| Middle | 0.1127 | 0.1098 | 0.7315 | 24 |
| Low | -0.6985 | -0.5928 | 1.0769 | 78 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -0.6893 | [-1.2060, -0.1726] | 0.0089 | False |
| Middle | 0.1219 | [-0.4365, 0.6803] | 0.6687 | True |

**Verdict:** Detectable income gradient in this GDELT-monitored system (at least one CI excludes 0).  
R² = 0.1359

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | tier |
| --- | --- | --- | --- | --- | --- | --- |
| E127 | Sikkim | Low | 2 | 447.2 | -5.1878 | low |
| E18 | Arunachal Pradesh | Low | 33 | 1151.8 | -3.5380 | low |
| E20 | Arunachal Pradesh | Low | 172 | 3444.3 | -2.9942 | low |
| E21 | Arunachal Pradesh | Low | 186 | 2877.9 | -2.7366 | low |
| E107 | Nagaland | Low | 309 | 2509.5 | -2.0931 | low |
| E69 | Jharkhand | Low | 536 | 4078.7 | -2.0286 | low |
| E103 | Meghalaya | Low | 170 | 1165.5 | -1.9226 | low |
| E106 | Mizoram | Low | 124 | 797.5 | -1.8579 | low |
| E104 | Meghalaya | Low | 81 | 501.4 | -1.8178 | low |
| E71 | Jharkhand | Low | 399 | 2412.8 | -1.7985 | low |
| E70 | Jharkhand | Low | 951 | 5311.1 | -1.7196 | low |
| E22 | Arunachal Pradesh | Low | 155 | 745.8 | -1.5685 | low |
| E19 | Arunachal Pradesh | Low | 435 | 2010.1 | -1.5297 | low |
| E105 | Meghalaya | Low | 109 | 492.1 | -1.5038 | low |
| E135 | Telangana | High | 1002 | 4344.8 | -1.4666 | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | tier |
| --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 13938 | 2574.9 | 1.6887 | high |
| E01 | Kerala | Middle | 34918 | 6828.4 | 1.6319 | high |
| E100 | Manipur | Low | 1936 | 475.6 | 1.4030 | high |
| E94 | Maharashtra | High | 39317 | 11375.9 | 1.2401 | high |
| E143 | Uttar Pradesh | Low | 24116 | 8145.8 | 1.0853 | high |
| E42 | Delhi | High | 33940 | 11501.6 | 1.0821 | high |
| E92 | Maharashtra | High | 11788 | 4501.0 | 0.9627 | high |
| E133 | Tamil Nadu | Middle | 3065 | 1292.1 | 0.8635 | high |
| E04 | Telangana | High | 887 | 380.4 | 0.8460 | high |
| E138 | Tripura | Low | 1690 | 747.8 | 0.8150 | high |
| E29 | Assam | Low | 4831 | 2222.4 | 0.7763 | high |
| E80 | Kerala | Middle | 3445 | 1635.5 | 0.7448 | high |
| E25 | Assam | Low | 5822 | 2831.1 | 0.7209 | high |
| E95 | Maharashtra | High | 19382 | 9558.4 | 0.7069 | high |
| E81 | Madhya Pradesh | Low | 12032 | 5952.5 | 0.7037 | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -5.1878 | -5.1878 | 1 |
| Arunachal Pradesh | Low | -2.4734 | -2.7366 | 5 |
| Mizoram | Low | -1.8579 | -1.8579 | 1 |
| Jharkhand | Low | -1.8489 | -1.7985 | 3 |
| Meghalaya | Low | -1.6443 | -1.6608 | 4 |
| Odisha | Low | -1.2580 | -1.2741 | 3 |
| Chhattisgarh | Low | -1.0746 | -1.0945 | 3 |
| Nagaland | Low | -1.0263 | -0.9053 | 5 |
| Uttarakhand | Low | -0.8131 | -0.8871 | 7 |
| Rajasthan | Low | -0.7800 | -0.6695 | 4 |
| West Bengal | Middle | -0.5669 | -0.4301 | 7 |
| Bihar | Low | -0.4511 | -0.4049 | 6 |
| Goa | High | -0.4156 | -0.4156 | 2 |
| Gujarat | High | -0.3460 | -0.2793 | 9 |
| Telangana | High | -0.3103 | -0.3103 | 2 |
| Haryana | High | -0.2787 | 0.1220 | 3 |
| Himachal Pradesh | Low | -0.2689 | -0.3095 | 8 |
| Tripura | Low | -0.2233 | -0.3089 | 4 |
| Assam | Low | -0.1819 | -0.3011 | 9 |
| Karnataka | High | 0.1886 | 0.2118 | 5 |
| Uttar Pradesh | Low | 0.2348 | 0.1584 | 8 |
| Andhra Pradesh | Middle | 0.2506 | 0.2506 | 2 |
| Punjab | Middle | 0.2768 | 0.1423 | 5 |
| Madhya Pradesh | Low | 0.3370 | 0.5389 | 4 |
| Maharashtra | High | 0.3435 | 0.0946 | 9 |
| Tamil Nadu | Middle | 0.3723 | 0.5483 | 5 |
| Kerala | Middle | 0.5853 | 0.3228 | 5 |
| Jammu and Kashmir | Low | 0.6980 | 0.6980 | 1 |
| Manipur | Low | 0.7301 | 0.7301 | 2 |
| Delhi | High | 1.0821 | 1.0821 | 1 |

## Figures

- [Observed vs expected calibration](plot5_observed_vs_expected.png)
- [log_ratio residual histogram](plot6_log_ratio_histogram.png)
- [Coverage imbalance ranking (extremes)](plot7_log_ratio_ranking.png)
- [log_ratio by income group](plot8_log_ratio_by_income.png)
- [Legacy: PSS vs MSS scatter](plot1_pss_vs_mss_scatter.png)
- [Legacy: DI by income group](plot2_di_by_income_group.png)
- [Legacy: DI per event](plot3_di_per_event.png)
- [Legacy: Spatial DI map](plot4_spatial_di_map.png)

## Output files

- `data/expected_coverage.csv`
- `data/state_expected_coverage.csv`
- `data/di_results.csv` (legacy)
- `data/events_quarantine.csv`
- `outputs/pipeline_result.md`
