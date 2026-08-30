#!/usr/bin/env python3
"""Download accessible article text from GDELT article-metadata URLs.

The downloader runs network requests concurrently across publishers while
serializing and rate-limiting each origin. Extraction runs in a process pool,
SQLite writes are batched, and weak/empty pages can use declared canonical,
AMP, HTTPS, and narrowly targeted browser-rendering fallbacks.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tqdm import tqdm

from article_extractor import extract_article_text
from article_fetcher import (
    RETRYABLE_HTTP_STATUSES,
    AsyncArticleFetcher,
    _mojibake_score,
    article_redirect_status,
    host_for,
    redirects_article_to_homepage,
)


DEFAULT_USER_AGENT = "CVND-Research/1.0 (+https://github.com/rokpolar/CVND)"
RETRYABLE_RESULT_STATUSES = (
    "request_error",
    "host_deferred",
    "extract_empty",
    "extract_weak",
)


def open_metadata(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc


def connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
          url TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'pending',
          http_status INTEGER,
          final_url TEXT,
          retrieved_at_utc TEXT,
          response_bytes INTEGER,
          content_sha256 TEXT,
          page_title TEXT,
          body_text TEXT,
          canonical_url TEXT,
          extraction_method TEXT,
          extraction_confidence REAL,
          word_count INTEGER,
          candidate_count INTEGER,
          supporting_methods TEXT,
          selected_attempt_url TEXT,
          fallback_used TEXT,
          attempt_count INTEGER NOT NULL DEFAULT 0,
          error TEXT
        );
        CREATE TABLE IF NOT EXISTS event_articles (
          event_id TEXT NOT NULL,
          state TEXT NOT NULL,
          source_record_id TEXT NOT NULL,
          gkg_record_id TEXT,
          published_at TEXT NOT NULL,
          url TEXT NOT NULL,
          source_domain TEXT,
          source_lang TEXT,
          gdelt_title TEXT,
          authors TEXT,
          tone REAL,
          sharing_image TEXT,
          PRIMARY KEY (event_id, url),
          FOREIGN KEY (url) REFERENCES documents(url)
        );
        CREATE TABLE IF NOT EXISTS download_attempts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          document_url TEXT NOT NULL,
          attempt_kind TEXT NOT NULL,
          attempted_url TEXT NOT NULL,
          started_at_utc TEXT NOT NULL,
          finished_at_utc TEXT NOT NULL,
          status TEXT NOT NULL,
          http_status INTEGER,
          final_url TEXT,
          response_bytes INTEGER,
          transport_attempts INTEGER NOT NULL DEFAULT 1,
          extraction_method TEXT,
          extraction_confidence REAL,
          word_count INTEGER,
          error TEXT,
          FOREIGN KEY (document_url) REFERENCES documents(url)
        );
        CREATE INDEX IF NOT EXISTS idx_event_articles_url ON event_articles(url);
        CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
        CREATE INDEX IF NOT EXISTS idx_download_attempts_document
          ON download_attempts(document_url);
        """
    )
    existing_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(documents)")
    }
    extra_columns = {
        "canonical_url": "TEXT",
        "extraction_method": "TEXT",
        "extraction_confidence": "REAL",
        "word_count": "INTEGER",
        "candidate_count": "INTEGER",
        "supporting_methods": "TEXT",
        "selected_attempt_url": "TEXT",
        "fallback_used": "TEXT",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, column_type in extra_columns.items():
        if name not in existing_columns:
            connection.execute(
                f"ALTER TABLE documents ADD COLUMN {name} {column_type}"
            )
    connection.commit()
    return connection


def import_metadata(connection: sqlite3.Connection, input_path: Path) -> tuple[int, int]:
    article_links = 0
    for row in open_metadata(input_path):
        url = str(row.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        connection.execute("INSERT OR IGNORE INTO documents(url) VALUES (?)", (url,))
        connection.execute(
            """
            INSERT OR REPLACE INTO event_articles(
              event_id, state, source_record_id, gkg_record_id, published_at,
              url, source_domain, source_lang, gdelt_title, authors, tone,
              sharing_image
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(row["event_id"]),
                str(row["state"]),
                str(row["source_record_id"]),
                row.get("gkg_record_id"),
                str(row["published_at"]),
                url,
                row.get("source_domain"),
                row.get("source_lang"),
                row.get("title"),
                row.get("authors"),
                row.get("tone"),
                row.get("sharing_image"),
            ),
        )
        article_links += 1
        if article_links % 5000 == 0:
            connection.commit()
    connection.commit()
    unique_urls = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return article_links, int(unique_urls)


def save_result(
    connection: sqlite3.Connection,
    url: str,
    result: dict[str, Any],
    attempts: Iterable[dict[str, Any]] | None = None,
    *,
    commit: bool = True,
) -> None:
    history = list(attempts or [])
    connection.execute(
        """
        UPDATE documents SET
          status = ?, http_status = ?, final_url = ?, retrieved_at_utc = ?,
          response_bytes = ?, content_sha256 = ?, page_title = ?, body_text = ?,
          canonical_url = ?, extraction_method = ?, extraction_confidence = ?,
          word_count = ?, candidate_count = ?, supporting_methods = ?,
          selected_attempt_url = ?, fallback_used = ?,
          attempt_count = COALESCE(attempt_count, 0) + ?, error = ?
        WHERE url = ?
        """,
        (
            result.get("status"),
            result.get("http_status"),
            result.get("final_url"),
            result.get("retrieved_at_utc"),
            result.get("response_bytes"),
            result.get("content_sha256"),
            result.get("page_title"),
            result.get("body_text"),
            result.get("canonical_url"),
            result.get("extraction_method"),
            result.get("extraction_confidence"),
            result.get("word_count"),
            result.get("candidate_count"),
            json.dumps(result.get("supporting_methods") or [], ensure_ascii=False),
            result.get("selected_attempt_url"),
            result.get("fallback_used"),
            len(history),
            result.get("error"),
            url,
        ),
    )
    if history:
        connection.executemany(
            """
            INSERT INTO download_attempts(
              document_url, attempt_kind, attempted_url,
              started_at_utc, finished_at_utc, status, http_status, final_url,
              response_bytes, transport_attempts, extraction_method,
              extraction_confidence, word_count, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    url,
                    item["attempt_kind"],
                    item["attempted_url"],
                    item["started_at_utc"],
                    item["finished_at_utc"],
                    item["status"],
                    item.get("http_status"),
                    item.get("final_url"),
                    item.get("response_bytes"),
                    item.get("transport_attempts", 1),
                    item.get("extraction_method"),
                    item.get("extraction_confidence"),
                    item.get("word_count"),
                    item.get("error"),
                )
                for item in history
            ],
        )
    if commit:
        connection.commit()


def round_robin_origins(urls: Iterable[str]) -> Iterator[str]:
    """Spread a sorted or clustered input across origins fairly."""
    buckets: dict[str, deque[str]] = defaultdict(deque)
    for url in urls:
        buckets[host_for(url)].append(url)
    active = deque(buckets)
    while active:
        origin = active.popleft()
        bucket = buckets[origin]
        yield bucket.popleft()
        if bucket:
            active.append(origin)


class DownloadProgress:
    """Use tqdm for a fixed-width live bar and stable redirected logs."""

    def __init__(
        self,
        total: int,
        *,
        stream: Any | None = None,
        min_interval: float = 0.1,
    ) -> None:
        self.total = total
        self.stream = stream or sys.stderr
        self.min_interval = min_interval
        self.started = time.monotonic()
        self.interactive = bool(
            getattr(self.stream, "isatty", lambda: False)()
        )
        colour = (
            "cyan"
            if "NO_COLOR" not in os.environ
            and os.environ.get("TERM", "") != "dumb"
            else None
        )
        self.bar = (
            tqdm(
                total=total,
                desc="Crawling",
                unit="URL",
                file=self.stream,
                dynamic_ncols=True,
                mininterval=min_interval,
                smoothing=0.1,
                ascii=" ▏▎▍▌▋▊▉█",
                colour=colour,
                position=0,
                bar_format=(
                    "{desc} {percentage:5.1f}%|{bar}| "
                    "{n_fmt}/{total_fmt} "
                    "[{elapsed} • {rate_fmt} • ETA {remaining}]"
                ),
            )
            if self.interactive
            else None
        )
        self.status_bar = (
            tqdm(
                total=0,
                desc=f"Status  {self._status_summary({})}",
                file=self.stream,
                dynamic_ncols=True,
                mininterval=min_interval,
                position=1,
                leave=True,
                bar_format="{desc}",
            )
            if self.interactive
            else None
        )

    @staticmethod
    def _status_summary(status_counts: dict[str, int]) -> str:
        ok = status_counts.get("ok", 0)
        http = status_counts.get("http_error", 0)
        request = status_counts.get("request_error", 0)
        weak = status_counts.get("extract_empty", 0) + status_counts.get(
            "extract_weak", 0
        )
        deferred = status_counts.get("host_deferred", 0)
        categorized = ok + http + request + weak + deferred
        other = max(sum(status_counts.values()) - categorized, 0)
        return (
            f"ok={ok} http={http} request={request} weak={weak} "
            f"deferred={deferred} other={other}"
        )

    def update(
        self,
        completed: int,
        status_counts: dict[str, int],
        *,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        elapsed = max(now - self.started, 0.001)
        rate = completed / elapsed
        remaining = max(self.total - completed, 0)
        eta = remaining / rate if rate else float("inf")
        summary = self._status_summary(status_counts)

        if self.bar is None:
            if force or completed % 100 == 0 or completed == self.total:
                print(
                    f"Processed {completed:,}/{self.total:,} "
                    f"({rate:.2f} URLs/s, ETA {eta / 60:.1f} min): "
                    f"{json.dumps(dict(status_counts), ensure_ascii=False)}",
                    file=self.stream,
                    flush=True,
                )
            return
        if self.status_bar is not None:
            self.status_bar.set_description_str(
                f"Status  {summary}", refresh=False
            )
        delta = max(completed - int(self.bar.n), 0)
        rendered = self.bar.update(delta) if delta else False
        if force:
            self.bar.refresh()
        if self.status_bar is not None and (rendered or force):
            self.status_bar.refresh()

    def close(self, completed: int, status_counts: dict[str, int]) -> None:
        if self.bar is not None:
            self.update(completed, status_counts, force=True)
            if self.status_bar is not None:
                self.status_bar.close()
            self.bar.close()


def select_download_urls(
    connection: sqlite3.Connection,
    *,
    retry_failed: bool,
    limit: int | None,
    retry_before: str | None = None,
) -> list[str]:
    if retry_failed:
        status_placeholders = ",".join("?" for _ in RETRYABLE_RESULT_STATUSES)
        http_placeholders = ",".join("?" for _ in RETRYABLE_HTTP_STATUSES)
        where = (
            f"status IN ({status_placeholders}) OR "
            f"(status = 'http_error' AND http_status IN ({http_placeholders}))"
        )
        parameters: list[Any] = [
            *RETRYABLE_RESULT_STATUSES,
            *sorted(RETRYABLE_HTTP_STATUSES),
        ]
        if retry_before is not None:
            where = (
                f"({where}) AND "
                "(retrieved_at_utc IS NULL OR retrieved_at_utc < ?)"
            )
            parameters.append(retry_before)
    else:
        where = "status = 'pending'"
        parameters = []
    sql = f"SELECT url FROM documents WHERE {where} ORDER BY rowid"
    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(limit)
    return [row[0] for row in connection.execute(sql, parameters)]


def internal_error_result(url: str, exc: Exception) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    now = datetime.now(timezone.utc).isoformat()
    error = f"internal downloader error: {exc}"[:1000]
    return (
        {
            "status": "request_error",
            "retrieved_at_utc": now,
            "selected_attempt_url": url,
            "error": error,
        },
        [
            {
                "attempt_kind": "internal",
                "attempted_url": url,
                "started_at_utc": now,
                "finished_at_utc": now,
                "status": "request_error",
                "transport_attempts": 1,
                "error": error,
            }
        ],
    )


async def download_urls(
    connection: sqlite3.Connection,
    urls: list[str],
    args: argparse.Namespace,
) -> None:
    if not urls:
        return
    result_queue: asyncio.Queue[
        tuple[str, dict[str, Any], list[dict[str, Any]]]
    ] = asyncio.Queue(maxsize=args.workers * 4)
    status_counts: dict[str, int] = defaultdict(int)
    host_buckets: dict[str, deque[str]] = defaultdict(deque)
    for url in urls:
        host_buckets[host_for(url)].append(url)
    # Materialize a publisher-round-robin work queue. A per-host semaphore
    # bounds overlapping responses, while OriginThrottle still spaces request
    # starts according to the robots/default delay.
    work_queue: asyncio.Queue[str] = asyncio.Queue()
    active_hosts = deque(host_buckets.values())
    while active_hosts:
        host_urls = active_hosts.popleft()
        work_queue.put_nowait(host_urls.popleft())
        if host_urls:
            active_hosts.append(host_urls)
    per_host_workers = max(1, int(getattr(args, "per_host_workers", 1)))
    host_slots = {
        host: asyncio.Semaphore(per_host_workers) for host in host_buckets
    }

    async def host_worker(fetcher: AsyncArticleFetcher) -> None:
        while True:
            try:
                url = work_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                async with host_slots[host_for(url)]:
                    try:
                        async with asyncio.timeout(args.article_timeout):
                            result, attempts = await fetcher.fetch_article(url)
                    except TimeoutError:
                        result, attempts = internal_error_result(
                            url,
                            TimeoutError(
                                f"article exceeded {args.article_timeout}s"
                            ),
                        )
                    except Exception as exc:
                        result, attempts = internal_error_result(url, exc)
                await result_queue.put((url, result, attempts))
            finally:
                work_queue.task_done()

    async def writer() -> None:
        completed = 0
        pending_writes = 0
        last_commit = time.monotonic()
        progress = DownloadProgress(len(urls))
        try:
            while completed < len(urls):
                commit_due = max(
                    0.1, args.commit_seconds - (time.monotonic() - last_commit)
                )
                try:
                    url, result, attempts = await asyncio.wait_for(
                        result_queue.get(), timeout=commit_due
                    )
                except TimeoutError:
                    if pending_writes:
                        connection.commit()
                        pending_writes = 0
                    last_commit = time.monotonic()
                    continue
                completed += 1
                try:
                    save_result(connection, url, result, attempts, commit=False)
                    pending_writes += 1
                    status_counts[str(result.get("status") or "unknown")] += 1
                    if (
                        pending_writes >= args.commit_every
                        or time.monotonic() - last_commit >= args.commit_seconds
                    ):
                        connection.commit()
                        pending_writes = 0
                        last_commit = time.monotonic()
                    progress.update(completed, status_counts)
                finally:
                    result_queue.task_done()
            connection.commit()
        finally:
            progress.close(completed, status_counts)

    with ProcessPoolExecutor(max_workers=args.extract_workers) as extraction_pool:
        async with AsyncArticleFetcher(
            workers=args.workers,
            per_host_delay=args.delay,
            timeout=args.timeout,
            max_bytes=args.max_bytes,
            retries=args.retries,
            user_agent=args.user_agent,
            extraction_executor=extraction_pool,
            browser_enabled=not args.no_browser_fallback,
            browser_workers=args.browser_workers,
            browser_timeout=args.browser_timeout,
            browser_wait_ms=args.browser_wait_ms,
            browser_failure_limit=args.browser_failure_limit,
            host_failure_limit=args.host_failure_limit,
            browser_channel=args.browser_channel,
        ) as fetcher:
            writer_task = asyncio.create_task(writer())
            worker_count = min(args.workers, len(urls))
            host_tasks = [
                asyncio.create_task(host_worker(fetcher))
                for _ in range(worker_count)
            ]
            await work_queue.join()
            await asyncio.gather(*host_tasks)
            await result_queue.join()
            await writer_task


def default_output_path(input_path: Path) -> Path:
    name = input_path.name
    if name.endswith(".jsonl.gz"):
        name = name.removesuffix(".jsonl.gz")
    elif name.endswith(".jsonl"):
        name = name.removesuffix(".jsonl")
    return input_path.with_name(name + ".sqlite")


def parse_utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "timestamp must be ISO 8601, for example 2026-08-30T03:53:00Z"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Article metadata JSONL or JSONL.GZ")
    parser.add_argument("--output", type=Path, help="SQLite output/checkpoint path")
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Minimum seconds between requests to the same origin",
    )
    parser.add_argument("--workers", type=int, default=32, help="Concurrent network workers")
    parser.add_argument(
        "--per-host-workers",
        type=int,
        default=1,
        help=(
            "Maximum in-flight article responses per host (default: 1). "
            "Request starts remain spaced by --delay/robots rules."
        ),
    )
    parser.add_argument(
        "--extract-workers",
        type=int,
        default=min(4, os.cpu_count() or 4),
        help="Article extraction process workers",
    )
    parser.add_argument("--commit-every", type=int, default=100)
    parser.add_argument("--commit-seconds", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--article-timeout", type=float, default=90.0)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--limit", type=int, help="Maximum URLs to attempt this run")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--retry-before",
        type=parse_utc_timestamp,
        help=(
            "With --retry-failed, only retry documents whose latest result "
            "predates this ISO-8601 timestamp. This resumes an interrupted "
            "retry manifest without repeating URLs already handled in that run."
        ),
    )
    parser.add_argument("--no-browser-fallback", action="store_true")
    parser.add_argument("--browser-workers", type=int, default=2)
    parser.add_argument("--browser-timeout", type=float, default=20.0)
    parser.add_argument("--browser-wait-ms", type=int, default=1500)
    parser.add_argument("--browser-failure-limit", type=int, default=3)
    parser.add_argument("--host-failure-limit", type=int, default=3)
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args(list(argv) if argv is not None else None)


