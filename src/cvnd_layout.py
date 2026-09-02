"""Convention-based paths for the CVND primary analysis stack.

Resolve data artifacts by logical key via data_path(key). Tier layout:
  data/raw/          — external inputs
  data/cache/        — satellite / GEE caches
  data/intermediate/ — pipeline step outputs
  data/results/      — joined flood + article outputs
  data/archive/      — legacy fallbacks (unchanged)
"""

from __future__ import annotations

from pathlib import Path

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
    "gdelt_articles": "raw/gdelt_bq.articles.jsonl.gz",
    "gdelt_sql": "raw/gdelt_emdat_query.sql",
    "gdelt_meta": "raw/gdelt_bq.meta.json",
    "gdelt_article_database": "raw/gdelt_bq.articles.sqlite",
    "events_quarantine": "raw/events_quarantine.csv",
    # cache
    "flood_extent": "cache/flood_extent.csv",
    "sits_scores": "cache/sits_scores",
    "sits_patches": "cache/sits_patches",
    "sits_patches_index": "cache/sits_patches_index.csv",
    "satellite_checkpoint_a": "cache/satellite_checkpoint_a.json",
    "satellite_checkpoint_b": "cache/satellite_checkpoint_b.json",
    "ne_india_states": "cache/ne_india_states.gpkg",
    # intermediate
    "flood_combined": "intermediate/flood_combined.csv",
    "event_aoi_area": "intermediate/event_aoi_area.csv",
    "post_cloud": "intermediate/post_cloud.csv",
    "severity_raw": "intermediate/severity_raw.csv",
    "event_relevance_database": "intermediate/gdelt_event_relevance.sqlite",
    "event_relevance_pilot_manifest": "intermediate/gdelt_event_relevance_pilot.csv",
    "event_relevance_pilot_evaluation": "intermediate/gdelt_event_relevance_pilot_evaluation.json",
    "event_relevance_pilot_annotated": "intermediate/gdelt_event_relevance_pilot_evaluated.csv",
    "article_retrieval_event_qc": "intermediate/article_retrieval_qc_by_event.csv",
    "article_retrieval_year_qc": "intermediate/article_retrieval_qc_by_year.csv",
    "article_retrieval_unresolved": "intermediate/article_retrieval_unresolved.csv.gz",
    # results
    "event_article_counts": "results/event_article_counts.csv",
    "event_articles": "results/event_articles.csv.gz",
    "event_article_counts_heuristic": "results/event_article_counts.heuristic.csv",
    "event_articles_heuristic": "results/event_articles.heuristic.csv.gz",
    "event_flood_articles": "results/event_flood_articles.csv",
    "state_flood_articles": "results/state_flood_articles.csv",
    # archive fallback
    "flood_area_results": "archive/flood_area_results.csv",
}

OUTPUT_FILES: dict[str, str] = {}


def data_path(key: str) -> Path:
    """Return absolute path for a registered data artifact."""
    try:
        rel = DATA_FILES[key]
    except KeyError as exc:
        known = ", ".join(sorted(DATA_FILES))
        raise KeyError(f"Unknown data key {key!r}. Known keys: {known}") from exc
    return DATA / rel


def output_path(key: str) -> Path:
    """Return absolute path for a registered output artifact under outputs/."""
    try:
        rel = OUTPUT_FILES[key]
    except KeyError as exc:
        known = ", ".join(sorted(OUTPUT_FILES))
        raise KeyError(f"Unknown output key {key!r}. Known keys: {known}") from exc
    return OUTPUTS / rel
