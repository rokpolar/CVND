# Coverage disparity results

News window: 30 days.
N = 1198 district-event observations; 432 districts; 160 parent events; 63 source floods.
Excluded: 350 of 1548 registry rows.
Spearman rho = 0.1512970635; p = 1.428e-07.

Primary model: log E[article_count] = intercept + beta_flood log(1 + flood_area_km2) + beta_urban urban_population_share. NB2 variance = mu + alpha * mu²; alpha is estimated.

M1/M2/M3 use the same complete-case sample. Fixed decision rule: positive coefficient and two-sided p < 0.05; prefer state-clustered inference when the prespecified cluster rule is met. No cutoff on urbanization enters the model.

| Model / SE | Term | Coefficient (SE) | 95% CI | p | IRR [95% CI] | 10pp IRR [95% CI] |
| --- | --- | --- | --- | --- | --- | --- |
| model_1 / ordinary | Intercept | 4.2139 (0.1198) | [3.9791, 4.4487] | 4.624e-271 | 67.618 [53.468, 85.513] | — |
| model_1 / ordinary | log_flood_area | -0.0869 (0.0263) | [-0.1385, -0.0354] | 0.0009527 | 0.917 [0.871, 0.965] | — |
| model_1 / state_clustered | Intercept | 4.2139 (0.4376) | [3.3189, 5.1089] | 1.543e-10 | 67.618 [27.629, 165.483] | — |
| model_1 / state_clustered | log_flood_area | -0.0869 (0.0885) | [-0.2680, 0.0941] | 0.3342 | 0.917 [0.765, 1.099] | — |
| model_2 / ordinary | Intercept | 3.5546 (0.1553) | [3.2502, 3.8590] | 6.074e-116 | 34.974 [25.796, 47.417] | — |
| model_2 / ordinary | log_flood_area | -0.0126 (0.0290) | [-0.0694, 0.0441] | 0.6628 | 0.987 [0.933, 1.045] | — |
| model_2 / ordinary | urban_population_share | 1.3837 (0.2482) | [0.8973, 1.8701] | 2.469e-08 | 3.990 [2.453, 6.489] | 1.148 [1.094, 1.206] |
| model_2 / state_clustered | Intercept | 3.5546 (0.5464) | [2.4370, 4.6722] | 4.026e-07 | 34.974 [11.439, 106.933] | — |
| model_2 / state_clustered | log_flood_area | -0.0126 (0.1028) | [-0.2229, 0.1976] | 0.9031 | 0.987 [0.800, 1.218] | — |
| model_2 / state_clustered | urban_population_share | 1.3837 (0.4444) | [0.4747, 2.2927] | 0.004136 | 3.990 [1.608, 9.901] | 1.148 [1.049, 1.258] |
| model_3 / ordinary | Intercept | 3.7482 (0.2797) | [3.1999, 4.2964] | 6.129e-41 | 42.443 [24.530, 73.436] | — |
| model_3 / ordinary | C(year)[T.2016] | 0.0153 (0.3575) | [-0.6855, 0.7160] | 0.9659 | 1.015 [0.504, 2.046] | — |
| model_3 / ordinary | C(year)[T.2017] | 0.0042 (0.2859) | [-0.5562, 0.5647] | 0.9882 | 1.004 [0.573, 1.759] | — |
| model_3 / ordinary | C(year)[T.2018] | 0.0861 (0.2780) | [-0.4588, 0.6309] | 0.7569 | 1.090 [0.632, 1.879] | — |
| model_3 / ordinary | C(year)[T.2019] | 0.0829 (0.2620) | [-0.4306, 0.5963] | 0.7518 | 1.086 [0.650, 1.815] | — |
| model_3 / ordinary | C(year)[T.2020] | -1.4346 (0.2737) | [-1.9710, -0.8982] | 1.59e-07 | 0.238 [0.139, 0.407] | — |
| model_3 / ordinary | C(year)[T.2021] | -1.2750 (0.2815) | [-1.8268, -0.7233] | 5.926e-06 | 0.279 [0.161, 0.485] | — |
| model_3 / ordinary | C(year)[T.2022] | -0.4072 (0.3408) | [-1.0751, 0.2608] | 0.2322 | 0.666 [0.341, 1.298] | — |
| model_3 / ordinary | C(year)[T.2023] | -0.1664 (0.2933) | [-0.7412, 0.4085] | 0.5706 | 0.847 [0.477, 1.505] | — |
| model_3 / ordinary | C(year)[T.2024] | -0.4634 (0.2995) | [-1.0504, 0.1236] | 0.1218 | 0.629 [0.350, 1.132] | — |
| model_3 / ordinary | C(year)[T.2025] | 0.2261 (0.3131) | [-0.3875, 0.8396] | 0.4702 | 1.254 [0.679, 2.316] | — |
| model_3 / ordinary | log_flood_area | -0.0090 (0.0316) | [-0.0709, 0.0528] | 0.7745 | 0.991 [0.932, 1.054] | — |
| model_3 / ordinary | urban_population_share | 1.3855 (0.2518) | [0.8920, 1.8790] | 3.751e-08 | 3.997 [2.440, 6.547] | 1.149 [1.093, 1.207] |
| model_3 / state_clustered | Intercept | 3.7482 (0.5429) | [2.6378, 4.8585] | 1.381e-07 | 42.443 [13.982, 128.831] | — |
| model_3 / state_clustered | C(year)[T.2016] | 0.0153 (0.5440) | [-1.0973, 1.1279] | 0.9778 | 1.015 [0.334, 3.089] | — |
| model_3 / state_clustered | C(year)[T.2017] | 0.0042 (0.4112) | [-0.8368, 0.8452] | 0.9919 | 1.004 [0.433, 2.329] | — |
| model_3 / state_clustered | C(year)[T.2018] | 0.0861 (0.8245) | [-1.6003, 1.7724] | 0.9176 | 1.090 [0.202, 5.885] | — |
| model_3 / state_clustered | C(year)[T.2019] | 0.0829 (0.4852) | [-0.9095, 1.0752] | 0.8656 | 1.086 [0.403, 2.931] | — |
| model_3 / state_clustered | C(year)[T.2020] | -1.4346 (0.8290) | [-3.1300, 0.2608] | 0.09415 | 0.238 [0.044, 1.298] | — |
| model_3 / state_clustered | C(year)[T.2021] | -1.2750 (0.5881) | [-2.4778, -0.0722] | 0.0385 | 0.279 [0.084, 0.930] | — |
| model_3 / state_clustered | C(year)[T.2022] | -0.4072 (0.6138) | [-1.6625, 0.8481] | 0.5123 | 0.666 [0.190, 2.335] | — |
| model_3 / state_clustered | C(year)[T.2023] | -0.1664 (0.5006) | [-1.1902, 0.8575] | 0.742 | 0.847 [0.304, 2.357] | — |
| model_3 / state_clustered | C(year)[T.2024] | -0.4634 (0.4927) | [-1.4712, 0.5444] | 0.3548 | 0.629 [0.230, 1.724] | — |
| model_3 / state_clustered | C(year)[T.2025] | 0.2261 (0.6104) | [-1.0224, 1.4745] | 0.7138 | 1.254 [0.360, 4.369] | — |
| model_3 / state_clustered | log_flood_area | -0.0090 (0.0723) | [-0.1569, 0.1388] | 0.9013 | 0.991 [0.855, 1.149] | — |
| model_3 / state_clustered | urban_population_share | 1.3855 (0.4581) | [0.4486, 2.3223] | 0.00517 | 3.997 [1.566, 10.199] | 1.149 [1.046, 1.261] |
| model_2_source_fe / ordinary | Intercept | 4.5020 (0.7169) | [3.0968, 5.9071] | 3.399e-10 | 90.194 [22.127, 367.652] | — |
| model_2_source_fe / ordinary | C(satellite_source)[T.S1] | -1.0362 (0.7192) | [-2.4458, 0.3733] | 0.1496 | 0.355 [0.087, 1.453] | — |
| model_2_source_fe / ordinary | C(satellite_source)[T.SITS_NDWI] | -0.4557 (0.7969) | [-2.0176, 1.1062] | 0.5674 | 0.634 [0.133, 3.023] | — |
| model_2_source_fe / ordinary | C(satellite_source)[T.SITS_NDWI_RESTORED] | -0.1997 (1.1805) | [-2.5135, 2.1141] | 0.8657 | 0.819 [0.081, 8.283] | — |
| model_2_source_fe / ordinary | log_flood_area | -0.0026 (0.0293) | [-0.0600, 0.0548] | 0.9293 | 0.997 [0.942, 1.056] | — |
| model_2_source_fe / ordinary | urban_population_share | 1.4517 (0.2470) | [0.9676, 1.9358] | 4.174e-09 | 4.270 [2.632, 6.930] | 1.156 [1.102, 1.214] |
| model_2_source_fe / state_clustered | Intercept | 4.5020 (0.6730) | [3.1255, 5.8784] | 2.451e-07 | 90.194 [22.771, 357.240] | — |
| model_2_source_fe / state_clustered | C(satellite_source)[T.S1] | -1.0362 (0.8134) | [-2.6998, 0.6274] | 0.2128 | 0.355 [0.067, 1.873] | — |
| model_2_source_fe / state_clustered | C(satellite_source)[T.SITS_NDWI] | -0.4557 (0.8396) | [-2.1729, 1.2615] | 0.5914 | 0.634 [0.114, 3.531] | — |
| model_2_source_fe / state_clustered | C(satellite_source)[T.SITS_NDWI_RESTORED] | -0.1997 (0.8580) | [-1.9544, 1.5551] | 0.8176 | 0.819 [0.142, 4.735] | — |
| model_2_source_fe / state_clustered | log_flood_area | -0.0026 (0.1113) | [-0.2302, 0.2250] | 0.9815 | 0.997 [0.794, 1.252] | — |
| model_2_source_fe / state_clustered | urban_population_share | 1.4517 (0.4652) | [0.5003, 2.4030] | 0.004059 | 4.270 [1.649, 11.057] | 1.156 [1.051, 1.272] |
| model_2_by_source_SITS_NDWI / ordinary | Intercept | 3.7882 (0.6977) | [2.4208, 5.1555] | 5.641e-08 | 44.175 [11.255, 173.389] | — |
| model_2_by_source_SITS_NDWI / ordinary | log_flood_area | 0.2395 (0.1718) | [-0.0971, 0.5761] | 0.1632 | 1.271 [0.907, 1.779] | — |
| model_2_by_source_SITS_NDWI / ordinary | urban_population_share | -3.6259 (1.6783) | [-6.9153, -0.3365] | 0.03074 | 0.027 [0.001, 0.714] | 0.696 [0.501, 0.967] |
| model_2_by_source_S1 / ordinary | Intercept | 3.4783 (0.1594) | [3.1659, 3.7908] | 1.534e-105 | 32.405 [23.709, 44.290] | — |
| model_2_by_source_S1 / ordinary | log_flood_area | -0.0069 (0.0297) | [-0.0651, 0.0513] | 0.8154 | 0.993 [0.937, 1.053] | — |
| model_2_by_source_S1 / ordinary | urban_population_share | 1.4742 (0.2493) | [0.9856, 1.9627] | 3.341e-09 | 4.367 [2.679, 7.119] | 1.159 [1.104, 1.217] |
| model_2_by_source_S1 / state_clustered | Intercept | 3.4783 (0.6181) | [2.2142, 4.7425] | 4.446e-06 | 32.405 [9.154, 114.715] | — |
| model_2_by_source_S1 / state_clustered | log_flood_area | -0.0069 (0.1127) | [-0.2374, 0.2235] | 0.9514 | 0.993 [0.789, 1.251] | — |
| model_2_by_source_S1 / state_clustered | urban_population_share | 1.4742 (0.4748) | [0.5030, 2.4453] | 0.004229 | 4.367 [1.654, 11.534] | 1.159 [1.052, 1.277] |
| model_2_sits_only / ordinary | Intercept | 3.7068 (0.6391) | [2.4542, 4.9594] | 6.628e-09 | 40.724 [11.637, 142.514] | — |
| model_2_sits_only / ordinary | log_flood_area | 0.2617 (0.1524) | [-0.0371, 0.5605] | 0.08602 | 1.299 [0.964, 1.752] | — |
| model_2_sits_only / ordinary | urban_population_share | -3.6935 (1.5248) | [-6.6820, -0.7050] | 0.01542 | 0.025 [0.001, 0.494] | 0.691 [0.513, 0.932] |
| source_event_robustness / ordinary | Intercept | 4.0624 (0.8120) | [2.4709, 5.6540] | 5.653e-07 | 58.116 [11.833, 285.435] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0317-IND] | -1.6189 (0.8582) | [-3.3009, 0.0631] | 0.05924 | 0.198 [0.037, 1.065] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0333-IND] | -2.7080 (1.4084) | [-5.4683, 0.0523] | 0.05451 | 0.067 [0.004, 1.054] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0374-IND] | -0.6223 (0.9475) | [-2.4793, 1.2347] | 0.5113 | 0.537 [0.084, 3.437] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0406-IND] | -1.0036 (0.8989) | [-2.7655, 0.7584] | 0.2643 | 0.367 [0.063, 2.135] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0504-IND] | 1.3678 (0.9770) | [-0.5472, 3.2827] | 0.1615 | 3.927 [0.579, 26.648] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0139-IND] | -2.1639 (1.0063) | [-4.1362, -0.1915] | 0.03153 | 0.115 [0.016, 0.826] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0239-IND] | -0.0106 (0.9145) | [-1.8029, 1.7817] | 0.9907 | 0.989 [0.165, 5.940] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0267-IND] | -0.1041 (0.9483) | [-1.9627, 1.7545] | 0.9126 | 0.901 [0.140, 5.780] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0271-IND] | -1.7487 (0.9114) | [-3.5350, 0.0377] | 0.05503 | 0.174 [0.029, 1.038] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0554-IND] | 0.2763 (1.3769) | [-2.4223, 2.9749] | 0.8409 | 1.318 [0.089, 19.588] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0180-IND] | -2.1719 (0.8541) | [-3.8460, -0.4979] | 0.01099 | 0.114 [0.021, 0.608] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0289-IND] | -0.0017 (0.8720) | [-1.7108, 1.7074] | 0.9985 | 0.998 [0.181, 5.515] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0290-IND] | -1.8321 (1.1303) | [-4.0475, 0.3834] | 0.1051 | 0.160 [0.017, 1.467] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0294-IND] | -5.4076 (1.0793) | [-7.5231, -3.2922] | 5.438e-07 | 0.004 [0.001, 0.037] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0342-IND] | -0.2031 (0.8454) | [-1.8601, 1.4538] | 0.8101 | 0.816 [0.156, 4.279] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0364-IND] | 0.7270 (1.2208) | [-1.6657, 3.1198] | 0.5515 | 2.069 [0.189, 22.642] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0517-IND] | -1.4567 (0.8676) | [-3.1572, 0.2438] | 0.09316 | 0.233 [0.043, 1.276] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0205-IND] | -0.8644 (0.9822) | [-2.7895, 1.0607] | 0.3788 | 0.421 [0.061, 2.888] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0213-IND] | -2.0613 (1.1343) | [-4.2844, 0.1618] | 0.06917 | 0.127 [0.014, 1.176] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0216-IND] | -0.2569 (1.3730) | [-2.9480, 2.4342] | 0.8516 | 0.773 [0.052, 11.407] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0286-IND] | -2.0480 (1.1377) | [-4.2779, 0.1819] | 0.07184 | 0.129 [0.014, 1.199] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0295-IND] | 0.2311 (0.8164) | [-1.3690, 1.8312] | 0.7771 | 1.260 [0.254, 6.242] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0345-IND] | -1.8924 (0.9676) | [-3.7888, 0.0040] | 0.05049 | 0.151 [0.023, 1.004] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0370-IND] | -2.7698 (0.8757) | [-4.4863, -1.0534] | 0.001563 | 0.063 [0.011, 0.349] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0372-IND] | -3.3766 (0.9735) | [-5.2846, -1.4686] | 0.0005234 | 0.034 [0.005, 0.230] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0288-IND] | 0.6314 (1.2169) | [-1.7537, 3.0166] | 0.6038 | 1.880 [0.173, 20.421] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0331-IND] | -0.4492 (0.8097) | [-2.0362, 1.1378] | 0.5791 | 0.638 [0.131, 3.120] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0383-IND] | 0.2753 (0.8721) | [-1.4339, 1.9845] | 0.7522 | 1.317 [0.238, 7.276] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0499-IND] | -2.1198 (0.9223) | [-3.9275, -0.3120] | 0.02155 | 0.120 [0.020, 0.732] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0574-IND] | -2.6194 (1.0352) | [-4.6484, -0.5905] | 0.01139 | 0.073 [0.010, 0.554] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0206-IND] | -0.8674 (1.0758) | [-2.9761, 1.2412] | 0.4201 | 0.420 [0.051, 3.460] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0304-IND] | -2.2416 (0.8151) | [-3.8393, -0.6440] | 0.005959 | 0.106 [0.022, 0.525] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0446-IND] | -1.1726 (0.8675) | [-2.8729, 0.5278] | 0.1765 | 0.310 [0.057, 1.695] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0316-IND] | -3.3275 (0.8412) | [-4.9762, -1.6788] | 7.629e-05 | 0.036 [0.007, 0.187] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0366-IND] | -3.6469 (1.1767) | [-5.9532, -1.3407] | 0.001939 | 0.026 [0.003, 0.262] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0435-IND] | -6.9621 (1.1183) | [-9.1540, -4.7702] | 4.799e-10 | 0.001 [0.000, 0.008] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0458-IND] | -1.4739 (1.0761) | [-3.5831, 0.6352] | 0.1708 | 0.229 [0.028, 1.887] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0585-IND] | -2.0876 (1.0757) | [-4.1959, 0.0207] | 0.05229 | 0.124 [0.015, 1.021] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0677-IND] | 0.3776 (1.0291) | [-1.6394, 2.3946] | 0.7137 | 1.459 [0.194, 10.963] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0722-IND] | -1.7636 (0.8526) | [-3.4348, -0.0925] | 0.0386 | 0.171 [0.032, 0.912] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0748-IND] | 0.0131 (1.1293) | [-2.2003, 2.2265] | 0.9907 | 1.013 [0.111, 9.268] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0293-IND] | -0.9089 (0.8381) | [-2.5515, 0.7337] | 0.2782 | 0.403 [0.078, 2.083] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0539-IND] | -0.9889 (0.9620) | [-2.8743, 0.8965] | 0.3039 | 0.372 [0.056, 2.451] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0590-IND] | -4.0484 (1.4909) | [-6.9704, -1.1263] | 0.006619 | 0.017 [0.001, 0.324] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0330-IND] | 0.4854 (1.0761) | [-1.6237, 2.5945] | 0.6519 | 1.625 [0.197, 13.390] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0359-IND] | -0.2811 (0.8542) | [-1.9554, 1.3932] | 0.7421 | 0.755 [0.142, 4.028] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0428-IND] | -1.4454 (0.8243) | [-3.0610, 0.1702] | 0.07952 | 0.236 [0.047, 1.186] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0486-IND] | -1.2694 (1.0753) | [-3.3770, 0.8382] | 0.2378 | 0.281 [0.034, 2.312] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0846-IND] | 0.9111 (1.2132) | [-1.4667, 3.2889] | 0.4526 | 2.487 [0.231, 26.814] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0399-IND] | -2.7975 (0.8911) | [-4.5439, -1.0511] | 0.001692 | 0.061 [0.011, 0.350] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0481-IND] | -0.9722 (0.8383) | [-2.6152, 0.6708] | 0.2461 | 0.378 [0.073, 1.956] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0561-IND] | 1.0114 (1.2186) | [-1.3770, 3.3997] | 0.4066 | 2.749 [0.252, 29.955] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0624-IND] | -0.9989 (1.1292) | [-3.2121, 1.2142] | 0.3763 | 0.368 [0.040, 3.368] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0647-IND] | -1.1583 (0.8697) | [-2.8628, 0.5463] | 0.1829 | 0.314 [0.057, 1.727] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0402-IND] | -1.0903 (0.8610) | [-2.7779, 0.5973] | 0.2054 | 0.336 [0.062, 1.817] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0469-IND] | -0.1033 (0.9795) | [-2.0231, 1.8165] | 0.916 | 0.902 [0.132, 6.150] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0751-IND] | 0.8066 (0.9461) | [-1.0476, 2.6609] | 0.3939 | 2.240 [0.351, 14.309] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0803-IND] | -1.9076 (0.9580) | [-3.7853, -0.0300] | 0.04646 | 0.148 [0.023, 0.970] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0859-IND] | -1.9011 (0.8780) | [-3.6220, -0.1802] | 0.03037 | 0.149 [0.027, 0.835] | — |
| source_event_robustness / ordinary | log_flood_area | 0.0589 (0.0344) | [-0.0085, 0.1262] | 0.08666 | 1.061 [0.992, 1.135] | — |
| source_event_robustness / ordinary | urban_population_share | 0.9106 (0.2875) | [0.3471, 1.4740] | 0.001538 | 2.486 [1.415, 4.367] | 1.095 [1.035, 1.159] |

