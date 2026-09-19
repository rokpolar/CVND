# Relative coverage scoring

News window: 14 days.

Status: available. Input rows: 1548; eligible: 1074; source events: 63; scored: 1074.

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
  "input_sha256": "7262ac312d7e41f183e08ea3cf250c8ba74925bbfb3a78fce44f71a3da0a1c48",
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
      "n_rows": 1074,
      "n_sources": 63,
      "row_weighted": {
        "mae": 42.41037832645906,
        "mean_negative_log_predictive_probability": 3.7725297189044986,
        "coverage_90": 0.9404096834264432,
        "mean_interval_width_90": 150.42830540037244,
        "observed_zero_rate": 0.2737430167597765,
        "mean_predicted_zero_probability": 0.30698834314302387
      },
      "source_macro": {
        "mae": 63.86338574116464,
        "mean_negative_log_predictive_probability": 4.776205563460848,
        "coverage_90": 0.8803227676744804,
        "mean_interval_width_90": 152.26698256943394,
        "observed_zero_rate": 0.15410200713985536,
        "mean_predicted_zero_probability": 0.3080532742929871
      }
    },
    "poisson": {
      "n_rows": 1074,
      "n_sources": 63,
      "row_weighted": {
        "mae": 43.15588497161878,
        "mean_negative_log_predictive_probability": 53.60643843359867,
        "coverage_90": 0.07355679702048418,
        "mean_interval_width_90": 17.98324022346369,
        "observed_zero_rate": 0.2737430167597765,
        "mean_predicted_zero_probability": 4.1640640556500554e-08
      },
      "source_macro": {
        "mae": 64.19365773655612,
        "mean_negative_log_predictive_probability": 101.47086588557636,
        "coverage_90": 0.08635701960163476,
        "mean_interval_width_90": 18.28557492054114,
        "observed_zero_rate": 0.15410200713985536,
        "mean_predicted_zero_probability": 2.953593886486483e-07
      }
    }
  },
  "poisson_comparison_common_success": {
    "scope": "Only test rows with both NB2 and Poisson predictions; source_macro averages within source, then equally across sources.",
    "n_rows": 1074,
    "fraction_of_eligible": 1.0,
    "nb2": {
      "n_rows": 1074,
      "n_sources": 63,
      "row_weighted": {
        "mae": 42.41037832645906,
        "mean_negative_log_predictive_probability": 3.7725297189044986,
        "coverage_90": 0.9404096834264432,
        "mean_interval_width_90": 150.42830540037244,
        "observed_zero_rate": 0.2737430167597765,
        "mean_predicted_zero_probability": 0.30698834314302387
      },
      "source_macro": {
        "mae": 63.86338574116464,
        "mean_negative_log_predictive_probability": 4.776205563460848,
        "coverage_90": 0.8803227676744804,
        "mean_interval_width_90": 152.26698256943394,
        "observed_zero_rate": 0.15410200713985536,
        "mean_predicted_zero_probability": 0.3080532742929871
      }
    },
    "poisson": {
      "n_rows": 1074,
      "n_sources": 63,
      "row_weighted": {
        "mae": 43.15588497161878,
        "mean_negative_log_predictive_probability": 53.60643843359867,
        "coverage_90": 0.07355679702048418,
        "mean_interval_width_90": 17.98324022346369,
        "observed_zero_rate": 0.2737430167597765,
        "mean_predicted_zero_probability": 4.1640640556500554e-08
      },
      "source_macro": {
        "mae": 64.19365773655612,
        "mean_negative_log_predictive_probability": 101.47086588557636,
        "coverage_90": 0.08635701960163476,
        "mean_interval_width_90": 18.28557492054114,
        "observed_zero_rate": 0.15410200713985536,
        "mean_predicted_zero_probability": 2.953593886486483e-07
      }
    }
  },
  "calibration": {
    "nb2": [
      {
        "bin": 0,
        "n": 108,
        "expected_min": 13.008530470991872,
        "expected_max": 21.963018518854035,
        "observed_mean": 88.68518518518519,
        "expected_mean": 19.65849818446805
      },
      {
        "bin": 1,
        "n": 107,
        "expected_min": 21.967239359562154,
        "expected_max": 24.239773458636044,
        "observed_mean": 56.299065420560744,
        "expected_mean": 23.302886283190873
      },
      {
        "bin": 2,
        "n": 107,
        "expected_min": 24.252639816191195,
        "expected_max": 26.15814879037382,
        "observed_mean": 27.747663551401867,
        "expected_mean": 25.275910353197524
      },
      {
        "bin": 3,
        "n": 108,
        "expected_min": 26.180880627416457,
        "expected_max": 27.863358980280776,
        "observed_mean": 35.611111111111114,
        "expected_mean": 27.033564877580766
      },
      {
        "bin": 4,
        "n": 107,
        "expected_min": 27.887864699596005,
        "expected_max": 29.517896440615154,
        "observed_mean": 25.214953271028037,
        "expected_mean": 28.681413315253028
      },
      {
        "bin": 5,
        "n": 107,
        "expected_min": 29.524695340988572,
        "expected_max": 31.395259532374435,
        "observed_mean": 18.485981308411215,
        "expected_mean": 30.433696442167815
      },
      {
        "bin": 6,
        "n": 108,
        "expected_min": 31.428221617041928,
        "expected_max": 33.61213597744624,
        "observed_mean": 18.564814814814813,
        "expected_mean": 32.476388092686854
      },
      {
        "bin": 7,
        "n": 107,
        "expected_min": 33.6144702049313,
        "expected_max": 36.230918948682415,
        "observed_mean": 9.551401869158878,
        "expected_mean": 34.863746748963074
      },
      {
        "bin": 8,
        "n": 107,
        "expected_min": 36.26480144158591,
        "expected_max": 40.84305634904786,
        "observed_mean": 5.747663551401869,
        "expected_mean": 38.42404691458631
      },
      {
        "bin": 9,
        "n": 108,
        "expected_min": 40.88301254967885,
        "expected_max": 79.47384469542459,
        "observed_mean": 27.36111111111111,
        "expected_mean": 48.17926655504178
      }
    ],
    "poisson": [
      {
        "bin": 0,
        "n": 108,
        "expected_min": 11.10971972047844,
        "expected_max": 19.058377029757636,
        "observed_mean": 63.120370370370374,
        "expected_mean": 16.976427485310214
      },
      {
        "bin": 1,
        "n": 107,
        "expected_min": 19.062921793020525,
        "expected_max": 22.334716673852803,
        "observed_mean": 81.10280373831776,
        "expected_mean": 20.73124972209564
      },
      {
        "bin": 2,
        "n": 107,
        "expected_min": 22.3955673049243,
        "expected_max": 24.535913390498337,
        "observed_mean": 38.90654205607477,
        "expected_mean": 23.58231172497871
      },
      {
        "bin": 3,
        "n": 108,
        "expected_min": 24.55371476679139,
        "expected_max": 26.296209630652065,
        "observed_mean": 32.49074074074074,
        "expected_mean": 25.420347389944318
      },
      {
        "bin": 4,
        "n": 107,
        "expected_min": 26.345738316732803,
        "expected_max": 28.273099784607027,
        "observed_mean": 17.411214953271028,
        "expected_mean": 27.180360068169275
      },
      {
        "bin": 5,
        "n": 107,
        "expected_min": 28.2834499454126,
        "expected_max": 30.460111829319885,
        "observed_mean": 15.093457943925234,
        "expected_mean": 29.236986649029223
      },
      {
        "bin": 6,
        "n": 108,
        "expected_min": 30.47555746924158,
        "expected_max": 33.520432083257155,
        "observed_mean": 21.50925925925926,
        "expected_mean": 32.06376298821028
      },
      {
        "bin": 7,
        "n": 107,
        "expected_min": 33.538168321506625,
        "expected_max": 37.97725201692343,
        "observed_mean": 9.785046728971963,
        "expected_mean": 35.513169619130686
      },
      {
        "bin": 8,
        "n": 107,
        "expected_min": 37.98418432579368,
        "expected_max": 44.8401106025647,
        "observed_mean": 5.644859813084112,
        "expected_mean": 41.26830585190928
      },
      {
        "bin": 9,
        "n": 108,
        "expected_min": 44.85480373966039,
        "expected_max": 127.31086059816188,
        "observed_mean": 28.435185185185187,
        "expected_mean": 57.49392442712031
      }
    ]
  },
  "folds": [
    {
      "fold_id": 0,
      "n_train": 859,
      "n_test": 215,
      "n_train_sources": 53,
      "n_test_sources": 10,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0317-IND",
        "2015-0333-IND",
        "2015-0374-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0139-IND",
        "2016-0267-IND",
        "2016-0271-IND",
        "2016-0554-IND",
        "2017-0180-IND",
        "2017-0289-IND",
        "2017-0290-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0495-IND",
        "2017-0517-IND",
        "2018-0205-IND",
        "2018-0216-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2019-0288-IND",
        "2019-0383-IND",
        "2019-0499-IND",
        "2019-0574-IND",
        "2020-0304-IND",
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
        "2022-0590-IND",
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
        "2025-0751-IND",
        "2025-0803-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2016-0239-IND",
        "2017-0294-IND",
        "2018-0213-IND",
        "2018-0372-IND",
        "2019-0331-IND",
        "2020-0206-IND",
        "2020-0446-IND",
        "2023-0486-IND",
        "2024-0561-IND",
        "2025-0690-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.950391500647346,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.7176440713660215,
            "log_flood_area": -0.12466486259029905,
            "log_population": 0.36972203996996356,
            "year_c": -0.044395682145882555,
            "alpha": 3.950391500647346
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
            "Intercept": 4.076472132674385,
            "log_flood_area": -0.224690837921027,
            "log_population": 0.39242988419499564,
            "year_c": -0.07882546989763567
          }
        }
      }
    },
    {
      "fold_id": 1,
      "n_train": 859,
      "n_test": 215,
      "n_train_sources": 51,
      "n_test_sources": 12,
      "train_source_ids": [
        "2015-0317-IND",
        "2015-0333-IND",
        "2015-0374-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0239-IND",
        "2016-0267-IND",
        "2016-0271-IND",
        "2016-0554-IND",
        "2017-0180-IND",
        "2017-0289-IND",
        "2017-0290-IND",
        "2017-0294-IND",
        "2017-0342-IND",
        "2017-0495-IND",
        "2017-0517-IND",
        "2018-0205-IND",
        "2018-0213-IND",
        "2018-0216-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0345-IND",
        "2018-0372-IND",
        "2019-0288-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0574-IND",
        "2020-0206-IND",
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
        "2023-0330-IND",
        "2023-0359-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2023-0846-IND",
        "2024-0399-IND",
        "2024-0481-IND",
        "2024-0561-IND",
        "2024-0647-IND",
        "2025-0469-IND",
        "2025-0690-IND",
        "2025-0803-IND"
      ],
      "test_source_ids": [
        "2015-0107-IND",
        "2016-0139-IND",
        "2017-0364-IND",
        "2018-0370-IND",
        "2019-0499-IND",
        "2020-0304-IND",
        "2022-0539-IND",
        "2022-0590-IND",
        "2024-0624-IND",
        "2025-0402-IND",
        "2025-0751-IND",
        "2025-0859-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.8570797859854316,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.8571482953854117,
            "log_flood_area": -0.09209375135404606,
            "log_population": 0.17289472792608168,
            "year_c": -0.017125242337716166,
            "alpha": 3.8570797859854316
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
            "Intercept": 4.038102478531749,
            "log_flood_area": -0.14616483328109436,
            "log_population": 0.23375350586356047,
            "year_c": -0.03501930070199899
          }
        }
      }
    },
    {
      "fold_id": 2,
      "n_train": 859,
      "n_test": 215,
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
        "2017-0289-IND",
        "2017-0290-IND",
        "2017-0294-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0495-IND",
        "2017-0517-IND",
        "2018-0213-IND",
        "2018-0286-IND",
        "2018-0345-IND",
        "2018-0370-IND",
        "2018-0372-IND",
        "2019-0288-IND",
        "2019-0331-IND",
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
        "2022-0293-IND",
        "2022-0539-IND",
        "2022-0590-IND",
        "2023-0428-IND",
        "2023-0486-IND",
        "2024-0399-IND",
        "2024-0481-IND",
        "2024-0561-IND",
        "2024-0624-IND",
        "2025-0402-IND",
        "2025-0469-IND",
        "2025-0690-IND",
        "2025-0751-IND",
        "2025-0803-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2015-0374-IND",
        "2016-0271-IND",
        "2018-0205-IND",
        "2018-0216-IND",
        "2018-0295-IND",
        "2019-0383-IND",
        "2021-0677-IND",
        "2021-0681-IND",
        "2021-0722-IND",
        "2021-0748-IND",
        "2023-0330-IND",
        "2023-0359-IND",
        "2023-0846-IND",
        "2024-0647-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 3.9378128040945826,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 2.9467207271956277,
            "log_flood_area": 0.05991833351280431,
            "log_population": -0.07428841511283123,
            "year_c": -0.03782593547819947,
            "alpha": 3.9378128040945826
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
            "Intercept": 2.788288516847382,
            "log_flood_area": 0.09715715498083143,
            "log_population": -0.07996106727264808,
            "year_c": -0.03733926180190575
          }
        }
      }
    },
    {
      "fold_id": 3,
      "n_train": 859,
      "n_test": 215,
      "n_train_sources": 49,
      "n_test_sources": 14,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0317-IND",
        "2015-0333-IND",
        "2015-0374-IND",
        "2016-0139-IND",
        "2016-0239-IND",
        "2016-0267-IND",
        "2016-0271-IND",
        "2017-0290-IND",
        "2017-0294-IND",
        "2017-0342-IND",
        "2017-0364-IND",
        "2017-0517-IND",
        "2018-0205-IND",
        "2018-0213-IND",
        "2018-0216-IND",
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
        "2021-0458-IND",
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
        "2025-0402-IND",
        "2025-0690-IND",
        "2025-0751-IND",
        "2025-0859-IND"
      ],
      "test_source_ids": [
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0554-IND",
        "2017-0180-IND",
        "2017-0289-IND",
        "2017-0495-IND",
        "2018-0286-IND",
        "2021-0366-IND",
        "2021-0435-IND",
        "2021-0585-IND",
        "2022-0293-IND",
        "2023-0428-IND",
        "2025-0469-IND",
        "2025-0803-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 4.238786882698555,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.85755403227857,
            "log_flood_area": -0.10018712980928116,
            "log_population": 0.11665491137173045,
            "year_c": -0.008777482019728073,
            "alpha": 4.238786882698555
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
            "Intercept": 4.015109699050837,
            "log_flood_area": -0.14624638886449548,
            "log_population": 0.16144271202791866,
            "year_c": -0.016844115057467107
          }
        }
      }
    },
    {
      "fold_id": 4,
      "n_train": 860,
      "n_test": 214,
      "n_train_sources": 50,
      "n_test_sources": 13,
      "train_source_ids": [
        "2015-0107-IND",
        "2015-0374-IND",
        "2015-0406-IND",
        "2015-0504-IND",
        "2016-0139-IND",
        "2016-0239-IND",
        "2016-0271-IND",
        "2016-0554-IND",
        "2017-0180-IND",
        "2017-0289-IND",
        "2017-0294-IND",
        "2017-0364-IND",
        "2017-0495-IND",
        "2018-0205-IND",
        "2018-0213-IND",
        "2018-0216-IND",
        "2018-0286-IND",
        "2018-0295-IND",
        "2018-0370-IND",
        "2018-0372-IND",
        "2019-0331-IND",
        "2019-0383-IND",
        "2019-0499-IND",
        "2020-0206-IND",
        "2020-0304-IND",
        "2020-0446-IND",
        "2021-0366-IND",
        "2021-0435-IND",
        "2021-0585-IND",
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
        "2023-0846-IND",
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
        "2015-0333-IND",
        "2016-0267-IND",
        "2017-0290-IND",
        "2017-0342-IND",
        "2017-0517-IND",
        "2018-0345-IND",
        "2019-0288-IND",
        "2019-0574-IND",
        "2021-0316-IND",
        "2021-0458-IND",
        "2024-0399-IND",
        "2024-0481-IND"
      ],
      "models": {
        "nb2": {
          "status": "available",
          "converged": true,
          "alpha": 4.355027621160563,
          "parameter_count": 5,
          "required_train_rows": 30,
          "warnings": [],
          "coefficients": {
            "Intercept": 3.842064176542395,
            "log_flood_area": -0.11759771259737913,
            "log_population": 0.14672516824598908,
            "year_c": -0.01720805334723157,
            "alpha": 4.355027621160563
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
            "Intercept": 4.044144241860749,
            "log_flood_area": -0.1795730518624848,
            "log_population": 0.20925256618634083,
            "year_c": -0.04677637191750782
          }
        }
      }
    }
  ],
  "scoring_reason_counts": {
    "oof_prediction_available": 1074,
    "excluded_by_input_contract": 474
  }
}
```

## Interpretation limits

- Observed GDELT coverage under accessible-body and heuristic definitions, not socially deserved coverage, causal discrimination, or intentional neglect.
- Central 90% discrete prediction intervals are plug-in approximations; beta/alpha estimation uncertainty is not included. They are not confidence intervals for the mean.
- Candidate labels are exploratory alerts, not confirmed or multiplicity-adjusted discoveries. No quota or equal tail proportions are imposed.
- Census 2011 total district population is not affected or exposed population. Boundaries, observation selection, source dependence and satellite/news window differences remain limitations.
- Operational sample gates do not guarantee power. Marginal count variance exceeding its mean does not establish conditional overdispersion.
