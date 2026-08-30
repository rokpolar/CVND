#!/usr/bin/env python3
"""Audit article-body retrieval before event relevance classification.

The report mirrors the classifier's state and onset-through-onset+93-day
candidate expansion. It makes historical URL survival visible rather than
silently treating inaccessible publisher pages as irrelevant articles.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence, TextIO

from article_fetcher import RETRYABLE_HTTP_STATUSES
from cvnd_layout import data_path


EVENT_WINDOW_DAYS = 93
PRIMARY_BODY_STATUS = "ok"
WEAK_BODY_STATUS = "extract_weak"
RETRYABLE_RESULT_STATUSES = frozenset(
    {"request_error", "host_deferred", "extract_empty", "extract_weak"}
)
ARCHIVE_HTTP_STATUSES = frozenset({404, 410})
ACCESS_RESTRICTED_HTTP_STATUSES = frozenset({401, 403})

KNOWN_DOCUMENT_STATUSES = (
    "pending",
    "ok",
    "extract_weak",
    "extract_empty",
    "host_deferred",
    "request_error",
    "http_error",
    "redirect_home",
    "redirect_listing",
    "domain_parked",
    "robots_denied",
    "non_html",
    "too_large",
)
RECOVERY_CLASSES = (
    "primary_available",
    "weak_body_retryable",
    "transient_retryable",
    "not_attempted",
    "archive_candidate",
    "access_restricted",
    "terminal_other",
)

STATE_URL_QUERY = """
SELECT
  ea.state,
  ea.url,
  MIN(ea.published_at) AS published_at,
  MAX(ea.source_domain) AS source_domain,
  MAX(ea.source_lang) AS source_lang,
  d.status,
  d.http_status,
  d.final_url,
  d.retrieved_at_utc,
  d.page_title,
  d.canonical_url,
  d.extraction_method,
  d.extraction_confidence,
  d.word_count,
  d.selected_attempt_url,
  d.fallback_used,
  d.attempt_count,
  d.error,
  CASE WHEN d.body_text IS NOT NULL AND LENGTH(d.body_text) > 0
       THEN 1 ELSE 0 END AS has_body
FROM event_articles AS ea
JOIN documents AS d ON d.url = ea.url
WHERE ea.url LIKE 'http://%' OR ea.url LIKE 'https://%'
GROUP BY ea.state, ea.url
ORDER BY ea.state, ea.url
"""

UNIQUE_URL_QUERY = """
SELECT
  d.url,
  MIN(ea.published_at) AS published_at,
  d.status,
  d.http_status,
  CASE WHEN d.body_text IS NOT NULL AND LENGTH(d.body_text) > 0
       THEN 1 ELSE 0 END AS has_body
