# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-20 00:37:41`

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
| Monsoon flag | **Excluded** from NegBin (metadata only; sensitivity branch) |
| GDELT volume offset | **None** (primary) |
| Media window (design) | onset + 14 days |
| Outcome (interim) | `mss_results.total_articles` as `n_articles_0_14` proxy |
| Severity proxy (AIC) | `population_exposed` |
| Flood area source | `flood_combined.combined_km2` (district-level; via severity_raw) |
| Deaths handling | Option A: `log1p(deaths)` with `fillna(0)` + `deaths_missing` flag (rows kept) |
| Deaths missing (flag=1) | 24 / 138 |
| N events | 138 |
| NegBin AIC | 2564.2 |
| NegBin log-likelihood | -1268.1 |
| under_flag (log_ratio &lt; 0) | 81 (58.7%) |
| over_flag (log_ratio &gt; 0) | 57 (41.3%) |
| severity_tier | Tertiles (low ≤ P33, high ≥ P67; exploratory only) |

## Absolute under-coverage (`under_flag`)

| income_group | n_under | n | share |
| --- | --- | --- | --- |
| High | 11 | 29 | 37.9% |
| Middle | 11 | 26 | 42.3% |
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
Model:              GLM              AIC:            2564.1589
Link Function:      Log              BIC:            -453.7880
Dependent Variable: n_articles_0_14  Log-Likelihood: -1268.1  
Date:               2026-07-20 00:37 LL-Null:        -1312.0  
No. Observations:   138              Deviance:       157.19   
Df Model:           13               Pearson chi2:   154.     
Df Residuals:       124              Scale:          1.0000   
Method:             IRLS                                      
--------------------------------------------------------------
                 Coef.  Std.Err.    z    P>|z|   [0.025 0.975]
--------------------------------------------------------------
const            5.4984   0.6082  9.0402 0.0000  4.3063 6.6905
log1p_severity   0.0854   0.0410  2.0847 0.0371  0.0051 0.1657
log1p_deaths     0.3569   0.0644  5.5397 0.0000  0.2306 0.4832
deaths_missing   1.4083   0.4273  3.2960 0.0010  0.5709 2.2458
year_2016        1.3621   0.5822  2.3398 0.0193  0.2211 2.5031
year_2017        0.7729   0.3763  2.0538 0.0400  0.0353 1.5104
year_2018        0.4486   0.5016  0.8942 0.3712 -0.5346 1.4317
year_2019        0.3650   0.5193  0.7029 0.4821 -0.6528 1.3829
year_2020       -0.4255   0.5001 -0.8509 0.3948 -1.4057 0.5547
year_2021        0.0218   0.4386  0.0498 0.9603 -0.8377 0.8814
year_2022       -0.6850   0.4485 -1.5274 0.1267 -1.5640 0.1940
year_2023        0.4845   0.4299  1.1269 0.2598 -0.3581 1.3272
year_2024        0.1068   0.4670  0.2288 0.8191 -0.8086 1.0222
year_2025       -0.3628   0.5887 -0.6163 0.5377 -1.5166 0.7910
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | 0.1566 | 0.2058 | 0.8085 | 29 |
| Middle | 0.0757 | 0.0698 | 0.6780 | 26 |
| Low | -0.9133 | -0.5930 | 1.3776 | 83 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -1.0698 | [-1.8482, -0.2915] | 0.0071 | False |
| Middle | -0.0808 | [-0.7335, 0.5718] | 0.8082 | True |