def validate_args(args: argparse.Namespace) -> None:
    positive = {
        "workers": args.workers,
        "per-host-workers": args.per_host_workers,
        "extract-workers": args.extract_workers,
        "commit-every": args.commit_every,
        "commit-seconds": args.commit_seconds,
        "timeout": args.timeout,
        "article-timeout": args.article_timeout,
        "max-bytes": args.max_bytes,
        "browser-workers": args.browser_workers,
        "browser-timeout": args.browser_timeout,
        "browser-failure-limit": args.browser_failure_limit,
        "host-failure-limit": args.host_failure_limit,
    }
    invalid = [name for name, value in positive.items() if value <= 0]
    if args.delay < 0 or args.retries < 0 or args.browser_wait_ms < 0 or invalid:
        fields = ", ".join(invalid or ["delay/retries/browser-wait-ms"])
        raise ValueError(f"invalid non-positive downloader option: {fields}")
    if args.limit is not None and args.limit < 0:
        raise ValueError("limit must be non-negative")
    if args.retry_before is not None and not args.retry_failed:
        raise ValueError("--retry-before requires --retry-failed")


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_args(args)
        output = args.output or default_output_path(args.input)
        connection = connect_database(output)
        try:
            links, unique_urls = import_metadata(connection, args.input)
            print(f"Imported {links:,} event/article links, {unique_urls:,} unique URLs")
            urls = select_download_urls(
                connection,
                retry_failed=args.retry_failed,
                limit=args.limit,
                retry_before=args.retry_before,
            )
            print(
                f"Scheduled {len(urls):,} URLs with {args.workers} network / "
                f"{args.extract_workers} extraction workers"
            )
            asyncio.run(download_urls(connection, urls, args))
            counts = dict(
                connection.execute(
                    "SELECT status, COUNT(*) FROM documents GROUP BY status"
                ).fetchall()
            )
            print(f"Saved resumable article database: {output}")
            print("Status counts: " + json.dumps(counts, ensure_ascii=False))
        finally:
            connection.close()
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
