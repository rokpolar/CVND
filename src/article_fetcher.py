"""Asynchronous, polite article fetching with high-value fallbacks.

Network concurrency is global while request spacing is enforced per origin.
Downloaded HTML is handed to the existing CPU-heavy ensemble extractor through
an executor supplied by the caller.  Browser rendering is lazy and is only
used for pages that look like JavaScript application shells.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from charset_normalizer import from_bytes

from article_extractor import extract_article, parse_html


RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
FALLBACK_EXTRACTION_STATUSES = {"extract_empty", "extract_weak"}
TERMINAL_STATUSES = {
    "domain_parked",
    "non_html",
    "redirect_home",
    "redirect_listing",
    "robots_denied",
    "too_large",
}
JS_MARKER_RE = re.compile(
    r"(__NEXT_DATA__|__NUXT__|webpackJsonp|enable javascript|"
    r"id=[\"'](?:app|root|__next)[\"'])",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def origin_for(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def host_for(url: str) -> str:
    return (urlsplit(url).netloc or "").lower().removeprefix("www.")


def article_redirect_status(original_url: str, final_url: str) -> str | None:
    """Detect expired deep links redirected to home or section listing pages."""
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


def decode_page(raw: bytes) -> str:
    detected = from_bytes(raw).best()
    encoding = detected.encoding if detected is not None and detected.encoding else "utf-8"
    page = raw.decode(encoding, errors="replace")
    try:
        utf8_page = raw.decode("utf-8")
    except UnicodeDecodeError:
        utf8_page = None
    if utf8_page is not None and _mojibake_score(utf8_page) < _mojibake_score(page):
        return utf8_page
    return page


def extract_page(content: str, url: str) -> dict[str, Any]:
    """Top-level process-pool entry point."""
    return extract_article(content, url=url)


def normalized_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def same_site(left: str, right: str) -> bool:
    a = normalized_host(left)
    b = normalized_host(right)
    return bool(a and b and (a == b or a.endswith("." + b) or b.endswith("." + a)))


def https_variant(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "http" or not parsed.netloc:
        return None
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def fallback_links(content: str, base_url: str) -> list[tuple[str, str]]:
    """Return declared same-site canonical and AMP alternatives."""
    soup = parse_html(content)
    alternatives: list[tuple[str, str]] = []
    seen = {base_url.rstrip("/")}
    declarations = (
        ("canonical", soup.find("link", rel=lambda value: value and "canonical" in value)),
        ("amp", soup.find("link", rel=lambda value: value and "amphtml" in value)),
    )
    for kind, tag in declarations:
        href = str(tag.get("href") or "").strip() if tag else ""
        candidate = urljoin(base_url, href)
        parsed = urlsplit(candidate)
        key = candidate.rstrip("/")
        if (
            not href
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or key in seen
            or not same_site(base_url, candidate)
            or article_redirect_status(base_url, candidate) is not None
        ):
            continue
        seen.add(key)
        alternatives.append((kind, candidate))
    return alternatives


def looks_like_javascript_shell(content: str, extraction: dict[str, Any]) -> bool:
    if extraction.get("status") not in FALLBACK_EXTRACTION_STATUSES:
        return False
    soup = parse_html(content)
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    visible_words = len(re.findall(r"\w+", soup.get_text(" ", strip=True)))
    marker = bool(JS_MARKER_RE.search(content[:1_000_000]))
    script_count = content[:1_000_000].lower().count("<script")
    return marker and visible_words < 220 or visible_words < 60 and script_count >= 5


def extraction_rank(result: dict[str, Any]) -> tuple[int, float, int, int]:
    status_rank = {
        "ok": 8,
        "extract_weak": 7,
        "extract_empty": 6,
        "redirect_listing": 5,
        "redirect_home": 5,
        "domain_parked": 4,
        "non_html": 3,
        "http_error": 2,
        "request_error": 1,
        "host_deferred": 1,
        "robots_denied": 0,
    }.get(str(result.get("status")), 0)
    return (
        status_rank,
        float(result.get("extraction_confidence") or 0.0),
        int(result.get("word_count") or 0),
        len(str(result.get("body_text") or "")),
    )


def retry_after_seconds(headers: httpx.Headers) -> float | None:
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            now = datetime.now(parsed.tzinfo or timezone.utc)
            return max(0.0, (parsed - now).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


@dataclass
class HttpFetch:
    status: str
    attempted_url: str
    final_url: str | None = None
    http_status: int | None = None
    retrieved_at_utc: str | None = None
    response_bytes: int | None = None
    raw: bytes | None = None
    content_type: str | None = None
    error: str | None = None
    transport_attempts: int = 1
    retry_after: float | None = None


class OriginThrottle:
    """Serialize each origin and enforce spacing between request starts."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_start: dict[str, float] = {}

    async def run(
        self,
        url: str,
        delay: float,
        operation: Callable[[], Awaitable[HttpFetch]],
    ) -> HttpFetch:
        host = host_for(url)
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._next_start.get(host, 0.0) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_start[host] = time.monotonic() + max(delay, 0.0)
            return await operation()


