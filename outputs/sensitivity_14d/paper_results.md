# Coverage disparity results

News window: 14 days.
N = 1074 district-event observations; 403 districts; 153 parent events; 63 source floods.
Excluded: 474 of 1548 registry rows.
Spearman rho = 0.1523345329; p = 5.282e-07.

Primary model: log E[article_count] = intercept + beta_flood log(1 + flood_area_km2) + beta_urban urban_population_share. NB2 variance = mu + alpha * mu²; alpha is estimated.

M1/M2/M3 use the same complete-case sample. Fixed decision rule: positive coefficient and two-sided p < 0.05; prefer state-clustered inference when the prespecified cluster rule is met. No cutoff on urbanization enters the model.

| Model / SE | Term | Coefficient (SE) | 95% CI | p | IRR [95% CI] | 10pp IRR [95% CI] |
| --- | --- | --- | --- | --- | --- | --- |
| model_1 / ordinary | Intercept | 3.7467 (0.1406) | [3.4713, 4.0222] | 1.488e-156 | 42.382 [32.177, 55.825] | — |
| model_1 / ordinary | log_flood_area | -0.0760 (0.0306) | [-0.1360, -0.0160] | 0.01302 | 0.927 [0.873, 0.984] | — |
| model_1 / state_clustered | Intercept | 3.7467 (0.5019) | [2.7186, 4.7748] | 3.945e-08 | 42.382 [15.159, 118.493] | — |
| model_1 / state_clustered | log_flood_area | -0.0760 (0.1108) | [-0.3030, 0.1510] | 0.4984 | 0.927 [0.739, 1.163] | — |
| model_2 / ordinary | Intercept | 3.3986 (0.1942) | [3.0180, 3.7792] | 1.375e-68 | 29.923 [20.451, 43.781] | — |
| model_2 / ordinary | log_flood_area | -0.0319 (0.0351) | [-0.1006, 0.0368] | 0.3634 | 0.969 [0.904, 1.038] | — |
| model_2 / ordinary | urban_population_share | 0.6828 (0.2862) | [0.1219, 1.2437] | 0.01704 | 1.979 [1.130, 3.468] | 1.071 [1.012, 1.132] |
| model_2 / state_clustered | Intercept | 3.3986 (0.6282) | [2.1119, 4.6854] | 9.045e-06 | 29.923 [8.264, 108.352] | — |
| model_2 / state_clustered | log_flood_area | -0.0319 (0.1264) | [-0.2909, 0.2271] | 0.8029 | 0.969 [0.748, 1.255] | — |
| model_2 / state_clustered | urban_population_share | 0.6828 (0.3818) | [-0.0992, 1.4648] | 0.08452 | 1.979 [0.906, 4.327] | 1.071 [0.990, 1.158] |
| model_3 / ordinary | Intercept | 3.1775 (0.3230) | [2.5444, 3.8106] | 7.804e-23 | 23.987 [12.736, 45.179] | — |
| model_3 / ordinary | C(year)[T.2016] | 0.2650 (0.3939) | [-0.5070, 1.0370] | 0.5011 | 1.303 [0.602, 2.821] | — |
| model_3 / ordinary | C(year)[T.2017] | 0.2218 (0.3083) | [-0.3824, 0.8260] | 0.4718 | 1.248 [0.682, 2.284] | — |
| model_3 / ordinary | C(year)[T.2018] | 0.5593 (0.3146) | [-0.0572, 1.1759] | 0.0754 | 1.749 [0.944, 3.241] | — |
| model_3 / ordinary | C(year)[T.2019] | 0.2888 (0.2916) | [-0.2828, 0.8604] | 0.322 | 1.335 [0.754, 2.364] | — |
| model_3 / ordinary | C(year)[T.2020] | -2.0115 (0.3102) | [-2.6194, -1.4035] | 8.883e-11 | 0.134 [0.073, 0.246] | — |
| model_3 / ordinary | C(year)[T.2021] | -0.5772 (0.3215) | [-1.2073, 0.0529] | 0.07257 | 0.561 [0.299, 1.054] | — |
| model_3 / ordinary | C(year)[T.2022] | 0.1743 (0.3859) | [-0.5820, 0.9306] | 0.6515 | 1.190 [0.559, 2.536] | — |
| model_3 / ordinary | C(year)[T.2023] | -0.2580 (0.3252) | [-0.8955, 0.3794] | 0.4276 | 0.773 [0.408, 1.461] | — |
| model_3 / ordinary | C(year)[T.2024] | 0.1544 (0.3298) | [-0.4920, 0.8008] | 0.6397 | 1.167 [0.611, 2.227] | — |
| model_3 / ordinary | C(year)[T.2025] | 0.2005 (0.3462) | [-0.4780, 0.8791] | 0.5624 | 1.222 [0.620, 2.409] | — |
| model_3 / ordinary | log_flood_area | -0.0044 (0.0377) | [-0.0784, 0.0695] | 0.9064 | 0.996 [0.925, 1.072] | — |
| model_3 / ordinary | urban_population_share | 0.9074 (0.2819) | [0.3549, 1.4600] | 0.001288 | 2.478 [1.426, 4.306] | 1.095 [1.036, 1.157] |
| model_3 / state_clustered | Intercept | 3.1775 (0.5042) | [2.1448, 4.2102] | 8.138e-07 | 23.987 [8.540, 67.372] | — |
| model_3 / state_clustered | C(year)[T.2016] | 0.2650 (0.4323) | [-0.6205, 1.1505] | 0.5448 | 1.303 [0.538, 3.160] | — |
| model_3 / state_clustered | C(year)[T.2017] | 0.2218 (0.4032) | [-0.6041, 1.0476] | 0.5866 | 1.248 [0.547, 2.851] | — |
| model_3 / state_clustered | C(year)[T.2018] | 0.5593 (0.8293) | [-1.1394, 2.2580] | 0.5056 | 1.749 [0.320, 9.564] | — |
| model_3 / state_clustered | C(year)[T.2019] | 0.2888 (0.3731) | [-0.4755, 1.0531] | 0.4454 | 1.335 [0.622, 2.867] | — |
| model_3 / state_clustered | C(year)[T.2020] | -2.0115 (0.5222) | [-3.0811, -0.9419] | 0.0006238 | 0.134 [0.046, 0.390] | — |
| model_3 / state_clustered | C(year)[T.2021] | -0.5772 (0.5382) | [-1.6796, 0.5252] | 0.2926 | 0.561 [0.186, 1.691] | — |
| model_3 / state_clustered | C(year)[T.2022] | 0.1743 (0.4179) | [-0.6818, 1.0304] | 0.6798 | 1.190 [0.506, 2.802] | — |
| model_3 / state_clustered | C(year)[T.2023] | -0.2580 (0.5120) | [-1.3069, 0.7908] | 0.6183 | 0.773 [0.271, 2.205] | — |
| model_3 / state_clustered | C(year)[T.2024] | 0.1544 (0.3654) | [-0.5941, 0.9028] | 0.6759 | 1.167 [0.552, 2.467] | — |
| model_3 / state_clustered | C(year)[T.2025] | 0.2005 (0.4533) | [-0.7281, 1.1291] | 0.6616 | 1.222 [0.483, 3.093] | — |
| model_3 / state_clustered | log_flood_area | -0.0044 (0.0922) | [-0.1933, 0.1844] | 0.962 | 0.996 [0.824, 1.203] | — |
| model_3 / state_clustered | urban_population_share | 0.9074 (0.4507) | [-0.0159, 1.8307] | 0.0538 | 2.478 [0.984, 6.238] | 1.095 [0.998, 1.201] |
| model_2_source_fe / ordinary | Intercept | 4.3015 (0.9119) | [2.5143, 6.0887] | 2.391e-06 | 73.809 [12.357, 440.849] | — |
| model_2_source_fe / ordinary | C(satellite_source)[T.S1] | -0.9477 (0.9176) | [-2.7462, 0.8508] | 0.3017 | 0.388 [0.064, 2.342] | — |
| model_2_source_fe / ordinary | log_flood_area | -0.0239 (0.0356) | [-0.0937, 0.0459] | 0.5025 | 0.976 [0.911, 1.047] | — |
| model_2_source_fe / ordinary | urban_population_share | 0.7038 (0.2845) | [0.1463, 1.2614] | 0.01336 | 2.021 [1.158, 3.530] | 1.073 [1.015, 1.134] |
| model_2_source_fe / state_clustered | Intercept | 4.3015 (0.6871) | [2.8941, 5.7089] | 9.104e-07 | 73.809 [18.067, 301.535] | — |
| model_2_source_fe / state_clustered | C(satellite_source)[T.S1] | -0.9477 (0.8925) | [-2.7760, 0.8805] | 0.2974 | 0.388 [0.062, 2.412] | — |
| model_2_source_fe / state_clustered | log_flood_area | -0.0239 (0.1327) | [-0.2957, 0.2479] | 0.8584 | 0.976 [0.744, 1.281] | — |
| model_2_source_fe / state_clustered | urban_population_share | 0.7038 (0.4059) | [-0.1276, 1.5352] | 0.09391 | 2.021 [0.880, 4.642] | 1.073 [0.987, 1.166] |
| model_2_by_source_S1 / ordinary | Intercept | 3.3448 (0.1966) | [2.9594, 3.7301] | 6.541e-65 | 28.354 [19.287, 41.682] | — |
| model_2_by_source_S1 / ordinary | log_flood_area | -0.0219 (0.0357) | [-0.0918, 0.0480] | 0.5399 | 0.978 [0.912, 1.049] | — |
| model_2_by_source_S1 / ordinary | urban_population_share | 0.7066 (0.2845) | [0.1491, 1.2642] | 0.01299 | 2.027 [1.161, 3.540] | 1.073 [1.015, 1.135] |
| model_2_by_source_S1 / state_clustered | Intercept | 3.3448 (0.6741) | [1.9639, 4.7256] | 3.08e-05 | 28.354 [7.127, 112.801] | — |
| model_2_by_source_S1 / state_clustered | log_flood_area | -0.0219 (0.1327) | [-0.2938, 0.2501] | 0.8704 | 0.978 [0.745, 1.284] | — |
| model_2_by_source_S1 / state_clustered | urban_population_share | 0.7066 (0.4079) | [-0.1289, 1.5422] | 0.09422 | 2.027 [0.879, 4.675] | 1.073 [0.987, 1.167] |
| source_event_robustness / ordinary | Intercept | 3.7208 (0.8119) | [2.1295, 5.3121] | 4.587e-06 | 41.299 [8.411, 202.783] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0317-IND] | -3.7980 (0.8921) | [-5.5465, -2.0494] | 2.07e-05 | 0.022 [0.004, 0.129] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0333-IND] | -2.7027 (1.4256) | [-5.4968, 0.0914] | 0.05798 | 0.067 [0.004, 1.096] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0374-IND] | -0.6807 (0.9472) | [-2.5372, 1.1759] | 0.4724 | 0.506 [0.079, 3.241] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0406-IND] | -1.0133 (0.8983) | [-2.7740, 0.7473] | 0.2593 | 0.363 [0.062, 2.111] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2015-0504-IND] | -0.1951 (0.9996) | [-2.1542, 1.7641] | 0.8453 | 0.823 [0.116, 5.836] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0139-IND] | -1.9020 (1.0378) | [-3.9362, 0.1321] | 0.06685 | 0.149 [0.020, 1.141] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0239-IND] | -0.5505 (0.9328) | [-2.3786, 1.2777] | 0.5551 | 0.577 [0.093, 3.588] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0267-IND] | -0.0579 (0.9485) | [-1.9169, 1.8011] | 0.9513 | 0.944 [0.147, 6.057] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0271-IND] | -2.9043 (0.9175) | [-4.7024, -1.1061] | 0.001548 | 0.055 [0.009, 0.331] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2016-0554-IND] | 0.5076 (1.3891) | [-2.2150, 3.2301] | 0.7148 | 1.661 [0.109, 25.282] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0180-IND] | -2.6662 (0.8572) | [-4.3463, -0.9862] | 0.001868 | 0.070 [0.013, 0.373] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0289-IND] | -1.0565 (0.8712) | [-2.7641, 0.6511] | 0.2253 | 0.348 [0.063, 1.918] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0290-IND] | -1.8360 (1.1361) | [-4.0627, 0.3906] | 0.1061 | 0.159 [0.017, 1.478] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0294-IND] | -6.5426 (1.4186) | [-9.3229, -3.7622] | 3.987e-06 | 0.001 [0.000, 0.023] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0342-IND] | -0.4779 (0.8447) | [-2.1334, 1.1776] | 0.5715 | 0.620 [0.118, 3.247] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0364-IND] | 0.7270 (1.2288) | [-1.6815, 3.1354] | 0.5541 | 2.069 [0.186, 22.999] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2017-0517-IND] | -1.5256 (0.8661) | [-3.2232, 0.1720] | 0.07817 | 0.217 [0.040, 1.188] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0205-IND] | -0.8971 (0.9830) | [-2.8238, 1.0296] | 0.3615 | 0.408 [0.059, 2.800] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0213-IND] | -2.8206 (1.2491) | [-5.2687, -0.3725] | 0.02394 | 0.060 [0.005, 0.689] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0216-IND] | -0.3543 (1.3869) | [-3.0727, 2.3640] | 0.7984 | 0.702 [0.046, 10.633] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0286-IND] | -2.0488 (1.1443) | [-4.2916, 0.1940] | 0.07339 | 0.129 [0.014, 1.214] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0295-IND] | 0.2336 (0.8154) | [-1.3645, 1.8318] | 0.7745 | 1.263 [0.256, 6.245] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0345-IND] | -1.8183 (0.9678) | [-3.7151, 0.0785] | 0.06027 | 0.162 [0.024, 1.082] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0370-IND] | -2.6498 (0.8765) | [-4.3677, -0.9318] | 0.002502 | 0.071 [0.013, 0.394] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2018-0372-IND] | -3.3206 (0.9746) | [-5.2307, -1.4104] | 0.0006565 | 0.036 [0.005, 0.244] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0288-IND] | 0.7044 (1.2241) | [-1.6949, 3.1036] | 0.565 | 2.023 [0.184, 22.279] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0331-IND] | -1.0872 (0.8158) | [-2.6861, 0.5118] | 0.1827 | 0.337 [0.068, 1.668] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0383-IND] | 0.3449 (0.8695) | [-1.3593, 2.0491] | 0.6916 | 1.412 [0.257, 7.761] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0499-IND] | -2.2053 (0.9223) | [-4.0130, -0.3976] | 0.0168 | 0.110 [0.018, 0.672] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2019-0574-IND] | -2.6018 (1.0393) | [-4.6388, -0.5648] | 0.0123 | 0.074 [0.010, 0.568] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0206-IND] | -0.8142 (1.0797) | [-2.9304, 1.3020] | 0.4508 | 0.443 [0.053, 3.677] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0304-IND] | -4.1177 (0.8147) | [-5.7144, -2.5211] | 4.313e-07 | 0.016 [0.003, 0.080] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2020-0446-IND] | -2.3074 (0.8749) | [-4.0222, -0.5927] | 0.008355 | 0.100 [0.018, 0.553] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0316-IND] | -3.9357 (0.8614) | [-5.6240, -2.2474] | 4.899e-06 | 0.020 [0.004, 0.106] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0366-IND] | -3.2938 (1.2698) | [-5.7825, -0.8051] | 0.009487 | 0.037 [0.003, 0.447] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0435-IND] | -7.4240 (1.3266) | [-10.0242, -4.8238] | 2.193e-08 | 0.001 [0.000, 0.008] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0458-IND] | -1.3215 (1.0791) | [-3.4365, 0.7936] | 0.2207 | 0.267 [0.032, 2.211] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0585-IND] | -2.1829 (1.0819) | [-4.3034, -0.0624] | 0.04363 | 0.113 [0.014, 0.939] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0677-IND] | 0.5620 (1.0310) | [-1.4588, 2.5828] | 0.5857 | 1.754 [0.233, 13.234] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0722-IND] | -1.9661 (0.8521) | [-3.6363, -0.2960] | 0.02103 | 0.140 [0.026, 0.744] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2021-0748-IND] | -0.0902 (1.1358) | [-2.3163, 2.1359] | 0.9367 | 0.914 [0.099, 8.465] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0293-IND] | -0.7726 (0.8405) | [-2.4200, 0.8748] | 0.358 | 0.462 [0.089, 2.398] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2022-0539-IND] | -3.4901 (1.0403) | [-5.5290, -1.4513] | 0.0007935 | 0.030 [0.004, 0.234] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0330-IND] | 0.4421 (1.0805) | [-1.6757, 2.5598] | 0.6824 | 1.556 [0.187, 12.933] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0359-IND] | -1.9901 (0.8548) | [-3.6655, -0.3147] | 0.0199 | 0.137 [0.026, 0.730] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0428-IND] | -2.4791 (0.8224) | [-4.0910, -0.8673] | 0.002574 | 0.084 [0.017, 0.420] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0486-IND] | -1.1835 (1.0783) | [-3.2970, 0.9300] | 0.2724 | 0.306 [0.037, 2.534] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2023-0846-IND] | 0.9699 (1.2201) | [-1.4214, 3.3612] | 0.4266 | 2.638 [0.241, 28.824] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0399-IND] | -6.8487 (1.3554) | [-9.5052, -4.1923] | 4.347e-07 | 0.001 [0.000, 0.015] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0481-IND] | -0.9265 (0.8360) | [-2.5650, 0.7120] | 0.2677 | 0.396 [0.077, 2.038] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0561-IND] | 1.1807 (1.2266) | [-1.2234, 3.5848] | 0.3358 | 3.257 [0.294, 36.046] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0624-IND] | -0.9073 (1.1340) | [-3.1298, 1.3153] | 0.4237 | 0.404 [0.044, 3.726] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2024-0647-IND] | -1.2497 (0.8694) | [-2.9537, 0.4544] | 0.1506 | 0.287 [0.052, 1.575] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0402-IND] | -0.9965 (0.8576) | [-2.6773, 0.6844] | 0.2452 | 0.369 [0.069, 1.982] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0469-IND] | -1.4254 (1.0083) | [-3.4017, 0.5508] | 0.1575 | 0.240 [0.033, 1.735] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0751-IND] | -1.1072 (0.9627) | [-2.9940, 0.7795] | 0.2501 | 0.330 [0.050, 2.180] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0803-IND] | -1.8370 (0.9583) | [-3.7152, 0.0412] | 0.05525 | 0.159 [0.024, 1.042] | — |
| source_event_robustness / ordinary | C(source_record_id)[T.2025-0859-IND] | -1.8936 (0.8805) | [-3.6193, -0.1679] | 0.0315 | 0.151 [0.027, 0.845] | — |
| source_event_robustness / ordinary | log_flood_area | 0.1141 (0.0430) | [0.0298, 0.1984] | 0.007987 | 1.121 [1.030, 1.219] | — |
| source_event_robustness / ordinary | urban_population_share | 1.0148 (0.3054) | [0.4162, 1.6135] | 0.0008921 | 2.759 [1.516, 5.020] | 1.107 [1.042, 1.175] |

