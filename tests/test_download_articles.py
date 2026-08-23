import asyncio
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
from article_extractor import clean_candidate  # noqa: E402
from article_fetcher import (  # noqa: E402
    AsyncArticleFetcher,
    HttpFetch,
    fallback_links,
    looks_like_javascript_shell,
)


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

    def test_attempt_history_and_selected_fallback_are_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            connection = download_articles.connect_database(
                Path(tmp) / "articles.sqlite"
            )
            try:
                url = "https://example.com/article"
                connection.execute("INSERT INTO documents(url) VALUES (?)", (url,))
                attempt = {
                    "attempt_kind": "amp",
                    "attempted_url": "https://example.com/article/amp",
                    "started_at_utc": "2020-01-01T00:00:00+00:00",
                    "finished_at_utc": "2020-01-01T00:00:01+00:00",
                    "status": "ok",
                    "http_status": 200,
                    "transport_attempts": 1,
                }
                download_articles.save_result(
                    connection,
                    url,
                    {
                        "status": "ok",
                        "body_text": "article body",
                        "fallback_used": "amp",
                        "selected_attempt_url": attempt["attempted_url"],
                    },
                    [attempt],
                )
                fallback, count = connection.execute(
                    "SELECT fallback_used, attempt_count FROM documents"
                ).fetchone()
                self.assertEqual((fallback, count), ("amp", 1))
                kind, attempted = connection.execute(
                    "SELECT attempt_kind, attempted_url FROM download_attempts"
                ).fetchone()
                self.assertEqual((kind, attempted), ("amp", attempt["attempted_url"]))
            finally:
                connection.close()

    def test_round_robin_spreads_origins(self):
        urls = [
            "https://a.example/1",
            "https://a.example/2",
            "https://b.example/1",
            "https://b.example/2",
            "https://c.example/1",
        ]
        self.assertEqual(
            list(download_articles.round_robin_origins(urls)),
            [urls[0], urls[2], urls[4], urls[1], urls[3]],
        )

    def test_declared_fallbacks_stay_on_site(self):
        source = """
        <link rel="canonical" href="https://news.example.com/story/42">
        <link rel="amphtml" href="https://amp.news.example.com/story/42/amp">
        """
        self.assertEqual(
            fallback_links(source, "http://news.example.com/story/42?source=gdelt"),
            [
                ("canonical", "https://news.example.com/story/42"),
                ("amp", "https://amp.news.example.com/story/42/amp"),
            ],
        )

    def test_javascript_shell_detection_is_narrow(self):
        shell = '<html><body><div id="root"></div><script src="app.js"></script></body></html>'
        self.assertTrue(
            looks_like_javascript_shell(shell, {"status": "extract_empty"})
        )
        self.assertFalse(looks_like_javascript_shell(shell, {"status": "ok"}))

    def test_canonical_fallback_replaces_weak_original(self):
        original_url = "https://news.example.com/story?tracking=1"
        canonical_url = "https://news.example.com/story"
        weak_html = f'<link rel="canonical" href="{canonical_url}"><p>Short</p>'
        calls = []
        fetcher = object.__new__(AsyncArticleFetcher)

        async def logical_attempt(url, kind, *, rendered=False):
            calls.append((kind, url, rendered))
            if kind == "original":
                result = {
                    "status": "extract_weak",
                    "final_url": original_url,
                    "extraction_confidence": 0.3,
                    "word_count": 3,
                    "body_text": "Short",
                    "fallback_used": None,
                }
                extraction = {"status": "extract_weak"}
                page = weak_html
            else:
                result = {
                    "status": "ok",
                    "final_url": canonical_url,
                    "extraction_confidence": 0.9,
                    "word_count": 200,
                    "body_text": "Full article",
                    "fallback_used": kind,
                }
                extraction = {"status": "ok"}
                page = "<article>Full article</article>"
            history = {
                "attempt_kind": kind,
                "attempted_url": url,
                "started_at_utc": "start",
                "finished_at_utc": "finish",
                "status": result["status"],
            }
            return result, history, page, extraction

        fetcher._logical_attempt = logical_attempt
        result, attempts = asyncio.run(fetcher.fetch_article(original_url))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fallback_used"], "canonical")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(calls[1], ("canonical", canonical_url, False))

    def test_permanent_404_does_not_trigger_https_fallback(self):
        url = "http://news.example.com/missing"
        fetcher = object.__new__(AsyncArticleFetcher)
        calls = []

        async def logical_attempt(attempted_url, kind, *, rendered=False):
            calls.append((kind, attempted_url))
            result = {
                "status": "http_error",
                "http_status": 404,
                "final_url": attempted_url,
                "fallback_used": None,
            }
            history = {
                "attempt_kind": kind,
                "attempted_url": attempted_url,
                "started_at_utc": "start",
                "finished_at_utc": "finish",
                "status": "http_error",
            }
            return result, history, None, None

        fetcher._logical_attempt = logical_attempt
        result, attempts = asyncio.run(fetcher.fetch_article(url))
        self.assertEqual(result["status"], "http_error")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(calls, [("original", url)])

    def test_empty_html_is_classified_as_extract_empty(self):
        fetcher = object.__new__(AsyncArticleFetcher)

        async def fetch_http(url):
            return HttpFetch(
                status="html",
                attempted_url=url,
                final_url=url,
                http_status=200,
                raw=b"",
            )

        fetcher._fetch_http = fetch_http
        result, attempt, page, extraction = asyncio.run(
            fetcher._logical_attempt("https://example.com/empty", "original")
        )
        self.assertEqual(result["status"], "extract_empty")
        self.assertEqual(attempt["status"], "extract_empty")
        self.assertIsNone(page)
        self.assertIsNone(extraction)

    def test_browser_circuit_breaker_counts_pending_and_failures(self):
        fetcher = object.__new__(AsyncArticleFetcher)
        fetcher.browser_failure_limit = 2
        fetcher._browser_failures = {}
        fetcher._browser_pending = {}
        url = "https://www.example.com/story"
        self.assertTrue(fetcher._reserve_browser(url))
        self.assertTrue(fetcher._reserve_browser(url))
        self.assertFalse(fetcher._reserve_browser(url))
        fetcher._record_browser_result(url, "extract_weak")
        self.assertFalse(fetcher._reserve_browser(url))

    def test_open_host_circuit_defers_without_network_request(self):
        fetcher = object.__new__(AsyncArticleFetcher)
        fetcher.host_failure_limit = 3
        fetcher._host_transient_failures = {"example.com": 3}
        result = asyncio.run(fetcher._fetch_http("https://www.example.com/story"))
        self.assertEqual(result.status, "host_deferred")
        self.assertIn("circuit open", result.error)

    def test_multilingual_headline_tail_is_removed(self):
        article = " ".join(["This is a verified article paragraph with details."] * 20)
        headlines = [
            "குபீர் போராளிகளுக்கு கொண்டாட்டம்!",
            "பதவியை ராஜினாமா செய்தார் மத்திய அமைச்சர்",
            "லடாக்கில் ராணுவத்தினருக்கு அவமதிப்பு",
            "கங்கை ஆற்றில் சிக்கன் பிரியாணி சாப்பிடுவது குற்றமில்லை",
            "தமிழகத்தில் இருந்து பிரதமர் உருவாக விருப்பம்",
            "வரம்பு மீறும் ராகுலை வரலாறு மன்னிக்காது!",
        ]
        cleaned = clean_candidate(
            {"title": "Flood report", "body": article + "\n\n" + "\n\n".join(headlines)}
        )["body"]
        self.assertIn("verified article paragraph", cleaned)
        self.assertNotIn("குபீர்", cleaned)
        self.assertNotIn("ராகுலை", cleaned)


if __name__ == "__main__":
    unittest.main()
