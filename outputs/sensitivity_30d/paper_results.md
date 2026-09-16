# Coverage disparity results

N = 1191 district-event observations; 429 districts; 160 parent events; 63 source floods.
Excluded: 362 of 1553 registry rows.
Spearman rho = 0.1583764044; p = 3.91e-08.

Primary model: log E[article_count] = intercept + beta_flood log(1 + flood_area_km2) + beta_urban urban_population_share. NB2 variance = mu + alpha * mu²; alpha is estimated.

M1/M2/M3 use the same complete-case sample. Fixed decision rule: positive coefficient and two-sided p < 0.05; prefer state-clustered inference when the prespecified cluster rule is met. No cutoff on urbanization enters the model.

| Model / SE | Term | Coefficient (SE) | 95% CI | p | IRR [95% CI] | 10pp IRR [95% CI] |
| --- | --- | --- | --- | --- | --- | --- |
| model_1 / ordinary | Intercept | 4.1606 (0.1208) | [3.9240, 4.3973] | 3.915e-260 | 64.113 [50.600, 81.233] | — |
| model_1 / ordinary | log_flood_area | -0.0747 (0.0263) | [-0.1262, -0.0232] | 0.004484 | 0.928 [0.881, 0.977] | — |
| model_1 / state_clustered | Intercept | 4.1606 (0.4639) | [3.2119, 5.1094] | 7.33e-10 | 64.113 [24.827, 165.566] | — |
| model_1 / state_clustered | log_flood_area | -0.0747 (0.0929) | [-0.2646, 0.1153] | 0.428 | 0.928 [0.767, 1.122] | — |
| model_2 / ordinary | Intercept | 3.4611 (0.1574) | [3.1526, 3.7696] | 3.593e-107 | 31.852 [23.397, 43.362] | — |
| model_2 / ordinary | log_flood_area | 0.0062 (0.0292) | [-0.0510, 0.0633] | 0.8319 | 1.006 [0.950, 1.065] | — |
| model_2 / ordinary | urban_population_share | 1.4155 (0.2456) | [0.9341, 1.8970] | 8.275e-09 | 4.119 [2.545, 6.666] | 1.152 [1.098, 1.209] |
| model_2 / state_clustered | Intercept | 3.4611 (0.6112) | [2.2110, 4.7112] | 4.034e-06 | 31.852 [9.125, 111.183] | — |
| model_2 / state_clustered | log_flood_area | 0.0062 (0.1126) | [-0.2240, 0.2364] | 0.9565 | 1.006 [0.799, 1.267] | — |
| model_2 / state_clustered | urban_population_share | 1.4155 (0.4667) | [0.4611, 2.3700] | 0.005061 | 4.119 [1.586, 10.697] | 1.152 [1.047, 1.267] |
| model_3 / ordinary | Intercept | 3.6867 (0.2805) | [3.1369, 4.2365] | 1.874e-39 | 39.913 [23.033, 69.166] | — |
| model_3 / ordinary | C(year)[T.2016] | 0.0057 (0.3575) | [-0.6950, 0.7064] | 0.9872 | 1.006 [0.499, 2.027] | — |
| model_3 / ordinary | C(year)[T.2017] | -0.0335 (0.2860) | [-0.5940, 0.5271] | 0.9068 | 0.967 [0.552, 1.694] | — |
| model_3 / ordinary | C(year)[T.2018] | 0.1014 (0.2781) | [-0.4438, 0.6465] | 0.7155 | 1.107 [0.642, 1.909] | — |
| model_3 / ordinary | C(year)[T.2019] | 0.0137 (0.2639) | [-0.5035, 0.5309] | 0.9587 | 1.014 [0.604, 1.700] | — |
| model_3 / ordinary | C(year)[T.2020] | -1.4549 (0.2737) | [-1.9915, -0.9184] | 1.067e-07 | 0.233 [0.136, 0.399] | — |
| model_3 / ordinary | C(year)[T.2021] | -1.2739 (0.2816) | [-1.8257, -0.7220] | 6.069e-06 | 0.280 [0.161, 0.486] | — |
| model_3 / ordinary | C(year)[T.2022] | -0.4086 (0.3426) | [-1.0801, 0.2630] | 0.2331 | 0.665 [0.340, 1.301] | — |
| model_3 / ordinary | C(year)[T.2023] | -0.1880 (0.2938) | [-0.7638, 0.3878] | 0.5222 | 0.829 [0.466, 1.474] | — |
| model_3 / ordinary | C(year)[T.2024] | -0.4802 (0.2996) | [-1.0674, 0.1070] | 0.1089 | 0.619 [0.344, 1.113] | — |
| model_3 / ordinary | C(year)[T.2025] | 0.2420 (0.3163) | [-0.3779, 0.8620] | 0.4442 | 1.274 [0.685, 2.368] | — |
| model_3 / ordinary | log_flood_area | 0.0085 (0.0320) | [-0.0542, 0.0712] | 0.7906 | 1.009 [0.947, 1.074] | — |
| model_3 / ordinary | urban_population_share | 1.4038 (0.2499) | [0.9140, 1.8936] | 1.936e-08 | 4.071 [2.494, 6.643] | 1.151 [1.096, 1.208] |
| model_3 / state_clustered | Intercept | 3.6867 (0.5636) | [2.5339, 4.8395] | 3.655e-07 | 39.913 [12.603, 126.406] | — |
| model_3 / state_clustered | C(year)[T.2016] | 0.0057 (0.5511) | [-1.1214, 1.1328] | 0.9918 | 1.006 [0.326, 3.104] | — |
| model_3 / state_clustered | C(year)[T.2017] | -0.0335 (0.4063) | [-0.8644, 0.7974] | 0.9349 | 0.967 [0.421, 2.220] | — |
| model_3 / state_clustered | C(year)[T.2018] | 0.1014 (0.8235) | [-1.5830, 1.7857] | 0.9029 | 1.107 [0.205, 5.964] | — |
| model_3 / state_clustered | C(year)[T.2019] | 0.0137 (0.4824) | [-0.9730, 1.0003] | 0.9776 | 1.014 [0.378, 2.719] | — |
| model_3 / state_clustered | C(year)[T.2020] | -1.4549 (0.8357) | [-3.1641, 0.2542] | 0.09228 | 0.233 [0.042, 1.289] | — |
| model_3 / state_clustered | C(year)[T.2021] | -1.2739 (0.5922) | [-2.4851, -0.0626] | 0.03995 | 0.280 [0.083, 0.939] | — |
| model_3 / state_clustered | C(year)[T.2022] | -0.4086 (0.6082) | [-1.6524, 0.8353] | 0.507 | 0.665 [0.192, 2.305] | — |
| model_3 / state_clustered | C(year)[T.2023] | -0.1880 (0.5076) | [-1.2263, 0.8502] | 0.7138 | 0.829 [0.293, 2.340] | — |
| model_3 / state_clustered | C(year)[T.2024] | -0.4802 (0.5015) | [-1.5059, 0.5454] | 0.3462 | 0.619 [0.222, 1.725] | — |
| model_3 / state_clustered | C(year)[T.2025] | 0.2420 (0.6157) | [-1.0173, 1.5013] | 0.6971 | 1.274 [0.362, 4.488] | — |
| model_3 / state_clustered | log_flood_area | 0.0085 (0.0774) | [-0.1497, 0.1667] | 0.9134 | 1.009 [0.861, 1.181] | — |
| model_3 / state_clustered | urban_population_share | 1.4038 (0.4688) | [0.4450, 2.3626] | 0.005574 | 4.071 [1.561, 10.618] | 1.151 [1.046, 1.266] |
| model_2_by_source_S1 / ordinary | Intercept | 3.4611 (0.1574) | [3.1526, 3.7696] | 3.593e-107 | 31.852 [23.397, 43.362] | — |
| model_2_by_source_S1 / ordinary | log_flood_area | 0.0062 (0.0292) | [-0.0510, 0.0633] | 0.8319 | 1.006 [0.950, 1.065] | — |
| model_2_by_source_S1 / ordinary | urban_population_share | 1.4155 (0.2456) | [0.9341, 1.8970] | 8.275e-09 | 4.119 [2.545, 6.666] | 1.152 [1.098, 1.209] |
| model_2_by_source_S1 / state_clustered | Intercept | 3.4611 (0.6112) | [2.2110, 4.7112] | 4.034e-06 | 31.852 [9.125, 111.183] | — |
| model_2_by_source_S1 / state_clustered | log_flood_area | 0.0062 (0.1126) | [-0.2240, 0.2364] | 0.9565 | 1.006 [0.799, 1.267] | — |
| model_2_by_source_S1 / state_clustered | urban_population_share | 1.4155 (0.4667) | [0.4611, 2.3700] | 0.005061 | 4.119 [1.586, 10.697] | 1.152 [1.047, 1.267] |
| source_event_robustness / ordinary | Intercept | 3.9999 (0.8102) | [2.4119, 5.5880] | 7.945e-07 | 54.594 [11.155, 267.190] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0317-IND] | -1.6466 (0.8560) | [-3.3243, 0.0310] | 0.05439 | 0.193 [0.036, 1.032] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0333-IND] | -2.7088 (1.4055) | [-5.4636, 0.0460] | 0.05395 | 0.067 [0.004, 1.047] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0374-IND] | -0.6517 (0.9450) | [-2.5039, 1.2005] | 0.4904 | 0.521 [0.082, 3.322] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0406-IND] | -1.0693 (0.8966) | [-2.8266, 0.6880] | 0.233 | 0.343 [0.059, 1.990] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0504-IND] | 1.3746 (0.9749) | [-0.5363, 3.2855] | 0.1586 | 3.954 [0.585, 26.721] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0139-IND] | -2.1846 (1.0040) | [-4.1523, -0.2168] | 0.02956 | 0.113 [0.016, 0.805] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0239-IND] | -0.0297 (0.9118) | [-1.8167, 1.7573] | 0.974 | 0.971 [0.163, 5.797] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0267-IND] | -0.1586 (0.9458) | [-2.0124, 1.6951] | 0.8668 | 0.853 [0.134, 5.447] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0271-IND] | -1.7932 (0.9090) | [-3.5748, -0.0116] | 0.04853 | 0.166 [0.028, 0.988] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0554-IND] | 0.2904 (1.3732) | [-2.4011, 2.9819] | 0.8325 | 1.337 [0.091, 19.726] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0180-IND] | -2.2191 (0.8518) | [-3.8887, -0.5495] | 0.009187 | 0.109 [0.020, 0.577] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0289-IND] | -0.0686 (0.8697) | [-1.7732, 1.6361] | 0.9372 | 0.934 [0.170, 5.135] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0290-IND] | -1.8781 (1.1279) | [-4.0888, 0.3326] | 0.0959 | 0.153 [0.017, 1.395] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0294-IND] | -5.4350 (1.0777) | [-7.5473, -3.3228] | 4.576e-07 | 0.004 [0.001, 0.036] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0342-IND] | -0.2889 (0.8432) | [-1.9417, 1.3638] | 0.7319 | 0.749 [0.143, 3.911] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0364-IND] | 0.7534 (1.2184) | [-1.6347, 3.1414] | 0.5364 | 2.124 [0.195, 23.137] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0517-IND] | -1.5220 (0.8655) | [-3.2184, 0.1744] | 0.07866 | 0.218 [0.040, 1.190] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0205-IND] | -0.9182 (0.9797) | [-2.8383, 1.0019] | 0.3486 | 0.399 [0.059, 2.723] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0213-IND] | -2.0598 (1.1323) | [-4.2791, 0.1594] | 0.06888 | 0.127 [0.014, 1.173] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0216-IND] | -0.2574 (1.3691) | [-2.9409, 2.4261] | 0.8509 | 0.773 [0.053, 11.315] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0286-IND] | -2.0595 (1.1354) | [-4.2849, 0.1659] | 0.06971 | 0.128 [0.014, 1.180] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0295-IND] | 0.2354 (0.8144) | [-1.3609, 1.8316] | 0.7726 | 1.265 [0.256, 6.244] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0345-IND] | -1.9420 (0.9652) | [-3.8337, -0.0503] | 0.04421 | 0.143 [0.022, 0.951] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0370-IND] | -2.8162 (0.8735) | [-4.5282, -1.1043] | 0.001263 | 0.060 [0.011, 0.331] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0372-IND] | -3.4304 (0.9713) | [-5.3341, -1.5267] | 0.0004128 | 0.032 [0.005, 0.217] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0288-IND] | 0.6582 (1.2135) | [-1.7204, 3.0367] | 0.5876 | 1.931 [0.179, 20.836] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0331-IND] | -0.5543 (0.8086) | [-2.1391, 1.0306] | 0.4931 | 0.575 [0.118, 2.803] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0383-IND] | 0.0648 (0.8738) | [-1.6478, 1.7773] | 0.9409 | 1.067 [0.192, 5.914] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0499-IND] | -2.1719 (0.9206) | [-3.9763, -0.3675] | 0.01831 | 0.114 [0.019, 0.692] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0574-IND] | -2.7212 (1.0342) | [-4.7482, -0.6941] | 0.008511 | 0.066 [0.009, 0.500] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0206-IND] | -0.9252 (1.0735) | [-3.0293, 1.1789] | 0.3888 | 0.396 [0.048, 3.251] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0304-IND] | -2.2909 (0.8129) | [-3.8842, -0.6976] | 0.004832 | 0.101 [0.021, 0.498] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0446-IND] | -1.1954 (0.8655) | [-2.8918, 0.5010] | 0.1672 | 0.303 [0.055, 1.650] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0316-IND] | -3.3546 (0.8390) | [-4.9991, -1.7101] | 6.384e-05 | 0.035 [0.007, 0.181] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0366-IND] | -3.6970 (1.1743) | [-5.9986, -1.3954] | 0.001642 | 0.025 [0.002, 0.248] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0435-IND] | -6.9916 (1.1171) | [-9.1810, -4.8021] | 3.882e-10 | 0.001 [0.000, 0.008] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0458-IND] | -1.4767 (1.0734) | [-3.5805, 0.6271] | 0.1689 | 0.228 [0.028, 1.872] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0585-IND] | -2.1566 (1.0736) | [-4.2608, -0.0523] | 0.04457 | 0.116 [0.014, 0.949] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0677-IND] | 0.3905 (1.0270) | [-1.6224, 2.4033] | 0.7038 | 1.478 [0.197, 11.059] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0722-IND] | -1.7692 (0.8509) | [-3.4370, -0.1015] | 0.03759 | 0.170 [0.032, 0.903] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0748-IND] | -0.0726 (1.1266) | [-2.2807, 2.1356] | 0.9487 | 0.930 [0.102, 8.462] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0293-IND] | -0.9443 (0.8368) | [-2.5845, 0.6959] | 0.2591 | 0.389 [0.075, 2.005] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0539-IND] | -0.9899 (0.9595) | [-2.8705, 0.8906] | 0.3022 | 0.372 [0.057, 2.437] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0590-IND] | -4.0952 (1.4862) | [-7.0080, -1.1823] | 0.00586 | 0.017 [0.001, 0.307] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0330-IND] | 0.4155 (1.0738) | [-1.6892, 2.5202] | 0.6988 | 1.515 [0.185, 12.432] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0359-IND] | -0.3660 (0.8534) | [-2.0387, 1.3066] | 0.668 | 0.693 [0.130, 3.694] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0428-IND] | -1.4647 (0.8221) | [-3.0761, 0.1466] | 0.07481 | 0.231 [0.046, 1.158] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0486-IND] | -1.3104 (1.0726) | [-3.4127, 0.7920] | 0.2218 | 0.270 [0.033, 2.208] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0846-IND] | 0.8961 (1.2109) | [-1.4772, 3.2694] | 0.4593 | 2.450 [0.228, 26.295] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0399-IND] | -2.8318 (0.8889) | [-4.5740, -1.0896] | 0.001444 | 0.059 [0.010, 0.336] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0481-IND] | -1.0302 (0.8361) | [-2.6689, 0.6084] | 0.2179 | 0.357 [0.069, 1.838] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0561-IND] | 1.0432 (1.2168) | [-1.3418, 3.4282] | 0.3913 | 2.838 [0.261, 30.820] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0624-IND] | -1.0398 (1.1266) | [-3.2479, 1.1683] | 0.356 | 0.354 [0.039, 3.216] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0647-IND] | -1.2268 (0.8677) | [-2.9274, 0.4739] | 0.1574 | 0.293 [0.054, 1.606] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0402-IND] | -1.0657 (0.8668) | [-2.7647, 0.6333] | 0.2189 | 0.344 [0.063, 1.884] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0469-IND] | -0.0931 (0.9771) | [-2.0082, 1.8220] | 0.9241 | 0.911 [0.134, 6.184] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0751-IND] | 0.7314 (0.9439) | [-1.1186, 2.5814] | 0.4384 | 2.078 [0.327, 13.216] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0803-IND] | -1.9465 (0.9561) | [-3.8204, -0.0727] | 0.04175 | 0.143 [0.022, 0.930] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0859-IND] | -1.9579 (0.8759) | [-3.6746, -0.2412] | 0.02539 | 0.141 [0.025, 0.786] | — |
| source_event_robustness / ordinary | log_flood_area | 0.0823 (0.0349) | [0.0139, 0.1508] | 0.01837 | 1.086 [1.014, 1.163] | — |
| source_event_robustness / ordinary | urban_population_share | 0.9382 (0.2859) | [0.3780, 1.4985] | 0.00103 | 2.555 [1.459, 4.475] | 1.098 [1.039, 1.162] |