Flood IRR is per one-unit increase in log(1 + km²); the urbanization IRR is per 0→1 change, with 10 percentage points reported separately.

## Model availability

- model_1: estimated
- model_2: estimated
- model_3: estimated
- model_2_source_fe: estimated (sensitivity)
- model_2_by_source_S1: estimated (sensitivity)
- model_2_by_source_NDWI: insufficient sample: N=5 < 20
- source_event_robustness: estimated secondary unconditional source fixed-effects NB2; 59 source events
- exposed_population_robustness: not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used

## Descriptive distributions and missingness

```json
{
  "distributions": {
    "flood_area_km2": {
      "count": 1074.0,
      "mean": 197.391114432,
      "std": 385.9047580035,
      "min": 0.0147,
      "25%": 16.61985,
      "50%": 75.8401,
      "75%": 233.5644,
      "max": 5894.8599
    },
    "article_count": {
      "count": 1074.0,
      "mean": 31.3687150838,
      "std": 83.2359965235,
      "min": 0.0,
      "25%": 0.0,
      "50%": 3.5,
      "75%": 26.75,
      "max": 1112.0
    },
    "urban_population_share": {
      "count": 1074.0,
      "mean": 0.2268479017,
      "std": 0.1991048829,
      "min": 0.0,
      "25%": 0.0876401087,
      "50%": 0.1516732422,
      "75%": 0.3011023494,
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
    "flood_area_km2": 71,
    "article_count": 344,
    "urban_population_share": 119
  },
  "exclusion_counts": {
    "article_collection_incomplete": 344,
    "article_count_missing_or_invalid": 344,
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
      "success": 1074,
      "total": 1548,
      "rate": 0.6937984496
    },
    "satellite_source_counts": {
      "S1": 1069,
      "NDWI": 5
    }
  },
  "estimated_dispersion": {
    "model_1": 4.1306310561,
    "model_2": 4.1090830928,
    "model_3": 3.760385848
  },
  "article_count_variance": 6928.2311172664,
  "article_count_mean": 31.3687150838
}
```

## Selection check

```
urbanization_group  rows  excluded  exclusion_rate
              high   387        65        0.167959
               low   660       175        0.265152
            medium   382       115        0.301047
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
