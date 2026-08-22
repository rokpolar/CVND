import gzip
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import download_articles  # noqa: E402


class DownloadArticlesTests(unittest.TestCase):
    def test_extractor_prefers_article_content(self):
        source = """
        <html><head><title>Flood report</title></head><body>
          <main><p>Main fallback</p><article>
            <h1>Flood report</h1><p>Detailed article paragraph.</p>
          </article></main><nav><p>Navigation</p></nav>
        </body></html>
        """
        title, body = download_articles.extract_article_text(source)
        self.assertEqual(title, "Flood report")
        self.assertIn("Detailed article paragraph.", body)
        self.assertNotIn("Main fallback", body)
        self.assertNotIn("Navigation", body)

    def test_metadata_import_deduplicates_network_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "articles.jsonl.gz"
            database_path = root / "articles.sqlite"
            rows = []
            for event_id in ("E001", "E002"):
                rows.append(
                    {
                        "event_id": event_id,
                        "state": "Odisha",
                        "source_record_id": f"source-{event_id}",
                        "gkg_record_id": f"gkg-{event_id}",
                        "published_at": "2020-06-10T00:00:00+00:00",
                        "url": "https://example.com/shared",
                        "source_domain": "example.com",
                        "source_lang": "en",
                    }
                )
            with gzip.open(input_path, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")

            connection = download_articles.connect_database(database_path)
            try:
                links, unique_urls = download_articles.import_metadata(
                    connection, input_path
                )
                self.assertEqual(links, 2)
                self.assertEqual(unique_urls, 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM event_articles"
                    ).fetchone()[0],
                    2,
                )
            finally:
                connection.close()

    def test_database_is_resumable_by_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "articles.sqlite"
            connection = download_articles.connect_database(database_path)
            try:
                connection.execute(
                    "INSERT INTO documents(url) VALUES (?)",
                    ("https://example.com/article",),
                )
                download_articles.save_result(
                    connection,
                    "https://example.com/article",
                    {"status": "ok", "body_text": "article body"},
                )
                status, body = connection.execute(
                    "SELECT status, body_text FROM documents"
                ).fetchone()
                self.assertEqual(status, "ok")
                self.assertEqual(body, "article body")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
