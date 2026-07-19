# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-19 22:46:08`

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
| NegBin AIC | 2564.8 |
| NegBin log-likelihood | -1267.4 |
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
Model:              GLM              AIC:            2564.7749
Link Function:      Log              BIC:            -448.9895
Dependent Variable: n_articles_0_14  Log-Likelihood: -1267.4  
Date:               2026-07-19 22:46 LL-Null:        -1312.4  
No. Observations:   138              Deviance:       157.06   
Df Model:           14               Pearson chi2:   148.     
Df Residuals:       123              Scale:          1.0000   
Method:             IRLS                                      
--------------------------------------------------------------
                 Coef.  Std.Err.    z    P>|z|   [0.025 0.975]
--------------------------------------------------------------
const            5.4085   0.6747  8.0159 0.0000  4.0860 6.7309
log1p_severity   0.0875   0.0404  2.1658 0.0303  0.0083 0.1667
log1p_deaths     0.3347   0.0708  4.7265 0.0000  0.1959 0.4736
deaths_missing   1.2785   0.4279  2.9878 0.0028  0.4398 2.1172
monsoon_flag     0.2428   0.2890  0.8402 0.4008 -0.3236 0.8093
year_2016        1.3255   0.5924  2.2376 0.0252  0.1645 2.4866
year_2017        0.7379   0.3777  1.9534 0.0508 -0.0025 1.4782
year_2018        0.4153   0.4873  0.8523 0.3940 -0.5398 1.3705
year_2019        0.3752   0.5461  0.6870 0.4921 -0.6952 1.4456
year_2020       -0.3716   0.5174 -0.7183 0.4726 -1.3856 0.6424
year_2021        0.0355   0.4712  0.0754 0.9399 -0.8880 0.9591
year_2022       -0.5488   0.5254 -1.0446 0.2962 -1.5786 0.4809
year_2023        0.4917   0.4667  1.0535 0.2921 -0.4231 1.4065
year_2024        0.0717   0.4820  0.1487 0.8818 -0.8730 1.0164
year_2025       -0.3856   0.5664 -0.6807 0.4960 -1.4956 0.7245
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | 0.1166 | 0.2985 | 0.8110 | 29 |
| Middle | 0.0977 | 0.0613 | 0.7024 | 26 |
| Low | -0.8989 | -0.5828 | 1.3681 | 83 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -1.0154 | [-1.7857, -0.2451] | 0.0098 | False |
| Middle | -0.0189 | [-0.6745, 0.6368] | 0.9550 | True |