**Verdict:** Detectable income gradient in this GDELT-monitored system (at least one CI excludes 0).  
R² = 0.1599

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E126 | Sikkim | Low | 2 | 4014.9 | -7.3816 | True | low |
| E127 | Sikkim | Low | 2 | 1787.0 | -6.5723 | True | low |
| E18 | Arunachal Pradesh | Low | 33 | 1021.4 | -3.4179 | True | low |
| E28 | Assam | Low | 120 | 2398.9 | -2.9913 | True | low |
| E21 | Arunachal Pradesh | Low | 186 | 2801.0 | -2.7095 | True | low |
| E159 | Uttarakhand | Low | 327 | 4789.0 | -2.6827 | True | low |
| E104 | Meghalaya | Low | 81 | 1157.7 | -2.6540 | True | low |
| E105 | Meghalaya | Low | 109 | 1206.2 | -2.3997 | True | low |
| E19 | Arunachal Pradesh | Low | 435 | 4084.9 | -2.2387 | True | low |
| E10 | Odisha | Low | 173 | 1522.0 | -2.1719 | True | low |
| E103 | Meghalaya | Low | 170 | 1430.2 | -2.1272 | True | low |
| E106 | Mizoram | Low | 124 | 1042.9 | -2.1259 | True | low |
| E102 | Meghalaya | Low | 340 | 2633.9 | -2.0460 | True | low |
| E153 | Uttarakhand | Low | 233 | 1784.7 | -2.0341 | True | low |
| E70 | Jharkhand | Low | 951 | 7174.6 | -2.0203 | True | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 13938 | 1912.4 | 1.9860 | False | high |
| E05 | Maharashtra | High | 4504 | 1021.0 | 1.4838 | False | high |
| E01 | Kerala | Middle | 34918 | 8427.2 | 1.4215 | False | high |
| E94 | Maharashtra | High | 39317 | 9963.9 | 1.3726 | False | high |
| E92 | Maharashtra | High | 11788 | 3093.2 | 1.3378 | False | high |
| E95 | Maharashtra | High | 19382 | 5599.7 | 1.2416 | False | high |
| E91 | Maharashtra | High | 7701 | 2704.6 | 1.0463 | False | high |
| E134 | Tamil Nadu | Middle | 3361 | 1431.6 | 0.8532 | False | high |
| E86 | Madhya Pradesh | Low | 8173 | 3596.8 | 0.8207 | False | high |
| E42 | Delhi | High | 33940 | 15101.6 | 0.8098 | False | high |
| E133 | Tamil Nadu | Middle | 3065 | 1397.1 | 0.7855 | False | high |
| E98 | Maharashtra | High | 2766 | 1285.2 | 0.7663 | False | high |
| E09 | Karnataka | High | 2110 | 1046.8 | 0.7007 | False | high |
| E141 | Uttar Pradesh | Low | 3005 | 1553.6 | 0.6595 | False | high |
| E97 | Maharashtra | High | 20891 | 11695.6 | 0.5801 | False | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -6.9769 | -6.9769 | 2 |
| Arunachal Pradesh | Low | -2.5373 | -2.4741 | 4 |
| Meghalaya | Low | -2.3067 | -2.2635 | 4 |
| Mizoram | Low | -2.1259 | -2.1259 | 1 |
| Jharkhand | Low | -1.5429 | -1.3415 | 3 |
| Nagaland | Low | -1.4984 | -1.4984 | 2 |
| Odisha | Low | -1.1338 | -1.2714 | 5 |
| Tripura | Low | -1.0199 | -1.3623 | 4 |
| Uttarakhand | Low | -0.9345 | -0.7998 | 11 |
| Telangana | High | -0.8607 | -0.8607 | 2 |
| Chhattisgarh | Low | -0.8419 | -0.9128 | 3 |
| Assam | Low | -0.8362 | -0.4992 | 7 |
| Haryana | High | -0.7721 | -0.7721 | 2 |
| Goa | High | -0.7284 | -0.7284 | 2 |
| Manipur | Low | -0.5911 | -0.5911 | 1 |
| Rajasthan | Low | -0.5894 | -0.8634 | 3 |
| West Bengal | Middle | -0.4058 | -0.4148 | 6 |
| Himachal Pradesh | Low | -0.4051 | -0.4127 | 9 |
| Bihar | Low | -0.3727 | -0.3055 | 6 |
| Gujarat | High | -0.2046 | -0.1370 | 8 |
| Andhra Pradesh | Middle | -0.1340 | 0.0518 | 5 |
| Madhya Pradesh | Low | 0.0547 | 0.1074 | 6 |
| Kerala | Middle | 0.2573 | 0.1461 | 5 |
| Uttar Pradesh | Low | 0.2748 | 0.2731 | 11 |
| Punjab | Middle | 0.2885 | -0.1393 | 4 |
| Karnataka | High | 0.3072 | 0.4652 | 6 |
| Tamil Nadu | Middle | 0.4389 | 0.3524 | 6 |
| Jammu and Kashmir | Low | 0.5790 | 0.5790 | 1 |
| Delhi | High | 0.8098 | 0.8098 | 1 |
| Maharashtra | High | 1.0309 | 1.1439 | 8 |

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
