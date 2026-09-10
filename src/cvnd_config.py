"""Model, merge, and visualization constants for the CVND primary stack."""

from __future__ import annotations

LOG_RATIO_EPS = 0.5
MEDIA_WINDOW_DAYS = 93  # collect_gdelt.py default: onset through onset+93 days
MONSOON_MONTHS = frozenset({6, 7, 8, 9})

PSS_W_AREA = 0.5
PSS_W_POP = 0.5

CLOUD_MAX_PCT = 60

COLOR_UNDER = "#FF0000"
COLOR_MID = "#FFE600"
COLOR_OVER = "#00FF00"
COLOR_UNKNOWN = "#9E9E9E"
COLORS_INCOME = {
    "High": COLOR_OVER,
    "Middle": COLOR_MID,
    "Low": COLOR_UNDER,
    # state_income labels states with no per-capita GSDP 'Unknown'. visualize.py
    # builds a pd.Categorical from INCOME_ORDER, and a value outside the
    # categories becomes NaN -- so without this entry those events would drop out
    # of every figure with nothing said.
    "Unknown": COLOR_UNKNOWN,
}
INCOME_ORDER = ["High", "Middle", "Low", "Unknown"]

LOG_RATIO_CMAP_STOPS = [
    (0.0, COLOR_UNDER),
    (0.5, COLOR_MID),
    (1.0, COLOR_OVER),
]

FIGURES: list[tuple[str, str]] = [
    ("plot1_pss_vs_mss_scatter.png", "PSS vs MSS scatter"),
    ("plot5_observed_vs_expected.png", "Observed vs expected calibration"),
    ("plot6_log_ratio_histogram.png", "log_ratio residual histogram"),
    ("plot7_log_ratio_ranking.png", "Coverage imbalance ranking (extremes)"),
    ("plot8_log_ratio_by_income.png", "log_ratio by income group"),
    ("plot9_coverage_map.png", "Coverage imbalance choropleth map"),
]