Flood IRR is per one-unit increase in log(1 + km²); the urbanization IRR is per 0→1 change, with 10 percentage points reported separately.

## Model availability

- model_1: estimated
- model_2: estimated
- model_3: estimated
- model_2_source_fe: estimated (sensitivity)
- model_2_by_source_SITS_NDWI: estimated (sensitivity)
- model_2_by_source_SITS_NDWI_RESTORED: insufficient sample: N=4 < 20
- model_2_by_source_S1: estimated (sensitivity)
- model_2_by_source_NDWI: insufficient sample: N=7 < 20
- model_2_sits_only: estimated (sensitivity)
- source_event_robustness: estimated secondary unconditional source fixed-effects NB2; 60 source events
- exposed_population_robustness: not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used

## Descriptive distributions and missingness

```json
{
  "distributions": {
    "flood_area_km2": {
      "count": 1198.0,
      "mean": 184.0613254591,
      "std": 367.9398013139,
      "min": 0.0147,
      "25%": 14.90785,
      "50%": 68.5838,
      "75%": 212.51525,
      "max": 5894.8599
    },
    "article_count": {
      "count": 1198.0,
      "mean": 48.3739565943,
      "std": 144.3466786315,
      "min": 0.0,
      "25%": 1.0,
      "50%": 7.0,
      "75%": 46.0,
      "max": 3291.0
    },
    "urban_population_share": {
      "count": 1198.0,
      "mean": 0.2225157939,
      "std": 0.195753362,
      "min": 0.0,
      "25%": 0.0876401087,
      "50%": 0.1500736031,
      "75%": 0.2892693567,
      "max": 1.0
    }
  },
  "available_input_distributions": {
    "flood_area_km2": {
      "count": 1477.0,
      "mean": 171.6973004062,
      "std": 348.9887699761,
      "min": 0.0028,
      "25%": 13.9896,
      "50%": 61.2126,
      "75%": 181.0263,
      "max": 5894.8599
    },
    "article_count": {
      "count": 1340.0,
      "mean": 47.1604477612,
      "std": 138.0509060239,
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
    "flood_area_km2": 71,
    "article_count": 208,
    "urban_population_share": 119
  },
  "exclusion_counts": {
    "article_collection_incomplete": 208,
    "article_count_missing_or_invalid": 208,
    "census_unmatched": 119,
    "census_invalid": 119,
    "census_population_inconsistent": 119,
    "satellite_missing_or_invalid": 71
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
      "success": 1477,
      "total": 1548,
      "rate": 0.9541343669
    },
    "gdelt_collection": {
      "success": 1548,
      "total": 1548,
      "rate": 1.0
    },
    "article_observation": {
      "success": 1340,
      "total": 1548,
      "rate": 0.8656330749
    },
    "article_complete": {
      "success": 18,
      "total": 1548,
      "rate": 0.011627907
    },
    "article_partial_lower_bound": {
      "success": 1322,
      "total": 1548,
      "rate": 0.854005168
    },
    "final_analyzable": {
      "success": 1198,
      "total": 1548,
      "rate": 0.7739018088
    },
    "satellite_source_counts": {
      "S1": 1158,
      "SITS_NDWI": 29,
      "NDWI": 7,
      "SITS_NDWI_RESTORED": 4
    }
  },
  "estimated_dispersion": {
    "model_1": 3.6075585728,
    "model_2": 3.5193002226,
    "model_3": 3.2755374637
  },
  "article_count_variance": 20835.9636319513,
  "article_count_mean": 48.3739565943
}
```

