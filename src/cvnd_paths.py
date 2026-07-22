"""Shared paths and constants for the CVND primary analysis stack.

Primary DAG (cached / default runner):
    severity_raw → PSS → MSS (gdelt_bq_part*.json) → NegBin expected coverage → visualize

Legacy / optional scripts live under src/archive/ and data/archive/.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"
ARCHIVE_SRC = ROOT / "src" / "archive"
ARCHIVE_DATA = DATA / "archive"

#  Canonical data paths 
EVENTS = DATA / "events.csv"
EVENTS_QUARANTINE = DATA / "events_quarantine.csv"
EMDAT = DATA / "emdat_raw.csv"
SEVERITY_RAW = DATA / "severity_raw.csv"
FLOOD_COMBINED = DATA / "flood_combined.csv"
FLOOD_EXTENT = DATA / "flood_extent.csv"
POPULATION = DATA / "population.csv"
PSS_RESULTS = DATA / "pss_results.csv"
MSS_RESULTS = DATA / "mss_results.csv"
EXPECTED_COVERAGE = DATA / "expected_coverage.csv"
STATE_EXPECTED_COVERAGE = DATA / "state_expected_coverage.csv"
MSS_WEIGHT_META = DATA / "mss_weight_sensitivity.json"
MSS_WEIGHT_PROVENANCE = DATA / "mss_weight_provenance.csv"
MSS_RANK_STABILITY = DATA / "mss_rank_stability.csv"
PIPELINE_RESULT_MD = OUTPUTS / "pipeline_result.md"
NE_INDIA_STATES = DATA / "ne_india_states.gpkg"

# Model / score constants
LOG_RATIO_EPS = 0.5
MEDIA_WINDOW_DAYS = 14  # design window; article counts are not guaranteed filtered to it
MONSOON_MONTHS = frozenset({6, 7, 8, 9})

# PSS primary weights (equal after log1p+MinMax)
PSS_W_AREA = 0.5
PSS_W_POP = 0.5

# Merge cloud routing (flood-date district cloud %)
CLOUD_MAX_PCT = 60

# Plot palette (vivid; red = under-covered, green = over-covered)
COLOR_UNDER = "#FF0000"
COLOR_MID = "#FFE600"
COLOR_OVER = "#00FF00"
COLORS_INCOME = {
    "High": COLOR_OVER,
    "Middle": COLOR_MID,
    "Low": COLOR_UNDER,
}
INCOME_ORDER = ["High", "Middle", "Low"]

LOG_RATIO_CMAP_STOPS = [
    (0.0, COLOR_UNDER),
    (0.5, COLOR_MID),
    (1.0, COLOR_OVER),
]

# Active figure filenames (plots 2–4 retired with legacy DI; IDs kept for paper links)
FIGURES: list[tuple[str, str]] = [
    ("plot1_pss_vs_mss_scatter.png", "PSS vs MSS scatter"),
    ("plot5_observed_vs_expected.png", "Observed vs expected calibration"),
    ("plot6_log_ratio_histogram.png", "log_ratio residual histogram"),
    ("plot7_log_ratio_ranking.png", "Coverage imbalance ranking (extremes)"),
    ("plot8_log_ratio_by_income.png", "log_ratio by income group"),
    ("plot9_coverage_map.png", "Coverage imbalance choropleth map"),
]
