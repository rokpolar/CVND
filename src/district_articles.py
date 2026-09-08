#!/usr/bin/env python3
"""Collect and count GDELT articles for the CVND district primary unit.

This module intentionally sits beside the legacy state collector.  The state
collector has a wider, inclusive compatibility window; district analysis has
one fixed window (onset <= publication < onset + 14 days) and requires an
explicit district location in the GKG location block or, when requested, the
article title.  A state match by itself can never create a district article.

The module also contains the small deterministic heuristic export used by the
district primary analysis.  It reuses ``classify_event_articles``' keyword
lexicon and emits one row for every registry row, including zero and missing
observations.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import pandas as pd

from cvnd_layout import ROOT, data_path
from collect_gdelt import (
    GKG_TABLE,
    INDIA_MEDIA_LANGUAGES,
    STRICT_FLOOD_THEMES,
    BROAD_FLOOD_THEMES,
    _atomic_write,
    _csv_values,
    _json_ready,
    _sql_array,
    _sql_string,
    coalesce_query_ranges,
)
from district_keys import is_missing_name, make_event_district_id, normalize_name


from cvnd_config import PRIMARY_MEDIA_WINDOW_DAYS

DISTRICT_WINDOW_DAYS = PRIMARY_MEDIA_WINDOW_DAYS
# State labels only: the legacy collector also uses city terms for recall.
DISTRICT_STATE_ALIASES = {
    "Delhi": ("NCT of Delhi",),
    "Jammu and Kashmir": ("Jammu & Kashmir", "Jammu Kashmir"),
    "Odisha": ("Orissa",),
    "Puducherry": ("Pondicherry",),
    "Tamil Nadu": ("Tamilnadu",),
    "Uttarakhand": ("Uttaranchal",),
}
PRIMARY_SPATIAL_UNIT = "district"
COLLECTION_COMPLETE = "complete"
COLLECTION_COMPLETE_ZERO = "complete_zero"
COLLECTION_FAILED = "failed"
COLLECTION_INCOMPLETE = "incomplete"
COLLECTION_MISSING = "missing"

REQUIRED_REGISTRY_COLUMNS = {
    "event_id",
    "source_record_id",
    "state",
    "district",
    "start_date",
}
REQUIRED_ARTICLE_COLUMNS = {
    "event_district_id",
    "event_id",
    "state",
    "district",
    "published_at",
    "url",
    "district_evidence",
    "locations_lower",
}
COUNT_COLUMNS = (
    "event_district_id",
    "event_id",
    "source_record_id",
    "state",
    "district",
    "start_date",
    "candidate_article_count",
    "heuristic_pass_count",
    "final_article_count",
    "count_source",
    "collection_status",
    "query_collection_status",
    "missing_text_count",
    "weak_text_count",
)


def clean_scalar(value: Any) -> str:
    """Return a stable, whitespace-normalized scalar suitable for keys."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return re.sub(r"\s+", " ", text)


def normalize_district(value: Any) -> str:
    """Use the repository's conservative district key normalizer."""
    return normalize_name(value)


def deterministic_event_district_id(event_id: Any, district: Any) -> str:
    """Use the canonical repository key; do not invent an alternate format."""
    return make_event_district_id(event_id, district)


def _is_missing_district(value: Any) -> bool:
    normalized = normalize_district(value)
    return is_missing_name(value) or normalized in {
        "district missing",
        "district_missing",
        "unknown",
        "not available",
        "administrative unit not available",
    }


