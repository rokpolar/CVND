"""Convention-based paths for the CVND primary analysis stack.

Resolve data artifacts by logical key via data_path(key). Tier layout:
  data/raw/          — external inputs
  data/cache/        — satellite / GEE caches
  data/intermediate/ — pipeline step outputs
  data/results/      — scores and model outputs
  data/archive/      — legacy fallbacks (unchanged)
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_printable_output() -> None:
    """Stop a legacy console encoding from killing the run.

    The Windows console defaults to a legacy codepage (cp949 on the machine this
    is developed on), where printing an em dash or "km²" raises
    UnicodeEncodeError. That made `--help` exit with a traceback on every script,
    and killed a local run on the FIRST event, because the per-event status line
    in sar_flood_area.py contains an em dash. Colab is UTF-8 and never saw it.

    UTF-8 first, since that renders correctly on Colab, on Windows Terminal and
    through a pipe. `errors="replace"` is set either way, so a console that truly
    cannot encode a character prints a placeholder instead of aborting the run.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:          # already wrapped or detached
            continue
        for kwargs in ({"encoding": "utf-8", "errors": "replace"},
                       {"errors": "replace"}):
            try:
                reconfigure(**kwargs)
                break
            except (ValueError, OSError, LookupError):
                continue

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"
ARCHIVE_SRC = ROOT / "src" / "archive"
ARCHIVE_DATA = DATA / "archive"

DATA_FILES: dict[str, str] = {
    # raw
    "events": "raw/events.csv",
    "population": "raw/population.csv",
    "state_area": "raw/state_area.csv",
    # Official EM-DAT workbook and its state-level derived workbook.
    "emdat": "raw/EM-DAT-BASE.xlsx",
    "emdat_base": "raw/EM-DAT-BASE.xlsx",
    "emdat_state": "raw/EM-DAT.xlsx",
    # API output is staging data until it is validated and promoted to BASE.
    "emdat_api_csv": "raw/emdat_api_raw.csv",
    "emdat_meta": "raw/emdat_api_raw.meta.json",
    "gdelt_bq": "raw/gdelt_bq.json",
    "gdelt_sql": "raw/gdelt_emdat_query.sql",
    "gdelt_meta": "raw/gdelt_bq.meta.json",
    "events_quarantine": "raw/events_quarantine.csv",
    # cache
    "flood_extent": "cache/flood_extent.csv",
    "sits_scores": "cache/sits_scores",
    "sits_patches": "cache/sits_patches",
    "sits_patches_index": "cache/sits_patches_index.csv",
    "satellite_checkpoint_a": "cache/satellite_checkpoint_a.json",
    "satellite_checkpoint_b": "cache/satellite_checkpoint_b.json",
    # Sentinel-1 patches for the Kuro Siwo FloodViT model (6ch, 224px, linear sigma0)
    "sar_patches": "cache/sar_patches",
    "sar_patches_index": "cache/sar_patches_index.csv",
    "sar_checkpoint": "cache/sar_checkpoint.json",
    # Per-event flood area from sar_flood_area.py (Kuro Siwo FloodViT over S1).
    # Written to the run's --state-dir, which is a Drive folder on Colab; copy it
    # here so merge_results.py can pick it up.
    "sar_flood_area": "cache/sar_flood_area.csv",
    "ne_india_states": "cache/ne_india_states.gpkg",
    # intermediate
    "flood_combined": "intermediate/flood_combined.csv",
    "event_aoi_area": "intermediate/event_aoi_area.csv",
    "post_cloud": "intermediate/post_cloud.csv",
    "severity_raw": "intermediate/severity_raw.csv",
    # results
    "pss_results": "results/pss_results.csv",
    "mss_results": "results/mss_results.csv",
    "expected_coverage": "results/expected_coverage.csv",
    "state_expected_coverage": "results/state_expected_coverage.csv",
    "mss_weight_meta": "results/mss_weight_sensitivity.json",
    "mss_weight_provenance": "results/mss_weight_provenance.csv",
    "mss_rank_stability": "results/mss_rank_stability.csv",
    # archive fallback
    "flood_area_results": "archive/flood_area_results.csv",
}

OUTPUT_FILES: dict[str, str] = {
    "pipeline_result": "pipeline_result.md",
}


def data_path(key: str) -> Path:
    """Return absolute path for a registered data artifact."""
    try:
        rel = DATA_FILES[key]
    except KeyError as exc:
        known = ", ".join(sorted(DATA_FILES))
        raise KeyError(f"Unknown data key {key!r}. Known keys: {known}") from exc
    return DATA / rel


def output_path(key: str) -> Path:
    """Return absolute path for a registered output artifact."""
    try:
        rel = OUTPUT_FILES[key]
    except KeyError as exc:
        known = ", ".join(sorted(OUTPUT_FILES))
        raise KeyError(f"Unknown output key {key!r}. Known keys: {known}") from exc
    return OUTPUTS / rel
