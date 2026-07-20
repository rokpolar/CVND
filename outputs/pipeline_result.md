# CVND Pipeline Results — Expected Coverage

Generated: `2026-07-20 01:07:38`

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
| Deaths missing (metadata) | 24 / 138 |
| N events | 138 |
| NegBin AIC | 2573.3 |
| NegBin log-likelihood | -1273.6 |
| under_flag (log_ratio &lt; 0) | 81 (58.7%) |
| over_flag (log_ratio &gt; 0) | 57 (41.3%) |
| severity_tier | Tertiles (low ≤ P33, high ≥ P67; exploratory only) |

## Absolute under-coverage (`under_flag`)

| income_group | n_under | n | share |
| --- | --- | --- | --- |
| High | 12 | 29 | 41.4% |
| Middle | 13 | 26 | 50.0% |
| Low | 56 | 83 | 67.5% |

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
Model:              GLM              AIC:            2573.2640
Link Function:      Log              BIC:            -457.6638
Dependent Variable: n_articles_0_14  Log-Likelihood: -1273.6  
Date:               2026-07-20 01:07 LL-Null:        -1309.5  
No. Observations:   138              Deviance:       158.24   
Df Model:           12               Pearson chi2:   156.     
Df Residuals:       125              Scale:          1.0000   
Method:             IRLS                                      
--------------------------------------------------------------
                 Coef.  Std.Err.    z    P>|z|   [0.025 0.975]
--------------------------------------------------------------
const            6.6098   0.5219 12.6643 0.0000  5.5869 7.6328
log1p_severity   0.0796   0.0447  1.7783 0.0754 -0.0081 0.1673
log1p_deaths     0.1646   0.0276  5.9707 0.0000  0.1106 0.2187
year_2016        1.6957   0.5503  3.0814 0.0021  0.6171 2.7742
year_2017        0.6984   0.3684  1.8956 0.0580 -0.0237 1.4205
year_2018        0.4404   0.5128  0.8588 0.3904 -0.5646 1.4454
year_2019        0.6943   0.5622  1.2350 0.2168 -0.4076 1.7962
year_2020       -0.0790   0.5419 -0.1457 0.8842 -1.1411 0.9832
year_2021        0.0578   0.5175  0.1116 0.9111 -0.9565 1.0721
year_2022       -0.3449   0.4836 -0.7131 0.4758 -1.2926 0.6029
year_2023        0.6738   0.4602  1.4643 0.1431 -0.2281 1.5757
year_2024       -0.1667   0.4866 -0.3426 0.7319 -1.1205 0.7871
year_2025       -0.5911   0.5994 -0.9861 0.3241 -1.7659 0.5837
==============================================================

