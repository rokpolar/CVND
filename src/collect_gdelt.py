#!/usr/bin/env python3
"""Collect historical GDELT coverage for canonical EM-DAT state-events.

The GDELT DOC API is suitable only for recent exploration. This collector uses
the partitioned GDELT 2.0 GKG BigQuery table so the full 2015+ EM-DAT period can
be queried reproducibly. It can write reviewable SQL without credentials or
execute that SQL when Google Application Default Credentials are configured.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from cvnd_layout import data_path


GKG_TABLE = "gdelt-bq.gdeltv2.gkg_partitioned"
TIB_BYTES = 1024 ** 4
DEFAULT_BATCH_LIMIT_TIB = 0.95

STRICT_FLOOD_THEMES = (
    "NATURAL_DISASTER_FLOOD",
    "NATURAL_DISASTER_FLOODING",
    "NATURAL_DISASTER_FLOODS",
    "NATURAL_DISASTER_FLOODED",
    "NATURAL_DISASTER_FLOODED_AREAS",
    "NATURAL_DISASTER_FLOODED_ROAD",
    "NATURAL_DISASTER_FLOODED_ROADS",
    "NATURAL_DISASTER_FLOODWATER",
    "NATURAL_DISASTER_FLOODWATERS",
    "NATURAL_DISASTER_FLOOD_WARNING",
    "NATURAL_DISASTER_FLOOD_WATER",
    "NATURAL_DISASTER_FLOOD_WATERS",
    "NATURAL_DISASTER_FLASH_FLOOD",
    "NATURAL_DISASTER_FLASH_FLOODS",
)

BROAD_FLOOD_THEMES = STRICT_FLOOD_THEMES + (
    "NATURAL_DISASTER_HEAVY_RAIN",
    "NATURAL_DISASTER_HEAVY_RAINS",
    "NATURAL_DISASTER_TORRENTIAL_RAIN",
    "NATURAL_DISASTER_TORRENTIAL_RAINFALL",
    "NATURAL_DISASTER_TORRENTIAL_RAINS",
    "NATURAL_DISASTER_HIGH_WATER",
    "NATURAL_DISASTER_HIGH_WATERS",
    "NATURAL_DISASTER_WATER_LEVEL",
    "NATURAL_DISASTER_MONSOON",
    "NATURAL_DISASTER_MONSOON_RAIN",
    "NATURAL_DISASTER_MONSOON_RAINS",
)

# Exact intersection of languages individually enumerated by India's 2011
# Census C-16 mother-tongue table and languages supported by GDELT Translingual
# 2.0. English enters GKG with blank TranslationInfo and is normalized to `en`;
# translated sources use the ISO 639-2 codes below.
INDIA_MEDIA_LANGUAGES = (
    "en",
    "ara",  # Arabic/Arbi
    "ben",  # Bengali
    "guj",  # Gujarati
    "hin",  # Hindi
    "kan",  # Kannada
    "mal",  # Malayalam
    "mar",  # Marathi
    "nep",  # Nepali
    "ori",  # Odia/Oriya
    "pan",  # Punjabi
    "pus",  # Afghani/Kabuli/Pashto
    "snd",  # Sindhi
    "tam",  # Tamil
    "tel",  # Telugu
    "urd",  # Urdu
)

STATE_SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "Delhi": ("New Delhi", "NCT of Delhi"),
    "Jammu and Kashmir": ("Jammu & Kashmir", "Jammu Kashmir"),
    "Karnataka": ("Bangalore",),
    "Odisha": ("Orissa",),
    "Puducherry": ("Pondicherry",),
    "Tamil Nadu": ("Tamilnadu",),
    "Uttarakhand": ("Uttaranchal",),
}

REQUIRED_OUTPUT_COLUMNS = {
    "event_id",
    "state",
    "source_record_id",
    "source_lang",
    "article_count",
    "first_article_date",
    "last_article_date",
    "coverage_days",
}


def _sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _sql_array(values: Iterable[str]) -> str:
    return "[" + ", ".join(_sql_string(value) for value in values) + "]"


def _unique_terms(state: str, district: str, include_district: bool) -> list[str]:
    terms = [state, *STATE_SEARCH_ALIASES.get(state, ())]
    district = str(district or "").strip()
    if (
        include_district
        and district
        and district.lower() != state.lower()
        and district != "Administrative unit not available"
    ):
        terms.append(district)
    return list(dict.fromkeys(term.lower() for term in terms if term.strip()))


def prepare_event_windows(
    events: pd.DataFrame,
    *,
    pre_days: int,
    post_days: int,
    include_district: bool,
) -> list[dict[str, Any]]:
    required = {
        "event_id", "state", "district", "start_date", "source_record_id", "event_source"
    }
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"events.csv is missing columns: {sorted(missing)}")
    if pre_days < 0 or post_days < 0:
        raise ValueError("pre_days and post_days must be non-negative")
    if not (events["event_source"] == "emdat_official_state").all():
        raise ValueError("GDELT collection accepts only official EM-DAT state-events")

    rows = []
    for _, row in events.sort_values("event_id").iterrows():
        onset = date.fromisoformat(str(row["start_date"]))
        rows.append(
            {
                "event_id": str(row["event_id"]),
                "state": str(row["state"]),
                "source_record_id": str(row["source_record_id"]),
                "onset_date": onset,
                "query_start": onset - timedelta(days=pre_days),
                "query_end": onset + timedelta(days=post_days),
                "location_terms": _unique_terms(
                    str(row["state"]), str(row["district"]), include_district
                ),
            }
        )
    if not rows:
        raise ValueError("No canonical events selected")
    return rows


def _event_struct(row: dict[str, Any]) -> str:
    return (
        "STRUCT("
        f"{_sql_string(row['event_id'])} AS event_id, "
        f"{_sql_string(row['state'])} AS state, "
        f"{_sql_string(row['source_record_id'])} AS source_record_id, "
        f"DATE '{row['onset_date'].isoformat()}' AS onset_date, "
        f"DATE '{row['query_start'].isoformat()}' AS query_start, "
        f"DATE '{row['query_end'].isoformat()}' AS query_end, "
        f"{_sql_array(row['location_terms'])} AS location_terms)"
    )


def coalesce_query_ranges(windows: list[dict[str, Any]]) -> list[tuple[date, date]]:
    """Union event windows into contiguous ranges for exact partition pruning."""
    intervals = sorted((row["query_start"], row["query_end"]) for row in windows)
    merged: list[tuple[date, date]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def coupled_event_groups(
    windows: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Keep overlapping windows from the same state in one atomic batch.

    Their article assignment is coupled: splitting them would let one URL be
    assigned independently in multiple batches. Different states remain
    independent because the primary query intentionally permits a URL to count
    once for every state it explicitly matches.
    """
    groups: list[list[dict[str, Any]]] = []
    by_state: dict[str, list[dict[str, Any]]] = {}
    for window in windows:
        by_state.setdefault(window["state"], []).append(window)

    for state_windows in by_state.values():
        ordered = sorted(
            state_windows,
            key=lambda row: (row["query_start"], row["query_end"], row["event_id"]),
        )
        current = [ordered[0]]
        current_end = ordered[0]["query_end"]
        for window in ordered[1:]:
            if window["query_start"] <= current_end:
                current.append(window)
                current_end = max(current_end, window["query_end"])
            else:
                groups.append(current)
                current = [window]
                current_end = window["query_end"]
        groups.append(current)

    return sorted(
        groups,
        key=lambda group: (
            min(row["query_start"] for row in group),
            min(row["event_id"] for row in group),
        ),
    )


