# Coverage disparity results

News window: 30 days.
N = 1198 district-event observations; 432 districts; 160 parent events; 63 source floods.
Excluded: 350 of 1548 registry rows.
Spearman rho = 0.1538125362; p = 8.79e-08.

Primary model: log E[article_count] = intercept + beta_flood log(1 + flood_area_km2) + beta_urban urban_population_share. NB2 variance = mu + alpha * mu²; alpha is estimated.

M1/M2/M3 use the same complete-case sample. Fixed decision rule: positive coefficient and two-sided p < 0.05; prefer state-clustered inference when the prespecified cluster rule is met. No cutoff on urbanization enters the model.

| Model / SE | Term | Coefficient (SE) | 95% CI | p | IRR [95% CI] | 10pp IRR [95% CI] |
| --- | --- | --- | --- | --- | --- | --- |
| model_1 / ordinary | Intercept | 4.1979 (0.1195) | [3.9637, 4.4322] | 2.848e-270 | 66.549 [52.651, 84.115] | — |
| model_1 / ordinary | log_flood_area | -0.0819 (0.0260) | [-0.1329, -0.0309] | 0.001635 | 0.921 [0.876, 0.970] | — |
| model_1 / state_clustered | Intercept | 4.1979 (0.4466) | [3.2846, 5.1113] | 2.632e-10 | 66.549 [26.699, 165.879] | — |
| model_1 / state_clustered | log_flood_area | -0.0819 (0.0904) | [-0.2669, 0.1030] | 0.3724 | 0.921 [0.766, 1.109] | — |
| model_2 / ordinary | Intercept | 3.5172 (0.1562) | [3.2111, 3.8233] | 2.662e-112 | 33.689 [24.805, 45.754] | — |
| model_2 / ordinary | log_flood_area | -0.0045 (0.0288) | [-0.0609, 0.0519] | 0.875 | 0.995 [0.941, 1.053] | — |
| model_2 / ordinary | urban_population_share | 1.4064 (0.2489) | [0.9186, 1.8942] | 1.6e-08 | 4.081 [2.506, 6.648] | 1.151 [1.096, 1.209] |
| model_2 / state_clustered | Intercept | 3.5172 (0.5710) | [2.3493, 4.6850] | 1.029e-06 | 33.689 [10.479, 108.309] | — |
| model_2 / state_clustered | log_flood_area | -0.0045 (0.1067) | [-0.2227, 0.2137] | 0.9664 | 0.995 [0.800, 1.238] | — |
| model_2 / state_clustered | urban_population_share | 1.4064 (0.4547) | [0.4765, 2.3364] | 0.004353 | 4.081 [1.610, 10.343] | 1.151 [1.049, 1.263] |
| model_3 / ordinary | Intercept | 3.7202 (0.2802) | [3.1710, 4.2695] | 3.238e-40 | 41.275 [23.831, 71.488] | — |
| model_3 / ordinary | C(year)[T.2016] | 0.0140 (0.3576) | [-0.6867, 0.7148] | 0.9687 | 1.014 [0.503, 2.044] | — |
| model_3 / ordinary | C(year)[T.2017] | -0.0077 (0.2857) | [-0.5677, 0.5523] | 0.9785 | 0.992 [0.567, 1.737] | — |
| model_3 / ordinary | C(year)[T.2018] | 0.0934 (0.2781) | [-0.4517, 0.6386] | 0.7369 | 1.098 [0.637, 1.894] | — |
| model_3 / ordinary | C(year)[T.2019] | 0.0798 (0.2623) | [-0.4344, 0.5940] | 0.761 | 1.083 [0.648, 1.811] | — |
| model_3 / ordinary | C(year)[T.2020] | -1.4402 (0.2737) | [-1.9765, -0.9038] | 1.421e-07 | 0.237 [0.139, 0.405] | — |
| model_3 / ordinary | C(year)[T.2021] | -1.2730 (0.2816) | [-1.8250, -0.7211] | 6.171e-06 | 0.280 [0.161, 0.486] | — |
| model_3 / ordinary | C(year)[T.2022] | -0.4117 (0.3410) | [-1.0800, 0.2566] | 0.2273 | 0.663 [0.340, 1.293] | — |
| model_3 / ordinary | C(year)[T.2023] | -0.1724 (0.2937) | [-0.7481, 0.4033] | 0.5572 | 0.842 [0.473, 1.497] | — |
| model_3 / ordinary | C(year)[T.2024] | -0.4674 (0.2995) | [-1.0545, 0.1197] | 0.1187 | 0.627 [0.348, 1.127] | — |
| model_3 / ordinary | C(year)[T.2025] | 0.2211 (0.3131) | [-0.3926, 0.8347] | 0.4801 | 1.247 [0.675, 2.304] | — |
| model_3 / ordinary | log_flood_area | -0.0022 (0.0314) | [-0.0638, 0.0594] | 0.9445 | 0.998 [0.938, 1.061] | — |
| model_3 / ordinary | urban_population_share | 1.4008 (0.2524) | [0.9062, 1.8954] | 2.842e-08 | 4.058 [2.475, 6.655] | 1.150 [1.095, 1.209] |
| model_3 / state_clustered | Intercept | 3.7202 (0.5498) | [2.5957, 4.8448] | 1.994e-07 | 41.275 [13.407, 127.072] | — |
| model_3 / state_clustered | C(year)[T.2016] | 0.0140 (0.5478) | [-1.1064, 1.1345] | 0.9797 | 1.014 [0.331, 3.110] | — |
| model_3 / state_clustered | C(year)[T.2017] | -0.0077 (0.4072) | [-0.8405, 0.8251] | 0.985 | 0.992 [0.431, 2.282] | — |
| model_3 / state_clustered | C(year)[T.2018] | 0.0934 (0.8236) | [-1.5910, 1.7779] | 0.9105 | 1.098 [0.204, 5.917] | — |
| model_3 / state_clustered | C(year)[T.2019] | 0.0798 (0.4804) | [-0.9027, 1.0622] | 0.8692 | 1.083 [0.405, 2.893] | — |
| model_3 / state_clustered | C(year)[T.2020] | -1.4402 (0.8328) | [-3.1435, 0.2631] | 0.09439 | 0.237 [0.043, 1.301] | — |
| model_3 / state_clustered | C(year)[T.2021] | -1.2730 (0.5891) | [-2.4779, -0.0682] | 0.03909 | 0.280 [0.084, 0.934] | — |
| model_3 / state_clustered | C(year)[T.2022] | -0.4117 (0.6140) | [-1.6674, 0.8441] | 0.5079 | 0.663 [0.189, 2.326] | — |
| model_3 / state_clustered | C(year)[T.2023] | -0.1724 (0.5008) | [-1.1966, 0.8518] | 0.7331 | 0.842 [0.302, 2.344] | — |
| model_3 / state_clustered | C(year)[T.2024] | -0.4674 (0.4953) | [-1.4804, 0.5457] | 0.3532 | 0.627 [0.228, 1.726] | — |
| model_3 / state_clustered | C(year)[T.2025] | 0.2211 (0.6109) | [-1.0284, 1.4705] | 0.7201 | 1.247 [0.358, 4.352] | — |
| model_3 / state_clustered | log_flood_area | -0.0022 (0.0742) | [-0.1539, 0.1496] | 0.9767 | 0.998 [0.857, 1.161] | — |
| model_3 / state_clustered | urban_population_share | 1.4008 (0.4653) | [0.4492, 2.3523] | 0.005353 | 4.058 [1.567, 10.510] | 1.150 [1.046, 1.265] |
| model_2_source_fe / ordinary | Intercept | 4.4971 (0.7144) | [3.0969, 5.8973] | 3.078e-10 | 89.756 [22.128, 364.060] | — |
| model_2_source_fe / ordinary | C(satellite_source)[T.S1] | -1.0275 (0.7166) | [-2.4321, 0.3771] | 0.1516 | 0.358 [0.088, 1.458] | — |
| model_2_source_fe / ordinary | log_flood_area | 0.0041 (0.0291) | [-0.0530, 0.0612] | 0.8886 | 1.004 [0.948, 1.063] | — |
| model_2_source_fe / ordinary | urban_population_share | 1.4160 (0.2461) | [0.9337, 1.8982] | 8.67e-09 | 4.121 [2.544, 6.674] | 1.152 [1.098, 1.209] |
| model_2_source_fe / state_clustered | Intercept | 4.4971 (0.6725) | [3.1218, 5.8724] | 2.462e-07 | 89.756 [22.686, 355.106] | — |
| model_2_source_fe / state_clustered | C(satellite_source)[T.S1] | -1.0275 (0.8140) | [-2.6923, 0.6373] | 0.2169 | 0.358 [0.068, 1.891] | — |
| model_2_source_fe / state_clustered | log_flood_area | 0.0041 (0.1125) | [-0.2259, 0.2341] | 0.9713 | 1.004 [0.798, 1.264] | — |
| model_2_source_fe / state_clustered | urban_population_share | 1.4160 (0.4652) | [0.4646, 2.3674] | 0.004928 | 4.121 [1.591, 10.670] | 1.152 [1.048, 1.267] |
| model_2_by_source_S1 / ordinary | Intercept | 3.4611 (0.1574) | [3.1526, 3.7696] | 3.593e-107 | 31.852 [23.397, 43.362] | — |
| model_2_by_source_S1 / ordinary | log_flood_area | 0.0062 (0.0292) | [-0.0510, 0.0633] | 0.8319 | 1.006 [0.950, 1.065] | — |
| model_2_by_source_S1 / ordinary | urban_population_share | 1.4155 (0.2456) | [0.9341, 1.8970] | 8.275e-09 | 4.119 [2.545, 6.666] | 1.152 [1.098, 1.209] |
| model_2_by_source_S1 / state_clustered | Intercept | 3.4611 (0.6112) | [2.2110, 4.7112] | 4.034e-06 | 31.852 [9.125, 111.183] | — |
| model_2_by_source_S1 / state_clustered | log_flood_area | 0.0062 (0.1126) | [-0.2240, 0.2364] | 0.9565 | 1.006 [0.799, 1.267] | — |
| model_2_by_source_S1 / state_clustered | urban_population_share | 1.4155 (0.4667) | [0.4611, 2.3700] | 0.005061 | 4.119 [1.586, 10.697] | 1.152 [1.047, 1.267] |
| source_event_robustness / ordinary | Intercept | 4.0238 (0.8120) | [2.4322, 5.6153] | 7.227e-07 | 55.911 [11.384, 274.601] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0317-IND] | -1.6237 (0.8576) | [-3.3046, 0.0572] | 0.05832 | 0.197 [0.037, 1.059] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0333-IND] | -2.7028 (1.4078) | [-5.4620, 0.0564] | 0.05487 | 0.067 [0.004, 1.058] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0374-IND] | -0.6264 (0.9468) | [-2.4821, 1.2293] | 0.5082 | 0.535 [0.084, 3.419] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0406-IND] | -1.0238 (0.8982) | [-2.7842, 0.7366] | 0.2543 | 0.359 [0.062, 2.089] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0504-IND] | 1.3618 (0.9769) | [-0.5528, 3.2764] | 0.1633 | 3.903 [0.575, 26.482] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0139-IND] | -2.1661 (1.0058) | [-4.1374, -0.1949] | 0.03126 | 0.115 [0.016, 0.823] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0239-IND] | -0.0096 (0.9139) | [-1.8007, 1.7815] | 0.9916 | 0.990 [0.165, 5.939] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0267-IND] | -0.1194 (0.9475) | [-1.9766, 1.7377] | 0.8997 | 0.887 [0.139, 5.684] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0271-IND] | -1.7591 (0.9107) | [-3.5441, 0.0259] | 0.05342 | 0.172 [0.029, 1.026] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0554-IND] | 0.2906 (1.3763) | [-2.4070, 2.9882] | 0.8328 | 1.337 [0.090, 19.850] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0180-IND] | -2.1848 (0.8534) | [-3.8575, -0.5122] | 0.01046 | 0.113 [0.021, 0.599] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0289-IND] | -0.0223 (0.8712) | [-1.7298, 1.6853] | 0.9796 | 0.978 [0.177, 5.394] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0290-IND] | -1.8512 (1.1299) | [-4.0657, 0.3633] | 0.1013 | 0.157 [0.017, 1.438] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0294-IND] | -5.4166 (1.0791) | [-7.5316, -3.3016] | 5.18e-07 | 0.004 [0.001, 0.037] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0342-IND] | -0.2321 (0.8445) | [-1.8873, 1.4231] | 0.7834 | 0.793 [0.151, 4.150] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0364-IND] | 0.7261 (1.2204) | [-1.6659, 3.1180] | 0.5519 | 2.067 [0.189, 22.601] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0517-IND] | -1.4779 (0.8668) | [-3.1768, 0.2211] | 0.08821 | 0.228 [0.042, 1.247] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0205-IND] | -0.8792 (0.9815) | [-2.8029, 1.0445] | 0.3704 | 0.415 [0.061, 2.842] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0213-IND] | -2.0563 (1.1337) | [-4.2784, 0.1658] | 0.06971 | 0.128 [0.014, 1.180] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0216-IND] | -0.2538 (1.3727) | [-2.9442, 2.4366] | 0.8533 | 0.776 [0.053, 11.434] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0286-IND] | -2.0454 (1.1371) | [-4.2740, 0.1832] | 0.07204 | 0.129 [0.014, 1.201] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0295-IND] | 0.2367 (0.8161) | [-1.3628, 1.8362] | 0.7718 | 1.267 [0.256, 6.273] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0345-IND] | -1.9052 (0.9668) | [-3.8002, -0.0103] | 0.04877 | 0.149 [0.022, 0.990] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0370-IND] | -2.7822 (0.8751) | [-4.4973, -1.0671] | 0.001476 | 0.062 [0.011, 0.344] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0372-IND] | -3.3974 (0.9731) | [-5.3047, -1.4902] | 0.0004806 | 0.033 [0.005, 0.225] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0288-IND] | 0.6355 (1.2165) | [-1.7488, 3.0198] | 0.6014 | 1.888 [0.174, 20.487] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0331-IND] | -0.4765 (0.8095) | [-2.0631, 1.1101] | 0.5561 | 0.621 [0.127, 3.035] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0383-IND] | 0.2853 (0.8717) | [-1.4233, 1.9938] | 0.7435 | 1.330 [0.241, 7.344] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0499-IND] | -2.1462 (0.9222) | [-3.9537, -0.3387] | 0.01995 | 0.117 [0.019, 0.713] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0574-IND] | -2.6982 (1.0362) | [-4.7290, -0.6674] | 0.009212 | 0.067 [0.009, 0.513] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0206-IND] | -0.8849 (1.0750) | [-2.9919, 1.2222] | 0.4105 | 0.413 [0.050, 3.395] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0304-IND] | -2.2553 (0.8144) | [-3.8516, -0.6590] | 0.00562 | 0.105 [0.021, 0.517] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0446-IND] | -1.1837 (0.8672) | [-2.8834, 0.5160] | 0.1723 | 0.306 [0.056, 1.675] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0316-IND] | -3.3332 (0.8407) | [-4.9809, -1.6855] | 7.34e-05 | 0.036 [0.007, 0.185] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0366-IND] | -3.6614 (1.1760) | [-5.9662, -1.3565] | 0.001849 | 0.026 [0.003, 0.258] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0435-IND] | -6.9741 (1.1183) | [-9.1659, -4.7823] | 4.477e-10 | 0.001 [0.000, 0.008] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0458-IND] | -1.4656 (1.0756) | [-3.5737, 0.6426] | 0.173 | 0.231 [0.028, 1.901] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0585-IND] | -2.1187 (1.0753) | [-4.2262, -0.0111] | 0.04881 | 0.120 [0.015, 0.989] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0677-IND] | 0.3896 (1.0287) | [-1.6267, 2.4059] | 0.7049 | 1.476 [0.197, 11.088] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0722-IND] | -1.7731 (0.8525) | [-3.4440, -0.1021] | 0.03755 | 0.170 [0.032, 0.903] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0748-IND] | -0.0238 (1.1291) | [-2.2368, 2.1893] | 0.9832 | 0.977 [0.107, 8.929] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0293-IND] | -0.9303 (0.8376) | [-2.5720, 0.7114] | 0.2667 | 0.394 [0.076, 2.037] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0539-IND] | -0.9801 (0.9615) | [-2.8646, 0.9045] | 0.3081 | 0.375 [0.057, 2.471] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0590-IND] | -4.0581 (1.4903) | [-6.9791, -1.1372] | 0.006469 | 0.017 [0.001, 0.321] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0330-IND] | 0.4630 (1.0752) | [-1.6443, 2.5703] | 0.6668 | 1.589 [0.193, 13.069] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0359-IND] | -0.3274 (0.8550) | [-2.0032, 1.3484] | 0.7018 | 0.721 [0.135, 3.851] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0428-IND] | -1.4497 (0.8238) | [-3.0644, 0.1650] | 0.07846 | 0.235 [0.047, 1.179] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0486-IND] | -1.2786 (1.0746) | [-3.3849, 0.8276] | 0.2341 | 0.278 [0.034, 2.288] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0846-IND] | 0.9016 (1.2127) | [-1.4752, 3.2784] | 0.4572 | 2.464 [0.229, 26.533] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0399-IND] | -2.8052 (0.8904) | [-4.5504, -1.0600] | 0.00163 | 0.060 [0.011, 0.346] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0481-IND] | -0.9898 (0.8376) | [-2.6314, 0.6517] | 0.2373 | 0.372 [0.072, 1.919] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0561-IND] | 1.0318 (1.2180) | [-1.3554, 3.4189] | 0.3969 | 2.806 [0.258, 30.537] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0624-IND] | -1.0109 (1.1286) | [-3.2228, 1.2010] | 0.3704 | 0.364 [0.040, 3.324] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0647-IND] | -1.1877 (0.8692) | [-2.8914, 0.5159] | 0.1718 | 0.305 [0.055, 1.675] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0402-IND] | -1.1015 (0.8604) | [-2.7879, 0.5848] | 0.2005 | 0.332 [0.062, 1.795] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0469-IND] | -0.0894 (0.9791) | [-2.0084, 1.8295] | 0.9272 | 0.914 [0.134, 6.231] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0751-IND] | 0.7763 (0.9455) | [-1.0769, 2.6296] | 0.4116 | 2.173 [0.341, 13.868] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0803-IND] | -1.9316 (0.9579) | [-3.8090, -0.0541] | 0.04376 | 0.145 [0.022, 0.947] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0859-IND] | -1.9203 (0.8774) | [-3.6400, -0.2006] | 0.02863 | 0.147 [0.026, 0.818] | — |
| source_event_robustness / ordinary | log_flood_area | 0.0692 (0.0344) | [0.0017, 0.1367] | 0.04444 | 1.072 [1.002, 1.147] | — |
| source_event_robustness / ordinary | urban_population_share | 0.9464 (0.2893) | [0.3794, 1.5134] | 0.001071 | 2.576 [1.461, 4.542] | 1.099 [1.039, 1.163] |

