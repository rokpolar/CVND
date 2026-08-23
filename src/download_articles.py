#!/usr/bin/env python3
"""Download accessible article text from GDELT article-metadata URLs.

GDELT supplies URLs and metadata, not full article bodies. This collector reads
the compressed JSONL produced by collect_gdelt.py, stores event/article links in
SQLite, fetches each unique URL once, respects robots.txt, and resumes safely.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from charset_normalizer import from_bytes
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from article_extractor import extract_article, extract_article_text

DEFAULT_USER_AGENT = "CVND-Research/1.0 (+https://github.com/rokpolar/CVND)"


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
        CREATE INDEX IF NOT EXISTS idx_event_articles_url ON event_articles(url);
        CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
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
        connection.execute(
            "INSERT OR IGNORE INTO documents(url) VALUES (?)",
            (url,),
        )
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


class RobotsCache:
    def __init__(self, session: requests.Session, user_agent: str, timeout: float) -> None:
        self.session = session
        self.user_agent = user_agent
        self.timeout = timeout
        self.cache: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        split = urlsplit(url)
        origin = f"{split.scheme}://{split.netloc}"
        if origin not in self.cache:
            robots_url = origin + "/robots.txt"
            try:
                response = self.session.get(robots_url, timeout=self.timeout)
                if response.status_code == 200:
                    parser = RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse(response.text.splitlines())
                    self.cache[origin] = parser
                else:
                    self.cache[origin] = None
            except requests.RequestException:
                self.cache[origin] = None
        parser = self.cache[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)


def build_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en,*;q=0.5",
        }
    )
    retry = Retry(
        total=2,
        connect=2,
        read=1,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def article_redirect_status(original_url: str, final_url: str) -> str | None:
    """Detect expired deep links redirected to a home or section listing page."""
    original = urlsplit(original_url)
    final = urlsplit(final_url)
    original_parts = [part for part in original.path.split("/") if part]
    final_parts = [part for part in final.path.split("/") if part]
    if original_parts and not final_parts:
        return "redirect_home"
    if (
        len(original_parts) >= 2
        and len(final_parts) < len(original_parts)
        and original_parts[: len(final_parts)] == final_parts
    ):
        return "redirect_listing"
    return None


def redirects_article_to_homepage(original_url: str, final_url: str) -> bool:
    return article_redirect_status(original_url, final_url) == "redirect_home"


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in ("â€", "â€™", "Ã", "Â", "�"))


def fetch_article(
    session: requests.Session,
    robots: RobotsCache,
    url: str,
    *,
    timeout: float,
    max_bytes: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    if not robots.allowed(url):
        return {"status": "robots_denied", "retrieved_at_utc": now}
    try:
        with session.get(url, timeout=timeout, stream=True, allow_redirects=True) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status_code >= 400:
                return {
                    "status": "http_error",
                    "http_status": response.status_code,
                    "final_url": response.url,
                    "retrieved_at_utc": now,
                    "error": f"HTTP {response.status_code}",
                }
            redirect_status = article_redirect_status(url, response.url)
            if redirect_status:
                return {
                    "status": redirect_status,
                    "http_status": response.status_code,
                    "final_url": response.url,
                    "retrieved_at_utc": now,
                    "error": "article URL redirected to publisher home/listing page",
                }
            if "html" not in content_type:
                return {
                    "status": "non_html",
                    "http_status": response.status_code,
                    "final_url": response.url,
                    "retrieved_at_utc": now,
                    "error": content_type[:200],
                }
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    return {
                        "status": "too_large",
                        "http_status": response.status_code,
                        "final_url": response.url,
                        "retrieved_at_utc": now,
                        "response_bytes": size,
                        "error": f"response exceeds {max_bytes} bytes",
                    }
                chunks.append(chunk)
            raw = b"".join(chunks)
            detected = from_bytes(raw).best()
            encoding = (
                detected.encoding
                if detected is not None and detected.encoding
                else response.encoding or "utf-8"
            )
            page = raw.decode(encoding, errors="replace")
            try:
                utf8_page = raw.decode("utf-8")
            except UnicodeDecodeError:
                utf8_page = None
            if utf8_page is not None and _mojibake_score(utf8_page) < _mojibake_score(page):
                page = utf8_page
            extraction = extract_article(page, url=response.url)
            body = str(extraction.get("body") or "")
            result = {
                "status": extraction["status"],
                "http_status": response.status_code,
                "final_url": response.url,
                "retrieved_at_utc": now,
                "response_bytes": len(raw),
                "content_sha256": (
                    hashlib.sha256(body.encode("utf-8")).hexdigest()
                    if body
                    else None
                ),
                "page_title": extraction.get("title"),
                "body_text": body,
                "canonical_url": extraction.get("canonical_url"),
                "extraction_method": extraction.get("method"),
                "extraction_confidence": extraction.get("confidence"),
                "word_count": extraction.get("word_count"),
                "candidate_count": extraction.get("candidate_count"),
                "supporting_methods": extraction.get("supporting_methods"),
            }
            if extraction["status"] == "redirect_home":
                result["error"] = "page canonical URL points to publisher homepage"
            return result
    except requests.RequestException as exc:
        return {
            "status": "request_error",
            "retrieved_at_utc": now,
            "error": str(exc)[:1000],
        }


def save_result(connection: sqlite3.Connection, url: str, result: dict[str, Any]) -> None:
    connection.execute(
        """
        UPDATE documents SET
          status = ?, http_status = ?, final_url = ?, retrieved_at_utc = ?,
          response_bytes = ?, content_sha256 = ?, page_title = ?, body_text = ?,
          canonical_url = ?, extraction_method = ?, extraction_confidence = ?,
          word_count = ?, candidate_count = ?, supporting_methods = ?,
          error = ?
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
            result.get("error"),
            url,
        ),
    )
    connection.commit()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Bxxx.articles.jsonl.gz metadata")
    parser.add_argument("--output", type=Path, help="SQLite output/checkpoint path")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between URLs")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--limit", type=int, help="Maximum URLs to attempt this run")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.delay < 0 or args.timeout <= 0 or args.max_bytes <= 0:
            raise ValueError("delay must be non-negative; timeout/max-bytes must be positive")
        output = args.output or args.input.with_name(
            args.input.name.removesuffix(".jsonl.gz") + ".articles.sqlite"
        )
        connection = connect_database(output)
        try:
            links, unique_urls = import_metadata(connection, args.input)
            print(f"Imported {links:,} event/article links, {unique_urls:,} unique URLs")
            where = "status != 'ok'" if args.retry_failed else "status = 'pending'"
            sql = f"SELECT url FROM documents WHERE {where} ORDER BY url"
            parameters: tuple[Any, ...] = ()
            if args.limit is not None:
                sql += " LIMIT ?"
                parameters = (args.limit,)
            urls = [row[0] for row in connection.execute(sql, parameters)]
            session = build_session(args.user_agent)
            robots = RobotsCache(session, args.user_agent, args.timeout)
            for index, url in enumerate(urls, start=1):
                result = fetch_article(
                    session,
                    robots,
                    url,
                    timeout=args.timeout,
                    max_bytes=args.max_bytes,
                )
                save_result(connection, url, result)
                if index % 100 == 0 or index == len(urls):
                    print(f"Processed {index:,}/{len(urls):,}: {result['status']}")
                if index < len(urls) and args.delay:
                    time.sleep(args.delay)
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
