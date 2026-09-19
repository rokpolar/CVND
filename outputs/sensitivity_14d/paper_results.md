# Coverage disparity results

News window: 14 days.
N = 1069 district-event observations; 400 districts; 153 parent events; 63 source floods.
Excluded: 479 of 1548 registry rows.
Spearman rho = 0.1567326285; p = 2.6e-07.

Primary model: log E[article_count] = intercept + beta_flood log(1 + flood_area_km2) + beta_urban urban_population_share. NB2 variance = mu + alpha * mu²; alpha is estimated.

M1/M2/M3 use the same complete-case sample. Fixed decision rule: positive coefficient and two-sided p < 0.05; prefer state-clustered inference when the prespecified cluster rule is met. No cutoff on urbanization enters the model.

| Model / SE | Term | Coefficient (SE) | 95% CI | p | IRR [95% CI] | 10pp IRR [95% CI] |
| --- | --- | --- | --- | --- | --- | --- |
| model_1 / ordinary | Intercept | 3.7121 (0.1426) | [3.4327, 3.9915] | 1.845e-149 | 40.940 [30.960, 54.138] | — |
| model_1 / ordinary | log_flood_area | -0.0690 (0.0311) | [-0.1299, -0.0082] | 0.02623 | 0.933 [0.878, 0.992] | — |
| model_1 / state_clustered | Intercept | 3.7121 (0.5205) | [2.6459, 4.7783] | 9.251e-08 | 40.940 [14.096, 118.905] | — |
| model_1 / state_clustered | log_flood_area | -0.0690 (0.1133) | [-0.3011, 0.1631] | 0.5474 | 0.933 [0.740, 1.177] | — |
| model_2 / ordinary | Intercept | 3.3448 (0.1966) | [2.9594, 3.7301] | 6.541e-65 | 28.354 [19.287, 41.682] | — |
| model_2 / ordinary | log_flood_area | -0.0219 (0.0357) | [-0.0918, 0.0480] | 0.5399 | 0.978 [0.912, 1.049] | — |
| model_2 / ordinary | urban_population_share | 0.7066 (0.2845) | [0.1491, 1.2642] | 0.01299 | 2.027 [1.161, 3.540] | 1.073 [1.015, 1.135] |
| model_2 / state_clustered | Intercept | 3.3448 (0.6741) | [1.9639, 4.7256] | 3.08e-05 | 28.354 [7.127, 112.801] | — |
| model_2 / state_clustered | log_flood_area | -0.0219 (0.1327) | [-0.2938, 0.2501] | 0.8704 | 0.978 [0.745, 1.284] | — |
| model_2 / state_clustered | urban_population_share | 0.7066 (0.4079) | [-0.1289, 1.5422] | 0.09422 | 2.027 [0.879, 4.675] | 1.073 [0.987, 1.167] |
| model_3 / ordinary | Intercept | 3.1198 (0.3252) | [2.4825, 3.7571] | 8.448e-22 | 22.642 [11.971, 42.825] | — |
| model_3 / ordinary | C(year)[T.2016] | 0.2698 (0.3942) | [-0.5028, 1.0424] | 0.4937 | 1.310 [0.605, 2.836] | — |
| model_3 / ordinary | C(year)[T.2017] | 0.2052 (0.3086) | [-0.3997, 0.8101] | 0.5061 | 1.228 [0.671, 2.248] | — |
| model_3 / ordinary | C(year)[T.2018] | 0.5791 (0.3151) | [-0.0384, 1.1965] | 0.06606 | 1.784 [0.962, 3.309] | — |
| model_3 / ordinary | C(year)[T.2019] | 0.2381 (0.2929) | [-0.3360, 0.8122] | 0.4163 | 1.269 [0.715, 2.253] | — |
| model_3 / ordinary | C(year)[T.2020] | -2.0175 (0.3104) | [-2.6260, -1.4091] | 8.066e-11 | 0.133 [0.072, 0.244] | — |
| model_3 / ordinary | C(year)[T.2021] | -0.5667 (0.3218) | [-1.1975, 0.0640] | 0.07823 | 0.567 [0.302, 1.066] | — |
| model_3 / ordinary | C(year)[T.2022] | 0.1656 (0.3862) | [-0.5913, 0.9225] | 0.6681 | 1.180 [0.554, 2.516] | — |
| model_3 / ordinary | C(year)[T.2023] | -0.2593 (0.3255) | [-0.8972, 0.3786] | 0.4256 | 0.772 [0.408, 1.460] | — |
| model_3 / ordinary | C(year)[T.2024] | 0.1514 (0.3301) | [-0.4955, 0.7983] | 0.6465 | 1.163 [0.609, 2.222] | — |
| model_3 / ordinary | C(year)[T.2025] | 0.2295 (0.3500) | [-0.4565, 0.9154] | 0.512 | 1.258 [0.634, 2.498] | — |
| model_3 / ordinary | log_flood_area | 0.0085 (0.0388) | [-0.0675, 0.0846] | 0.8261 | 1.009 [0.935, 1.088] | — |
| model_3 / ordinary | urban_population_share | 0.9327 (0.2806) | [0.3828, 1.4826] | 0.0008872 | 2.541 [1.466, 4.405] | 1.098 [1.039, 1.160] |
| model_3 / state_clustered | Intercept | 3.1198 (0.5179) | [2.0590, 4.1806] | 1.713e-06 | 22.642 [7.838, 65.403] | — |
| model_3 / state_clustered | C(year)[T.2016] | 0.2698 (0.4363) | [-0.6240, 1.1636] | 0.5414 | 1.310 [0.536, 3.201] | — |
| model_3 / state_clustered | C(year)[T.2017] | 0.2052 (0.3950) | [-0.6038, 1.0143] | 0.6074 | 1.228 [0.547, 2.757] | — |
| model_3 / state_clustered | C(year)[T.2018] | 0.5791 (0.8283) | [-1.1177, 2.2758] | 0.4903 | 1.784 [0.327, 9.736] | — |
| model_3 / state_clustered | C(year)[T.2019] | 0.2381 (0.3689) | [-0.5176, 0.9938] | 0.5239 | 1.269 [0.596, 2.701] | — |
| model_3 / state_clustered | C(year)[T.2020] | -2.0175 (0.5228) | [-3.0885, -0.9466] | 0.0006126 | 0.133 [0.046, 0.388] | — |
| model_3 / state_clustered | C(year)[T.2021] | -0.5667 (0.5378) | [-1.6683, 0.5348] | 0.301 | 0.567 [0.189, 1.707] | — |
| model_3 / state_clustered | C(year)[T.2022] | 0.1656 (0.4208) | [-0.6964, 1.0275] | 0.6969 | 1.180 [0.498, 2.794] | — |
| model_3 / state_clustered | C(year)[T.2023] | -0.2593 (0.5119) | [-1.3079, 0.7894] | 0.6165 | 0.772 [0.270, 2.202] | — |
| model_3 / state_clustered | C(year)[T.2024] | 0.1514 (0.3708) | [-0.6083, 0.9110] | 0.6862 | 1.163 [0.544, 2.487] | — |
| model_3 / state_clustered | C(year)[T.2025] | 0.2295 (0.4663) | [-0.7258, 1.1847] | 0.6265 | 1.258 [0.484, 3.270] | — |
| model_3 / state_clustered | log_flood_area | 0.0085 (0.0933) | [-0.1827, 0.1997] | 0.9279 | 1.009 [0.833, 1.221] | — |
| model_3 / state_clustered | urban_population_share | 0.9327 (0.4646) | [-0.0190, 1.8844] | 0.05444 | 2.541 [0.981, 6.583] | 1.098 [0.998, 1.207] |
| model_2_by_source_S1 / ordinary | Intercept | 3.3448 (0.1966) | [2.9594, 3.7301] | 6.541e-65 | 28.354 [19.287, 41.682] | — |
| model_2_by_source_S1 / ordinary | log_flood_area | -0.0219 (0.0357) | [-0.0918, 0.0480] | 0.5399 | 0.978 [0.912, 1.049] | — |
| model_2_by_source_S1 / ordinary | urban_population_share | 0.7066 (0.2845) | [0.1491, 1.2642] | 0.01299 | 2.027 [1.161, 3.540] | 1.073 [1.015, 1.135] |
| model_2_by_source_S1 / state_clustered | Intercept | 3.3448 (0.6741) | [1.9639, 4.7256] | 3.08e-05 | 28.354 [7.127, 112.801] | — |
| model_2_by_source_S1 / state_clustered | log_flood_area | -0.0219 (0.1327) | [-0.2938, 0.2501] | 0.8704 | 0.978 [0.745, 1.284] | — |
| model_2_by_source_S1 / state_clustered | urban_population_share | 0.7066 (0.4079) | [-0.1289, 1.5422] | 0.09422 | 2.027 [0.879, 4.675] | 1.073 [0.987, 1.167] |
| source_event_robustness / ordinary | Intercept | 3.7260 (0.8170) | [2.1247, 5.3272] | 5.102e-06 | 41.511 [8.370, 205.870] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0317-IND] | -3.8110 (0.8969) | [-5.5689, -2.0531] | 2.146e-05 | 0.022 [0.004, 0.128] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0333-IND] | -2.7178 (1.4275) | [-5.5157, 0.0800] | 0.05692 | 0.066 [0.004, 1.083] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0374-IND] | -0.6941 (0.9519) | [-2.5598, 1.1717] | 0.4659 | 0.500 [0.077, 3.227] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0406-IND] | -1.0307 (0.9032) | [-2.8009, 0.7395] | 0.2538 | 0.357 [0.061, 2.095] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0504-IND] | -0.2080 (1.0040) | [-2.1759, 1.7598] | 0.8358 | 0.812 [0.114, 5.811] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0139-IND] | -1.9148 (1.0423) | [-3.9576, 0.1281] | 0.06619 | 0.147 [0.019, 1.137] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0239-IND] | -0.5592 (0.9377) | [-2.3969, 1.2786] | 0.551 | 0.572 [0.091, 3.592] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0267-IND] | -0.0734 (0.9533) | [-1.9418, 1.7949] | 0.9386 | 0.929 [0.143, 6.019] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0271-IND] | -2.9207 (0.9222) | [-4.7282, -1.1133] | 0.001539 | 0.054 [0.009, 0.328] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0554-IND] | 0.4935 (1.3909) | [-2.2325, 3.2196] | 0.7227 | 1.638 [0.107, 25.019] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0180-IND] | -2.6805 (0.8622) | [-4.3704, -0.9905] | 0.001879 | 0.069 [0.013, 0.371] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0289-IND] | -1.0744 (0.8762) | [-2.7917, 0.6429] | 0.2201 | 0.341 [0.061, 1.902] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0290-IND] | -1.8514 (1.1403) | [-4.0864, 0.3836] | 0.1045 | 0.157 [0.017, 1.468] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0294-IND] | -6.5590 (1.4223) | [-9.3466, -3.7714] | 3.995e-06 | 0.001 [0.000, 0.023] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0342-IND] | -0.4962 (0.8499) | [-2.1619, 1.1695] | 0.5593 | 0.609 [0.115, 3.220] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0364-IND] | 0.7185 (1.2331) | [-1.6983, 3.1354] | 0.5601 | 2.051 [0.183, 22.998] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0517-IND] | -1.5429 (0.8711) | [-3.2503, 0.1644] | 0.07653 | 0.214 [0.039, 1.179] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0205-IND] | -0.9119 (0.9878) | [-2.8479, 1.0241] | 0.3559 | 0.402 [0.058, 2.784] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0213-IND] | -2.8327 (1.2530) | [-5.2885, -0.3768] | 0.02378 | 0.059 [0.005, 0.686] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0216-IND] | -0.3693 (1.3891) | [-3.0918, 2.3532] | 0.7903 | 0.691 [0.045, 10.519] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0286-IND] | -2.0599 (1.1488) | [-4.3115, 0.1916] | 0.07295 | 0.127 [0.013, 1.211] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0295-IND] | 0.2234 (0.8205) | [-1.3847, 1.8316] | 0.7854 | 1.250 [0.250, 6.244] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0345-IND] | -1.8331 (0.9725) | [-3.7392, 0.0730] | 0.05945 | 0.160 [0.024, 1.076] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0370-IND] | -2.6654 (0.8814) | [-4.3928, -0.9379] | 0.002494 | 0.070 [0.012, 0.391] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0372-IND] | -3.3356 (0.9793) | [-5.2550, -1.4162] | 0.0006591 | 0.036 [0.005, 0.243] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0288-IND] | 0.6949 (1.2280) | [-1.7119, 3.1017] | 0.5715 | 2.004 [0.181, 22.237] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0331-IND] | -1.0989 (0.8211) | [-2.7083, 0.5105] | 0.1808 | 0.333 [0.067, 1.666] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0383-IND] | 0.0923 (0.8779) | [-1.6283, 1.8130] | 0.9162 | 1.097 [0.196, 6.129] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0499-IND] | -2.2193 (0.9272) | [-4.0365, -0.4021] | 0.01668 | 0.109 [0.018, 0.669] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0574-IND] | -2.6176 (1.0436) | [-4.6630, -0.5723] | 0.01213 | 0.073 [0.009, 0.564] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0206-IND] | -0.8318 (1.0838) | [-2.9561, 1.2925] | 0.4428 | 0.435 [0.052, 3.642] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0304-IND] | -4.1327 (0.8198) | [-5.7394, -2.5259] | 4.627e-07 | 0.016 [0.003, 0.080] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0446-IND] | -2.3206 (0.8798) | [-4.0449, -0.5963] | 0.008346 | 0.098 [0.018, 0.551] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0316-IND] | -3.9478 (0.8663) | [-5.6457, -2.2498] | 5.189e-06 | 0.019 [0.004, 0.105] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0366-IND] | -3.3079 (1.2743) | [-5.8055, -0.8102] | 0.009438 | 0.037 [0.003, 0.445] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0435-IND] | -7.4377 (1.3300) | [-10.0445, -4.8310] | 2.24e-08 | 0.001 [0.000, 0.008] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0458-IND] | -1.3311 (1.0838) | [-3.4553, 0.7930] | 0.2194 | 0.264 [0.032, 2.210] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0585-IND] | -2.2026 (1.0858) | [-4.3308, -0.0745] | 0.0425 | 0.111 [0.013, 0.928] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0677-IND] | 0.5508 (1.0352) | [-1.4781, 2.5797] | 0.5947 | 1.735 [0.228, 13.193] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0722-IND] | -1.9771 (0.8571) | [-3.6569, -0.2972] | 0.02107 | 0.138 [0.026, 0.743] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0748-IND] | -0.1099 (1.1397) | [-2.3436, 2.1238] | 0.9232 | 0.896 [0.096, 8.363] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0293-IND] | -0.7872 (0.8456) | [-2.4446, 0.8701] | 0.3519 | 0.455 [0.087, 2.387] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0539-IND] | -3.5010 (1.0446) | [-5.5483, -1.4537] | 0.0008034 | 0.030 [0.004, 0.234] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0330-IND] | 0.4231 (1.0846) | [-1.7026, 2.5488] | 0.6965 | 1.527 [0.182, 12.792] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0359-IND] | -2.0025 (0.8597) | [-3.6876, -0.3175] | 0.01985 | 0.135 [0.025, 0.728] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0428-IND] | -2.4910 (0.8275) | [-4.1128, -0.8693] | 0.002608 | 0.083 [0.016, 0.419] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0486-IND] | -1.1980 (1.0827) | [-3.3202, 0.9241] | 0.2685 | 0.302 [0.036, 2.520] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0846-IND] | 0.9580 (1.2244) | [-1.4418, 3.3579] | 0.434 | 2.607 [0.237, 28.728] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0399-IND] | -6.8617 (1.3584) | [-9.5242, -4.1992] | 4.391e-07 | 0.001 [0.000, 0.015] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0481-IND] | -0.9434 (0.8410) | [-2.5918, 0.7050] | 0.262 | 0.389 [0.075, 2.024] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0561-IND] | 1.1729 (1.2309) | [-1.2396, 3.5855] | 0.3406 | 3.231 [0.289, 36.071] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0624-IND] | -0.9224 (1.1381) | [-3.1532, 1.3083] | 0.4177 | 0.398 [0.043, 3.700] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0647-IND] | -1.2669 (0.8744) | [-2.9808, 0.4469] | 0.1474 | 0.282 [0.051, 1.564] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0402-IND] | -0.9496 (0.8709) | [-2.6566, 0.7574] | 0.2756 | 0.387 [0.070, 2.133] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0469-IND] | -1.4368 (1.0125) | [-3.4213, 0.5477] | 0.1559 | 0.238 [0.033, 1.729] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0751-IND] | -1.1230 (0.9675) | [-3.0193, 0.7734] | 0.2458 | 0.325 [0.049, 2.167] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0803-IND] | -1.8498 (0.9630) | [-3.7373, 0.0377] | 0.05475 | 0.157 [0.024, 1.038] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0859-IND] | -1.9093 (0.8854) | [-3.6448, -0.1739] | 0.03106 | 0.148 [0.026, 0.840] | — |
| source_event_robustness / ordinary | log_flood_area | 0.1162 (0.0434) | [0.0312, 0.2012] | 0.007369 | 1.123 [1.032, 1.223] | — |
| source_event_robustness / ordinary | urban_population_share | 1.0176 (0.3049) | [0.4200, 1.6152] | 0.0008454 | 2.767 [1.522, 5.029] | 1.107 [1.043, 1.175] |