Flood IRR is per one-unit increase in log(1 + km²); the urbanization IRR is per 0→1 change, with 10 percentage points reported separately.

## Model availability

- model_1: estimated
- model_2: estimated
- model_3: estimated
- model_2_source_fe: estimated (sensitivity)
- model_2_by_source_S1: estimated (sensitivity)
- model_2_by_source_NDWI: insufficient sample: N=7 < 20
- source_event_robustness: estimated secondary unconditional source fixed-effects NB2; 60 source events
- exposed_population_robustness: not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used

## Descriptive distributions and missingness

```json
{
  "distributions": {
    "flood_area_km2": {
      "count": 1198.0,
      "mean": 189.2790477462,
      "std": 371.0360350608,
      "min": 0.0147,
      "25%": 15.3951,
      "50%": 70.2084,
      "75%": 224.3579,
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
      "mean": 175.9307327014,
      "std": 351.7913438917,
      "min": 0.0028,
      "25%": 14.5393,
      "50%": 62.3161,
      "75%": 190.0684,
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
      "S1": 1191,
      "NDWI": 7
    }
  },
  "estimated_dispersion": {
    "model_1": 3.6102369105,
    "model_2": 3.5197433747,
    "model_3": 3.2757392243
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
- Default flood area is Sentinel-1 new water over the eligible AOI, with Track A S2 NDWI only where S1 is missing. Observed S1 zero is retained. Historical inputs retain their recorded sources. Under opt-in sits_primary routing, SITS-NDWI is used on retained clear tiles with Sentinel-1 converted to the SITS-NDWI scale (S1_TO_SITS) where SITS cannot measure the district; the satellite-source fixed effect, by-source and SITS-only subsamples are sensitivity analyses, not a correction.
- Source fixed-effects NB2 is secondary and susceptible to incidental-parameter bias; ordinary SE are reported.
- district-based urbanization tercile cutpoints: [0.1369414084546159, 0.2557930624760398]; unknown Census matches cannot be assigned an urbanization level