def prepare_district_registry(events: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize an event_district registry.

    Missing or state-fallback rows are retained for audit/count output but are
    marked ``primary_eligible=False``.  They are never sent to the district
    query, so a state-level observation cannot be silently copied to a district.
    """
    missing = REQUIRED_REGISTRY_COLUMNS - set(events.columns)
    if missing:
        raise ValueError(f"event_districts is missing columns: {sorted(missing)}")
    frame = events.copy()
    for column in ("event_id", "source_record_id", "state", "district", "start_date"):
        frame[column] = frame[column].map(clean_scalar)
    if "event_district_id" not in frame.columns:
        raise ValueError(
            "event_districts must provide event_district_id; build the registry "
            "with src/build_emdat_events.py before district collection"
        )
    frame["event_district_id"] = frame["event_district_id"].map(clean_scalar)
    if frame["event_district_id"].eq("").any():
        raise ValueError("event_districts contains an empty event_district_id")
    if frame["event_district_id"].replace("", pd.NA).dropna().duplicated().any():
        raise ValueError("event_districts has duplicate event_district_id values")
    frame["primary_eligible"] = (
        frame["event_district_id"].ne("")
        & ~frame["district"].map(_is_missing_district)
        & ~frame.apply(
            lambda row: normalize_district(row["district"]) == normalize_district(row["state"]),
            axis=1,
        )
    )
    if 'aoi_level' in frame:
        frame['primary_eligible'] &= frame['aoi_level'].eq('district')
    if 'district_resolution_confidence' in frame:
        frame['primary_eligible'] &= frame['district_resolution_confidence'].eq('high')
    for value in frame.loc[frame["primary_eligible"], "start_date"]:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid start_date in event_districts: {value!r}") from exc
    return frame


def prepare_district_windows(
    events: pd.DataFrame,
    *,
    window_days: int = DISTRICT_WINDOW_DAYS,
    include_ineligible: bool = False,
) -> list[dict[str, Any]]:
    """Return fixed half-open district windows for eligible registry rows."""
    if window_days != DISTRICT_WINDOW_DAYS:
        raise ValueError("Primary district collection requires a fixed 14-day window")
    frame = prepare_district_registry(events)
    if not include_ineligible:
        frame = frame[frame["primary_eligible"]].copy()
    windows: list[dict[str, Any]] = []
    for _, row in frame.sort_values("event_district_id").iterrows():
        onset = date.fromisoformat(row["start_date"])
        end_exclusive = onset + timedelta(days=window_days)
        windows.append(
            {
                "event_district_id": row["event_district_id"],
                "event_id": row["event_id"],
                "source_record_id": row["source_record_id"],
                "state": row["state"],
                "district": row["district"],
                "onset_date": onset,
                "query_start": onset,
                "query_end_exclusive": end_exclusive,
                # query_end is retained as a convenient inclusive partition
                # endpoint; the join always uses query_end_exclusive.
                "query_end": end_exclusive - timedelta(days=1),
                "location_terms": [normalize_district(row["district"])],
                "state_terms": list(dict.fromkeys(
                    [normalize_district(row["state"])]
                    + [normalize_district(alias) for alias in DISTRICT_STATE_ALIASES.get(row["state"], ())]
                )),
            }
        )
    if not windows:
        raise ValueError("No eligible district registry rows")
    return windows


def _literal_regex(term: str) -> str:
    # Escape RE2 metacharacters without Python re.escape's escaped whitespace.
    return re.sub(r'([.\^$*+?{}\[\]\\|()])', r'\\\1', term)


def _event_struct(row: Mapping[str, Any]) -> str:
    return (
        "STRUCT("
        f"{_sql_string(str(row['event_district_id']))} AS event_district_id, "
        f"{_sql_string(str(row['event_id']))} AS event_id, "
        f"{_sql_string(str(row['source_record_id']))} AS source_record_id, "
        f"{_sql_string(str(row['state']))} AS state, "
        f"{_sql_string(str(row['district']))} AS district, "
        f"DATE '{row['onset_date'].isoformat()}' AS onset_date, "
        f"DATE '{row['query_start'].isoformat()}' AS query_start, "
        f"DATE '{row['query_end_exclusive'].isoformat()}' AS query_end_exclusive, "
        f"{_sql_array(row['location_terms'])} AS district_terms, "
        f"{_sql_array(row['state_terms'])} AS state_terms, "
        f"{_sql_array(_literal_regex(t) for t in row['location_terms'])} AS district_patterns, "
        f"{_sql_array(_literal_regex(t) for t in row['state_terms'])} AS state_patterns)"
    )


def build_district_query(
    windows: Sequence[Mapping[str, Any]],
    *,
    topic_profile: str = "strict",
    languages: tuple[str, ...] = (),
    include_domains: tuple[str, ...] = (),
    exclude_domains: tuple[str, ...] = (),
    title_fallback: bool = False,
    article_metadata_profile: str = "rich",
) -> str:
    """Build district-only GKG SQL.

    The candidate predicate has a district term in every branch.  In
    particular, it contains no state-only fallback branch.  Deduplication is
    performed at URL + state + district before nearest-onset assignment.
    """
    if not windows:
        raise ValueError("At least one district window is required")
    if topic_profile not in {"strict", "broad"}:
        raise ValueError("topic_profile must be 'strict' or 'broad'")
    if article_metadata_profile not in {"basic", "rich"}:
        raise ValueError("article_metadata_profile must be 'basic' or 'rich'")
    themes = STRICT_FLOOD_THEMES if topic_profile == "strict" else BROAD_FLOOD_THEMES
    global_start = min(row["query_start"] for row in windows)
    global_end = max(row["query_end_exclusive"] for row in windows)
    event_sql = ",\n    ".join(_event_struct(row) for row in windows)
    ranges = coalesce_query_ranges(
        [{"query_start": row["query_start"], "query_end": row["query_end"]} for row in windows]
    )
    partition_filter = "(\n        " + "\n        OR ".join(
        "(_PARTITIONTIME >= TIMESTAMP(" + _sql_string(start.isoformat()) + ") "
        "AND _PARTITIONTIME < TIMESTAMP(" + _sql_string((end + timedelta(days=1)).isoformat()) + "))"
        for start, end in ranges
    ) + "\n      )"
    filters = [
        partition_filter,
        f"`DATE` >= {global_start.strftime('%Y%m%d')}000000",
        f"`DATE` < {(global_end).strftime('%Y%m%d')}000000",
        "DocumentIdentifier IS NOT NULL",
        "EXISTS (SELECT 1 FROM UNNEST(SPLIT(COALESCE(V2Locations, ''), ';')) AS location_ref "
        "WHERE UPPER(SPLIT(location_ref, '#')[SAFE_OFFSET(2)]) = 'IN')",
        "EXISTS (SELECT 1 FROM UNNEST(SPLIT(COALESCE(V2Themes, ''), ';')) AS theme_ref "
        f"WHERE SPLIT(theme_ref, ',')[SAFE_OFFSET(0)] IN UNNEST({_sql_array(themes)}))",
    ]
    if include_domains:
        filters.append(
            f"LOWER(COALESCE(SourceCommonName, '')) IN UNNEST({_sql_array(tuple(d.lower() for d in include_domains))})"
        )
    if exclude_domains:
        filters.append(
            f"LOWER(COALESCE(SourceCommonName, '')) NOT IN UNNEST({_sql_array(tuple(d.lower() for d in exclude_domains))})"
        )
    title_expression = (
        "LOWER(COALESCE(REGEXP_EXTRACT(Extras, r'<PAGE_TITLE>([^<]*)</PAGE_TITLE>'), ''))"
        if title_fallback or article_metadata_profile == "rich" else "CAST('' AS STRING)"
    )
    metadata = ""
    if article_metadata_profile == "rich":
        metadata = """,
    GKGRECORDID AS gkg_record_id,
    LOWER(COALESCE(SourceCommonName, '')) AS source_domain,
    REGEXP_EXTRACT(Extras, r'<PAGE_TITLE>([^<]*)</PAGE_TITLE>') AS title,
    REGEXP_EXTRACT(Extras, r'<PAGE_AUTHORS>([^<]*)</PAGE_AUTHORS>') AS authors,
    SAFE_CAST(SPLIT(COALESCE(V2Tone, ''), ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone,
    NULLIF(SharingImage, '') AS sharing_image"""
    else:
        metadata = """,
    CAST(NULL AS STRING) AS gkg_record_id,
    LOWER(COALESCE(NET.REG_DOMAIN(DocumentIdentifier), '')) AS source_domain,
    CAST(NULL AS STRING) AS title,
    CAST(NULL AS STRING) AS authors,
    CAST(NULL AS FLOAT64) AS tone,
    CAST(NULL AS STRING) AS sharing_image"""
    language_filter = ""
    if languages:
        normalized = tuple("en" if lang == "eng" else lang for lang in languages)
        language_filter = f"WHERE source_lang IN UNNEST({_sql_array(normalized)})"
    where_sql = "\n      AND ".join(filters)
    # The district and state terms are checked against the same GKG location
    # block.  This prevents a Puri in another state from satisfying Odisha's
    # Puri district window.
    structured_match = """EXISTS (
    SELECT 1
    FROM UNNEST(SPLIT(g.locations_lower, ';')) AS location_ref
    CROSS JOIN UNNEST(e.district_terms) AS district_term
    WHERE SPLIT(location_ref, '#')[SAFE_OFFSET(2)] = 'in'
      AND EXISTS (
        SELECT 1 FROM UNNEST(SPLIT(COALESCE(SPLIT(location_ref, '#')[SAFE_OFFSET(1]), ''), ',')) AS location_part
        WHERE TRIM(location_part) = district_term
      )
      AND EXISTS (
        SELECT 1
        FROM UNNEST(SPLIT(COALESCE(SPLIT(location_ref, '#')[SAFE_OFFSET(1]), ''), ',')) AS state_location_part
        CROSS JOIN UNNEST(e.state_terms) AS state_term
        WHERE TRIM(state_location_part) = state_term
      )
  )"""
    title_match = """EXISTS (
    SELECT 1 FROM UNNEST(e.district_patterns) AS district_term
    CROSS JOIN UNNEST(e.state_patterns) AS state_term
    WHERE district_term <> '' AND state_term <> ''
      AND REGEXP_CONTAINS(
        g.title_lower,
        CONCAT(r'(^|[^\\p{L}\\p{N}])', district_term, r'([^\\p{L}\\p{N}]|$)')
      )
      AND REGEXP_CONTAINS(
        g.title_lower,
        CONCAT(r'(^|[^\\p{L}\\p{N}])', state_term, r'([^\\p{L}\\p{N}]|$)')
      )
  )"""
    candidate_predicate = structured_match
    if title_fallback:
        candidate_predicate += "\n  OR " + title_match
    return f"""#standardSQL
-- Generated by src/district_articles.py.
-- Unit: one explicit district x parent event; window is onset <= date < onset+14.
-- State-only GKG matches are intentionally excluded.
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
      ELSE COALESCE(REGEXP_EXTRACT(COALESCE(TranslationInfo, ''), r'srclc:([a-z]{{3}})'), 'en')
    END AS source_lang{metadata}
  FROM `{GKG_TABLE}`
  WHERE {where_sql}
),
gkg AS (
  SELECT * FROM gkg_raw
  {language_filter}
),
candidate_matches AS (
  SELECT e.event_district_id, e.event_id, e.source_record_id, e.state, e.district,
         e.onset_date, g.*,
         CASE WHEN {structured_match} THEN 'gkg_location' ELSE 'title' END AS district_evidence,
         ABS(DATE_DIFF(DATE(g.published_at), e.onset_date, DAY)) AS onset_distance
  FROM event_windows e
  JOIN gkg AS g
    ON DATE(g.published_at) >= e.query_start
   AND DATE(g.published_at) < e.query_end_exclusive
  WHERE {candidate_predicate}
),
deduplicated AS (
  SELECT * EXCEPT(assignment_rank, onset_distance)
  FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY normalized_url, state, district
      ORDER BY onset_distance, onset_date, event_district_id, published_at, url
    ) AS assignment_rank
    FROM candidate_matches
  )
  WHERE assignment_rank = 1
)
SELECT event_district_id, event_id, source_record_id, state, district,
       onset_date, published_at, url, normalized_url, source_domain, source_lang,
       gkg_record_id, title, authors, tone, sharing_image, district_evidence, locations_lower
