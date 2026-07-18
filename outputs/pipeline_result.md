# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-19 02:28:57`

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
| Deaths handling | Option A: `log1p(deaths)` with `fillna(0)` + `deaths_missing` flag (rows kept) |
| Deaths missing (flag=1) | 24 / 138 |
| N events | 138 |
| NegBin AIC | 2563.3 |
| NegBin log-likelihood | -1266.6 |
| under_flag (log_ratio &lt; 0) | 83 (60.1%) |
| over_flag (log_ratio &gt; 0) | 55 (39.9%) |
| severity_tier | Tertiles (low ≤ P33, high ≥ P67; exploratory only) |

## Absolute under-coverage (`under_flag`)

| income_group | n_under | n | share |
| --- | --- | --- | --- |
| High | 11 | 29 | 37.9% |
| Middle | 11 | 26 | 42.3% |
| Low | 61 | 83 | 73.5% |

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
Model:              GLM              AIC:            2563.2665
Link Function:      Log              BIC:            -449.1278
Dependent Variable: n_articles_0_14  Log-Likelihood: -1266.6  
Date:               2026-07-19 02:28 LL-Null:        -1312.8  
No. Observations:   138              Deviance:       156.92   
Df Model:           14               Pearson chi2:   148.     
Df Residuals:       123              Scale:          1.0000   
Method:             IRLS                                      
--------------------------------------------------------------
                 Coef.  Std.Err.    z    P>|z|   [0.025 0.975]
--------------------------------------------------------------
const            5.4732   0.6411  8.5372 0.0000  4.2167 6.7298
log1p_severity   0.0855   0.0337  2.5389 0.0111  0.0195 0.1515
log1p_deaths     0.3234   0.0710  4.5558 0.0000  0.1843 0.4626
deaths_missing   1.2203   0.4285  2.8482 0.0044  0.3806 2.0601
monsoon_flag     0.2390   0.2840  0.8414 0.4001 -0.3177 0.7957
year_2016        1.3411   0.5821  2.3038 0.0212  0.2002 2.4820
year_2017        0.7351   0.3735  1.9683 0.0490  0.0031 1.4671
year_2018        0.4283   0.4839  0.8852 0.3760 -0.5200 1.3767
year_2019        0.3606   0.5650  0.6383 0.5233 -0.7467 1.4679
year_2020       -0.4241   0.4788 -0.8858 0.3757 -1.3625 0.5143
year_2021        0.0430   0.4682  0.0918 0.9268 -0.8746 0.9606
year_2022       -0.6156   0.5085 -1.2106 0.2260 -1.6122 0.3810
year_2023        0.4272   0.4754  0.8986 0.3689 -0.5045 1.3589
year_2024        0.0697   0.4770  0.1462 0.8838 -0.8651 1.0045
year_2025       -0.3850   0.5688 -0.6769 0.4984 -1.4999 0.7298
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | 0.1367 | 0.3195 | 0.7970 | 29 |
| Middle | 0.0982 | 0.1419 | 0.7071 | 26 |
| Low | -0.8981 | -0.5878 | 1.3579 | 83 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -1.0348 | [-1.7875, -0.2821] | 0.0071 | False |
| Middle | -0.0385 | [-0.6705, 0.5935] | 0.9050 | True |