## Selection check

```
urbanization_group  rows  excluded  exclusion_rate
              high   387        41        0.105943
               low   660       116        0.175758
            medium   382        74        0.193717
           unknown   119       119        1.000000
```

## Conclusion candidate

H1 is not supported. Higher urbanization is associated with greater expected coverage at similar observed flood extent; this supports H2 alone.

These results describe associations at similar observed flood extent; they do not establish intent or causation.

## Data-quality warnings

- Associational analysis: flood extent does not control all disaster impacts, outlet availability, population size, or media access.
- Census 2011 and GAUL 2015 may not represent event-year district boundaries or urbanization.
- GDELT-indexed district-explicit coverage is not all disaster reporting; location extraction and language coverage can affect selection.
- District rows within a source flood and repeated districts may be dependent; state clustering is only a partial correction.
- 244 registry onset dates are month-imputed; their 30-day news windows have timing uncertainty.
- Article counts use the local state corpus plus targeted BigQuery supplementation of districts without usable local candidates. This is conditional corpus coverage, not exhaustive district recollection; districts with some local coverage may still have missed articles.
- 1322 article counts are observed LLM-QA lower bounds: validated relevant decisions are counted, while unavailable-body, uncertain and unsubmitted candidates remain unresolved and are not imputed as zero.
- model_2_by_source_SITS_NDWI: 10 state clusters / N=29; require >= 20 clusters and N > 2G; ordinary SE used and independence assumption is a limitation
- model_2_sits_only: 10 state clusters / N=33; require >= 20 clusters and N > 2G; ordinary SE used and independence assumption is a limitation
- Default flood area is Sentinel-1 new water over the eligible AOI, with Track A S2 NDWI only where S1 is missing. Observed S1 zero is retained. Historical inputs retain their recorded sources. Under opt-in sits_primary routing, SITS-NDWI is used on retained clear tiles with Sentinel-1 converted to the SITS-NDWI scale (S1_TO_SITS) where SITS cannot measure the district; the satellite-source fixed effect, by-source and SITS-only subsamples are sensitivity analyses, not a correction.
- Source fixed-effects NB2 is secondary and susceptible to incidental-parameter bias; ordinary SE are reported.
- district-based urbanization tercile cutpoints: [0.1369414084546159, 0.2557930624760398]; unknown Census matches cannot be assigned an urbanization level