def plan_query_batches(
    windows: list[dict[str, Any]],
    *,
    max_bytes: int,
    estimate_windows: Callable[[list[dict[str, Any]]], int],
) -> list[dict[str, Any]]:
    """Pack chronological event groups under an exact dry-run byte ceiling."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    units = coupled_event_groups(windows)
    batches: list[dict[str, Any]] = []
    start = 0
    while start < len(units):
        low, high = 1, len(units) - start
        best_count = 0
        best_bytes = 0
        cache: dict[int, int] = {}

        while low <= high:
            count = (low + high) // 2
            candidate = [
                row
                for group in units[start : start + count]
                for row in group
            ]
            if count not in cache:
                cache[count] = int(estimate_windows(candidate))
            estimated = cache[count]
            if estimated <= max_bytes:
                best_count = count
                best_bytes = estimated
                low = count + 1
            else:
                high = count - 1

        if best_count == 0:
            atomic_group = units[start]
            estimated = int(estimate_windows(atomic_group))
            event_ids = ", ".join(row["event_id"] for row in atomic_group)
            raise ValueError(
                "An indivisible same-state overlap group exceeds the batch limit: "
                f"{event_ids} requires {estimated / TIB_BYTES:.3f} TiB"
            )

        batch_windows = [
            row
            for group in units[start : start + best_count]
            for row in group
        ]
        batches.append(
            {
                "windows": sorted(batch_windows, key=lambda row: row["event_id"]),
                "estimated_bytes": best_bytes,
            }
        )
        start += best_count
    return batches


def build_query(
    windows: list[dict[str, Any]],
    *,
    topic_profile: str = "strict",
    languages: tuple[str, ...] = (),
    include_domains: tuple[str, ...] = (),
    exclude_domains: tuple[str, ...] = (),
    title_fallback: bool = False,
) -> str:
    """Build Standard SQL with one-article-per-state assignment.

    An article may count for multiple states only when it explicitly matches
    each state. Within one state, a normalized URL is assigned to the nearest
    event onset so overlapping EM-DAT windows cannot double-count it.
    """
    themes = STRICT_FLOOD_THEMES if topic_profile == "strict" else BROAD_FLOOD_THEMES
    if topic_profile not in {"strict", "broad"}:
        raise ValueError("topic_profile must be 'strict' or 'broad'")

    global_start = min(row["query_start"] for row in windows)
    global_end = max(row["query_end"] for row in windows)
    event_sql = ",\n    ".join(_event_struct(row) for row in windows)
    partition_ranges = coalesce_query_ranges(windows)
    partition_filter = "(\n        " + "\n        OR ".join(
        "(_PARTITIONTIME >= TIMESTAMP(" + _sql_string(start.isoformat()) + ") "
        "AND _PARTITIONTIME < TIMESTAMP(" + _sql_string((end + timedelta(days=1)).isoformat()) + "))"
        for start, end in partition_ranges
    ) + "\n      )"

    filters = [
        partition_filter,
        f"`DATE` >= {global_start.strftime('%Y%m%d')}000000",
        f"`DATE` <= {global_end.strftime('%Y%m%d')}235959",
        "DocumentIdentifier IS NOT NULL",
        "EXISTS (\n"
        "        SELECT 1\n"
        "        FROM UNNEST(SPLIT(COALESCE(V2Locations, ''), ';')) AS location_ref\n"
        "        WHERE UPPER(SPLIT(location_ref, '#')[SAFE_OFFSET(2)]) = 'IN'\n"
        "      )",
        "EXISTS (\n"
        "        SELECT 1\n"
        "        FROM UNNEST(SPLIT(COALESCE(V2Themes, ''), ';')) AS theme_ref\n"
        f"        WHERE SPLIT(theme_ref, ',')[SAFE_OFFSET(0)] IN UNNEST({_sql_array(themes)})\n"
        "      )",
    ]

    language_filter = ""
    if languages:
        normalized = tuple("en" if lang == "eng" else lang for lang in languages)
        language_filter = f"  WHERE source_lang IN UNNEST({_sql_array(normalized)})"

    if include_domains:
        filters.append(
            f"LOWER(COALESCE(SourceCommonName, '')) IN UNNEST({_sql_array(tuple(d.lower() for d in include_domains))})"
        )
    if exclude_domains:
        filters.append(
            f"LOWER(COALESCE(SourceCommonName, '')) NOT IN UNNEST({_sql_array(tuple(d.lower() for d in exclude_domains))})"
        )

    where_sql = "\n      AND ".join(filters)
    title_expression = (
        "LOWER(COALESCE(REGEXP_EXTRACT(Extras, "
        "r'<PAGE_TITLE>([^<]*)</PAGE_TITLE>'), ''))"
        if title_fallback
        else "CAST('' AS STRING)"
    )
    return f"""#standardSQL