Flood IRR is per one-unit increase in log(1 + km²); the urbanization IRR is per 0→1 change, with 10 percentage points reported separately.

## Model availability

- model_1: estimated
- model_2: estimated
- model_3: estimated
- model_2_source_fe: insufficient source variation: fewer than two satellite sources
- model_2_by_source_S1: estimated (sensitivity)
- source_event_robustness: estimated secondary unconditional source fixed-effects NB2; 59 source events
- exposed_population_robustness: not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used

## Descriptive distributions and missingness

```json
{
  "distributions": {
    "flood_area_km2": {
      "count": 1069.0,
      "mean": 198.2556417212,
      "std": 386.5982729276,
      "min": 0.0147,
      "25%": 16.6597,
      "50%": 77.6744,
      "75%": 233.9059,
      "max": 5894.8599
    },
    "article_count": {
      "count": 1069.0,
      "mean": 31.0907390084,
      "std": 82.6196793848,
      "min": 0.0,
      "25%": 0.0,
      "50%": 3.0,
      "75%": 27.0,
      "max": 1112.0
    },
    "urban_population_share": {
      "count": 1069.0,
      "mean": 0.2267711483,
      "std": 0.1995168939,
      "min": 0.0,
      "25%": 0.0876401087,
      "50%": 0.1497659752,
      "75%": 0.2980065236,
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
      "count": 1204.0,
      "mean": 30.3712624585,
      "std": 79.5526929819,
      "min": 0.0,
      "25%": 0.0,
      "50%": 4.0,
      "75%": 25.0,
      "max": 1112.0
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
    "flood_area_km2": 78,
    "article_count": 344,
    "urban_population_share": 119
  },
  "exclusion_counts": {
    "article_collection_incomplete": 344,
    "article_count_missing_or_invalid": 344,
    "census_unmatched": 119,
    "census_invalid": 119,
    "census_population_inconsistent": 119,
    "satellite_missing_or_invalid": 78
  },
  "stage_qc": {
    "district_extraction": {
      "success": 1548,
      "total": 1548,
      "rate": 1.0
    },
    "district_aoi_match": {
      "success": 1548,
      "total": 1548,
      "rate": 1.0
    },
    "census_match": {
      "success": 1429,
      "total": 1548,
      "rate": 0.923126615
    },
    "satellite_observation": {
      "success": 1470,
      "total": 1548,
      "rate": 0.9496124031
    },
    "gdelt_collection": {
      "success": 1548,
      "total": 1548,
      "rate": 1.0
    },
    "article_observation": {
      "success": 1204,
      "total": 1548,
      "rate": 0.7777777778
    },
    "article_complete": {
      "success": 23,
      "total": 1548,
      "rate": 0.0148578811
    },
    "article_partial_lower_bound": {
      "success": 1181,
      "total": 1548,
      "rate": 0.7629198966
    },
    "final_analyzable": {
      "success": 1069,
      "total": 1548,
      "rate": 0.6905684755
    },
    "satellite_source_counts": {
      "S1": 1069
    }
  },
  "estimated_dispersion": {
    "model_1": 4.1386198898,
    "model_2": 4.1151535099,
    "model_3": 3.7655166746
  },
  "article_count_variance": 6826.0114216444,
  "article_count_mean": 31.0907390084
}
```

