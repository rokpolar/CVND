# Relative coverage scoring

News window: 30 days.

Status: available. Input rows: 1548; eligible: 1198; source events: 63; scored: 1198.

Formula: `article_count ~ log_flood_area + log_population + year_c`. Estimated NB2 alpha; source-group five-fold OOF only.

Labels identify exploratory relative coverage candidates under the fitted observed-count distribution.

## Settings and provenance

```json
{
  "settings": {
    "min_rows": 50,
    "min_sources": 10,
    "min_train_rows": 30,
    "min_train_sources": 5,
    "rows_per_parameter": 5,
    "tail_threshold": 0.05,
    "n_splits": 5
  },
  "transforms": {
    "log_flood_area": "log1p(flood_area_km2)",
    "log_population": "log(total_population / 1000000)",
    "year_c": "start_date.year - 2020"
  },
  "input_sha256": "59f3ede8c5fee2b7e9bab068a8a0729a01f4765538804ccd614238af56c963e5",
  "git_sha": "4f7a28e5b41b390fc2aabe77db46b713a4cbe2c4",
  "library_versions": {
    "numpy": "2.5.2",
    "pandas": "3.0.5",
    "scipy": "1.18.0",
    "statsmodels": "0.14.6",
    "scikit-learn": "1.9.0",
    "matplotlib": "3.11.1"
  }
}
```

## OOF diagnostics

NB2/Poisson comparison uses common successful test rows only. Available-model diagnostics have separate coverage.