class AsyncRobotsCache:
    def __init__(
        self,
        user_agent: str,
        default_delay: float,
        loader: Callable[[str], Awaitable[HttpFetch]],
    ) -> None:
        self.user_agent = user_agent
        self.default_delay = default_delay
        self.loader = loader
        self._tasks: dict[str, asyncio.Task[RobotFileParser | None]] = {}
        self._lock = asyncio.Lock()

    async def _load(self, origin: str) -> RobotFileParser | None:
        robots_url = origin + "/robots.txt"
        fetched = await self.loader(robots_url)
        if fetched.http_status != 200 or not fetched.raw:
            return None
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(decode_page(fetched.raw).splitlines())
        return parser

    async def parser_for(self, url: str) -> RobotFileParser | None:
        origin = origin_for(url)
        async with self._lock:
            task = self._tasks.get(origin)
            if task is None:
                task = asyncio.create_task(self._load(origin))
                self._tasks[origin] = task
        try:
            # A per-article timeout must not cancel a robots load shared by
            # other URLs from the same origin.
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelled():
                raise
            async with self._lock:
                if self._tasks.get(origin) is task:
                    self._tasks.pop(origin, None)
            return None
        except Exception:
            async with self._lock:
                if self._tasks.get(origin) is task:
                    self._tasks.pop(origin, None)
            return None

    async def policy(self, url: str) -> tuple[bool, float]:
        parser = await self.parser_for(url)
        if parser is None:
            return True, self.default_delay
        allowed = parser.can_fetch(self.user_agent, url)
        crawl_delay = parser.crawl_delay(self.user_agent)
        if crawl_delay is None:
            crawl_delay = parser.crawl_delay("*")
        rate = parser.request_rate(self.user_agent) or parser.request_rate("*")
        rate_delay = rate.seconds / rate.requests if rate and rate.requests else 0.0
        delay = max(self.default_delay, float(crawl_delay or 0.0), rate_delay)
        return allowed, delay