```

## log_ratio by income group

| income_group | mean | median | std | n |
| --- | --- | --- | --- | --- |
| High | 0.0456 | 0.3012 | 0.9622 | 29 |
| Middle | -0.0107 | 0.0047 | 0.6474 | 26 |
| Low | -0.9083 | -0.6663 | 1.4304 | 83 |

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
| Low | -0.9538 | [-1.7954, -0.1123] | 0.0263 | False |
| Middle | -0.0562 | [-0.7038, 0.5913] | 0.8648 | True |

**Verdict:** Detectable income gradient in this GDELT-monitored system (at least one CI excludes 0).  
R² = 0.1224

## Most under-covered (lowest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E126 | Sikkim | Low | 2 | 3389.4 | -7.2123 | True | low |
| E127 | Sikkim | Low | 2 | 1902.2 | -6.6348 | True | low |
| E18 | Arunachal Pradesh | Low | 33 | 1628.9 | -3.8844 | True | low |
| E19 | Arunachal Pradesh | Low | 435 | 9569.8 | -3.0899 | True | low |
| E104 | Meghalaya | Low | 81 | 1521.8 | -2.9273 | True | low |
| E21 | Arunachal Pradesh | Low | 186 | 2780.9 | -2.7023 | True | low |
| E28 | Assam | Low | 120 | 1743.4 | -2.6722 | True | low |
| E159 | Uttarakhand | Low | 327 | 3994.6 | -2.5013 | True | low |
| E105 | Meghalaya | Low | 109 | 1318.9 | -2.4890 | True | low |
| E106 | Mizoram | Low | 124 | 1151.6 | -2.2251 | True | low |
| E103 | Meghalaya | Low | 170 | 1535.6 | -2.1983 | True | low |
| E136 | Tripura | Low | 360 | 3180.1 | -2.1773 | True | low |
| E10 | Odisha | Low | 173 | 1473.8 | -2.1398 | True | low |
| E57 | Haryana | High | 746 | 5967.7 | -2.0788 | True | low |
| E102 | Meghalaya | Low | 340 | 2538.9 | -2.0093 | True | low |

## Most over-covered (highest log_ratio)

| event_id | state | income_group | observed | expected | log_ratio | under_flag | severity_tier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E120 | Punjab | Middle | 13938 | 2013.3 | 1.9346 | False | high |
| E05 | Maharashtra | High | 4504 | 786.5 | 1.7446 | False | high |
| E01 | Kerala | Middle | 34918 | 7232.1 | 1.5744 | False | high |
| E94 | Maharashtra | High | 39317 | 9428.4 | 1.4279 | False | high |
| E95 | Maharashtra | High | 19382 | 5303.0 | 1.2960 | False | high |
| E92 | Maharashtra | High | 11788 | 4150.3 | 1.0438 | False | high |
| E42 | Delhi | High | 33940 | 12627.9 | 0.9887 | False | high |
| E140 | Uttar Pradesh | Low | 3681 | 1498.8 | 0.8984 | False | high |
| E86 | Madhya Pradesh | Low | 8173 | 3394.2 | 0.8787 | False | high |
| E97 | Maharashtra | High | 20891 | 9951.6 | 0.7416 | False | high |
| E09 | Karnataka | High | 2110 | 1039.9 | 0.7073 | False | high |
| E06 | Uttarakhand | Low | 4378 | 2186.2 | 0.6943 | False | high |
| E112 | Odisha | Low | 1999 | 1001.4 | 0.6910 | False | high |
| E144 | Uttar Pradesh | Low | 16660 | 8567.8 | 0.6650 | False | high |
| E68 | Jammu and Kashmir | Low | 5095 | 2633.5 | 0.6599 | False | high |

## State-level mean log_ratio

| state | income_group | mean_log_ratio | median_log_ratio | n_events |
| --- | --- | --- | --- | --- |
| Sikkim | Low | -6.9235 | -6.9235 | 2 |
| Arunachal Pradesh | Low | -2.8918 | -2.8961 | 4 |
| Meghalaya | Low | -2.4060 | -2.3436 | 4 |
| Mizoram | Low | -2.2251 | -2.2251 | 1 |
| Jharkhand | Low | -1.8498 | -1.8534 | 3 |
| Nagaland | Low | -1.4179 | -1.4179 | 2 |
| Telangana | High | -1.4020 | -1.4020 | 2 |
| Tripura | Low | -1.2964 | -1.5608 | 4 |
| Haryana | High | -1.1839 | -1.1839 | 2 |
| Odisha | Low | -1.0158 | -1.2079 | 5 |
| Chhattisgarh | Low | -0.8791 | -0.7485 | 3 |
| Uttarakhand | Low | -0.8732 | -0.9083 | 11 |
| Assam | Low | -0.8471 | -0.6517 | 7 |
| Goa | High | -0.6800 | -0.6800 | 2 |
| Manipur | Low | -0.6663 | -0.6663 | 1 |
| Rajasthan | Low | -0.6610 | -0.9633 | 3 |
| Bihar | Low | -0.3746 | -0.5181 | 6 |
| Himachal Pradesh | Low | -0.3355 | -0.2721 | 9 |
| Gujarat | High | -0.3297 | -0.3164 | 8 |
| West Bengal | Middle | -0.3179 | -0.2336 | 6 |
| Andhra Pradesh | Middle | -0.0600 | -0.1607 | 5 |
| Tamil Nadu | Middle | 0.0172 | 0.0848 | 6 |
| Kerala | Middle | 0.1858 | 0.1273 | 5 |
| Punjab | Middle | 0.2245 | -0.0226 | 4 |
| Madhya Pradesh | Low | 0.3257 | 0.2099 | 6 |
| Karnataka | High | 0.3266 | 0.5612 | 6 |
| Uttar Pradesh | Low | 0.3637 | 0.2539 | 11 |
| Jammu and Kashmir | Low | 0.6599 | 0.6599 | 1 |
| Maharashtra | High | 0.9428 | 0.8927 | 8 |
| Delhi | High | 0.9887 | 0.9887 | 1 |

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
