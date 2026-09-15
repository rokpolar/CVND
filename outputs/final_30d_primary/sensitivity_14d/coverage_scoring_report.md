# Relative coverage scoring

Status: available. Input rows: 1553; eligible: 1069; source events: 63; scored: 1069.

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
  "input_sha256": "79281623bc814617ac6906f6c0c44168872f9bc45cc60212ada92810067d35bd",
  "git_sha": "7dc25114acf948abe2001d8e9e7d73d25e6bee7c",
  "library_versions": {
    "numpy": "2.5.2",
    "pandas": "3.0.5",
    "scipy": "1.18.1",
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
      "n_rows": 1069,
      "n_sources": 63,
      "row_weighted": {
        "mae": 42.58667563520146,
        "mean_negative_log_predictive_probability": 3.746209471816398,
        "coverage_90": 0.9382600561272217,
        "mean_interval_width_90": 154.75210477081384,
        "observed_zero_rate": 0.27502338634237605,
        "mean_predicted_zero_probability": 0.3062191433904033
      },
      "source_macro": {
        "mae": 63.87631042048362,
        "mean_negative_log_predictive_probability": 4.708550015791583,
        "coverage_90": 0.872410552302058,
        "mean_interval_width_90": 156.9517589212478,
        "observed_zero_rate": 0.15439397979676356,
        "mean_predicted_zero_probability": 0.30588985071919056
      }
    },
    "poisson": {
      "n_rows": 1069,
      "n_sources": 63,
      "row_weighted": {
        "mae": 43.57521808689967,
        "mean_negative_log_predictive_probability": 51.272508658405414,
        "coverage_90": 0.07857811038353602,
        "mean_interval_width_90": 18.41534144059869,
        "observed_zero_rate": 0.27502338634237605,
        "mean_predicted_zero_probability": 2.2120455639721685e-07
      },
      "source_macro": {
        "mae": 64.39700701542435,
        "mean_negative_log_predictive_probability": 97.71138012040733,
        "coverage_90": 0.09887445426084772,
        "mean_interval_width_90": 18.743036722783398,
        "observed_zero_rate": 0.15439397979676356,
        "mean_predicted_zero_probability": 4.0906414688735647e-07
      }
    }
  },
  "poisson_comparison_common_success": {
    "scope": "Only test rows with both NB2 and Poisson predictions; source_macro averages within source, then equally across sources.",
    "n_rows": 1069,
    "fraction_of_eligible": 1.0,
    "nb2": {
      "n_rows": 1069,
      "n_sources": 63,
      "row_weighted": {
        "mae": 42.58667563520146,
        "mean_negative_log_predictive_probability": 3.746209471816398,
        "coverage_90": 0.9382600561272217,
        "mean_interval_width_90": 154.75210477081384,
        "observed_zero_rate": 0.27502338634237605,
        "mean_predicted_zero_probability": 0.3062191433904033
      },
      "source_macro": {
        "mae": 63.87631042048362,
        "mean_negative_log_predictive_probability": 4.708550015791583,
        "coverage_90": 0.872410552302058,
        "mean_interval_width_90": 156.9517589212478,
        "observed_zero_rate": 0.15439397979676356,
        "mean_predicted_zero_probability": 0.30588985071919056
      }
    },
    "poisson": {
      "n_rows": 1069,
      "n_sources": 63,
      "row_weighted": {
        "mae": 43.57521808689967,
        "mean_negative_log_predictive_probability": 51.272508658405414,
        "coverage_90": 0.07857811038353602,
        "mean_interval_width_90": 18.41534144059869,
        "observed_zero_rate": 0.27502338634237605,
        "mean_predicted_zero_probability": 2.2120455639721685e-07
      },
      "source_macro": {
        "mae": 64.39700701542435,
        "mean_negative_log_predictive_probability": 97.71138012040733,
        "coverage_90": 0.09887445426084772,
        "mean_interval_width_90": 18.743036722783398,
        "observed_zero_rate": 0.15439397979676356,
        "mean_predicted_zero_probability": 4.0906414688735647e-07
      }
    }
  },
  "calibration": {
    "nb2": [
      {
        "bin": 0,
        "n": 107,
        "expected_min": 14.188008155397885,
        "expected_max": 22.634961427762665,
        "observed_mean": 51.44859813084112,
        "expected_mean": 19.82981098737152
      },
      {
        "bin": 1,
        "n": 107,
        "expected_min": 22.81871839328099,
        "expected_max": 26.151776124262334,
        "observed_mean": 58.71028037383178,
        "expected_mean": 24.9357569798297
      },
      {
        "bin": 2,
        "n": 107,
        "expected_min": 26.15929115700508,
        "expected_max": 27.637942772243065,
        "observed_mean": 65.69158878504673,
        "expected_mean": 26.93551575678862
      },
      {
        "bin": 3,
        "n": 107,
        "expected_min": 27.6464598216227,
        "expected_max": 28.866982272809246,
        "observed_mean": 25.009345794392523,
        "expected_mean": 28.231891964620594
      },
      {
        "bin": 4,
        "n": 107,
        "expected_min": 28.870302700985686,
        "expected_max": 30.463559306930254,
        "observed_mean": 15.74766355140187,
        "expected_mean": 29.762738911641758
      },
      {
        "bin": 5,
        "n": 106,
        "expected_min": 30.471189144722022,
        "expected_max": 31.94290404723633,
        "observed_mean": 14.5,
        "expected_mean": 31.2140406651833
      },
      {
        "bin": 6,
        "n": 107,
        "expected_min": 31.942989817693064,
        "expected_max": 33.888000578965425,
        "observed_mean": 23.38317757009346,
        "expected_mean": 32.83158780364469
      },
      {
        "bin": 7,
        "n": 107,
        "expected_min": 33.898283022218905,
        "expected_max": 36.91089592825949,
        "observed_mean": 13.644859813084112,
        "expected_mean": 35.36694274052683
      },
      {
        "bin": 8,
        "n": 107,
        "expected_min": 36.91572799929517,
        "expected_max": 42.74278870706925,
        "observed_mean": 12.813084112149532,
        "expected_mean": 39.506659542576436
      },
      {
        "bin": 9,
        "n": 107,
        "expected_min": 42.86331817450719,
        "expected_max": 69.87050484186372,
        "observed_mean": 29.80373831775701,
        "expected_mean": 48.41623275277161
      }
    ],
    "poisson": [
      {
        "bin": 0,
        "n": 107,
        "expected_min": 9.187997149574022,
        "expected_max": 20.130792053786937,
        "observed_mean": 52.05607476635514,
        "expected_mean": 16.186206997991498
      },
      {
        "bin": 1,
        "n": 107,
        "expected_min": 20.184544424209417,
        "expected_max": 24.95672210499569,
        "observed_mean": 49.2803738317757,
        "expected_mean": 22.91780413018985
      },
      {
        "bin": 2,
        "n": 107,
        "expected_min": 24.985377784786603,
        "expected_max": 26.771458781344926,
        "observed_mean": 78.18691588785046,
        "expected_mean": 25.963051971308627
      },
      {
        "bin": 3,
        "n": 107,
        "expected_min": 26.775069700656967,
        "expected_max": 28.352416779183926,
        "observed_mean": 21.785046728971963,
        "expected_mean": 27.53234958069836
      },
      {
        "bin": 4,
        "n": 107,
        "expected_min": 28.36259977263115,
        "expected_max": 30.068214919113306,
        "observed_mean": 13.429906542056075,
        "expected_mean": 29.21318984152159
      },
      {
        "bin": 5,
        "n": 106,
        "expected_min": 30.073318093377015,
        "expected_max": 32.18616144385489,
        "observed_mean": 17.537735849056602,
        "expected_mean": 31.12546366276002
      },
      {
        "bin": 6,
        "n": 107,
        "expected_min": 32.19253998840845,
        "expected_max": 34.531742574413144,
        "observed_mean": 17.49532710280374,
        "expected_mean": 33.19778209088927
      },
      {
        "bin": 7,
        "n": 107,
        "expected_min": 34.58300179434108,
        "expected_max": 39.087794651604725,
        "observed_mean": 10.392523364485982,
        "expected_mean": 36.677764536113706
      },
      {
        "bin": 8,
        "n": 107,
        "expected_min": 39.20005242405219,
        "expected_max": 47.8335786436033,
        "observed_mean": 17.94392523364486,
        "expected_mean": 43.20433957152087
      },
      {
        "bin": 9,
        "n": 107,
        "expected_min": 47.87260225765736,
        "expected_max": 101.31981406479485,
        "observed_mean": 32.67289719626168,
        "expected_mean": 57.899188742885045
      }
    ]
  },
  "folds": [
    {
      "fold_id": 0,
      "n_train": 855,
      "n_test": 214,
      "n_train_sources": 53,
      "n_test_sources": 10,
      "train_source_ids": [
        "2015-0317-IND",
        "2015-0333-IND",
        "2015-0374-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0267-IND",
        "2016-0271-IND",
        "2016-0554-IND",
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
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2018-0372-IND",
        "2019-0288-IND",
        "2019-0499-IND",
        "2019-0574-IND",
        "2020-0206-IND",
        "2020-0304-IND",
        "2020-0446-IND",
        "2021-0316-IND",
        "2021-0366-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0585-IND",
        "2021-0677-IND",
        "2021-0681-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2022-0293-IND",
        "2022-0590-IND",
        "2023-0330-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2023-0846-IND",
        "2024-0399-IND",
        "2024-0481-IND",
        "2024-0561-IND",
        "2024-0647-IND",
        "2025-0402-IND",
        "2025-0469-IND",
        "2025-0803-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2015-0107-IND",
        "2016-0139-IND",
        "2016-0239-IND",
        "2018-0216-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2022-0539-IND",
        "2024-0624-IND",
        "2025-0690-IND",
        "2025-0751-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 4.0601841763260484,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.6740509405638804,
            "log_flood_area": -0.11950623615964324,
            "log_population": 0.30276187555028355,
            "year_c": -0.032709622941413205,
            "alpha": 4.0601841763260484
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
            "Intercept": 3.987211973209329,
            "log_flood_area": -0.20475709160116376,
            "log_population": 0.3201681417178505,
            "year_c": -0.06440893323493585
          }
        }
      }
    },
    {
      "fold_id": 1,
      "n_train": 855,
      "n_test": 214,
      "n_train_sources": 51,
      "n_test_sources": 12,
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
        "2017-0290-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0495-IND",
        "2018-0205-IND",
        "2018-0216-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2019-0288-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0574-IND",
        "2021-0316-IND",
        "2021-0366-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0585-IND",
        "2021-0677-IND",
        "2021-0681-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2022-0293-IND",
        "2022-0539-IND",
        "2023-0330-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0846-IND",
        "2024-0399-IND",
        "2024-0481-IND",
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
        "2017-0294-IND",
        "2017-0517-IND",
        "2018-0213-IND",
        "2018-0370-IND",
        "2018-0372-IND",
        "2019-0499-IND",
        "2020-0206-IND",
        "2020-0304-IND",
        "2020-0446-IND",
        "2022-0590-IND",
        "2023-0486-IND",
        "2024-0561-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.878047927439639,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.816987715502568,
            "log_flood_area": -0.08045642053913543,
            "log_population": 0.22080512872761973,
            "year_c": -0.03928675241765001,
            "alpha": 3.878047927439639
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
            "Intercept": 4.037565573872481,
            "log_flood_area": -0.14432328448900306,
            "log_population": 0.29068505432855435,
            "year_c": -0.05995420691861638
          }
        }
      }
    },
    {
      "fold_id": 2,
      "n_train": 855,
      "n_test": 214,
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
        "2018-0370-IND",
        "2018-0372-IND",
        "2019-0288-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0499-IND",
        "2020-0206-IND",
        "2020-0304-IND",
        "2020-0446-IND",
        "2021-0316-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0677-IND",
        "2021-0748-IND",
        "2022-0293-IND",
        "2022-0539-IND",
        "2022-0590-IND",
        "2023-0330-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2023-0846-IND",
        "2024-0481-IND",
        "2024-0561-IND",
        "2024-0624-IND",
        "2025-0402-IND",
        "2025-0469-IND",
        "2025-0690-IND",
        "2025-0751-IND",
        "2025-0803-IND"
      ],
      "test_source_ids": [
        "2016-0267-IND",
        "2016-0554-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2019-0574-IND",
        "2021-0366-IND",
        "2021-0585-IND",
        "2021-0681-IND",
        "2021-0722-IND",
        "2023-0359-IND",
        "2024-0399-IND",
        "2024-0647-IND",
        "2025-0859-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.897426335920995,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.2525478249231616,
            "log_flood_area": 0.017219581823991133,
            "log_population": 0.042464360153391126,
            "year_c": 0.017828208557653383,
            "alpha": 3.897426335920995
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
            "Intercept": 3.215713368526801,
            "log_flood_area": 0.029027497543954076,
            "log_population": 0.014067971291346433,
            "year_c": 0.019120854820675506
          }
        }
      }
    },
    {
      "fold_id": 3,
      "n_train": 855,
      "n_test": 214,
      "n_train_sources": 49,
      "n_test_sources": 14,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0317-IND",
        "2015-0374-IND",
        "2016-0139-IND",
        "2016-0239-IND",
        "2016-0267-IND",
        "2016-0271-IND",
        "2016-0554-IND",
        "2017-0289-IND",
        "2017-0294-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0517-IND",
        "2018-0205-IND",
        "2018-0213-IND",
        "2018-0216-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2018-0372-IND",
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
        "2021-0681-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2022-0539-IND",
        "2022-0590-IND",
        "2023-0330-IND",
        "2023-0359-IND",
        "2023-0486-IND",
        "2023-0846-IND",
        "2024-0399-IND",
        "2024-0481-IND",
        "2024-0561-IND",
        "2024-0624-IND",
        "2024-0647-IND",
        "2025-0690-IND",
        "2025-0751-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2015-0333-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2017-0180-IND",
        "2017-0290-IND",
        "2017-0495-IND",
        "2019-0288-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2022-0293-IND",
        "2023-0428-IND",
        "2025-0402-IND",
        "2025-0469-IND",
        "2025-0803-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 4.223602283583647,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.8144669634700277,
            "log_flood_area": -0.08657413678783629,
            "log_population": 0.043951621108288805,
            "year_c": -0.017838778170415598,
            "alpha": 4.223602283583647
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
            "Intercept": 3.9142508121640414,
            "log_flood_area": -0.1179525357784492,
            "log_population": 0.09349288389202669,
            "year_c": -0.022647161708514572
          }
        }
      }
    },
    {
      "fold_id": 4,
      "n_train": 856,
      "n_test": 213,
      "n_train_sources": 50,
      "n_test_sources": 13,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0333-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0139-IND",
        "2016-0239-IND",
        "2016-0267-IND",
        "2016-0554-IND",
        "2017-0180-IND",
        "2017-0290-IND",
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
        "2021-0366-IND",
        "2021-0435-IND",
        "2021-0458-IND",
        "2021-0585-IND",
        "2021-0681-IND",
        "2021-0722-IND",
        "2022-0293-IND",
        "2022-0539-IND",
        "2022-0590-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2024-0399-IND",
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
        "2015-0317-IND",
        "2015-0374-IND",
        "2016-0271-IND",
        "2017-0289-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2018-0205-IND",
        "2021-0316-IND",
        "2021-0677-IND",
        "2021-0748-IND",
        "2023-0330-IND",
        "2023-0846-IND",
        "2024-0481-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 4.393925783141803,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.694077760743969,
            "log_flood_area": -0.10247854934713374,
            "log_population": 0.092197307494149,
            "year_c": -0.05382091288172352,
            "alpha": 4.393925783141803
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
            "Intercept": 3.90459126295327,
            "log_flood_area": -0.17060572260230897,
            "log_population": 0.18487538091719288,
            "year_c": -0.08967518634584688
          }
        }
      }
    }
  ],
  "scoring_reason_counts": {
    "oof_prediction_available": 1069,
    "excluded_by_input_contract": 484
  }
}
```

## Interpretation limits

- Observed GDELT coverage under accessible-body and heuristic definitions, not socially deserved coverage, causal discrimination, or intentional neglect.
- Central 90% discrete prediction intervals are plug-in approximations; beta/alpha estimation uncertainty is not included. They are not confidence intervals for the mean.
- Candidate labels are exploratory alerts, not confirmed or multiplicity-adjusted discoveries. No quota or equal tail proportions are imposed.
- Census 2011 total district population is not affected or exposed population. Boundaries, observation selection, source dependence and satellite/news window differences remain limitations.
- Operational sample gates do not guarantee power. Marginal count variance exceeding its mean does not establish conditional overdispersion.