Flood IRR is per one-unit increase in log(1 + km²); the urbanization IRR is per 0→1 change, with 10 percentage points reported separately.

## Model availability

- model_1: estimated
- model_2: estimated
- model_3: estimated
- model_2_source_fe: insufficient source variation: fewer than two satellite sources
- model_2_by_source_S1: estimated (sensitivity)
- source_event_robustness: estimated secondary unconditional source fixed-effects NB2; 60 source events
- exposed_population_robustness: not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used

## Descriptive distributions and missingness

```json
{
  "distributions": {
    "flood_area_km2": {
      "count": 1191.0,
      "mean": 190.2800441646,
      "std": 371.891609504,
      "min": 0.0147,
      "25%": 15.9473,
      "50%": 71.6197,
      "75%": 225.1028,
      "max": 5894.8599
    },
    "article_count": {
      "count": 1191.0,
      "mean": 47.8354324097,
      "std": 143.7357979678,
      "min": 0.0,
      "25%": 1.0,
      "50%": 7.0,
      "75%": 46.0,
      "max": 3291.0
    },
    "urban_population_share": {
      "count": 1191.0,
      "mean": 0.2223676109,
      "std": 0.1962573875,
      "min": 0.0,
      "25%": 0.0876401087,
      "50%": 0.1486321135,
      "75%": 0.2882068663,
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
      "count": 1344.0,
      "mean": 47.5959821429,
      "std": 139.1341152416,
      "min": 0.0,
      "25%": 1.0,
      "50%": 8.0,
      "75%": 45.0,
      "max": 3291.0
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
    "article_count": 209,
    "urban_population_share": 124
  },
  "exclusion_counts": {
    "article_collection_incomplete": 209,
    "article_count_missing_or_invalid": 209,
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
      "success": 1344,
      "total": 1553,
      "rate": 0.8654217643
    },
    "article_complete": {
      "success": 18,
      "total": 1553,
      "rate": 0.0115904701
    },
    "article_partial_lower_bound": {
      "success": 1326,
      "total": 1553,
      "rate": 0.8538312943
    },
    "final_analyzable": {
      "success": 1191,
      "total": 1553,
      "rate": 0.7669027688
    },
    "satellite_source_counts": {
      "S1": 1191
    }
  },
  "estimated_dispersion": {
    "model_1": 3.6074843251,
    "model_2": 3.5132867539,
    "model_3": 3.2714220675
  },
  "article_count_variance": 20659.9796174389,
  "article_count_mean": 47.8354324097
}
```

