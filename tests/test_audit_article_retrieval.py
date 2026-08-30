from __future__ import annotations

import csv
import gzip
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from audit_article_retrieval import audit_retrieval  # noqa: E402


class AuditArticleRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "articles.sqlite"
        self.events = self.root / "events.csv"
        self.event_output = self.root / "event_qc.csv"
        self.year_output = self.root / "year_qc.csv"
        self.unresolved_output = self.root / "unresolved.csv.gz"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE documents (
              url TEXT PRIMARY KEY,
              status TEXT,
              http_status INTEGER,
              final_url TEXT,
              retrieved_at_utc TEXT,
              page_title TEXT,
              canonical_url TEXT,
              extraction_method TEXT,
              extraction_confidence REAL,
              word_count INTEGER,
              selected_attempt_url TEXT,
              fallback_used TEXT,
              attempt_count INTEGER,
              error TEXT,
              body_text TEXT
            );
            CREATE TABLE event_articles (
              event_id TEXT,
              state TEXT,
              source_record_id TEXT,
              published_at TEXT,
              url TEXT,
              source_domain TEXT,
              source_lang TEXT
            );
            """
        )
        documents = [
            ("https://a.test/ok", "ok", 200, "primary body"),
            ("https://a.test/weak", "extract_weak", 200, "weak body"),
            ("https://a.test/gone", "http_error", 404, None),
            ("https://b.test/error", "request_error", None, None),
            ("https://c.test/unmatched", "ok", 200, "other state body"),
        ]
        connection.executemany(
            """
            INSERT INTO documents(
              url, status, http_status, final_url, retrieved_at_utc,
              page_title, canonical_url, extraction_method,
              extraction_confidence, word_count, selected_attempt_url,
              fallback_used, attempt_count, error, body_text
            ) VALUES (?, ?, ?, ?, '2026-01-01T00:00:00+00:00',
                      NULL, NULL, NULL, NULL, NULL, ?, NULL, 1, NULL, ?)
            """,
            [
                (url, status, http_status, url, url, body)
                for url, status, http_status, body in documents
            ],
        )
        connection.executemany(
            """
            INSERT INTO event_articles(
              event_id, state, source_record_id, published_at, url,
              source_domain, source_lang
            ) VALUES (?, ?, ?, ?, ?, ?, 'en')
            """,
            [
                ("raw-1", "State A", "D-1", "2020-01-10", "https://a.test/ok", "a.test"),
                ("raw-1", "State A", "D-1", "2020-01-25", "https://a.test/weak", "a.test"),
                ("raw-1", "State A", "D-1", "2020-01-30", "https://a.test/gone", "a.test"),
                ("raw-3", "State B", "D-3", "2020-02-05", "https://b.test/error", "b.test"),
                ("raw-x", "State C", "D-X", "2020-03-01", "https://c.test/unmatched", "c.test"),
            ],
        )
        connection.commit()
        connection.close()

        with self.events.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "event_id",
                    "state",
                    "district",
                    "start_date",
                    "source_record_id",
                ),
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "event_id": "E001",
                        "state": "State A",
                        "district": "A1",
                        "start_date": "2020-01-01",
                        "source_record_id": "D-1",
                    },
                    {
                        "event_id": "E002",
                        "state": "State A",
                        "district": "A2",
                        "start_date": "2020-01-20",
                        "source_record_id": "D-2",
                    },
                    {
                        "event_id": "E003",
                        "state": "State B",
                        "district": "B1",
                        "start_date": "2020-02-01",
                        "source_record_id": "D-3",
                    },
                ]
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def read_csv(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_audit_mirrors_event_windows_and_separates_recovery_classes(self) -> None:
        result = audit_retrieval(
            self.database,
            self.events,
            self.event_output,
            self.year_output,
            self.unresolved_output,
        )

        self.assertEqual(result["events"], 3)
        self.assertEqual(result["unique_urls"], 5)
        self.assertEqual(result["candidate_event_url_pairs"], 6)
        self.assertEqual(result["unmatched_state_urls"], 1)
        self.assertEqual(result["unresolved_state_urls"], 3)

        by_event = {row["event_id"]: row for row in self.read_csv(self.event_output)}
        self.assertEqual(by_event["E001"]["candidate_event_url_count"], "3")
        self.assertEqual(
            by_event["E001"]["candidate_event_url_primary_body_count"], "1"
        )
        self.assertEqual(
            by_event["E001"]["candidate_event_url_weak_body_count"], "1"
        )
        self.assertEqual(
            by_event["E001"]["candidate_event_url_archive_candidate_count"], "1"
        )
        self.assertAlmostEqual(
            float(by_event["E001"]["candidate_event_url_primary_body_rate"]),
            1 / 3,
        )
        self.assertEqual(by_event["E002"]["candidate_event_url_count"], "2")
        self.assertEqual(
            by_event["E003"]["candidate_event_url_transient_retryable_count"],
            "1",
        )

        year = self.read_csv(self.year_output)[0]
        self.assertEqual(year["publication_year"], "2020")
        self.assertEqual(year["unique_url_count"], "5")
        self.assertEqual(year["unique_url_primary_body_count"], "2")
        self.assertEqual(year["candidate_event_url_count"], "6")

        with gzip.open(self.unresolved_output, "rt", encoding="utf-8", newline="") as handle:
            unresolved = list(csv.DictReader(handle))
        self.assertEqual(len(unresolved), 3)
        recovery = {row["url"]: row["recovery_class"] for row in unresolved}
        self.assertEqual(recovery["https://a.test/weak"], "weak_body_retryable")
        self.assertEqual(recovery["https://a.test/gone"], "archive_candidate")
        self.assertEqual(recovery["https://b.test/error"], "transient_retryable")


if __name__ == "__main__":
    unittest.main()