-- Generated by src/collect_gdelt.py. Review before execution.
-- Unit: one official EM-DAT DisNo. x Indian state/UT event.
-- Deduplication: exact GDELT DocumentIdentifier; one identifier per state is
-- assigned to the nearest event onset when windows overlap.
WITH event_windows AS (
  SELECT * FROM UNNEST([
    {event_sql}
  ])
),
gkg_raw AS (
  SELECT
    PARSE_TIMESTAMP('%Y%m%d%H%M%S', CAST(`DATE` AS STRING), 'UTC') AS published_at,
    DocumentIdentifier AS url,
    TRIM(DocumentIdentifier) AS normalized_url,
    LOWER(COALESCE(V2Locations, '')) AS locations_lower,
    {title_expression} AS title_lower,
    CASE
      WHEN REGEXP_EXTRACT(COALESCE(TranslationInfo, ''), r'srclc:([a-z]{{3}})') = 'eng' THEN 'en'
      ELSE COALESCE(
        REGEXP_EXTRACT(COALESCE(TranslationInfo, ''), r'srclc:([a-z]{{3}})'),
        'en'
      )
    END AS source_lang
  FROM `{GKG_TABLE}`
  WHERE {where_sql}
),
gkg AS (
  SELECT *
  FROM gkg_raw
{language_filter}
),
candidate_matches AS (
  SELECT
    e.event_id,
    e.state,
    e.source_record_id,
    e.onset_date,
    g.*,
    ABS(DATE_DIFF(DATE(g.published_at), e.onset_date, DAY)) AS onset_distance
  FROM event_windows e
  JOIN gkg AS g
    ON DATE(g.published_at) BETWEEN e.query_start AND e.query_end
  WHERE (
     EXISTS (
       SELECT 1
       FROM UNNEST(SPLIT(g.locations_lower, ';')) AS location_ref
       CROSS JOIN UNNEST(e.location_terms) AS term
       WHERE SPLIT(location_ref, '#')[SAFE_OFFSET(2)] = 'in'
         AND EXISTS (
           SELECT 1
           FROM UNNEST(SPLIT(
             COALESCE(SPLIT(location_ref, '#')[SAFE_OFFSET(1)], ''), ','
           )) AS location_part
           WHERE TRIM(location_part) = term
         )
     )
     OR EXISTS (
       SELECT 1
       FROM UNNEST(e.location_terms) AS term
       WHERE STRPOS(
         CONCAT(' ', REGEXP_REPLACE(g.title_lower, r'[^a-z0-9]+', ' '), ' '),
         CONCAT(' ', REGEXP_REPLACE(term, r'[^a-z0-9]+', ' '), ' ')
       ) > 0
     )
   )
),
assigned AS (
  SELECT * EXCEPT(assignment_rank, onset_distance)
  FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY normalized_url, state
      ORDER BY onset_distance, onset_date, event_id, published_at, url
    ) AS assignment_rank
    FROM candidate_matches
  )
  WHERE assignment_rank = 1
),
language_stats AS (
  SELECT
    event_id,
    state,
    source_record_id,
    source_lang,
    COUNT(DISTINCT normalized_url) AS article_count,
    MIN(DATE(published_at)) AS first_article_date,
    MAX(DATE(published_at)) AS last_article_date
  FROM assigned
  GROUP BY event_id, state, source_record_id, source_lang
),
event_days AS (
  SELECT event_id, COUNT(DISTINCT DATE(published_at)) AS coverage_days
  FROM assigned
  GROUP BY event_id
)
SELECT
  e.event_id,
  e.state,
  e.source_record_id,
  COALESCE(s.source_lang, 'und') AS source_lang,
  COALESCE(s.article_count, 0) AS article_count,
  s.first_article_date,
  s.last_article_date,
  COALESCE(d.coverage_days, 0) AS coverage_days,
  COALESCE(d.coverage_days, 0) AS coverage_days_threshold_1