## Selection check

```
urbanization_group  rows  excluded  exclusion_rate
              high   387        67        0.173127
               low   660       175        0.265152
            medium   382       118        0.308901
           unknown   119       119        1.000000
```

## Conclusion candidate

The analysis provides insufficient evidence for H1 or H2; the hypothesized positive associations are not established.

These results describe associations at similar observed flood extent; they do not establish intent or causation.

## Data-quality warnings

- Associational analysis: flood extent does not control all disaster impacts, outlet availability, population size, or media access.
- Census 2011 and GAUL 2015 may not represent event-year district boundaries or urbanization.
- GDELT-indexed district-explicit coverage is not all disaster reporting; location extraction and language coverage can affect selection.
- District rows within a source flood and repeated districts may be dependent; state clustering is only a partial correction.
- 244 registry onset dates are month-imputed; their 14-day news windows have timing uncertainty.
- Article counts use the local state corpus plus targeted BigQuery supplementation of districts without usable local candidates. This is conditional corpus coverage, not exhaustive district recollection; districts with some local coverage may still have missed articles.
- 1181 article counts are observed LLM-QA lower bounds: validated relevant decisions are counted, while unavailable-body, uncertain and unsubmitted candidates remain unresolved and are not imputed as zero.
- Default flood area is Sentinel-1 new water over the eligible AOI, with Track A S2 NDWI only where S1 is missing. Observed S1 zero is retained. Historical inputs retain their recorded sources. Under opt-in sits_primary routing, SITS-NDWI is used on retained clear tiles with Sentinel-1 converted to the SITS-NDWI scale (S1_TO_SITS) where SITS cannot measure the district; the satellite-source fixed effect, by-source and SITS-only subsamples are sensitivity analyses, not a correction.
- Source fixed-effects NB2 is secondary and susceptible to incidental-parameter bias; ordinary SE are reported.
- district-based urbanization tercile cutpoints: [0.1369414084546159, 0.2557930624760398]; unknown Census matches cannot be assigned an urbanization level