## Selection check

```
urbanization_group  rows  excluded  exclusion_rate
              high   387        44        0.113695
               low   660       116        0.175758
            medium   382        78        0.204188
           unknown   124       124        1.000000
```

## Conclusion candidate

H1 is not supported. Higher urbanization is associated with greater expected coverage at similar observed flood extent; this supports H2 alone.

These results describe associations at similar observed flood extent; they do not establish intent or causation.

## Data-quality warnings

- Associational analysis: flood extent does not control all disaster impacts, outlet availability, population size, or media access.
- Census 2011 and GAUL 2015 may not represent event-year district boundaries or urbanization.
- GDELT-indexed district-explicit coverage is not all disaster reporting; location extraction and language coverage can affect selection.
- District rows within a source flood and repeated districts may be dependent; state clustering is only a partial correction.
- 244 registry onset dates are month-imputed; their 14-day news windows have timing uncertainty.
- Article counts use the local state corpus plus targeted BigQuery supplementation of districts without usable local candidates. This is conditional corpus coverage, not exhaustive district recollection; districts with some local coverage may still have missed articles.
- 1326 article counts are observed LLM-QA lower bounds: validated relevant decisions are counted, while unavailable-body, uncertain and unsubmitted candidates remain unresolved and are not imputed as zero.
- Flood area is Sentinel-1 new water over the eligible AOI for every district under the interim routing (satellite_source S1), or, under sits_primary routing, SITS-NDWI on the retained clear tiles with Sentinel-1 converted to the SITS-NDWI scale (S1_TO_SITS) where SITS cannot measure the district; the satellite-source fixed effect, by-source and SITS-only subsamples are sensitivity analyses, not a correction.
- Source fixed-effects NB2 is secondary and susceptible to incidental-parameter bias; ordinary SE are reported.
- district-based urbanization tercile cutpoints: [0.1369414084546159, 0.2557930624760398]; unknown Census matches cannot be assigned an urbanization level