FROM event_windows e
LEFT JOIN language_stats s USING (event_id, state, source_record_id)
LEFT JOIN event_days d USING (event_id)
ORDER BY e.event_id, article_count DESC, source_lang
"""


def validate_output(rows: list[dict[str, Any]], expected_event_ids: set[str]) -> None:
    if not rows:
        raise ValueError("BigQuery returned no rows")
    missing_columns = REQUIRED_OUTPUT_COLUMNS - set(rows[0])
    if missing_columns:
        raise ValueError(f"GDELT output missing columns: {sorted(missing_columns)}")
    observed = {str(row["event_id"]) for row in rows}
    missing_events = expected_event_ids - observed
    extra_events = observed - expected_event_ids
    if missing_events or extra_events:
        raise ValueError(
            f"GDELT event coverage mismatch: missing={sorted(missing_events)}, "
            f"extra={sorted(extra_events)}"
        )
    pairs = [(str(row["event_id"]), str(row["source_lang"])) for row in rows]
    if len(pairs) != len(set(pairs)):
        raise ValueError("Duplicate event_id/source_lang rows in GDELT output")


def _json_ready(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def execute_query(
    sql: str,
    billing_project: str | None,
    *,
    maximum_bytes_billed: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for --execute; install requirements.txt"
        ) from exc

    client = bigquery.Client(project=billing_project)
    job_config = bigquery.QueryJobConfig()
    if maximum_bytes_billed is not None:
        job_config.maximum_bytes_billed = maximum_bytes_billed
    job = client.query(sql, job_config=job_config)
    rows = [
        {key: _json_ready(value) for key, value in dict(row.items()).items()}
        for row in job.result()
    ]
    return rows, {
        "job_id": job.job_id,
        "billing_project": client.project,
        "total_bytes_processed": int(job.total_bytes_processed or 0),
        "cache_hit": bool(job.cache_hit),
    }


def estimate_query(sql: str, billing_project: str | None) -> tuple[int, str]:
    """Validate SQL and estimate bytes through a BigQuery dry run."""
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for --estimate; install requirements.txt"
        ) from exc
    client = bigquery.Client(project=billing_project)
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False),
    )
    return int(job.total_bytes_processed or 0), client.project


def _query_options(args: argparse.Namespace, languages: tuple[str, ...]) -> dict[str, Any]:
    return {
        "topic_profile": args.topic_profile,
        "pre_days": args.pre_days,
        "post_days": args.post_days,
        "languages": list(languages),
        "include_domains": list(args.include_domain),
        "exclude_domains": list(args.exclude_domain),
        "include_district_term": not args.no_district_term,
        "title_fallback": args.title_fallback,
    }


def _build_query_for_args(
    windows: list[dict[str, Any]],
    args: argparse.Namespace,
    languages: tuple[str, ...],
) -> str:
    return build_query(
        windows,
        topic_profile=args.topic_profile,
        languages=languages,
        include_domains=tuple(args.include_domain),
        exclude_domains=tuple(args.exclude_domain),
        title_fallback=args.title_fallback,
    )


def _load_batch_manifest(batch_dir: Path) -> dict[str, Any]:
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Batch manifest not found: {manifest_path}; run --plan-batches first"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not manifest.get("batches"):
        raise ValueError(f"Invalid batch manifest: {manifest_path}")
    return manifest


def _verify_manifest_events(manifest: dict[str, Any], events_path: Path) -> None:
    current_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()
    if manifest.get("events_sha256") != current_hash:
        raise ValueError(
            "events.csv changed after batch planning; regenerate the plan with "
            "--plan-batches --overwrite"
        )


def write_batch_plan(
    batches: list[dict[str, Any]],
    *,
    args: argparse.Namespace,
    languages: tuple[str, ...],
    max_bytes: int,
) -> dict[str, Any]:
    manifest_path = args.batch_dir / "manifest.json"
    targets = [manifest_path]
    for index in range(1, len(batches) + 1):
        batch_id = f"B{index:03d}"
        targets.append(args.batch_dir / f"{batch_id}.sql")
    existing = [path for path in targets if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(
            f"Batch plan output exists: {existing[0]}; pass --overwrite"
        )

    manifest_batches = []
    for index, batch in enumerate(batches, start=1):
        batch_id = f"B{index:03d}"
        windows = batch["windows"]
        sql = _build_query_for_args(windows, args, languages)
        sql_name = f"{batch_id}.sql"
        output_name = f"{batch_id}.json"
        metadata_name = f"{batch_id}.meta.json"
        _atomic_write(args.batch_dir / sql_name, sql)
        manifest_batches.append(
            {
                "batch_id": batch_id,
                "event_ids": [row["event_id"] for row in windows],
                "event_count": len(windows),
                "query_start": min(row["query_start"] for row in windows).isoformat(),
                "query_end": max(row["query_end"] for row in windows).isoformat(),
                "estimated_bytes": batch["estimated_bytes"],
                "estimated_tib": round(batch["estimated_bytes"] / TIB_BYTES, 6),
                "sql_file": sql_name,
                "output_file": output_name,
                "metadata_file": metadata_name,
            }
        )

    manifest = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_table": GKG_TABLE,
        "events_sha256": hashlib.sha256(args.events.read_bytes()).hexdigest(),
        "batch_limit_bytes": max_bytes,
        "batch_limit_tib": round(max_bytes / TIB_BYTES, 6),
        "query_options": _query_options(args, languages),
        "batches": manifest_batches,
    }
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest


def _csv_values(values: str | None) -> tuple[str, ...]:
    if not values:
        return ()
    if values.strip().lower() == "all":
        return ()
    return tuple(value.strip().lower() for value in values.split(",") if value.strip())


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=data_path("events"))
    parser.add_argument("--sql-output", type=Path, default=data_path("gdelt_sql"))
    parser.add_argument("--output", type=Path, default=data_path("gdelt_bq"))
    parser.add_argument("--metadata", type=Path, default=data_path("gdelt_meta"))
    parser.add_argument(
        "--batch-dir",
        type=Path,
        default=data_path("gdelt_bq").parent / "gdelt_batches",
    )
    parser.add_argument(
        "--max-batch-tib",
        type=float,
        default=DEFAULT_BATCH_LIMIT_TIB,
        help="Dry-run and execution ceiling per batch in TiB (default: 0.95)",
    )
    parser.add_argument("--topic-profile", choices=("strict", "broad"), default="strict")
    parser.add_argument("--pre-days", type=int, default=0)
    parser.add_argument("--post-days", type=int, default=93)
    parser.add_argument(
        "--languages",
        default=",".join(INDIA_MEDIA_LANGUAGES),
        help=(
            "Comma-separated source-language codes; default is the exact "
            "India Census x GDELT-supported intersection; use 'all' for no filter"
        ),
    )
    parser.add_argument("--include-domain", action="append", default=[])
    parser.add_argument("--exclude-domain", action="append", default=[])
    parser.add_argument("--event-id", action="append", default=[])
    parser.add_argument("--no-district-term", action="store_true")
    parser.add_argument(
        "--title-fallback",
        action="store_true",
        help="Also scan GKG Extras page titles; improves recall but increases bytes processed",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--estimate", action="store_true", help="BigQuery dry run: validate SQL and estimate bytes")
    action.add_argument("--execute", action="store_true")
    action.add_argument(
        "--plan-batches",
        action="store_true",
        help="Dry-run chronological groups and write a resumable byte-capped plan",
    )
    action.add_argument(
        "--execute-batch",
        metavar="BATCH_ID",
        help="Execute one planned batch, such as B001",
    )
    action.add_argument(
        "--merge-batches",
        action="store_true",
        help="Merge all completed planned batches into the primary output",
    )
    parser.add_argument("--billing-project", default=os.getenv("GDELT_BILLING_PROJECT"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.event_id and (
            args.plan_batches or args.execute_batch or args.merge_batches
        ):
            raise ValueError(
                "--event-id cannot be combined with batch planning, execution, or merge"
            )
        events = pd.read_csv(args.events)
        if args.event_id:
            events = events[events["event_id"].isin(args.event_id)].copy()
            unknown = sorted(set(args.event_id) - set(events["event_id"]))
            if unknown:
                raise ValueError(f"Unknown event IDs: {unknown}")

        windows = prepare_event_windows(
            events,
            pre_days=args.pre_days,
            post_days=args.post_days,
            include_district=not args.no_district_term,
        )
        languages = _csv_values(args.languages)

        print(f"Events: {len(windows)}")
        print(f"Date range: {min(w['query_start'] for w in windows)} to {max(w['query_end'] for w in windows)}")
        print(f"Topic profile: {args.topic_profile}")
        print(f"Languages: {languages or 'all GKG source languages'}")

        if args.plan_batches:
            max_bytes = int(args.max_batch_tib * TIB_BYTES)
            if max_bytes <= 0:
                raise ValueError("--max-batch-tib must be positive")

            def estimate_windows(candidate: list[dict[str, Any]]) -> int:
                sql = _build_query_for_args(candidate, args, languages)
                estimated, project = estimate_query(sql, args.billing_project)
                print(
                    f"  dry run {len(candidate):3d} events: "
                    f"{estimated / TIB_BYTES:.3f} TiB ({project})"
                )
                return estimated

            batches = plan_query_batches(
                windows,
                max_bytes=max_bytes,
                estimate_windows=estimate_windows,
            )
            manifest = write_batch_plan(
                batches,
                args=args,
                languages=languages,
                max_bytes=max_bytes,
            )
            print(
                f"Wrote {len(manifest['batches'])} batches under "
                f"{args.max_batch_tib:.3f} TiB: {args.batch_dir / 'manifest.json'}"
            )
            for batch in manifest["batches"]:
                print(
                    f"  {batch['batch_id']}: {batch['event_count']} events, "
                    f"{batch['estimated_tib']:.3f} TiB, "
                    f"{batch['query_start']} to {batch['query_end']}"
                )
            return 0

        if args.execute_batch:
            manifest = _load_batch_manifest(args.batch_dir)
            _verify_manifest_events(manifest, args.events)
            batch = next(
                (
                    item
                    for item in manifest["batches"]
                    if item["batch_id"] == args.execute_batch
                ),
                None,
            )
            if batch is None:
                available = ", ".join(item["batch_id"] for item in manifest["batches"])
                raise ValueError(
                    f"Unknown batch {args.execute_batch!r}; available: {available}"
                )
            output_path = args.batch_dir / batch["output_file"]
            metadata_path = args.batch_dir / batch["metadata_file"]
            if output_path.exists() and not args.overwrite:
                print(f"Batch already complete; skipping: {output_path}")
                return 0

            sql_path = args.batch_dir / batch["sql_file"]
            sql = sql_path.read_text(encoding="utf-8")
            maximum_bytes_billed = int(manifest["batch_limit_bytes"])
            rows, job_meta = execute_query(
                sql,
                args.billing_project,
                maximum_bytes_billed=maximum_bytes_billed,
            )
            validate_output(rows, set(batch["event_ids"]))
            _atomic_write(
                output_path,
                json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            )
            metadata = {
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "batch_id": batch["batch_id"],
                "batch_limit_bytes": maximum_bytes_billed,
                "estimated_bytes": batch["estimated_bytes"],
                "event_ids": batch["event_ids"],
                "result_rows": len(rows),
                "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                **job_meta,
            }
            _atomic_write(
                metadata_path,
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            )
            print(f"Completed {batch['batch_id']}: {output_path}")
            print(f"Wrote provenance: {metadata_path}")
            return 0

        if args.merge_batches:
            manifest = _load_batch_manifest(args.batch_dir)
            _verify_manifest_events(manifest, args.events)
            missing = [
                item["batch_id"]
                for item in manifest["batches"]
                if not (args.batch_dir / item["output_file"]).exists()
            ]
            if missing:
                raise ValueError(
                    "Cannot merge; incomplete batches: " + ", ".join(missing)
                )
            for target in (args.output, args.metadata):
                if target.exists() and not args.overwrite:
                    raise FileExistsError(f"Output exists: {target}; pass --overwrite")

            rows: list[dict[str, Any]] = []
            batch_metadata = []
            expected_event_ids: set[str] = set()
            for batch in manifest["batches"]:
                rows.extend(
                    json.loads(
                        (args.batch_dir / batch["output_file"]).read_text(
                            encoding="utf-8"
                        )
                    )
                )
                expected_event_ids.update(batch["event_ids"])
                metadata_path = args.batch_dir / batch["metadata_file"]
                if metadata_path.exists():
                    batch_metadata.append(
                        json.loads(metadata_path.read_text(encoding="utf-8"))
                    )
            validate_output(rows, expected_event_ids)
            rows.sort(
                key=lambda row: (
                    str(row["event_id"]),
                    -int(row["article_count"]),
                    str(row["source_lang"]),
                )
            )
            _atomic_write(
                args.output,
                json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            )
            merged_metadata = {
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_table": GKG_TABLE,
                "collection_mode": "merged_batches",
                "events_sha256": manifest["events_sha256"],
                "event_count": len(expected_event_ids),
                "result_rows": len(rows),
                "batch_count": len(manifest["batches"]),
                "query_options": manifest["query_options"],
                "total_bytes_processed": sum(
                    int(item.get("total_bytes_processed", 0))
                    for item in batch_metadata
                ),
                "batch_job_ids": [
                    item.get("job_id") for item in batch_metadata if item.get("job_id")
                ],
            }
            _atomic_write(
                args.metadata,
                json.dumps(merged_metadata, ensure_ascii=False, indent=2) + "\n",
            )
            print(f"Merged {len(manifest['batches'])} batches: {args.output}")
            print(f"Wrote provenance: {args.metadata}")
            return 0

        sql = _build_query_for_args(windows, args, languages)
        if args.dry_run:
            print(sql)
            return 0

        if args.sql_output.exists() and not args.overwrite:
            raise FileExistsError(f"SQL output exists: {args.sql_output}; pass --overwrite")
        _atomic_write(args.sql_output, sql)
        print(f"Wrote reviewable SQL: {args.sql_output}")

        if args.estimate:
            bytes_processed, project = estimate_query(sql, args.billing_project)
            print(f"BigQuery project: {project}")
            print(f"Dry-run bytes processed: {bytes_processed:,} ({bytes_processed / 1e9:.3f} GB)")
            return 0

        if not args.execute:
            print("SQL only; pass --execute after configuring Google credentials")
            return 0

        for target in (args.output, args.metadata):
            if target.exists() and not args.overwrite:
                raise FileExistsError(f"Output exists: {target}; pass --overwrite")

        rows, job_meta = execute_query(sql, args.billing_project)
        validate_output(rows, {window["event_id"] for window in windows})
        payload = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(args.output, payload)

        metadata = {
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_table": GKG_TABLE,
            "events_sha256": hashlib.sha256(args.events.read_bytes()).hexdigest(),
            "emdat_base_sha256": (
                hashlib.sha256(data_path("emdat_base").read_bytes()).hexdigest()
                if data_path("emdat_base").exists()
                else None
            ),
            "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            "event_count": len(windows),
            "result_rows": len(rows),
            **_query_options(args, languages),
            **job_meta,
        }
        _atomic_write(args.metadata, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        print(f"Wrote {len(rows)} event-language rows: {args.output}")
        print(f"Wrote provenance: {args.metadata}")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