**Verdict:** Detectable income gradient in this GDELT-monitored system (at least one CI excludes 0).  
R² = 0.1586

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E126 | Sikkim | Low | 2 | 3894.5 | -7.3512 | True | low |
| E127 | Sikkim | Low | 2 | 1495.9 | -6.3945 | True | low |
| E18 | Arunachal Pradesh | Low | 33 | 1134.6 | -3.5230 | True | low |
| E28 | Assam | Low | 120 | 2516.8 | -3.0393 | True | low |
| E21 | Arunachal Pradesh | Low | 186 | 2697.9 | -2.6720 | True | low |
| E104 | Meghalaya | Low | 81 | 991.9 | -2.4995 | True | low |
| E159 | Uttarakhand | Low | 327 | 3658.7 | -2.4135 | True | low |
| E10 | Odisha | Low | 173 | 1676.2 | -2.2684 | True | low |
| E105 | Meghalaya | Low | 109 | 1009.3 | -2.2215 | True | low |
| E19 | Arunachal Pradesh | Low | 435 | 3536.1 | -2.0944 | True | low |
| E153 | Uttarakhand | Low | 233 | 1832.7 | -2.0606 | True | low |
| E69 | Jharkhand | Low | 536 | 4151.3 | -2.0462 | True | low |
| E70 | Jharkhand | Low | 951 | 7149.4 | -2.0168 | True | low |
| E106 | Mizoram | Low | 124 | 872.4 | -1.9476 | True | low |
| E103 | Meghalaya | Low | 170 | 1180.2 | -1.9351 | True | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 13938 | 2030.6 | 1.9261 | False | high |
| E05 | Maharashtra | High | 4504 | 1070.1 | 1.4368 | False | high |
| E01 | Kerala | Middle | 34918 | 8313.0 | 1.4351 | False | high |
| E94 | Maharashtra | High | 39317 | 9549.8 | 1.4151 | False | high |
| E92 | Maharashtra | High | 11788 | 3289.5 | 1.2762 | False | high |
| E134 | Tamil Nadu | Middle | 3361 | 1217.3 | 1.0154 | False | high |
| E91 | Maharashtra | High | 7701 | 2948.2 | 0.9601 | False | high |
| E95 | Maharashtra | High | 19382 | 7505.6 | 0.9487 | False | high |
| E133 | Tamil Nadu | Middle | 3065 | 1272.1 | 0.8792 | False | high |
| E148 | Uttar Pradesh | Low | 11906 | 5476.7 | 0.7765 | False | high |
| E140 | Uttar Pradesh | Low | 3681 | 1717.1 | 0.7624 | False | high |
| E98 | Maharashtra | High | 2766 | 1375.9 | 0.6981 | False | high |
| E97 | Maharashtra | High | 20891 | 10711.1 | 0.6680 | False | high |
| E130 | Tamil Nadu | Middle | 5189 | 2725.9 | 0.6436 | False | high |
| E73 | Karnataka | High | 8391 | 4562.9 | 0.6092 | False | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -6.8728 | -6.8728 | 2 |
| Arunachal Pradesh | Low | -2.4735 | -2.3832 | 4 |
| Meghalaya | Low | -2.1230 | -2.0783 | 4 |
| Mizoram | Low | -1.9476 | -1.9476 | 1 |
| Jharkhand | Low | -1.8251 | -2.0168 | 3 |
| Nagaland | Low | -1.3862 | -1.3862 | 2 |
| Odisha | Low | -1.1396 | -1.2351 | 5 |
| Tripura | Low | -0.9824 | -1.2795 | 4 |
| Uttarakhand | Low | -0.9138 | -0.8747 | 11 |
| Chhattisgarh | Low | -0.8332 | -0.8249 | 3 |
| Haryana | High | -0.8247 | -0.8247 | 2 |
| Telangana | High | -0.7907 | -0.7907 | 2 |
| Assam | Low | -0.7591 | -0.5610 | 7 |
| Goa | High | -0.7424 | -0.7424 | 2 |
| Rajasthan | Low | -0.5967 | -0.9397 | 3 |
| Manipur | Low | -0.4132 | -0.4132 | 1 |
| Himachal Pradesh | Low | -0.3841 | -0.3244 | 9 |
| West Bengal | Middle | -0.3606 | -0.3949 | 6 |
| Bihar | Low | -0.2995 | -0.2736 | 6 |
| Gujarat | High | -0.2109 | -0.2022 | 8 |
| Madhya Pradesh | Low | -0.1607 | -0.3186 | 6 |
| Andhra Pradesh | Middle | -0.0645 | 0.2428 | 5 |
| Punjab | Middle | 0.1164 | -0.4110 | 4 |
| Kerala | Middle | 0.2811 | 0.1825 | 5 |
| Uttar Pradesh | Low | 0.2871 | 0.3418 | 11 |
| Karnataka | High | 0.3514 | 0.5298 | 6 |
| Tamil Nadu | Middle | 0.5280 | 0.5055 | 6 |
| Delhi | High | 0.5348 | 0.5348 | 1 |
| Jammu and Kashmir | Low | 0.5398 | 0.5398 | 1 |
| Maharashtra | High | 0.9653 | 0.9544 | 8 |

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
