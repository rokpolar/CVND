#!/usr/bin/env python3
"""Internal historical GDELT BigQuery helpers for district collection.

The district entry point is ``src/district_articles.py``. This module keeps
the low-level SQL, BigQuery execution and serialization helpers it uses; it is
not a standalone command-line collector.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from cvnd_layout import ROOT, data_path

try:
    from dotenv import load_dotenv
except ImportError:  # Environment variables exported in the shell still work.
    pass
else:
    load_dotenv(ROOT / ".env")


GKG_TABLE = "gdelt-bq.gdeltv2.gkg_partitioned"
TIB_BYTES = 1024 ** 4
DEFAULT_MAXIMUM_TIB_BILLED = 2.0

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

REQUIRED_ARTICLE_COLUMNS = {
    "event_id",
    "state",
    "source_record_id",
    "gkg_record_id",
    "published_at",
    "url",
    "source_domain",
    "source_lang",
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


def build_query(
    windows: list[dict[str, Any]],
    *,
    topic_profile: str = "strict",
    languages: tuple[str, ...] = (),
    include_domains: tuple[str, ...] = (),
    exclude_domains: tuple[str, ...] = (),
    title_fallback: bool = False,
    result_level: str = "summary",
    article_metadata_profile: str = "basic",
) -> str:
    """Build Standard SQL with one-article-per-state assignment.

    An article may count for multiple states only when it explicitly matches
    each state. Within one state, a normalized URL is assigned to the nearest
    event onset so overlapping EM-DAT windows cannot double-count it.
    """
    themes = STRICT_FLOOD_THEMES if topic_profile == "strict" else BROAD_FLOOD_THEMES
    if topic_profile not in {"strict", "broad"}:
        raise ValueError("topic_profile must be 'strict' or 'broad'")
    if result_level not in {"summary", "articles"}:
        raise ValueError("result_level must be 'summary' or 'articles'")
    if article_metadata_profile not in {"basic", "rich"}:
        raise ValueError("article_metadata_profile must be 'basic' or 'rich'")

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
    include_article_metadata = result_level == "articles"
    include_rich_metadata = (
        include_article_metadata and article_metadata_profile == "rich"
    )
    title_expression = (
        "LOWER(COALESCE(REGEXP_EXTRACT(Extras, "
        "r'<PAGE_TITLE>([^<]*)</PAGE_TITLE>'), ''))"
        if title_fallback or include_rich_metadata
        else "CAST('' AS STRING)"
    )
    article_metadata_fields = ""
    if include_rich_metadata:
        article_metadata_fields = """,
    GKGRECORDID AS gkg_record_id,
    LOWER(COALESCE(SourceCommonName, '')) AS source_domain,
    REGEXP_EXTRACT(Extras, r'<PAGE_TITLE>([^<]*)</PAGE_TITLE>') AS title,
    REGEXP_EXTRACT(Extras, r'<PAGE_AUTHORS>([^<]*)</PAGE_AUTHORS>') AS authors,
    SAFE_CAST(SPLIT(COALESCE(V2Tone, ''), ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone,
    NULLIF(SharingImage, '') AS sharing_image"""
    elif include_article_metadata:
        article_metadata_fields = """,
    CAST(NULL AS STRING) AS gkg_record_id,
    LOWER(COALESCE(NET.REG_DOMAIN(DocumentIdentifier), '')) AS source_domain,
    CAST(NULL AS STRING) AS title,
    CAST(NULL AS STRING) AS authors,
    CAST(NULL AS FLOAT64) AS tone,
    CAST(NULL AS STRING) AS sharing_image"""

    if result_level == "articles":
        output_sql = """
SELECT
  event_id,
  state,
  source_record_id,
  gkg_record_id,
  onset_date,
  published_at,
  url,
  normalized_url,
  source_domain,
  source_lang,
  title,
  authors,
  tone,
  sharing_image
FROM assigned
ORDER BY event_id, published_at, normalized_url
"""
    else:
        output_sql = """,
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
    query = f"""#standardSQL
-- Generated by the internal GDELT backend. Review before execution.
-- Legacy helper query; district collection uses district_articles.py.
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
    END AS source_lang{article_metadata_fields}
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
)
{output_sql}
"""
    return query.rstrip() + "\n"


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


class ArticleSummaryAccumulator:
    """Build per-event language summaries while article rows stream to disk."""

    def __init__(self, windows: list[dict[str, Any]]) -> None:
        self.events = {row["event_id"]: row for row in windows}
        self.language_stats: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self.coverage_dates: dict[str, set[str]] = {
            event_id: set() for event_id in self.events
        }
        self.article_rows = 0

    def add(self, row: dict[str, Any]) -> None:
        missing = REQUIRED_ARTICLE_COLUMNS - set(row)
        if missing:
            raise ValueError(
                f"GDELT article output missing columns: {sorted(missing)}"
            )
        event_id = str(row["event_id"])
        if event_id not in self.events:
            raise ValueError(f"Unexpected article event_id: {event_id}")
        source_lang = str(row.get("source_lang") or "und")
        published_date = str(row["published_at"])[:10]
        key = (
            event_id,
            str(row["state"]),
            str(row["source_record_id"]),
            source_lang,
        )
        stats = self.language_stats.setdefault(
            key,
            {"article_count": 0, "first_article_date": None, "last_article_date": None},
        )
        stats["article_count"] += 1
        if stats["first_article_date"] is None or published_date < stats["first_article_date"]:
            stats["first_article_date"] = published_date
        if stats["last_article_date"] is None or published_date > stats["last_article_date"]:
            stats["last_article_date"] = published_date
        self.coverage_dates[event_id].add(published_date)
        self.article_rows += 1

    def finish(self) -> list[dict[str, Any]]:
        rows = []
        observed = {key[0] for key in self.language_stats}
        for (event_id, state, source_record_id, source_lang), stats in sorted(
            self.language_stats.items()
        ):
            coverage_days = len(self.coverage_dates[event_id])
            rows.append(
                {
                    "event_id": event_id,
                    "state": state,
                    "source_record_id": source_record_id,
                    "source_lang": source_lang,
                    **stats,
                    "coverage_days": coverage_days,
                    "coverage_days_threshold_1": coverage_days,
                }
            )
        for event_id in sorted(set(self.events) - observed):
            event = self.events[event_id]
            rows.append(
                {
                    "event_id": event_id,
                    "state": event["state"],
                    "source_record_id": event["source_record_id"],
                    "source_lang": "und",
                    "article_count": 0,
                    "first_article_date": None,
                    "last_article_date": None,
                    "coverage_days": 0,
                    "coverage_days_threshold_1": 0,
                }
            )
        rows.sort(
            key=lambda row: (
                str(row["event_id"]),
                -int(row["article_count"]),
                str(row["source_lang"]),
            )
        )
        validate_output(rows, set(self.events))
        return rows


def execute_article_query(
    sql: str,
    billing_project: str | None,
    *,
    article_output: Path,
    windows: list[dict[str, Any]],
    maximum_bytes_billed: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Stream article-level BigQuery rows to gzip and aggregate them locally."""
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for execution; install requirements.txt"
        ) from exc

    client = bigquery.Client(project=billing_project)
    job_config = bigquery.QueryJobConfig()
    if maximum_bytes_billed is not None:
        job_config.maximum_bytes_billed = maximum_bytes_billed
    job = client.query(sql, job_config=job_config)
    result = job.result(page_size=5000)

    article_output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{article_output.name}.", dir=article_output.parent
    )
    os.close(fd)
    accumulator = ArticleSummaryAccumulator(windows)
    try:
        with gzip.open(tmp_name, "wt", encoding="utf-8") as handle:
            for result_row in result:
                row = {
                    key: _json_ready(value)
                    for key, value in dict(result_row.items()).items()
                }
                accumulator.add(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        summary_rows = accumulator.finish()
        os.replace(tmp_name, article_output)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise

    return summary_rows, {
        "job_id": job.job_id,
        "billing_project": client.project,
        "total_bytes_processed": int(job.total_bytes_processed or 0),
        "cache_hit": bool(job.cache_hit),
        "article_rows": accumulator.article_rows,
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
        "article_metadata_profile": args.article_metadata_profile,
    }


def _build_query_for_args(
    windows: list[dict[str, Any]],
    args: argparse.Namespace,
    languages: tuple[str, ...],
    *,
    result_level: str = "summary",
) -> str:
    return build_query(
        windows,
        topic_profile=args.topic_profile,
        languages=languages,
        include_domains=tuple(args.include_domain),
        exclude_domains=tuple(args.exclude_domain),
        title_fallback=args.title_fallback,
        result_level=result_level,
        article_metadata_profile=args.article_metadata_profile,
    )


def _csv_values(values: str | None) -> tuple[str, ...]:
    if not values:
        return ()
    if values.strip().lower() == "all":
        return ()
    return tuple(value.strip().lower() for value in values.split(",") if value.strip())


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spatial-unit",
        choices=("district",),
        default="district",
        help=(
            "Dispatch to src/district_articles.py with the fixed 14-day "
            "district-primary contract."
        ),
    )
    parser.add_argument("--events", type=Path, default=data_path("events"))
    parser.add_argument("--sql-output", type=Path, default=data_path("gdelt_sql"))
    parser.add_argument("--output", type=Path, default=data_path("gdelt_bq"))
    parser.add_argument(
        "--article-output", type=Path, default=data_path("gdelt_articles")
    )
    parser.add_argument("--metadata", type=Path, default=data_path("gdelt_meta"))
    parser.add_argument(
        "--maximum-tib-billed",
        type=float,
        default=DEFAULT_MAXIMUM_TIB_BILLED,
        help="Reject execution above this BigQuery scan size in TiB (default: 2.0)",
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
    parser.add_argument(
        "--article-metadata-profile",
        choices=("basic", "rich"),
        default="basic",
        help=(
            "basic reuses URL/date/language columns; rich also scans GKG ID, "
            "source, title, authors, tone, and image"
        ),
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--estimate", action="store_true", help="BigQuery dry run: validate SQL and estimate bytes")
    action.add_argument("--execute", action="store_true")
    parser.add_argument("--billing-project", default=os.getenv("GDELT_BILLING_PROJECT"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    args = parse_args(argv_list)
    if args.spatial_unit == "district":
        # Keep one discoverable CLI while leaving all state defaults and SQL
        # semantics intact.  The district module has its own output contract.
        from district_articles import main as district_main

        forwarded: list[str] = []
        skip_value = False
        for value in argv_list:
            if skip_value:
                skip_value = False
                continue
            if value == "--spatial-unit":
                skip_value = True
                continue
            if value.startswith("--spatial-unit="):
                continue
            forwarded.append(str(value))
        return district_main(forwarded)
    try:
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

        sql = _build_query_for_args(
            windows, args, languages, result_level="articles"
        )
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

        maximum_bytes_billed = int(args.maximum_tib_billed * TIB_BYTES)
        if maximum_bytes_billed <= 0:
            raise ValueError("--maximum-tib-billed must be positive")

        for target in (args.article_output, args.output, args.metadata):
            if target.exists() and not args.overwrite:
                raise FileExistsError(f"Output exists: {target}; pass --overwrite")

        rows, job_meta = execute_article_query(
            sql,
            args.billing_project,
            article_output=args.article_output,
            windows=windows,
            maximum_bytes_billed=maximum_bytes_billed,
        )
        payload = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(args.output, payload)

        metadata = {
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_table": GKG_TABLE,
            "collection_mode": "article_metadata",
            "events_sha256": hashlib.sha256(args.events.read_bytes()).hexdigest(),
            "emdat_base_sha256": (
                hashlib.sha256(data_path("emdat_base").read_bytes()).hexdigest()
                if data_path("emdat_base").exists()
                else None
            ),
            "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            "event_count": len(windows),
            "result_rows": len(rows),
            "article_output": str(args.article_output),
            "maximum_bytes_billed": maximum_bytes_billed,
            **_query_options(args, languages),
            **job_meta,
        }
        _atomic_write(args.metadata, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        print(
            f"Wrote {job_meta['article_rows']:,} article rows: {args.article_output}"
        )
        print(f"Wrote {len(rows)} event-language rows: {args.output}")
        print(f"Wrote provenance: {args.metadata}")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