class BrowserRenderer:
    """Lazy Playwright renderer using installed Chrome where available."""

    def __init__(
        self,
        *,
        enabled: bool,
        workers: int,
        timeout: float,
        wait_ms: int,
        user_agent: str,
        channel: str | None = "chrome",
    ) -> None:
        self.enabled = enabled
        self.timeout = timeout
        self.wait_ms = wait_ms
        self.user_agent = user_agent
        self.channel = channel
        self._semaphore = asyncio.Semaphore(max(1, workers))
        self._startup_lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._startup_error: str | None = None

    async def _start(self) -> bool:
        if not self.enabled:
            self._startup_error = "browser fallback disabled"
            return False
        if self._context is not None:
            return True
        if self._startup_error:
            return False
        async with self._startup_lock:
            if self._context is not None:
                return True
            try:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                options = {"headless": True}
                if self.channel:
                    options["channel"] = self.channel
                self._browser = await self._playwright.chromium.launch(**options)
                self._context = await self._browser.new_context(
                    user_agent=self.user_agent,
                    locale="en-US",
                    java_script_enabled=True,
                )

                async def block_heavy_assets(route: Any) -> None:
                    if route.request.resource_type in {"image", "media", "font"}:
                        await route.abort()
                    else:
                        await route.continue_()

                await self._context.route("**/*", block_heavy_assets)
                return True
            except Exception as exc:  # Playwright has backend-specific errors.
                self._startup_error = str(exc)[:1000]
                await self.close()
                return False

    async def render(self, url: str) -> HttpFetch:
        started = utc_now()
        async with self._semaphore:
            if not await self._start():
                return HttpFetch(
                    status="browser_unavailable",
                    attempted_url=url,
                    retrieved_at_utc=started,
                    error=self._startup_error,
                )
            page = await self._context.new_page()
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.timeout * 1000),
                )
                if self.wait_ms:
                    await page.wait_for_timeout(self.wait_ms)
                try:
                    content = await page.content()
                except Exception:
                    await page.wait_for_timeout(500)
                    content = await page.content()
                raw = content.encode("utf-8")
                status = response.status if response else None
                if status is not None and status >= 400:
                    return HttpFetch(
                        status="http_error",
                        attempted_url=url,
                        final_url=page.url,
                        http_status=status,
                        retrieved_at_utc=started,
                        response_bytes=len(raw),
                        error=f"HTTP {status}",
                    )
                return HttpFetch(
                    status="html",
                    attempted_url=url,
                    final_url=page.url,
                    http_status=status,
                    retrieved_at_utc=started,
                    response_bytes=len(raw),
                    raw=raw,
                    content_type="text/html; rendered=playwright",
                )
            except Exception as exc:
                return HttpFetch(
                    status="browser_error",
                    attempted_url=url,
                    final_url=page.url,
                    retrieved_at_utc=started,
                    error=str(exc)[:1000],
                )
            finally:
                await page.close()

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._browser = None
        self._playwright = None