FROM documents AS d
JOIN event_articles AS ea ON ea.url = d.url
WHERE d.url LIKE 'http://%' OR d.url LIKE 'https://%'
GROUP BY d.url
ORDER BY d.url
"""

UNRESOLVED_FIELDS = (
    "state",
    "url",
    "published_at",
    "publication_year",
    "candidate_event_ids",
    "candidate_source_record_ids",
    "source_domain",
    "source_lang",
    "document_status",
    "http_status",
    "recovery_class",
    "attempt_count",
    "retrieved_at_utc",
    "final_url",
    "selected_attempt_url",
    "canonical_url",
    "page_title",
    "extraction_method",
    "extraction_confidence",
    "word_count",
    "fallback_used",
    "error",
)


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def safe_status_name(status: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", status.casefold()).strip("_") or "missing"


def recovery_class(status: Any, http_status: Any, has_body: Any) -> str:
    status_text = str(status or "pending")
    has_text = bool(has_body)
    try:
        http_code = int(http_status) if http_status is not None else None
    except (TypeError, ValueError):
        http_code = None

    if status_text == PRIMARY_BODY_STATUS and has_text:
        return "primary_available"
    if status_text == WEAK_BODY_STATUS and has_text:
        return "weak_body_retryable"
    if status_text == "pending":
        return "not_attempted"
    if status_text in RETRYABLE_RESULT_STATUSES or (
        status_text == "http_error" and http_code in RETRYABLE_HTTP_STATUSES
    ):
        return "transient_retryable"
    if status_text == "http_error" and http_code in ARCHIVE_HTTP_STATUSES:
        return "archive_candidate"
    if status_text == "http_error" and http_code in ACCESS_RESTRICTED_HTTP_STATUSES:
        return "access_restricted"
    return "terminal_other"


def accumulate(
    metrics: Counter[str],
    prefix: str,
    status: Any,
    http_status: Any,
    has_body: Any,
) -> str:
    category = recovery_class(status, http_status, has_body)
    metrics[f"{prefix}count"] += 1
    metrics[f"{prefix}{category}_count"] += 1
    if category == "primary_available":
        metrics[f"{prefix}primary_body_count"] += 1
        metrics[f"{prefix}sensitivity_body_count"] += 1
    elif category == "weak_body_retryable":
        metrics[f"{prefix}weak_body_count"] += 1
        metrics[f"{prefix}sensitivity_body_count"] += 1
    return category


def add_rates(row: dict[str, Any], metrics: Counter[str], prefix: str) -> None:
    total = metrics[f"{prefix}count"]
    primary = metrics[f"{prefix}primary_body_count"]
    sensitivity = metrics[f"{prefix}sensitivity_body_count"]
    row[f"{prefix}no_primary_body_count"] = total - primary
    row[f"{prefix}primary_body_rate"] = primary / total if total else 0.0
    row[f"{prefix}sensitivity_body_rate"] = sensitivity / total if total else 0.0


def load_events(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    required = {"event_id", "state", "start_date", "source_record_id"}
    missing = required - set(rows[0] if rows else ())
    if missing:
        raise ValueError(f"Event registry is missing columns: {sorted(missing)}")
    event_ids = [row["event_id"] for row in rows]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("Event registry contains duplicate event_id values")
    for row in rows:
        if parse_date(row["start_date"]) is None:
            raise ValueError(
                f"Invalid start_date for {row['event_id']}: {row['start_date']!r}"
            )
    return rows


@contextmanager
def atomic_csv(path: Path, fieldnames: Sequence[str]) -> Iterator[csv.DictWriter]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    opener = gzip.open if path.suffix == ".gz" else open
    handle: TextIO | None = None
    try:
        handle = opener(temporary, "wt", encoding="utf-8", newline="")
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        yield writer
        handle.close()
        handle = None
        temporary.replace(path)
    except Exception:
        if handle is not None:
            handle.close()
        temporary.unlink(missing_ok=True)
        raise


def write_table(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    with atomic_csv(path, fieldnames) as writer:
        for row in rows:
            writer.writerow({field: row.get(field, 0) for field in fieldnames})


def event_qc_fields() -> list[str]:
    return [
        "event_id",
        "source_record_id",
        "state",
        "district",
        "start_date",
        "window_end_date",
        "candidate_event_url_count",
        "candidate_event_url_primary_body_count",
        "candidate_event_url_weak_body_count",
        "candidate_event_url_sensitivity_body_count",
        "candidate_event_url_no_primary_body_count",
        "candidate_event_url_primary_body_rate",
        "candidate_event_url_sensitivity_body_rate",
        *[
            f"candidate_event_url_{category}_count"
            for category in RECOVERY_CLASSES
        ],
        *[f"status_{safe_status_name(status)}_count" for status in KNOWN_DOCUMENT_STATUSES],
        "status_other_count",
    ]


def year_qc_fields() -> list[str]:
    fields = ["publication_year"]
    for prefix in ("unique_url_", "candidate_event_url_"):
        fields.extend(
            [
                f"{prefix}count",
                f"{prefix}primary_body_count",
                f"{prefix}weak_body_count",
                f"{prefix}sensitivity_body_count",
                f"{prefix}no_primary_body_count",
                f"{prefix}primary_body_rate",
                f"{prefix}sensitivity_body_rate",
                *[f"{prefix}{category}_count" for category in RECOVERY_CLASSES],
            ]
        )
    return fields


def audit_retrieval(
    article_database: Path,
    events_path: Path,
    event_output: Path,
    year_output: Path,
    unresolved_output: Path,
) -> dict[str, Any]:
    if not article_database.exists():
        raise FileNotFoundError(f"Article database not found: {article_database}")
    events = load_events(events_path)
    by_state: dict[str, list[tuple[dict[str, str], date, date]]] = defaultdict(list)
    for event in events:
        start = parse_date(event["start_date"])
        assert start is not None
        by_state[event["state"]].append(
            (event, start, start + timedelta(days=EVENT_WINDOW_DAYS))
        )

    connection = sqlite3.connect(
        f"file:{article_database.resolve()}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    event_metrics: dict[str, Counter[str]] = {
        event["event_id"]: Counter() for event in events
    }
    year_metrics: dict[str, Counter[str]] = defaultdict(Counter)
    scanned_state_urls = 0
    invalid_publication_dates = 0
    unmatched_state_urls = 0
    candidate_pairs = 0
    unresolved_state_urls = 0

    try:
        with atomic_csv(unresolved_output, UNRESOLVED_FIELDS) as unresolved_writer:
            for row in connection.execute(STATE_URL_QUERY):
                scanned_state_urls += 1
                published = parse_date(row["published_at"])
                if published is None:
                    invalid_publication_dates += 1
                    continue
                matches = [
                    event
                    for event, window_start, window_end in by_state.get(
                        str(row["state"] or ""), []
                    )
                    if window_start <= published <= window_end
                ]
                if not matches:
                    unmatched_state_urls += 1
                    continue
                category = recovery_class(
                    row["status"], row["http_status"], row["has_body"]
                )
                year_key = str(published.year)
                for event in matches:
                    metrics = event_metrics[event["event_id"]]
                    accumulate(
                        metrics,
                        "candidate_event_url_",
                        row["status"],
                        row["http_status"],
                        row["has_body"],
                    )
                    status_text = str(row["status"] or "pending")
                    if status_text in KNOWN_DOCUMENT_STATUSES:
                        metrics[f"status_{safe_status_name(status_text)}_count"] += 1
                    else:
                        metrics["status_other_count"] += 1
                    accumulate(
                        year_metrics[year_key],
                        "candidate_event_url_",
                        row["status"],
                        row["http_status"],
                        row["has_body"],
                    )
                    candidate_pairs += 1
                if category != "primary_available":
                    unresolved_state_urls += 1
                    unresolved_writer.writerow(
                        {
                            "state": row["state"],
                            "url": row["url"],
                            "published_at": row["published_at"],
                            "publication_year": year_key,
                            "candidate_event_ids": "|".join(
                                event["event_id"] for event in matches
                            ),
                            "candidate_source_record_ids": "|".join(
                                event["source_record_id"] for event in matches
                            ),
                            "source_domain": row["source_domain"],
                            "source_lang": row["source_lang"],
                            "document_status": row["status"],
                            "http_status": row["http_status"],
                            "recovery_class": category,
                            "attempt_count": row["attempt_count"],
                            "retrieved_at_utc": row["retrieved_at_utc"],
                            "final_url": row["final_url"],
                            "selected_attempt_url": row["selected_attempt_url"],
                            "canonical_url": row["canonical_url"],
                            "page_title": row["page_title"],
                            "extraction_method": row["extraction_method"],
                            "extraction_confidence": row["extraction_confidence"],
                            "word_count": row["word_count"],
                            "fallback_used": row["fallback_used"],
                            "error": row["error"],
                        }
                    )

        unique_urls = 0
        for row in connection.execute(UNIQUE_URL_QUERY):
            unique_urls += 1
            published = parse_date(row["published_at"])
            year_key = str(published.year) if published else "unknown"
            accumulate(
                year_metrics[year_key],
                "unique_url_",
                row["status"],
                row["http_status"],
                row["has_body"],
            )
    finally:
        connection.close()

    event_rows: list[dict[str, Any]] = []
    for event in events:
        metrics = event_metrics[event["event_id"]]
        start = parse_date(event["start_date"])
        assert start is not None
        output_row: dict[str, Any] = {
            "event_id": event["event_id"],
            "source_record_id": event["source_record_id"],
            "state": event["state"],
            "district": event.get("district", ""),
            "start_date": event["start_date"],
            "window_end_date": (start + timedelta(days=EVENT_WINDOW_DAYS)).isoformat(),
        }
        output_row.update(metrics)
        add_rates(output_row, metrics, "candidate_event_url_")
        event_rows.append(output_row)

    year_rows: list[dict[str, Any]] = []
    for year_key in sorted(
        year_metrics, key=lambda value: (value == "unknown", value)
    ):
        metrics = year_metrics[year_key]
        output_row = {"publication_year": year_key, **metrics}
        add_rates(output_row, metrics, "unique_url_")
        add_rates(output_row, metrics, "candidate_event_url_")
        year_rows.append(output_row)

    write_table(event_output, event_qc_fields(), event_rows)
    write_table(year_output, year_qc_fields(), year_rows)
    return {
        "article_database": str(article_database),
        "candidate_event_url_pairs": candidate_pairs,
        "event_qc_output": str(event_output),
        "events": len(events),
        "invalid_publication_dates": invalid_publication_dates,
        "source_state_urls_scanned": scanned_state_urls,
        "unique_urls": unique_urls,
        "unmatched_state_urls": unmatched_state_urls,
        "unresolved_output": str(unresolved_output),
        "unresolved_state_urls": unresolved_state_urls,
        "year_qc_output": str(year_output),
        "years": len(year_rows),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--articles-database",
        type=Path,
        default=data_path("gdelt_article_database"),
    )
    parser.add_argument("--events", type=Path, default=data_path("events"))
    parser.add_argument(
        "--event-output",
        type=Path,
        default=data_path("article_retrieval_event_qc"),
    )
    parser.add_argument(
        "--year-output",
        type=Path,
        default=data_path("article_retrieval_year_qc"),
    )
    parser.add_argument(
        "--unresolved-output",
        type=Path,
        default=data_path("article_retrieval_unresolved"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = audit_retrieval(
            args.articles_database,
            args.events,
            args.event_output,
            args.year_output,
            args.unresolved_output,
        )
    except (FileNotFoundError, OSError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