**Verdict:** Detectable income gradient in this GDELT-monitored system (at least one CI excludes 0).  
R² = 0.1539

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E126 | Sikkim | Low | 2 | 4232.3 | -7.4343 | True | low |
| E127 | Sikkim | Low | 2 | 1498.3 | -6.3961 | True | low |
| E18 | Arunachal Pradesh | Low | 33 | 1114.6 | -3.5052 | True | low |
| E28 | Assam | Low | 120 | 2542.0 | -3.0493 | True | low |
| E21 | Arunachal Pradesh | Low | 186 | 2925.3 | -2.7529 | True | low |
| E159 | Uttarakhand | Low | 327 | 3977.3 | -2.4970 | True | low |
| E104 | Meghalaya | Low | 81 | 971.7 | -2.4790 | True | low |
| E10 | Odisha | Low | 173 | 1834.2 | -2.3585 | True | low |
| E105 | Meghalaya | Low | 109 | 1001.5 | -2.2139 | True | low |
| E153 | Uttarakhand | Low | 233 | 1852.8 | -2.0715 | True | low |
| E19 | Arunachal Pradesh | Low | 435 | 3406.0 | -2.0570 | True | low |
| E70 | Jharkhand | Low | 951 | 7378.3 | -2.0483 | True | low |
| E106 | Mizoram | Low | 124 | 862.8 | -1.9364 | True | low |
| E102 | Meghalaya | Low | 340 | 2350.1 | -1.9320 | True | low |
| E103 | Meghalaya | Low | 170 | 1165.6 | -1.9227 | True | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 13938 | 2045.1 | 1.9190 | False | high |
| E05 | Maharashtra | High | 4504 | 1059.3 | 1.4470 | False | high |
| E01 | Kerala | Middle | 34918 | 8455.6 | 1.4181 | False | high |
| E94 | Maharashtra | High | 39317 | 10082.8 | 1.3608 | False | high |
| E92 | Maharashtra | High | 11788 | 3246.6 | 1.2894 | False | high |
| E95 | Maharashtra | High | 19382 | 5949.4 | 1.1810 | False | high |
| E134 | Tamil Nadu | Middle | 3361 | 1263.1 | 0.9784 | False | high |
| E91 | Maharashtra | High | 7701 | 2913.4 | 0.9719 | False | high |
| E86 | Madhya Pradesh | Low | 8173 | 3234.1 | 0.9270 | False | high |
| E133 | Tamil Nadu | Middle | 3065 | 1242.2 | 0.9029 | False | high |
| E42 | Delhi | High | 33940 | 15453.2 | 0.7868 | False | high |
| E140 | Uttar Pradesh | Low | 3681 | 1736.4 | 0.7512 | False | high |
| E98 | Maharashtra | High | 2766 | 1358.2 | 0.7111 | False | high |
| E148 | Uttar Pradesh | Low | 11906 | 6049.3 | 0.6771 | False | high |
| E130 | Tamil Nadu | Middle | 5189 | 2697.4 | 0.6542 | False | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -6.9152 | -6.9152 | 2 |
| Arunachal Pradesh | Low | -2.4764 | -2.4049 | 4 |
| Meghalaya | Low | -2.1369 | -2.0729 | 4 |
| Mizoram | Low | -1.9364 | -1.9364 | 1 |
| Jharkhand | Low | -1.6562 | -1.4876 | 3 |
| Nagaland | Low | -1.4379 | -1.4379 | 2 |
| Odisha | Low | -1.1907 | -1.3257 | 5 |
| Tripura | Low | -0.9681 | -1.2660 | 4 |
| Uttarakhand | Low | -0.9480 | -0.8791 | 11 |
| Chhattisgarh | Low | -0.8970 | -0.9305 | 3 |
| Haryana | High | -0.8587 | -0.8587 | 2 |
| Telangana | High | -0.8497 | -0.8497 | 2 |
| Assam | Low | -0.7654 | -0.4182 | 7 |
| Goa | High | -0.7566 | -0.7566 | 2 |
| Rajasthan | Low | -0.6175 | -0.9196 | 3 |
| Himachal Pradesh | Low | -0.4159 | -0.4217 | 9 |
| Manipur | Low | -0.4103 | -0.4103 | 1 |
| West Bengal | Middle | -0.3988 | -0.4635 | 6 |
| Bihar | Low | -0.3648 | -0.2750 | 6 |
| Gujarat | High | -0.2495 | -0.1967 | 8 |
| Andhra Pradesh | Middle | -0.0857 | 0.1782 | 5 |
| Madhya Pradesh | Low | 0.0485 | 0.0542 | 6 |
| Kerala | Middle | 0.2455 | 0.0801 | 5 |
| Punjab | Middle | 0.2477 | -0.1566 | 4 |
| Karnataka | High | 0.2799 | 0.4367 | 6 |
| Uttar Pradesh | Low | 0.2858 | 0.3466 | 11 |
| Jammu and Kashmir | Low | 0.5214 | 0.5214 | 1 |
| Tamil Nadu | Middle | 0.5238 | 0.5138 | 6 |
| Delhi | High | 0.7868 | 0.7868 | 1 |
| Maharashtra | High | 0.9801 | 1.0765 | 8 |

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