```json
{
  "diagnostics_available": {
    "nb2": {
      "n_rows": 1198,
      "n_sources": 63,
      "row_weighted": {
        "mae": 61.29377870693645,
        "mean_negative_log_predictive_probability": 4.255657292570891,
        "coverage_90": 0.9524207011686143,
        "mean_interval_width_90": 221.60016694490818,
        "observed_zero_rate": 0.20868113522537562,
        "mean_predicted_zero_probability": 0.2384826782593484
      },
      "source_macro": {
        "mae": 86.06192115791258,
        "mean_negative_log_predictive_probability": 5.055063090407506,
        "coverage_90": 0.9226105695387281,
        "mean_interval_width_90": 226.17748139459448,
        "observed_zero_rate": 0.12469205690391293,
        "mean_predicted_zero_probability": 0.2383868456287647
      }
    },
    "poisson": {
      "n_rows": 1198,
      "n_sources": 63,
      "row_weighted": {
        "mae": 62.1391784372488,
        "mean_negative_log_predictive_probability": 71.81449771813158,
        "coverage_90": 0.08848080133555926,
        "mean_interval_width_90": 22.06010016694491,
        "observed_zero_rate": 0.20868113522537562,
        "mean_predicted_zero_probability": 1.924762878717857e-07
      },
      "source_macro": {
        "mae": 86.25884634327932,
        "mean_negative_log_predictive_probability": 128.21848486120163,
        "coverage_90": 0.10878254660702133,
        "mean_interval_width_90": 22.657753454039675,
        "observed_zero_rate": 0.12469205690391293,
        "mean_predicted_zero_probability": 2.482151031440571e-07
      }
    }
  },
  "poisson_comparison_common_success": {
    "scope": "Only test rows with both NB2 and Poisson predictions; source_macro averages within source, then equally across sources.",
    "n_rows": 1198,
    "fraction_of_eligible": 1.0,
    "nb2": {
      "n_rows": 1198,
      "n_sources": 63,
      "row_weighted": {
        "mae": 61.29377870693645,
        "mean_negative_log_predictive_probability": 4.255657292570891,
        "coverage_90": 0.9524207011686143,
        "mean_interval_width_90": 221.60016694490818,
        "observed_zero_rate": 0.20868113522537562,
        "mean_predicted_zero_probability": 0.2384826782593484
      },
      "source_macro": {
        "mae": 86.06192115791258,
        "mean_negative_log_predictive_probability": 5.055063090407506,
        "coverage_90": 0.9226105695387281,
        "mean_interval_width_90": 226.17748139459448,
        "observed_zero_rate": 0.12469205690391293,
        "mean_predicted_zero_probability": 0.2383868456287647
      }
    },
    "poisson": {
      "n_rows": 1198,
      "n_sources": 63,
      "row_weighted": {
        "mae": 62.1391784372488,
        "mean_negative_log_predictive_probability": 71.81449771813158,
        "coverage_90": 0.08848080133555926,
        "mean_interval_width_90": 22.06010016694491,
        "observed_zero_rate": 0.20868113522537562,
        "mean_predicted_zero_probability": 1.924762878717857e-07
      },
      "source_macro": {
        "mae": 86.25884634327932,
        "mean_negative_log_predictive_probability": 128.21848486120163,
        "coverage_90": 0.10878254660702133,
        "mean_interval_width_90": 22.657753454039675,
        "observed_zero_rate": 0.12469205690391293,
        "mean_predicted_zero_probability": 2.482151031440571e-07
      }
    }
  },
  "calibration": {
    "nb2": [
      {
        "bin": 0,
        "n": 120,
        "expected_min": 19.68562497390902,
        "expected_max": 34.92123660993571,
        "observed_mean": 63.233333333333334,
        "expected_mean": 29.56501086895331
      },
      {
        "bin": 1,
        "n": 120,
        "expected_min": 34.92241406767783,
        "expected_max": 38.082799290614,
        "observed_mean": 52.425,
        "expected_mean": 36.62845656986266
      },
      {
        "bin": 2,
        "n": 120,
        "expected_min": 38.08738178302869,
        "expected_max": 40.15814713226969,
        "observed_mean": 49.05,
        "expected_mean": 39.1945499311475
      },
      {
        "bin": 3,
        "n": 119,
        "expected_min": 40.20103237024247,
        "expected_max": 42.75246038606892,
        "observed_mean": 39.46218487394958,
        "expected_mean": 41.529752827783355
      },
      {
        "bin": 4,
        "n": 120,
        "expected_min": 42.77434572853396,
        "expected_max": 45.42555501670215,
        "observed_mean": 50.708333333333336,
        "expected_mean": 44.08033335823826
      },
      {
        "bin": 5,
        "n": 120,
        "expected_min": 45.447661667479515,
        "expected_max": 48.46450355493801,
        "observed_mean": 38.00833333333333,
        "expected_mean": 46.90867949743569
      },
      {
        "bin": 6,
        "n": 119,
        "expected_min": 48.51716982061166,
        "expected_max": 51.85252619485491,
        "observed_mean": 40.89915966386555,
        "expected_mean": 50.04598015885269
      },
      {
        "bin": 7,
        "n": 120,
        "expected_min": 51.915317691144644,
        "expected_max": 56.188456742518746,
        "observed_mean": 31.475,
        "expected_mean": 53.926626518386584
      },
      {
        "bin": 8,
        "n": 120,
        "expected_min": 56.193522673046246,
        "expected_max": 63.30563286389402,
        "observed_mean": 86.8,
        "expected_mean": 59.097346781062726
      },
      {
        "bin": 9,
        "n": 120,
        "expected_min": 63.403134929156415,
        "expected_max": 104.15224909025447,
        "observed_mean": 31.541666666666668,
        "expected_mean": 73.20529971767411
      }
    ],
    "poisson": [
      {
        "bin": 0,
        "n": 120,
        "expected_min": 9.773689734291008,
        "expected_max": 25.46567924942301,
        "observed_mean": 62.233333333333334,
        "expected_mean": 19.672871003320246
      },
      {
        "bin": 1,
        "n": 120,
        "expected_min": 25.466720886943236,
        "expected_max": 32.21008178825638,
        "observed_mean": 39.641666666666666,
        "expected_mean": 29.465371240957374
      },
      {
        "bin": 2,
        "n": 120,
        "expected_min": 32.21132745940911,
        "expected_max": 36.082401263327,
        "observed_mean": 46.666666666666664,
        "expected_mean": 34.27255536281836
      },
      {
        "bin": 3,
        "n": 119,
        "expected_min": 36.0885524276162,
        "expected_max": 39.32115055113183,
        "observed_mean": 47.91596638655462,
        "expected_mean": 37.643410186144486
      },
      {
        "bin": 4,
        "n": 120,
        "expected_min": 39.33514610837181,
        "expected_max": 43.108735417120414,
        "observed_mean": 27.791666666666668,
        "expected_mean": 41.1217868312207
      },
      {
        "bin": 5,
        "n": 120,
        "expected_min": 43.130269615818364,
        "expected_max": 47.8579819280757,
        "observed_mean": 42.041666666666664,
        "expected_mean": 45.36713586508897
      },
      {
        "bin": 6,
        "n": 119,
        "expected_min": 47.9116372889715,
        "expected_max": 52.43265091997106,
        "observed_mean": 33.596638655462186,
        "expected_mean": 50.14493037210197
      },
      {
        "bin": 7,
        "n": 120,
        "expected_min": 52.515661292225275,
        "expected_max": 60.03648862241535,
        "observed_mean": 56.28333333333333,
        "expected_mean": 56.42129276319907
      },
      {
        "bin": 8,
        "n": 120,
        "expected_min": 60.173276543190326,
        "expected_max": 72.67876465574166,
        "observed_mean": 39.03333333333333,
        "expected_mean": 65.68535642019808
      },
      {
        "bin": 9,
        "n": 120,
        "expected_min": 72.71318106830677,
        "expected_max": 206.0632359881595,
        "observed_mean": 88.40833333333333,
        "expected_mean": 91.39620759410704
      }
    ]
  },
  "folds": [
    {
      "fold_id": 0,
      "n_train": 958,
      "n_test": 240,
      "n_train_sources": 53,
      "n_test_sources": 10,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0317-IND",
        "2015-0333-IND",
        "2015-0374-IND",
        "2015-0406-IND",
        "2016-0139-IND",
        "2016-0239-IND",
        "2016-0267-IND",
        "2016-0271-IND",
        "2017-0180-IND",
        "2017-0289-IND",
        "2017-0290-IND",
        "2017-0294-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0495-IND",
        "2017-0517-IND",
        "2018-0205-IND",
        "2018-0213-IND",
        "2018-0216-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2019-0288-IND",
        "2019-0574-IND",
        "2020-0206-IND",
        "2020-0304-IND",
        "2020-0446-IND",
        "2021-0316-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0585-IND",
        "2021-0677-IND",
        "2021-0681-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2022-0293-IND",
        "2022-0539-IND",
        "2022-0590-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2023-0846-IND",
        "2024-0399-IND",
        "2024-0481-IND",
        "2024-0647-IND",
        "2025-0402-IND",
        "2025-0469-IND",
        "2025-0690-IND",
        "2025-0751-IND",
        "2025-0803-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2015-0504-IND",
        "2016-0554-IND",
        "2018-0372-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0499-IND",
        "2021-0366-IND",
        "2023-0330-IND",
        "2024-0561-IND",
        "2024-0624-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.515544677421052,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.876132135809853,
            "log_flood_area": -0.052894657233906565,
            "log_population": 0.12317377059872114,
            "year_c": -0.00644908052047541,
            "alpha": 3.515544677421052
          }
        },
        "poisson": {
          "status": "available",
          "converged": true,
          "alpha": null,
          "parameter_count": 4,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 4.0351757795134064,
            "log_flood_area": -0.0960192884349094,
            "log_population": 0.14817387540726343,
            "year_c": -0.021035857462015143
          }
        }
      }
    },
    {
      "fold_id": 1,
      "n_train": 958,
      "n_test": 240,
      "n_train_sources": 52,
      "n_test_sources": 11,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0317-IND",
        "2015-0374-IND",
        "2015-0504-IND",
        "2016-0239-IND",
        "2016-0271-IND",
        "2016-0554-IND",
        "2017-0180-IND",
        "2017-0289-IND",
        "2017-0290-IND",
        "2017-0294-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0495-IND",
        "2018-0205-IND",
        "2018-0213-IND",
        "2018-0216-IND",
        "2018-0295-IND",
        "2018-0372-IND",
        "2019-0288-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0499-IND",
        "2019-0574-IND",
        "2020-0206-IND",
        "2020-0446-IND",
        "2021-0316-IND",
        "2021-0366-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0677-IND",
        "2021-0681-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2022-0293-IND",
        "2022-0539-IND",
        "2022-0590-IND",
        "2023-0330-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2024-0399-IND",
        "2024-0481-IND",
        "2024-0561-IND",
        "2024-0624-IND",
        "2024-0647-IND",
        "2025-0402-IND",
        "2025-0469-IND",
        "2025-0690-IND",
        "2025-0751-IND",
        "2025-0803-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2015-0333-IND",
        "2015-0406-IND",
        "2016-0139-IND",
        "2016-0267-IND",
        "2017-0517-IND",
        "2018-0286-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2020-0304-IND",
        "2021-0585-IND",
        "2023-0846-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.3887997385092143,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 4.217466992821596,
            "log_flood_area": -0.08737963401282295,
            "log_population": 0.29076483708896916,
            "year_c": -0.03140605859070168,
            "alpha": 3.3887997385092143
          }
        },
        "poisson": {
          "status": "available",
          "converged": true,
          "alpha": null,
          "parameter_count": 4,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 4.565171068552661,
            "log_flood_area": -0.19045991804583187,
            "log_population": 0.37665388829664276,
            "year_c": -0.07986789217791282
          }
        }
      }
    },
    {
      "fold_id": 2,
      "n_train": 958,
      "n_test": 240,
      "n_train_sources": 49,
      "n_test_sources": 14,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0317-IND",
        "2015-0333-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0139-IND",
        "2016-0239-IND",
        "2016-0267-IND",
        "2016-0554-IND",
        "2017-0180-IND",
        "2017-0290-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0517-IND",
        "2018-0205-IND",
        "2018-0216-IND",
        "2018-0286-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2018-0372-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0499-IND",
        "2020-0206-IND",
        "2020-0304-IND",
        "2021-0366-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0585-IND",
        "2021-0677-IND",
        "2021-0681-IND",
        "2022-0293-IND",
        "2022-0539-IND",
        "2022-0590-IND",
        "2023-0330-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2023-0846-IND",
        "2024-0399-IND",
        "2024-0481-IND",
        "2024-0561-IND",
        "2024-0624-IND",
        "2024-0647-IND",
        "2025-0402-IND",
        "2025-0469-IND",
        "2025-0751-IND",
        "2025-0803-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2015-0374-IND",
        "2016-0271-IND",
        "2017-0289-IND",
        "2017-0294-IND",
        "2017-0495-IND",
        "2018-0213-IND",
        "2018-0295-IND",
        "2019-0288-IND",
        "2019-0574-IND",
        "2020-0446-IND",
        "2021-0316-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2025-0690-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.430780174405306,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.7622078386164945,
            "log_flood_area": -0.02822109968341105,
            "log_population": 0.3115688359505521,
            "year_c": -0.01700489643877507,
            "alpha": 3.430780174405306
          }
        },
        "poisson": {
          "status": "available",
          "converged": true,
          "alpha": null,
          "parameter_count": 4,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 4.025027425640753,
            "log_flood_area": -0.09653829498027272,
            "log_population": 0.3415168026982361,
            "year_c": -0.049506100807867395
          }
        }
      }
    },
    {
      "fold_id": 3,
      "n_train": 959,
      "n_test": 239,
      "n_train_sources": 49,
      "n_test_sources": 14,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0317-IND",
        "2015-0333-IND",
        "2015-0374-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0139-IND",
        "2016-0239-IND",
        "2016-0267-IND",
        "2016-0271-IND",
        "2016-0554-IND",
        "2017-0180-IND",
        "2017-0289-IND",
        "2017-0294-IND",
        "2017-0495-IND",
        "2017-0517-IND",
        "2018-0213-IND",
        "2018-0216-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2018-0372-IND",
        "2019-0288-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0499-IND",
        "2019-0574-IND",
        "2020-0206-IND",
        "2020-0304-IND",
        "2020-0446-IND",
        "2021-0316-IND",
        "2021-0366-IND",
        "2021-0585-IND",
        "2021-0677-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2022-0293-IND",
        "2022-0590-IND",
        "2023-0330-IND",
        "2023-0846-IND",
        "2024-0481-IND",
        "2024-0561-IND",
        "2024-0624-IND",
        "2024-0647-IND",
        "2025-0469-IND",
        "2025-0690-IND",
        "2025-0803-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2017-0290-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2018-0205-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0681-IND",
        "2022-0539-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2024-0399-IND",
        "2025-0402-IND",
        "2025-0751-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.6748747680316645,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 4.335892037769352,
            "log_flood_area": -0.149957098783821,
            "log_population": 0.13232947591313274,
            "year_c": -0.03610453821789048,
            "alpha": 3.6748747680316645
          }
        },
        "poisson": {
          "status": "available",
          "converged": true,
          "alpha": null,
          "parameter_count": 4,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 4.591046593108985,
            "log_flood_area": -0.2577797129804066,
            "log_population": 0.33065320794034475,
            "year_c": -0.09174050729198692
          }
        }
      }
    },
    {
      "fold_id": 4,
      "n_train": 959,
      "n_test": 239,
      "n_train_sources": 49,
      "n_test_sources": 14,
      "train_source_ids": [
        "2015-0333-IND",
        "2015-0374-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0139-IND",
        "2016-0267-IND",
        "2016-0271-IND",
        "2016-0554-IND",
        "2017-0289-IND",
        "2017-0290-IND",
        "2017-0294-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0495-IND",
        "2017-0517-IND",
        "2018-0205-IND",
        "2018-0213-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2018-0372-IND",
        "2019-0288-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0499-IND",
        "2019-0574-IND",
        "2020-0304-IND",
        "2020-0446-IND",
        "2021-0316-IND",
        "2021-0366-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0585-IND",
        "2021-0681-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2022-0539-IND",
        "2023-0330-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2023-0846-IND",
        "2024-0399-IND",
        "2024-0561-IND",
        "2024-0624-IND",
        "2025-0402-IND",
        "2025-0690-IND",
        "2025-0751-IND"
      ],
      "test_source_ids": [
        "2015-0107-IND",
        "2015-0317-IND",
        "2016-0239-IND",
        "2017-0180-IND",
        "2018-0216-IND",
        "2020-0206-IND",
        "2021-0677-IND",
        "2022-0293-IND",
        "2022-0590-IND",
        "2024-0481-IND",
        "2024-0647-IND",
        "2025-0469-IND",
        "2025-0803-IND",
        "2025-0859-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.7602469443288182,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 4.1189757815636145,
            "log_flood_area": -0.08077827209258723,
            "log_population": 0.2502937738862441,
            "year_c": -0.014365626597796244,
            "alpha": 3.7602469443288182
          }
        },
        "poisson": {
          "status": "available",
          "converged": true,
          "alpha": null,
          "parameter_count": 4,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 4.440146176036585,
            "log_flood_area": -0.18348597403972206,
            "log_population": 0.30376469925434046,
            "year_c": -0.0851864299765839
          }
        }
      }
    }
  ],
  "scoring_reason_counts": {
    "oof_prediction_available": 1198,
    "excluded_by_input_contract": 350
  }
}
```

## Interpretation limits

- Observed GDELT coverage under accessible-body and heuristic definitions, not socially deserved coverage, causal discrimination, or intentional neglect.
- Central 90% discrete prediction intervals are plug-in approximations; beta/alpha estimation uncertainty is not included. They are not confidence intervals for the mean.
- Candidate labels are exploratory alerts, not confirmed or multiplicity-adjusted discoveries. No quota or equal tail proportions are imposed.
- Census 2011 total district population is not affected or exposed population. Boundaries, observation selection, source dependence and satellite/news window differences remain limitations.
- Operational sample gates do not guarantee power. Marginal count variance exceeding its mean does not establish conditional overdispersion.