class AsyncArticleFetcher:
    def __init__(
        self,
        *,
        workers: int,
        per_host_delay: float,
        timeout: float,
        max_bytes: int,
        retries: int,
        user_agent: str,
        extraction_executor: Executor,
        browser_enabled: bool,
        browser_workers: int,
        browser_timeout: float,
        browser_wait_ms: int,
        browser_failure_limit: int,
        host_failure_limit: int,
        browser_channel: str | None = "chrome",
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.retries = retries
        self.user_agent = user_agent
        self.extraction_executor = extraction_executor
        self.global_semaphore = asyncio.Semaphore(workers)
        self.throttle = OriginThrottle()
        limits = httpx.Limits(
            max_connections=workers,
            max_keepalive_connections=max(8, workers),
            keepalive_expiry=30.0,
        )
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en,*;q=0.5",
            },
            follow_redirects=True,
            limits=limits,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
        )
        self.per_host_delay = per_host_delay
        self.browser_failure_limit = browser_failure_limit
        self.host_failure_limit = host_failure_limit
        self._browser_failures: dict[str, int] = {}
        self._browser_pending: dict[str, int] = {}
        self._host_transient_failures: dict[str, int] = {}
        self.robots = AsyncRobotsCache(user_agent, per_host_delay, self._load_robots)
        self.browser = BrowserRenderer(
            enabled=browser_enabled,
            workers=browser_workers,
            timeout=browser_timeout,
            wait_ms=browser_wait_ms,
            user_agent=user_agent,
            channel=browser_channel,
        )

    async def __aenter__(self) -> AsyncArticleFetcher:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self.browser.close()
        await self.client.aclose()

    async def _request_once(self, url: str, delay: float, max_bytes: int) -> HttpFetch:
        async def operation() -> HttpFetch:
            async with self.global_semaphore:
                try:
                    async with asyncio.timeout(self.timeout):
                        async with self.client.stream("GET", url) as response:
                            content_type = response.headers.get("Content-Type", "").lower()
                            if response.status_code >= 400:
                                return HttpFetch(
                                    status="http_error",
                                    attempted_url=url,
                                    final_url=str(response.url),
                                    http_status=response.status_code,
                                    retrieved_at_utc=utc_now(),
                                    content_type=content_type,
                                    error=f"HTTP {response.status_code}",
                                    retry_after=retry_after_seconds(response.headers),
                                )
                            redirect_status = article_redirect_status(url, str(response.url))
                            if redirect_status:
                                return HttpFetch(
                                    status=redirect_status,
                                    attempted_url=url,
                                    final_url=str(response.url),
                                    http_status=response.status_code,
                                    retrieved_at_utc=utc_now(),
                                    content_type=content_type,
                                    error="article URL redirected to publisher home/listing page",
                                )
                            if content_type and "html" not in content_type:
                                return HttpFetch(
                                    status="non_html",
                                    attempted_url=url,
                                    final_url=str(response.url),
                                    http_status=response.status_code,
                                    retrieved_at_utc=utc_now(),
                                    content_type=content_type,
                                    error=content_type[:200],
                                )
                            chunks: list[bytes] = []
                            size = 0
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > max_bytes:
                                    return HttpFetch(
                                        status="too_large",
                                        attempted_url=url,
                                        final_url=str(response.url),
                                        http_status=response.status_code,
                                        retrieved_at_utc=utc_now(),
                                        response_bytes=size,
                                        content_type=content_type,
                                        error=f"response exceeds {max_bytes} bytes",
                                    )
                                chunks.append(chunk)
                            raw = b"".join(chunks)
                            return HttpFetch(
                                status="html",
                                attempted_url=url,
                                final_url=str(response.url),
                                http_status=response.status_code,
                                retrieved_at_utc=utc_now(),
                                response_bytes=len(raw),
                                raw=raw,
                                content_type=content_type,
                            )
                except (httpx.RequestError, TimeoutError) as exc:
                    return HttpFetch(
                        status="request_error",
                        attempted_url=url,
                        retrieved_at_utc=utc_now(),
                        error=str(exc)[:1000],
                    )

        return await self.throttle.run(url, delay, operation)

    async def _load_robots(self, url: str) -> HttpFetch:
        return await self._request_once(url, self.per_host_delay, min(self.max_bytes, 1_000_000))

    async def _fetch_http(self, url: str) -> HttpFetch:
        host = host_for(url)
        if self._host_transient_failures.get(host, 0) >= self.host_failure_limit:
            return HttpFetch(
                status="host_deferred",
                attempted_url=url,
                retrieved_at_utc=utc_now(),
                error="host circuit open after repeated transient failures",
            )
        allowed, delay = await self.robots.policy(url)
        if not allowed:
            return HttpFetch(
                status="robots_denied",
                attempted_url=url,
                retrieved_at_utc=utc_now(),
                error="robots.txt disallows this URL",
            )
        last: HttpFetch | None = None
        for attempt_number in range(1, self.retries + 2):
            fetched = await self._request_once(url, delay, self.max_bytes)
            fetched.transport_attempts = attempt_number
            last = fetched
            if fetched.status == "html":
                return fetched
            retryable = fetched.status == "request_error" or (
                fetched.status == "http_error"
                and fetched.http_status in RETRYABLE_HTTP_STATUSES
            )
            if retryable:
                self._host_transient_failures[host] = (
                    self._host_transient_failures.get(host, 0) + 1
                )
            else:
                self._host_transient_failures.pop(host, None)
            if not retryable or attempt_number > self.retries:
                return fetched
            if self._host_transient_failures[host] >= self.host_failure_limit:
                fetched.error = (
                    f"{fetched.error or fetched.status}; host circuit opened"
                )[:1000]
                return fetched
            retry_delay = min(30.0, 2 ** (attempt_number - 1))
            if fetched.retry_after is not None:
                retry_delay = max(retry_delay, min(fetched.retry_after, 300.0))
            elif fetched.http_status == 429:
                retry_delay = max(retry_delay, delay)
            await asyncio.sleep(retry_delay)
        return last or HttpFetch(status="request_error", attempted_url=url)

    async def _fetch_browser(self, url: str) -> HttpFetch:
        allowed, delay = await self.robots.policy(url)
        if not allowed:
            return HttpFetch(
                status="robots_denied",
                attempted_url=url,
                retrieved_at_utc=utc_now(),
                error="robots.txt disallows this URL",
            )

        async def operation() -> HttpFetch:
            return await self.browser.render(url)

        return await self.throttle.run(url, delay, operation)

    async def _extract(self, raw: bytes, url: str) -> tuple[str, dict[str, Any]]:
        page = decode_page(raw)
        loop = asyncio.get_running_loop()
        extraction = await loop.run_in_executor(
            self.extraction_executor, extract_page, page, url
        )
        return page, extraction

    @staticmethod
    def _attempt_record(
        kind: str,
        fetched: HttpFetch,
        started_at: str,
        extraction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extraction = extraction or {}
        return {
            "attempt_kind": kind,
            "attempted_url": fetched.attempted_url,
            "started_at_utc": started_at,
            "finished_at_utc": utc_now(),
            "status": extraction.get("status") or fetched.status,
            "http_status": fetched.http_status,
            "final_url": fetched.final_url,
            "response_bytes": fetched.response_bytes,
            "transport_attempts": fetched.transport_attempts,
            "extraction_method": extraction.get("method"),
            "extraction_confidence": extraction.get("confidence"),
            "word_count": extraction.get("word_count"),
            "error": fetched.error,
        }

    @staticmethod
    def _document_result(
        fetched: HttpFetch,
        extraction: dict[str, Any] | None,
        kind: str,
    ) -> dict[str, Any]:
        extraction = extraction or {}
        body = str(extraction.get("body") or "")
        return {
            "status": extraction.get("status") or fetched.status,
            "http_status": fetched.http_status,
            "final_url": fetched.final_url,
            "retrieved_at_utc": fetched.retrieved_at_utc or utc_now(),
            "response_bytes": fetched.response_bytes,
            "content_sha256": (
                hashlib.sha256(body.encode("utf-8")).hexdigest() if body else None
            ),
            "page_title": extraction.get("title"),
            "body_text": body,
            "canonical_url": extraction.get("canonical_url"),
            "extraction_method": extraction.get("method"),
            "extraction_confidence": extraction.get("confidence"),
            "word_count": extraction.get("word_count"),
            "candidate_count": extraction.get("candidate_count"),
            "supporting_methods": extraction.get("supporting_methods"),
            "selected_attempt_url": fetched.attempted_url,
            "fallback_used": None if kind == "original" else kind,
            "error": fetched.error,
        }

    async def _logical_attempt(
        self,
        url: str,
        kind: str,
        *,
        rendered: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any], str | None, dict[str, Any] | None]:
        started_at = utc_now()
        fetched = await self._fetch_browser(url) if rendered else await self._fetch_http(url)
        if fetched.status == "html" and not fetched.raw:
            extraction = {
                "status": "extract_empty",
                "body": "",
                "confidence": 0.0,
                "word_count": 0,
                "candidate_count": 0,
                "supporting_methods": [],
            }
            result = self._document_result(fetched, extraction, kind)
            return result, self._attempt_record(kind, fetched, started_at, extraction), None, None
        if fetched.status != "html":
            result = self._document_result(fetched, None, kind)
            return result, self._attempt_record(kind, fetched, started_at), None, None
        page, extraction = await self._extract(fetched.raw, fetched.final_url or url)
        result = self._document_result(fetched, extraction, kind)
        return (
            result,
            self._attempt_record(kind, fetched, started_at, extraction),
            page,
            extraction,
        )

    def _reserve_browser(self, url: str) -> bool:
        host = host_for(url)
        used = self._browser_failures.get(host, 0) + self._browser_pending.get(
            host, 0
        )
        if used >= self.browser_failure_limit:
            return False
        self._browser_pending[host] = self._browser_pending.get(host, 0) + 1
        return True

    def _record_browser_result(self, url: str, status: str) -> None:
        host = host_for(url)
        pending = self._browser_pending.get(host, 0)
        if pending <= 1:
            self._browser_pending.pop(host, None)
        else:
            self._browser_pending[host] = pending - 1
        if status == "ok":
            self._browser_failures.pop(host, None)
        else:
            self._browser_failures[host] = self._browser_failures.get(host, 0) + 1

    async def fetch_article(
        self, url: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        pages: list[tuple[str, str, dict[str, Any]]] = []
        attempted_urls = {url.rstrip("/")}

        result, attempt, page, extraction = await self._logical_attempt(url, "original")
        attempts.append(attempt)
        candidates.append(result)
        if page is not None and extraction is not None:
            pages.append((result.get("final_url") or url, page, extraction))

        final_scheme = urlsplit(str(result.get("final_url") or url)).scheme.lower()
        https_worthy = result["status"] == "request_error" or (
            result["status"] == "http_error"
            and result.get("http_status") in {400, 403, 426}
            and final_scheme == "http"
        )
        if https_worthy:
            alternate = https_variant(url)
            if alternate and alternate.rstrip("/") not in attempted_urls:
                attempted_urls.add(alternate.rstrip("/"))
                item, history, fallback_page, fallback_extraction = (
                    await self._logical_attempt(alternate, "https")
                )
                attempts.append(history)
                candidates.append(item)
                if fallback_page is not None and fallback_extraction is not None:
                    pages.append(
                        (item.get("final_url") or alternate, fallback_page, fallback_extraction)
                    )

        best = max(candidates, key=extraction_rank)
        if best["status"] in FALLBACK_EXTRACTION_STATUSES:
            declared: list[tuple[str, str]] = []
            for page_url, content, _ in pages:
                declared.extend(fallback_links(content, page_url))
            for kind, alternate in declared:
                key = alternate.rstrip("/")
                if key in attempted_urls:
                    continue
                attempted_urls.add(key)
                item, history, fallback_page, fallback_extraction = (
                    await self._logical_attempt(alternate, kind)
                )
                attempts.append(history)
                candidates.append(item)
                if fallback_page is not None and fallback_extraction is not None:
                    pages.append(
                        (item.get("final_url") or alternate, fallback_page, fallback_extraction)
                    )
                best = max(candidates, key=extraction_rank)
                if best["status"] == "ok" and float(
                    best.get("extraction_confidence") or 0.0
                ) >= 0.75:
                    break

        best = max(candidates, key=extraction_rank)
        if best["status"] in FALLBACK_EXTRACTION_STATUSES:
            shell = next(
                (
                    (page_url, content)
                    for page_url, content, item_extraction in pages
                    if looks_like_javascript_shell(content, item_extraction)
                ),
                None,
            )
            if shell is not None and self._reserve_browser(shell[0]):
                page_url, _ = shell
                browser_status = "browser_error"
                try:
                    item, history, _, _ = await self._logical_attempt(
                        page_url, "browser", rendered=True
                    )
                    attempts.append(history)
                    candidates.append(item)
                    browser_status = str(item.get("status"))
                finally:
                    self._record_browser_result(page_url, browser_status)

        best = max(candidates, key=extraction_rank)
        best["attempt_count"] = len(attempts)
        return best, attempts
