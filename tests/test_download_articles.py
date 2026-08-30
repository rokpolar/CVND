import asyncio
import gzip
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import download_articles  # noqa: E402
import repair_article_database  # noqa: E402
from article_extractor import (  # noqa: E402
    body_from_json,
    clean_candidate,
    extract_article,
    looks_like_known_listing_page,
)
from bs4 import XMLParsedAsHTMLWarning  # noqa: E402
from article_fetcher import (  # noqa: E402
    AsyncRobotsCache,
    AsyncArticleFetcher,
    HttpFetch,
    OriginThrottle,
    fallback_links,
    looks_like_javascript_shell,
)


class DownloadArticlesTests(unittest.TestCase):
    def test_origin_throttle_does_not_hold_lock_for_entire_response(self):
        async def scenario():
            throttle = OriginThrottle()
            first_started = asyncio.Event()
            release_first = asyncio.Event()
            second_started = asyncio.Event()

            async def first_operation():
                first_started.set()
                await release_first.wait()
                return HttpFetch(
                    status="html", attempted_url="https://example.com/a"
                )

            async def second_operation():
                second_started.set()
                return HttpFetch(
                    status="html", attempted_url="https://example.com/b"
                )

            first = asyncio.create_task(
                throttle.run("https://example.com/a", 0.0, first_operation)
            )
            await first_started.wait()
            second = asyncio.create_task(
                throttle.run("https://example.com/b", 0.0, second_operation)
            )
            await asyncio.wait_for(second_started.wait(), timeout=0.5)
            release_first.set()
            await asyncio.gather(first, second)

        asyncio.run(scenario())

    def test_retry_before_resumes_only_stale_retryable_documents(self):
        with tempfile.TemporaryDirectory() as temporary:
            connection = download_articles.connect_database(
                Path(temporary) / "articles.sqlite"
            )
            try:
                connection.executemany(
                    """
                    INSERT INTO documents(url, status, retrieved_at_utc)
                    VALUES (?, ?, ?)
                    """,
                    [
                        ("https://example.com/old", "host_deferred", "2026-01-01T00:00:00+00:00"),
                        ("https://example.com/new", "host_deferred", "2026-08-30T04:00:00+00:00"),
                        ("https://example.com/missing", "request_error", None),
                        ("https://example.com/done", "ok", "2025-01-01T00:00:00+00:00"),
                    ],
                )
                selected = download_articles.select_download_urls(
                    connection,
                    retry_failed=True,
                    limit=None,
                    retry_before="2026-08-30T03:53:00+00:00",
                )
            finally:
                connection.close()
        self.assertEqual(
            selected,
            ["https://example.com/old", "https://example.com/missing"],
        )

    def test_retry_before_requires_retry_failed(self):
        args = download_articles.parse_args(
            [
                "articles.jsonl.gz",
                "--retry-before",
                "2026-08-30T03:53:00Z",
            ]
        )
        with self.assertRaisesRegex(ValueError, "requires --retry-failed"):
            download_articles.validate_args(args)

    def test_database_corrections_are_audited_and_reversible(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            CREATE TABLE documents (
              url TEXT PRIMARY KEY, status TEXT, body_text TEXT,
              content_sha256 TEXT, word_count INTEGER,
              extraction_confidence REAL, error TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("https://example.com/story", "ok", "old body", "old-hash", 2, 0.8, None),
        )
        change = {
            "url": "https://example.com/story",
            "kind": "html_markup_cleanup",
            "previous": ("ok", "old body", "old-hash", 2, 0.8, None),
            "new": ("ok", "new body", "new-hash", 2, 0.8, None),
        }
        repair_article_database.apply_corrections(connection, [change], "test-run")
        self.assertEqual(
            connection.execute("SELECT body_text FROM documents").fetchone()[0],
            "new body",
        )
        self.assertEqual(repair_article_database.rollback(connection, "test-run"), 1)
        self.assertEqual(
            connection.execute("SELECT body_text FROM documents").fetchone()[0],
            "old body",
        )

    def test_escaped_jsonld_markup_becomes_plain_text(self):
        body = body_from_json(
            "&lt;p&gt;Officials announced a detailed recovery programme for affected "
            "households across the district.&lt;/p&gt;"
            "&lt;p&gt;Funding dates and eligibility guidance were published today for "
            "residents seeking assistance.&lt;/p&gt;"
        )
        self.assertIn("recovery programme", body)
        self.assertNotIn("<p>", body)

    def test_audited_listing_rules_do_not_reject_normal_category_article(self):
        feed = " ".join(["Current headline and summary from the live news feed."] * 1200)
        self.assertTrue(
            looks_like_known_listing_page(
                "http://www.brecorder.com/top-news/123-story.html", "Latest News", feed
            )
        )
        self.assertFalse(
            looks_like_known_listing_page(
                "https://freemalaysiatoday.com/category/world/2024/01/01/story-slug/",
                "A specific article title",
                feed,
            )
        )

    def test_xhtml_declaration_does_not_emit_parser_warning(self):
        source = """<?xml version="1.0" encoding="UTF-8"?>
        <html><head><title>Flood report</title></head><body><article>
        <p>The flood recovery programme provides detailed assistance to affected
        households across the district and will continue throughout the year.</p>
        <p>Officials published implementation dates, funding details, eligibility
        rules, and contact information for residents seeking emergency support.</p>
        </article></body></html>
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = extract_article(source, url="https://example.com/flood")
        parser_warnings = [
            warning
            for warning in caught
            if issubclass(warning.category, XMLParsedAsHTMLWarning)
        ]
        self.assertEqual(parser_warnings, [])
        self.assertIn(result["status"], {"ok", "extract_weak"})

    def test_interactive_progress_bar_reports_rate_eta_and_statuses(self):
        class TerminalBuffer(io.StringIO):
            def isatty(self):
                return True

        stream = TerminalBuffer()
        progress = download_articles.DownloadProgress(
            200, stream=stream, min_interval=0
        )
        counts = {
            "ok": 30,
            "http_error": 10,
            "extract_weak": 3,
            "extract_empty": 2,
            "host_deferred": 2,
            "redirect_home": 3,
        }
        progress.update(50, counts)
        progress.close(50, counts)
        output = stream.getvalue()
        self.assertIn("25.0%", output)
        self.assertIn("50/200", output)
        self.assertIn("URL/s", output)
        self.assertIn("ETA", output)
        self.assertIn("Crawling", output)
        self.assertIn("Status", output)
        self.assertIn("█", output)
        self.assertIn(
            "ok=30 http=10 request=0 weak=5 deferred=2 other=3", output
        )

    def test_redirected_progress_keeps_periodic_log_format(self):
        stream = io.StringIO()
        progress = download_articles.DownloadProgress(200, stream=stream)
        progress.update(99, {"ok": 99})
        self.assertEqual(stream.getvalue(), "")
        progress.update(100, {"ok": 100})
        self.assertIn("Processed 100/200", stream.getvalue())

    def test_cancelled_robots_waiter_does_not_cancel_shared_load(self):
        async def scenario():
            loader_started = asyncio.Event()
            release_loader = asyncio.Event()
            calls = 0

            async def loader(url):
                nonlocal calls
                calls += 1
                loader_started.set()
                await release_loader.wait()
                return HttpFetch(
                    status="html",
                    attempted_url=url,
                    final_url=url,
                    http_status=200,
                    raw=b"User-agent: *\nAllow: /\n",
                )

            cache = AsyncRobotsCache("test-agent", 1.0, loader)
            first = asyncio.create_task(cache.parser_for("https://example.com/a"))
            second = asyncio.create_task(cache.parser_for("https://example.com/b"))
            await loader_started.wait()
            await asyncio.sleep(0)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            release_loader.set()
            parser = await second
            return parser, calls

        parser, calls = asyncio.run(scenario())
        self.assertIsNotNone(parser)
        self.assertTrue(parser.can_fetch("test-agent", "https://example.com/c"))
        self.assertEqual(calls, 1)

    def test_scheduler_bounds_active_articles_to_network_workers(self):
        class FakeFetcher:
            active = 0
            maximum_active = 0

            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def fetch_article(self, url):
                type(self).active += 1
                type(self).maximum_active = max(
                    type(self).maximum_active, type(self).active
                )
                try:
                    await asyncio.sleep(0.01)
                    return {"status": "ok", "body_text": "article"}, []
                finally:
                    type(self).active -= 1

        with tempfile.TemporaryDirectory() as tmp:
            connection = download_articles.connect_database(
                Path(tmp) / "articles.sqlite"
            )
            urls = [f"https://host-{index}.example/story" for index in range(20)]
            connection.executemany(
                "INSERT INTO documents(url) VALUES (?)", ((url,) for url in urls)
            )
            args = SimpleNamespace(
                workers=3,
                extract_workers=1,
                commit_every=100,
                commit_seconds=5.0,
                article_timeout=2.0,
                delay=0.0,
                timeout=1.0,
                max_bytes=1000,
                retries=0,
                user_agent="test-agent",
                no_browser_fallback=True,
                browser_workers=1,
                browser_timeout=1.0,
                browser_wait_ms=0,
                browser_failure_limit=1,
                host_failure_limit=1,
                browser_channel=None,
            )
            try:
                with (
                    patch.object(
                        download_articles, "AsyncArticleFetcher", FakeFetcher
                    ),
                    patch.object(
                        download_articles, "ProcessPoolExecutor", ThreadPoolExecutor
                    ),
                ):
                    asyncio.run(
                        download_articles.download_urls(connection, urls, args)
                    )
                self.assertEqual(FakeFetcher.maximum_active, args.workers)
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM documents WHERE status='ok'"
                    ).fetchone()[0],
                    len(urls),
                )
            finally:
                connection.close()

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

    def test_host_circuit_counts_failed_urls_not_transport_retries(self):
        fetcher = object.__new__(AsyncArticleFetcher)
        fetcher.host_failure_limit = 3
        fetcher.retries = 2
        fetcher.max_bytes = 1_000
        fetcher.per_host_delay = 0.0
        fetcher._host_transient_failures = {}

        class Robots:
            async def policy(self, _url):
                return True, 0.0

        fetcher.robots = Robots()
        calls = []

        async def request_once(url, _delay, _max_bytes):
            calls.append(url)
            return HttpFetch(
                status="request_error",
                attempted_url=url,
                error="temporary failure",
            )

        fetcher._request_once = request_once
        with patch("article_fetcher.asyncio.sleep", new_callable=AsyncMock):
            first = asyncio.run(fetcher._fetch_http("https://example.com/one"))
            self.assertEqual(first.status, "request_error")
            self.assertEqual(fetcher._host_transient_failures["example.com"], 1)
            self.assertEqual(len(calls), 3)

            second = asyncio.run(fetcher._fetch_http("https://example.com/two"))
            self.assertEqual(second.status, "request_error")
            self.assertEqual(fetcher._host_transient_failures["example.com"], 2)
            self.assertEqual(len(calls), 6)

            third = asyncio.run(fetcher._fetch_http("https://example.com/three"))
            self.assertEqual(third.status, "request_error")
            self.assertIn("circuit opened", third.error)
            self.assertEqual(fetcher._host_transient_failures["example.com"], 3)
            self.assertEqual(len(calls), 9)

            deferred = asyncio.run(fetcher._fetch_http("https://example.com/four"))
            self.assertEqual(deferred.status, "host_deferred")
            self.assertEqual(len(calls), 9)

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

    def test_headline_feed_is_not_accepted_as_article_body(self):
        title = "Centre assures support to Jammu Kashmir"
        headlines = [
            "Maharashtra Election Result Live Updates",
            "Climate change could erase thousands of jobs by 2050",
            "Railway passengers take note of new station rules",
            "Gold rate today in Delhi Mumbai and Hyderabad",
            "Technology companies announce a new investment plan",
            "Sports team eyes a major win in final match",
            "Global markets rise as investors assess inflation data",
            "Researchers publish findings from a decade long study",
        ]
        source = (
            f"<html><head><title>{title}</title></head><body><main>"
            + "".join(f"<p>{headline}</p>" for headline in headlines)
            + "</main></body></html>"
        )
        result = extract_article(source, url="https://news.example/story")
        self.assertEqual(result["status"], "extract_weak")
        self.assertLess(result["confidence"], 0.42)

    def test_privacy_notice_blocks_are_removed_from_article(self):
        article = " ".join(
            ["The government announced detailed flood recovery measures today."]
            * 12
        )
        cleaned = clean_candidate(
            {
                "title": "Flood recovery measures",
                "body": (
                    "Your Privacy is Important to us\n\n"
                    "We encourage you to review our Terms of Service and Privacy Policy.\n\n"
                    + article
                ),
            }
        )["body"]
        self.assertNotIn("Privacy is Important", cleaned)
        self.assertNotIn("Terms of Service", cleaned)
        self.assertIn("flood recovery measures", cleaned)


if __name__ == "__main__":
    unittest.main()
