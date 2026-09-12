# Relative coverage scoring

Status: insufficient_data. Input rows: 1630; eligible: 0; source events: 0; scored: 0.

Formula: `article_count ~ log_flood_area + log_population + year_c`. Estimated NB2 alpha; source-group five-fold OOF only.

No empirical conclusion is available.

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
  "input_sha256": "39f71098ab4a8b8e8d886b3976bd70c3f09e575fc7c634636d884871607a1cdb",
  "git_sha": "c94072bf9749e64ebdb4a0ee021a2940b98671b7",
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
      "n_rows": 0,
      "n_sources": 0,
      "row_weighted": {
        "mae": null,
        "mean_negative_log_predictive_probability": null,
        "coverage_90": null,
        "mean_interval_width_90": null,
        "observed_zero_rate": null,
        "mean_predicted_zero_probability": null
      },
      "source_macro": {
        "mae": null,
        "mean_negative_log_predictive_probability": null,
        "coverage_90": null,
        "mean_interval_width_90": null,
        "observed_zero_rate": null,
        "mean_predicted_zero_probability": null
      }
    },
    "poisson": {
      "n_rows": 0,
      "n_sources": 0,
      "row_weighted": {
        "mae": null,
        "mean_negative_log_predictive_probability": null,
        "coverage_90": null,
        "mean_interval_width_90": null,
        "observed_zero_rate": null,
        "mean_predicted_zero_probability": null
      },
      "source_macro": {
        "mae": null,
        "mean_negative_log_predictive_probability": null,
        "coverage_90": null,
        "mean_interval_width_90": null,
        "observed_zero_rate": null,
        "mean_predicted_zero_probability": null
      }
    }
  },
  "poisson_comparison_common_success": {
    "scope": "Only test rows with both NB2 and Poisson predictions; source_macro averages within source, then equally across sources.",
    "n_rows": 0,
    "fraction_of_eligible": null,
    "nb2": {
      "n_rows": 0,
      "n_sources": 0,
      "row_weighted": {
        "mae": null,
        "mean_negative_log_predictive_probability": null,
        "coverage_90": null,
        "mean_interval_width_90": null,
        "observed_zero_rate": null,
        "mean_predicted_zero_probability": null
      },
      "source_macro": {
        "mae": null,
        "mean_negative_log_predictive_probability": null,
        "coverage_90": null,
        "mean_interval_width_90": null,
        "observed_zero_rate": null,
        "mean_predicted_zero_probability": null
      }
    },
    "poisson": {
      "n_rows": 0,
      "n_sources": 0,
      "row_weighted": {
        "mae": null,
        "mean_negative_log_predictive_probability": null,
        "coverage_90": null,
        "mean_interval_width_90": null,
        "observed_zero_rate": null,
        "mean_predicted_zero_probability": null
      },
      "source_macro": {
        "mae": null,
        "mean_negative_log_predictive_probability": null,
        "coverage_90": null,
        "mean_interval_width_90": null,
        "observed_zero_rate": null,
        "mean_predicted_zero_probability": null
      }
    }
  },
  "calibration": {
    "nb2": [],
    "poisson": []
  },
  "folds": [],
  "scoring_reason_counts": {
    "excluded_by_input_contract": 1630
  }
}
```

## Interpretation limits

- Observed GDELT coverage under accessible-body and heuristic definitions, not socially deserved coverage, causal discrimination, or intentional neglect.
- Central 90% discrete prediction intervals are plug-in approximations; beta/alpha estimation uncertainty is not included. They are not confidence intervals for the mean.
- Candidate labels are exploratory alerts, not confirmed or multiplicity-adjusted discoveries. No quota or equal tail proportions are imposed.
- Census 2011 total district population is not affected or exposed population. Boundaries, observation selection, source dependence and satellite/news window differences remain limitations.
- Operational sample gates do not guarantee power. Marginal count variance exceeding its mean does not establish conditional overdispersion.