FROM deduplicated
ORDER BY event_district_id, published_at, normalized_url
""".rstrip() + "\n"


def _dedup_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        clean_scalar(row.get("normalized_url") or row.get("url")),
        normalize_district(row.get("state")),
        normalize_district(row.get("district")),
    )


def structured_location_matches(
    locations: Any,
    *,
    state: Any,
    district: Any,
) -> bool:
    """Check district and state in one India GKG location block.

    This reference implementation mirrors the SQL predicate and is useful for
    validating cached rows in tests or downstream tools.  It deliberately does
    not infer a district from a state-only block.
    """
    district_key = normalize_district(district)
    state_keys = {
        normalize_district(state),
        *(normalize_district(alias) for alias in DISTRICT_STATE_ALIASES.get(clean_scalar(state), ())),
    }
    if not district_key or not state_keys:
        return False
    for block in clean_scalar(locations).split(";"):
        parts = block.split("#")
        if len(parts) < 3 or parts[2].casefold() != "in":
            continue
        names = {normalize_district(item) for item in parts[1].split(",")}
        if district_key in names and state_keys.intersection(names):
            return True
    return False


class DistrictArticleAccumulator:
    """Aggregate article metadata while preserving zero-result registry rows."""

    def __init__(self, windows: Sequence[Mapping[str, Any]]) -> None:
        self.windows = {str(row["event_district_id"]): dict(row) for row in windows}
        self.rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(self, row: Mapping[str, Any]) -> None:
        missing = REQUIRED_ARTICLE_COLUMNS - set(row)
        if missing:
            raise ValueError(f"GDELT district article output missing columns: {sorted(missing)}")
        event_district_id = clean_scalar(row["event_district_id"])
        if event_district_id not in self.windows:
            raise ValueError(f"Unexpected event_district_id: {event_district_id}")
        key = _dedup_key(row)
        if not key[0]:
            raise ValueError("GDELT district article URL is empty")
        existing = self.rows_by_key.get(key)
        if existing is None or self._assignment_rank(row) < self._assignment_rank(existing):
            self.rows_by_key[key] = dict(row)

    def _assignment_rank(self, row: Mapping[str, Any]) -> tuple:
        event = self.windows[clean_scalar(row["event_district_id"])]
        published = date.fromisoformat(clean_scalar(row["published_at"])[:10])
        distance = abs((published - event["onset_date"]).days)
        return distance, event["onset_date"], clean_scalar(row["event_district_id"]), clean_scalar(row["published_at"]), clean_scalar(row["url"])

    @property
    def article_rows(self) -> int:
        return len(self.rows_by_key)

    def finish(self) -> list[dict[str, Any]]:
        counts: defaultdict[str, int] = defaultdict(int)
        for row in self.rows_by_key.values():
            counts[clean_scalar(row["event_district_id"])] += 1
        result = []
        for event_district_id, event in sorted(self.windows.items()):
            result.append({
                "event_district_id": event_district_id,
                "event_id": event["event_id"],
                "source_record_id": event["source_record_id"],
                "state": event["state"],
                "district": event["district"],
                "source_lang": "und",
                "article_count": counts[event_district_id],
                "collection_status": COLLECTION_COMPLETE,
                "result_status": "zero" if counts[event_district_id] == 0 else "nonzero",
            })
        return result


def _open_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"Expected JSON object at {path}:{line_number}")
                yield value


def execute_district_query(
    sql: str,
    billing_project: str | None,
    *,
    article_output: Path,
    windows: Sequence[Mapping[str, Any]],
    maximum_bytes_billed: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run BigQuery and atomically publish article metadata and summaries."""
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError("google-cloud-bigquery is required for district execution") from exc
    client = bigquery.Client(project=billing_project)
    config = bigquery.QueryJobConfig()
    if maximum_bytes_billed is not None:
        config.maximum_bytes_billed = maximum_bytes_billed
    job = client.query(sql, job_config=config)
    result = job.result(page_size=5000)
    article_output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{article_output.name}.", dir=article_output.parent)
    os.close(fd)
    accumulator = DistrictArticleAccumulator(windows)
    try:
        with gzip.open(tmp_name, "wt", encoding="utf-8") as handle:
            for result_row in result:
                row = {key: _json_ready(value) for key, value in dict(result_row.items()).items()}
                accumulator.add(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        summaries = accumulator.finish()
        os.replace(tmp_name, article_output)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return summaries, {
        "job_id": job.job_id,
        "billing_project": client.project,
        "total_bytes_processed": int(job.total_bytes_processed or 0),
        "cache_hit": bool(job.cache_hit),
        "article_rows": accumulator.article_rows,
    }


def write_collection_manifest(
    path: Path,
    registry: pd.DataFrame,
    *,
    status: str,
    metadata: Mapping[str, Any] | None = None,
    article_payload_sha256: str | None = None,
) -> None:
    """Atomically write a manifest that distinguishes zero from failed work."""
    if status not in {
        COLLECTION_COMPLETE, COLLECTION_COMPLETE_ZERO,
        COLLECTION_FAILED, COLLECTION_INCOMPLETE,
    }:
        raise ValueError(f"Invalid collection status: {status}")
    execution_status = COLLECTION_COMPLETE if status == COLLECTION_COMPLETE_ZERO else status
    entries = []
    for _, row in registry.iterrows():
        entries.append({
            "event_district_id": clean_scalar(row.get("event_district_id")),
            "event_id": clean_scalar(row.get("event_id")),
            "state": clean_scalar(row.get("state")),
            "district": clean_scalar(row.get("district")),
            "collection_status": execution_status if bool(row.get("primary_eligible", True)) else COLLECTION_MISSING,
            "result_status": "zero" if status == COLLECTION_COMPLETE_ZERO else None,
        })
    registry_sha256 = registry_fingerprint(registry)
    payload = {
        "schema_version": 2,
        "spatial_unit": PRIMARY_SPATIAL_UNIT,
        "window_days": DISTRICT_WINDOW_DAYS,
        "collection_status": execution_status,
        "result_status": "zero" if status == COLLECTION_COMPLETE_ZERO else None,
        "registry_sha256": registry_sha256,
        "article_payload_sha256": article_payload_sha256,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
        **(dict(metadata or {})),
    }
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def registry_fingerprint(registry: pd.DataFrame) -> str:
    """Hash identity and dates so a cached manifest cannot fit another run."""
    frame = prepare_district_registry(registry)
    columns = ["event_district_id", "event_id", "source_record_id", "state", "district", "start_date"]
    columns += [c for c in ["aoi_level", "district_resolution_confidence"] if c in frame]
    rows = frame.loc[:, columns].sort_values("event_district_id").to_dict(orient="records")
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def article_payload_fingerprint(article_rows: Iterable[Mapping[str, Any]]) -> str:
    """Hash canonical article metadata, independent of JSONL formatting."""
    rows = [dict(row) for row in article_rows]
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in sorted(rows, key=lambda row: (
            clean_scalar(row.get("event_district_id")),
            clean_scalar(row.get("normalized_url") or row.get("url")),
            clean_scalar(row.get("published_at")),
        ))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_fingerprint(path: Path) -> str:
    """Return the SHA-256 of the exact cached article payload bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Collection manifest must be a JSON object: {path}")
    return payload


def _read_manifest(path: Path | None) -> dict[str, str]:
    payload = _load_manifest(path)
    values: dict[str, str] = {}
    for entry in payload.get("entries", []):
        if isinstance(entry, dict) and entry.get("event_district_id"):
            values[clean_scalar(entry["event_district_id"])] = clean_scalar(
                entry.get("collection_status") or payload.get("collection_status") or COLLECTION_MISSING
            )
    return values


def _load_article_database_bodies(path: Path | None) -> dict[str, tuple[str, str, str | None]]:
    if path is None or not path.exists():
        return {}
    import sqlite3
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT url, status, body_text, page_title FROM documents"
        ).fetchall()
    except sqlite3.Error as exc:
        raise ValueError(f"Could not read article database {path}: {exc}") from exc
    finally:
        connection.close()
    return {str(url): (str(status or ""), str(body or ""), title) for url, status, body, title in rows}


def _heuristic_for_article(row: Mapping[str, Any], bodies: Mapping[str, tuple[str, str, str | None]]) -> str:
    from classify_event_articles import classify_heuristic
    url = clean_scalar(row.get("url"))
    body_record = bodies.get(url)
    if body_record is None:
        status = clean_scalar(row.get("document_status")) or ("ok" if row.get("body_text") else "")
        body = clean_scalar(row.get("body_text"))
        title = row.get("page_title") or row.get("title")
    else:
        status, body, title = body_record
    result, _excerpt, _matches = classify_heuristic(status, body, title)
    return result


def _title_mentions(title, term):
    term = normalize_name(term)
    return bool(term and re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", normalize_name(title)))


def has_district_evidence(row):
    method = clean_scalar(row.get('district_evidence'))
    if method == 'gkg_location':
        return structured_location_matches(row.get('locations_lower', ''), state=row['state'], district=row['district'])
    if method == 'title':
        state_terms = [row['state'], *DISTRICT_STATE_ALIASES.get(row['state'], ())]
        return _title_mentions(row.get('title'), row['district']) and any(_title_mentions(row.get('title'), term) for term in state_terms)
    return False


def build_district_counts(
    registry: pd.DataFrame,
    article_rows: Iterable[Mapping[str, Any]],
    *,
    manifest_path: Path | None = None,
    article_database: Path | None = None,
    article_payload_path: Path | None = None,
) -> pd.DataFrame:
    """Validate provenance/evidence/windows, assign once, and count known text.

    A missing/failed query or incomplete relevance observation never produces
    a final zero. Raw query success and usable article observation are separate.
    """
    frame = prepare_district_registry(registry)
    manifest = _load_manifest(manifest_path)
    raw_rows = [dict(row) for row in article_rows]
    if manifest:
        if manifest.get('schema_version') != 2:
            raise ValueError('Unsupported district collection manifest version; regenerate district collection')
        if manifest.get('spatial_unit') != PRIMARY_SPATIAL_UNIT or manifest.get('window_days') != DISTRICT_WINDOW_DAYS:
            raise ValueError('district manifest has wrong spatial unit or 14-day window')
        if manifest.get('registry_sha256') != registry_fingerprint(frame):
            raise ValueError('district collection manifest does not match this registry')
        expected = manifest.get('article_payload_sha256')
        if manifest.get('collection_status') == COLLECTION_COMPLETE and not expected:
            raise ValueError('complete district manifest is missing article_payload_sha256')
        if expected:
            observed = file_fingerprint(article_payload_path) if article_payload_path and article_payload_path.exists() else article_payload_fingerprint(raw_rows)
            if expected != observed:
                raise ValueError('district collection manifest does not match article metadata')
    status_by_id = _read_manifest(manifest_path)
    if len(manifest.get('entries', [])) != len(status_by_id):
        raise ValueError('duplicate or invalid manifest entries')
    bodies = _load_article_database_bodies(article_database)
    profiles = frame.set_index('event_district_id').to_dict('index')
    by_district = defaultdict(list)
    for event_id, profile in profiles.items():
        if profile['primary_eligible']:
            by_district[(normalize_name(profile['state']), normalize_name(profile['district']))].append((event_id, date.fromisoformat(profile['start_date'])))
    selected = {}
    for row in raw_rows:
        if REQUIRED_ARTICLE_COLUMNS - set(row):
            raise ValueError(f'district article row missing columns: {sorted(REQUIRED_ARTICLE_COLUMNS - set(row))}')
        key = clean_scalar(row['event_district_id'])
        if key not in profiles:
            raise ValueError(f'Article references unknown event_district_id: {key}')
        profile = profiles[key]
        for column in ['state', 'district', 'event_id'] + (['source_record_id'] if 'source_record_id' in row else []):
            if normalize_name(row[column]) != normalize_name(profile[column]):
                raise ValueError(f'Article identity disagrees with registry: {key}/{column}')
        if not has_district_evidence(row):
            continue
        published = pd.to_datetime(row['published_at'], utc=True, errors='coerce')
        if pd.isna(published):
            raise ValueError(f'Invalid publication date for {key}')
        published_date = published.date()
        choices = [(published_date - onset, onset, candidate) for candidate, onset in by_district[(normalize_name(row['state']), normalize_name(row['district']))] if onset <= published_date < onset + timedelta(days=DISTRICT_WINDOW_DAYS)]
        if not choices:
            continue
        _distance, _onset, assigned = min(choices)
        assigned_profile = profiles[assigned]
        candidate = {**row, 'event_district_id': assigned, 'event_id': assigned_profile['event_id']}
        dedup = _dedup_key(row)
        if not dedup[0]:
            raise ValueError('Empty district article URL')
        rank = (_distance, _onset, assigned, published, clean_scalar(row['url']))
        if dedup not in selected or rank < selected[dedup][0]:
            selected[dedup] = (rank, candidate)
    counts = defaultdict(lambda: {'candidate': 0, 'pass': 0, 'missing': 0, 'weak': 0})
    for _rank, row in selected.values():
        record = counts[row['event_district_id']]
        record['candidate'] += 1
        heuristic = _heuristic_for_article(row, bodies)
        record['pass'] += heuristic == 'keyword_match'
        record['missing'] += heuristic == 'no_body'
        record['weak'] += heuristic.startswith('weak_')
    output = []
    for row in frame.sort_values('event_district_id').to_dict('records'):
        key = row['event_district_id']
        query_status = status_by_id.get(key, COLLECTION_MISSING)
        if manifest.get('collection_status') in [COLLECTION_FAILED, COLLECTION_INCOMPLETE]:
            query_status = manifest['collection_status']
        if not row['primary_eligible']:
            query_status = COLLECTION_MISSING
        status = query_status
        record = counts[key]
        if status == COLLECTION_COMPLETE and (record['missing'] or record['weak']):
            status = COLLECTION_INCOMPLETE
        output.append({
            **{c: row[c] for c in ['event_district_id', 'event_id', 'source_record_id', 'state', 'district', 'start_date']},
            'candidate_article_count': record['candidate'],
            'heuristic_pass_count': record['pass'],
            'final_article_count': record['pass'] if status == COLLECTION_COMPLETE else float('nan'),
            'count_source': 'heuristic', 'collection_status': status,
            'query_collection_status': query_status,
            'missing_text_count': record['missing'], 'weak_text_count': record['weak'],
        })
    return pd.DataFrame(output, columns=COUNT_COLUMNS)


def write_district_counts(counts: pd.DataFrame, output: Path) -> None:
    missing = set(COUNT_COLUMNS) - set(counts.columns)
    if missing:
        raise ValueError(f"district count output missing columns: {sorted(missing)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(fd)
    try:
        counts.loc[:, list(COUNT_COLUMNS)].to_csv(tmp_name, index=False)
        os.replace(tmp_name, output)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


# Short names make the district entry point easy to exercise beside the legacy
# collect_gdelt.prepare_event_windows/build_query API.
prepare_event_windows = prepare_district_windows
build_query = build_district_query


def _path_for(key: str) -> Path:
    # All district artifacts are registered in cvnd_layout.py.  Keeping path
    # resolution there prevents a cached state artifact being mistaken for a
    # district artifact.
    return data_path(key)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=_path_for("event_districts"))
    parser.add_argument("--sql-output", type=Path, default=_path_for("district_gdelt_sql"))
    parser.add_argument("--article-output", type=Path, default=_path_for("district_gdelt_articles"))
    parser.add_argument("--manifest", type=Path, default=_path_for("district_gdelt_manifest"))
    parser.add_argument("--output", type=Path, default=_path_for("district_gdelt_counts"))
    parser.add_argument("--article-database", type=Path, default=_path_for("district_article_database"))
    parser.add_argument("--maximum-tib-billed", type=float, default=2.0)
    parser.add_argument("--topic-profile", choices=("strict", "broad"), default="strict")
    parser.add_argument("--languages", default=",".join(INDIA_MEDIA_LANGUAGES))
    parser.add_argument("--include-domain", action="append", default=[])
    parser.add_argument("--exclude-domain", action="append", default=[])
    parser.add_argument("--title-fallback", action="store_true")
    parser.add_argument("--article-metadata-profile", choices=("basic", "rich"), default="rich")
    parser.add_argument("--billing-project", default=os.getenv("GDELT_BILLING_PROJECT"))
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--execute", action="store_true")
    actions.add_argument("--estimate", action="store_true", help="BigQuery dry run: validate SQL and estimate bytes without billed execution")
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="Count cached district metadata and downloaded article bodies without querying GDELT",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    registry = pd.read_csv(args.events, dtype=str, keep_default_na=False)
    normalized = prepare_district_registry(registry)
    if args.counts_only:
        manifest = _load_manifest(args.manifest)
        if not manifest:
            raise FileNotFoundError(f"District collection manifest is required: {args.manifest}")
        if not args.article_output.exists() and manifest.get("collection_status") == COLLECTION_COMPLETE:
            raise FileNotFoundError(
                "A complete district manifest requires its article metadata payload; "
                f"missing {args.article_output}"
            )
        articles = list(_open_jsonl(args.article_output)) if args.article_output.exists() else []
        counts = build_district_counts(
            normalized,
            articles,
            manifest_path=args.manifest,
            article_database=args.article_database,
            article_payload_path=args.article_output if args.article_output.exists() else None,
        )
        write_district_counts(counts, args.output)
        print(f"Wrote district counts from cache: {args.output}")
        return 0
    windows = prepare_district_windows(normalized)
    sql = build_district_query(
        windows,
        topic_profile=args.topic_profile,
        languages=_csv_values(args.languages),
        include_domains=tuple(args.include_domain),
        exclude_domains=tuple(args.exclude_domain),
        title_fallback=args.title_fallback,
        article_metadata_profile=args.article_metadata_profile,
    )
    if args.sql_output.exists() and not args.overwrite:
        raise FileExistsError(f"SQL output exists: {args.sql_output}; pass --overwrite")
    _atomic_write(args.sql_output, sql)
    if args.estimate:
        from collect_gdelt import estimate_query
        processed, project = estimate_query(sql, args.billing_project)
        print(f'District BigQuery dry run: {processed:,} bytes ({processed / 1024**4:.3f} TiB), project={project}')
        if processed > int(args.maximum_tib_billed * 1024**4):
            raise ValueError('Estimated query exceeds maximum-tib-billed; no billed query executed')
        return 0
    if args.dry_run or not args.execute:
        print(f"Wrote reviewable district SQL: {args.sql_output}")
        return 0
    maximum_bytes = int(args.maximum_tib_billed * 1024**4)
    try:
        summaries, metadata = execute_district_query(
            sql,
            args.billing_project,
            article_output=args.article_output,
            windows=windows,
            maximum_bytes_billed=maximum_bytes,
        )
        status = COLLECTION_COMPLETE_ZERO if metadata["article_rows"] == 0 else COLLECTION_COMPLETE
        payload_hash = file_fingerprint(args.article_output)
        write_collection_manifest(
            args.manifest,
            normalized,
            status=status,
            metadata={**metadata, "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(), "topic_profile": args.topic_profile, "title_fallback": args.title_fallback, "languages": _csv_values(args.languages)},
            article_payload_sha256=payload_hash,
        )
        print(f"Wrote {metadata['article_rows']} district article rows; collection manifest complete")
        print('Next: download_articles.py, then district_articles.py --counts-only')
        return 0
    except Exception as exc:
        try:
            write_collection_manifest(args.manifest, normalized, status=COLLECTION_FAILED, metadata={"error": str(exc)})
        except Exception:
            pass
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
