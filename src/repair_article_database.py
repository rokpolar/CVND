#!/usr/bin/env python3
"""Apply conservative, reversible corrections to a completed article database."""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from article_extractor import (
    looks_like_known_listing_page,
    normalize_inline,
    parse_html,
    word_count,
)


MARKUP_RE = re.compile(r"<(?:p|div|br|article|section|blockquote)\b", re.I)


def strip_stored_markup(body: str) -> str:
    """Remove tags without re-running article selection on an accepted body."""
    fragment = parse_html(body)
    lines = (normalize_inline(line) for line in fragment.get_text("\n").splitlines())
    return "\n\n".join(line for line in lines if line)


def ensure_audit_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS article_corrections (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL,
          url TEXT NOT NULL,
          corrected_at_utc TEXT NOT NULL,
          correction_kind TEXT NOT NULL,
          previous_status TEXT NOT NULL,
          new_status TEXT NOT NULL,
          previous_body_text TEXT,
          previous_content_sha256 TEXT,
          previous_word_count INTEGER,
          previous_extraction_confidence REAL,
          previous_error TEXT,
          details TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_article_corrections_run
          ON article_corrections(run_id);
        """
    )


def corrections(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT url, status, page_title, body_text, content_sha256, word_count,
               extraction_confidence, extraction_method, error
        FROM documents
        WHERE status = 'ok'
        """
    )
    changes: list[dict[str, Any]] = []
    for row in rows:
        url, status, title, body, digest, words, confidence, method, error = row
        body = body or ""
        if looks_like_known_listing_page(url, title, body):
            changes.append(
                {
                    "url": url,
                    "kind": "confirmed_listing_page",
                    "previous": (status, body, digest, words, confidence, error),
                    "new": (
                        "redirect_listing",
                        "",
                        None,
                        0,
                        0.0,
                        "post-crawl audit: high-confidence listing/feed page",
                    ),
                }
            )
            continue
        if (
            method in {"jsonld.articleBody", "json.embedded.articleBody"}
            and MARKUP_RE.search(body)
        ):
            cleaned = strip_stored_markup(body)
            if cleaned and cleaned != body:
                cleaned_words = word_count(cleaned)
                changes.append(
                    {
                        "url": url,
                        "kind": "html_markup_cleanup",
                        "previous": (status, body, digest, words, confidence, error),
                        "new": (
                            "ok" if len(cleaned) >= 200 and cleaned_words >= 40 else "extract_weak",
                            cleaned,
                            hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
                            cleaned_words,
                            confidence,
                            error,
                        ),
                    }
                )
    return changes


def apply_corrections(
    connection: sqlite3.Connection, changes: list[dict[str, Any]], run_id: str
) -> None:
    corrected_at = datetime.now(timezone.utc).isoformat()
    ensure_audit_table(connection)
    with connection:
        for change in changes:
            old_status, old_body, old_hash, old_words, old_confidence, old_error = change[
                "previous"
            ]
            new_status, new_body, new_hash, new_words, new_confidence, new_error = change[
                "new"
            ]
            connection.execute(
                """
                INSERT INTO article_corrections(
                  run_id, url, corrected_at_utc, correction_kind,
                  previous_status, new_status, previous_body_text,
                  previous_content_sha256, previous_word_count,
                  previous_extraction_confidence, previous_error, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    change["url"],
                    corrected_at,
                    change["kind"],
                    old_status,
                    new_status,
                    old_body,
                    old_hash,
                    old_words,
                    old_confidence,
                    old_error,
                    "Conservative post-crawl correction; original values retained here.",
                ),
            )
            connection.execute(
                """
                UPDATE documents
                SET status = ?, body_text = ?, content_sha256 = ?, word_count = ?,
                    extraction_confidence = ?, error = ?
                WHERE url = ?
                """,
                (*change["new"], change["url"]),
            )


def rollback(connection: sqlite3.Connection, run_id: str) -> int:
    rows = connection.execute(
        """
        SELECT url, previous_status, previous_body_text, previous_content_sha256,
               previous_word_count, previous_extraction_confidence, previous_error
        FROM article_corrections WHERE run_id = ? ORDER BY id DESC
        """,
        (run_id,),
    ).fetchall()
    with connection:
        for row in rows:
            connection.execute(
                """
                UPDATE documents
                SET status = ?, body_text = ?, content_sha256 = ?, word_count = ?,
                    extraction_confidence = ?, error = ?
                WHERE url = ?
                """,
                (*row[1:], row[0]),
            )
        connection.execute("DELETE FROM article_corrections WHERE run_id = ?", (run_id,))
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true", help="commit proposed corrections")
    parser.add_argument("--rollback-run", metavar="RUN_ID")
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    try:
        if args.rollback_run:
            ensure_audit_table(connection)
            count = rollback(connection, args.rollback_run)
            print(f"Rolled back {count:,} corrections from run {args.rollback_run}")
            return 0
        changes = corrections(connection)
        by_kind: dict[str, int] = {}
        for change in changes:
            by_kind[change["kind"]] = by_kind.get(change["kind"], 0) + 1
        mode = "Applying" if args.apply else "Dry run"
        print(f"{mode}: {len(changes):,} conservative corrections")
        for kind, count in sorted(by_kind.items()):
            print(f"  {kind}: {count:,}")
        if args.apply and changes:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
            apply_corrections(connection, changes, run_id)
            print(f"Applied run {run_id}; rollback with --rollback-run {run_id}")
        elif not args.apply:
            print("No changes written. Re-run with --apply to commit them.")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
