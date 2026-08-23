"""High-precision article-body extraction from already downloaded HTML.

The extractor deliberately runs several independent strategies and chooses a
consensus result.  It never performs network access; download policy remains in
``download_articles.py``.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from html import unescape
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

import trafilatura
from bs4 import BeautifulSoup


MIN_BODY_CHARS = 200
MIN_BODY_WORDS = 40
MIN_BLOCK_CHARS = 25
ARTICLE_TYPES = {
    "article",
    "newsarticle",
    "reportagenewsarticle",
    "analysisnewsarticle",
    "backgroundnewsarticle",
    "opinionnewsarticle",
    "report",
}
POSITIVE_CONTAINER_RE = re.compile(
    r"(article|articlebody|story|storybody|post|entry|main|body|content|detail|news[-_]?text)",
    re.I,
)
NEGATIVE_CONTAINER_RE = re.compile(
    r"(advert|banner|breadcrumb|caption|comment|cookie|footer|header|menu|nav|"
    r"newsletter|pagination|promo|recommend|related|share|sidebar|social|"
    r"subscribe|ticker|trending|widget)",
    re.I,
)
ERROR_PAGE_RE = re.compile(
    r"(access\s*denied|request blocked|forbidden|service unavailable|"
    r"page (was )?not found|enable javascript to (run|view|continue)|"
    r"verify you are human|captcha|you don.?t have permission to access|nosuchkey)",
    re.I,
)
PARKED_DOMAIN_RE = re.compile(
    r"(this domain (name )?(may be|is) for sale|buy this domain|"
    r"domain parking|sedo domain parking|find information, resources and relevant links)",
    re.I,
)
NOISE_BLOCK_RE = re.compile(
    r"^\s*(advertisement|sponsored|sign in|log in|download (our )?app|"
    r"accept (all )?cookies|cookie (policy|settings)|share this|follow us|"
    r"subscribe( now)?|newsletter|related (news|stories|articles)|"
    r"also read|read more|latest news|top news|recommended|comments?)\s*:?[\s»›-]*$",
    re.I,
)
INLINE_PROMO_RE = re.compile(
    r"^\s*(also read|read (also|more)|related|recommended|watch|listen|"
    r"download the app|subscribe|follow (us|our)|click here)\s*[:»›-]",
    re.I,
)
HARD_TAIL_RE = re.compile(
    r"^\s*(as a subscriber\b|edited,? printed,? published\b|printed at\b|"
    r"living media india limited\b|for reprint rights\b|copyright\s*©?\s*\d{0,4}\b|"
    r"all rights reserved\b|if you are looking for issues beyond today\b|"
    r"stay informed on all the latest news\b)",
    re.I,
)
DOMAIN_SELECTORS = {
    "economictimes.indiatimes.com": (
        '[itemprop="articleBody"]',
        ".artText",
        ".article-content",
        ".Normal",
    ),
    "dailyexcelsior.com": (
        '[itemprop="articleBody"]',
        ".td-post-content",
        ".entry-content",
        ".post-content",
    ),
    "indiatoday.in": (
        '[itemprop="articleBody"]',
        ".story__content",
        ".Story_description",
        ".story-content",
    ),
    "thehindu.com": (
        '[itemprop="articleBody"]',
        ".articlebodycontent",
        '[data-component="ArticleBody"]',
    ),
}


def normalize_inline(value: Any) -> str:
    text = unescape(str(value or "")).replace("\u00a0", " ")
    return re.sub(r"[\t\r\f\v ]+", " ", text).strip()


def normalized_key(value: Any) -> str:
    return " ".join(
        re.findall(r"\w+", normalize_inline(value).lower(), flags=re.UNICODE)
    )


def word_count(value: str) -> int:
    return len(re.findall(r"\w+", value, flags=re.UNICODE))


def extract_title(soup: BeautifulSoup) -> str | None:
    for attrs in (
        {"property": "og:title"},
        {"name": "twitter:title"},
        {"name": "title"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            title = normalize_inline(tag["content"])
            if title:
                return title
    heading = soup.find("h1")
    if heading:
        title = normalize_inline(heading.get_text(" ", strip=True))
        if title:
            return title
    tag = soup.find("title")
    return normalize_inline(tag.get_text(" ", strip=True)) or None if tag else None


def declared_page_url(soup: BeautifulSoup, requested_url: str | None) -> str | None:
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and canonical.get("href"):
        return urljoin(requested_url or "", str(canonical["href"]).strip())
    og_url = soup.find("meta", attrs={"property": "og:url"})
    if og_url and og_url.get("content"):
        return urljoin(requested_url or "", str(og_url["content"]).strip())
    return None


def declares_homepage_for_article(
    soup: BeautifulSoup, requested_url: str | None
) -> bool:
    return declared_redirect_status(soup, requested_url) == "redirect_home"


def declared_redirect_status(
    soup: BeautifulSoup, requested_url: str | None
) -> str | None:
    if not requested_url:
        return None
    declared = declared_page_url(soup, requested_url)
    if not declared:
        return None
    requested_parts = [part for part in urlsplit(requested_url).path.split("/") if part]
    declared_parts = [part for part in urlsplit(declared).path.split("/") if part]
    if requested_parts and not declared_parts:
        return "redirect_home"
    if (
        len(requested_parts) >= 2
        and len(declared_parts) < len(requested_parts)
        and requested_parts[: len(declared_parts)] == declared_parts
    ):
        return "redirect_listing"
    return None


def looks_like_error_page(title: str | None, body: str) -> bool:
    text = normalize_inline(f"{title or ''} {body[:2500]}")
    if re.match(
        r"^(access\s*denied|forbidden|request blocked|service unavailable|"
        r"page (was )?not found|404\b|nosuchkey\b)",
        text,
        re.I,
    ):
        return True
    return word_count(text) < 100 and bool(ERROR_PAGE_RE.search(text))


def node_context(node: Any) -> str:
    values = [str(getattr(node, "name", "") or "")]
    for key in ("id", "class", "role", "itemprop", "data-component", "data-testid"):
        value = node.get(key)
        if isinstance(value, list):
            value = " ".join(value)
        if value:
            values.append(str(value))
    return " ".join(values)


def node_is_noise(node: Any, boundary: Any) -> bool:
    current = node
    while current is not None:
        name = str(getattr(current, "name", "") or "").lower()
        if name in {"nav", "aside", "footer", "header", "form"}:
            return True
        if hasattr(current, "get"):
            if str(current.get("aria-hidden") or "").lower() == "true":
                return True
            role = str(current.get("role") or "").lower()
            if role in {"navigation", "complementary", "banner", "contentinfo"}:
                return True
            if current is not boundary and NEGATIVE_CONTAINER_RE.search(
                node_context(current)
            ):
                return True
        if current is boundary:
            break
        current = getattr(current, "parent", None)
    return False


def link_density(node: Any) -> float:
    text = normalize_inline(node.get_text(" ", strip=True))
    if not text:
        return 1.0
    linked = sum(
        len(normalize_inline(tag.get_text(" ", strip=True)))
        for tag in node.find_all("a")
    )
    return min(linked / len(text), 1.0)


def is_noise_block(text: str) -> bool:
    if not text or NOISE_BLOCK_RE.fullmatch(text):
        return True
    if INLINE_PROMO_RE.match(text) and len(text) < 220:
        return True
    if re.match(r"^your browser does not support inline frames\b", text, re.I):
        return True
    if re.fullmatch(r"https?://\S+|[|/·•\-\s]+", text):
        return True
    if re.match(r"^©\s*\d{0,4}\s*copyright\b", text, re.I):
        return True
    return False


def looks_like_headline_block(text: str) -> bool:
    """Identify short link-headline blocks that commonly trail the real story."""
    words = word_count(text)
    punctuation = len(re.findall(r"[.!?।۔؟。！？]", text))
    ends_as_prose = text.rstrip().endswith((".", "!", "।", "۔", "。", "！"))
    return (
        not ends_as_prose
        and 35 <= len(text) <= 180
        and 5 <= words <= 28
        and punctuation <= 2
    )


def blocks_from_node(root: Any) -> tuple[list[str], float]:
    if root is None:
        return [], 1.0
    blocks: list[str] = []
    seen: set[str] = set()
    linked_chars = 0
    total_chars = 0
    tags = list(root.find_all(["p", "blockquote", "h2", "h3", "li"]))
    if getattr(root, "name", None) in {"p", "blockquote"}:
        tags.insert(0, root)
    for tag in tags:
        if tag.name == "blockquote" and tag.find("p"):
            continue
        if node_is_noise(tag, root):
            continue
        text = normalize_inline(tag.get_text(" ", strip=True))
        minimum = 90 if tag.name == "li" else MIN_BLOCK_CHARS
        density = link_density(tag)
        key = normalized_key(text)
        if (
            len(text) < minimum
            or not key
            or key in seen
            or is_noise_block(text)
            or (density > 0.65 and len(text) < 300)
        ):
            continue
        seen.add(key)
        blocks.append(text)
        total_chars += len(text)
        linked_chars += int(len(text) * density)
    if not blocks:
        for raw_line in root.get_text("\n", strip=True).splitlines():
            text = normalize_inline(raw_line)
            key = normalized_key(text)
            if (
                len(text) >= 40
                and key
                and key not in seen
                and not is_noise_block(text)
            ):
                seen.add(key)
                blocks.append(text)
        total_chars = sum(map(len, blocks))
    return blocks, linked_chars / max(total_chars, 1)


def candidate_from_node(
    node: Any, title: str | None, method: str
) -> dict[str, Any] | None:
    blocks, density = blocks_from_node(node)
    body = "\n\n".join(blocks)
    if len(body) < 20:
        return None
    structure = min(len(body), 12_000) + 140 * min(len(blocks), 20)
    structure -= int(density * 5000)
    if getattr(node, "name", None) == "article":
        structure += 1000
    if str(node.get("itemprop") or "").lower() == "articlebody":
        structure += 1200
    return {
        "title": title,
        "body": body,
        "method": method,
        "link_density": density,
        "structure_score": structure,
    }


def selectors_for_domain(url: str | None) -> Iterable[str]:
    host = urlsplit(url or "").hostname or ""
    host = host.lower().removeprefix("www.")
    for domain, selectors in DOMAIN_SELECTORS.items():
        if host == domain or host.endswith("." + domain):
            return selectors
    return ()


def dom_candidates(
    soup: BeautifulSoup, url: str | None, title: str | None
) -> list[dict[str, Any]]:
    nodes: list[tuple[Any, str]] = []
    seen_nodes: set[int] = set()

    def add(node: Any, method: str) -> None:
        if node is None or id(node) in seen_nodes:
            return
        seen_nodes.add(id(node))
        nodes.append((node, method))

    for selector in selectors_for_domain(url):
        for node in soup.select(selector):
            add(node, "dom.domain")
    for node in soup.select('[itemprop="articleBody"]'):
        add(node, "dom.itemprop")
    for node in soup.find_all("article"):
        add(node, "dom.article")
    for node in soup.select('main, [role="main"]'):
        add(node, "dom.main")
    for node in soup.find_all(["div", "section"]):
        context = node_context(node)
        if POSITIVE_CONTAINER_RE.search(context) and not NEGATIVE_CONTAINER_RE.search(
            context
        ):
            add(node, "dom.heuristic")
    add(soup.body, "dom.body")

    candidates = []
    for node, method in nodes:
        candidate = candidate_from_node(node, title, method)
        if candidate:
            candidates.append(candidate)
    candidates.sort(key=lambda value: value.get("structure_score", 0), reverse=True)
    return candidates[:10]


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def json_type_names(value: Any) -> set[str]:
    values = value if isinstance(value, list) else [value]
    return {
        item.rsplit("/", 1)[-1].rsplit("#", 1)[-1].lower()
        for item in values
        if isinstance(item, str)
    }


def coerce_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n\n".join(filter(None, (coerce_json_text(item) for item in value)))
    if not isinstance(value, dict):
        return ""
    for key in ("html", "rendered", "value"):
        if isinstance(value.get(key), str) and len(value[key]) >= 25:
            return value[key]
    parts = []
    for key in ("text", "content", "children", "nodes", "blocks"):
        if key in value:
            text = coerce_json_text(value[key])
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def body_from_json(value: Any) -> str:
    raw = coerce_json_text(value)
    if not raw:
        return ""
    if re.search(r"<(?:p|div|br|article|section|blockquote)\b", raw, re.I):
        fragment = BeautifulSoup(raw, "lxml")
        blocks, _ = blocks_from_node(fragment.body or fragment)
        if blocks:
            return "\n\n".join(blocks)
        raw = fragment.get_text("\n", strip=True)
    lines = [normalize_inline(line) for line in re.split(r"\n\s*\n|\r?\n", raw)]
    return "\n\n".join(line for line in lines if line)


def author_name(value: Any) -> str | None:
    if isinstance(value, str):
        return normalize_inline(value) or None
    if isinstance(value, dict):
        return normalize_inline(value.get("name") or value.get("@id")) or None
    if isinstance(value, list):
        names = [name for name in (author_name(item) for item in value) if name]
        return ", ".join(names) or None
    return None


def embedded_json_candidates(
    soup: BeautifulSoup, page_title: str | None
) -> list[dict[str, Any]]:
    candidates = []
    seen: set[str] = set()
    for script in soup.find_all("script"):
        script_type = str(script.get("type") or "").lower()
        script_id = str(script.get("id") or "")
        is_json_ld = "ld+json" in script_type
        if not (is_json_ld or script_type == "application/json" or script_id == "__NEXT_DATA__"):
            continue
        raw = script.string or script.get_text("", strip=False)
        if not raw or len(raw) > 8_000_000:
            continue
        raw = raw.strip().removeprefix("<!--").removesuffix("-->").strip()
        raw = raw.removeprefix("<![CDATA[").removesuffix("]]>").strip().rstrip(";")
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        for obj in walk_json(payload):
            is_article = bool(json_type_names(obj.get("@type")) & ARTICLE_TYPES)
            body_key = "articleBody" if "articleBody" in obj else None
            if body_key is None and is_article:
                body_key = next((key for key in ("body", "content") if key in obj), None)
            if body_key is None:
                continue
            body = body_from_json(obj[body_key])
            key = normalized_key(body)
            if len(body) < 20 or not key or key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "title": normalize_inline(
                        obj.get("headline")
                        or obj.get("name")
                        or obj.get("title")
                        or page_title
                    )
                    or None,
                    "body": body,
                    "method": ("jsonld." if is_json_ld else "json.embedded.")
                    + body_key,
                    "date": obj.get("datePublished") or obj.get("dateCreated"),
                    "author": author_name(obj.get("author")),
                    "language": obj.get("inLanguage"),
                    "link_density": 0.0,
                }
            )
    return candidates


def trafilatura_candidates(content: str, url: str | None) -> list[dict[str, Any]]:
    passes = (
        ("trafilatura.precision", {"favor_precision": True}),
        ("trafilatura.default", {}),
        ("trafilatura.recall", {"favor_recall": True}),
    )
    candidates = []
    for method, options in passes:
        try:
            raw = trafilatura.extract(
                content,
                url=url,
                output_format="json",
                with_metadata=True,
                include_comments=False,
                include_tables=False,
                include_links=False,
                deduplicate=True,
                **options,
            )
            data = json.loads(raw) if raw else None
        except (TypeError, ValueError, json.JSONDecodeError):
            data = None
        if not data or not normalize_inline(data.get("text")):
            continue
        candidates.append(
            {
                "title": normalize_inline(data.get("title")) or None,
                "body": str(data["text"]).strip(),
                "method": method,
                "date": data.get("date"),
                "author": data.get("author"),
                "language": data.get("language"),
                "link_density": 0.0,
            }
        )
    return candidates


def clean_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    result = dict(candidate)
    raw_body = str(result.get("body") or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block.strip() for block in re.split(r"\n\s*\n", raw_body) if block.strip()]
    if len(blocks) <= 1 and raw_body.count("\n") >= 2:
        blocks = [block.strip() for block in raw_body.splitlines() if block.strip()]
    title_key = normalized_key(result.get("title"))
    seen: list[str] = []
    cleaned: list[str] = []
    kept_chars = 0
    found_tail_boundary = False
    for block in blocks:
        text = normalize_inline(block)
        key = normalized_key(text)
        if kept_chars >= MIN_BODY_CHARS and (
            HARD_TAIL_RE.match(text) or NOISE_BLOCK_RE.fullmatch(text)
        ):
            found_tail_boundary = True
            break
        if not key or is_noise_block(text):
            continue
        if title_key and len(text) < max(len(str(result.get("title") or "")) * 1.35, 180):
            if key == title_key or SequenceMatcher(None, key, title_key).ratio() >= 0.93:
                continue
        duplicate = key in seen
        if not duplicate and len(key) >= 120:
            duplicate = any(
                len(previous) >= 120
                and SequenceMatcher(None, key, previous).ratio() >= 0.965
                for previous in seen[-30:]
            )
        if duplicate:
            continue
        seen.append(key)
        cleaned.append(text)
        kept_chars += len(text)
    headline_start = len(cleaned)
    while headline_start > 0 and looks_like_headline_block(cleaned[headline_start - 1]):
        headline_start -= 1
    headline_count = len(cleaned) - headline_start
    minimum_headlines = 4 if found_tail_boundary else 5
    minimum_article_chars = MIN_BODY_CHARS if found_tail_boundary else 500
    if headline_count >= minimum_headlines:
        article_chars = sum(len(block) for block in cleaned[:headline_start])
        if article_chars >= minimum_article_chars:
            cleaned = cleaned[:headline_start]
    result["body"] = "\n\n".join(cleaned)
    return result


def chrome_ratio(body: str) -> float:
    blocks = [normalize_inline(block) for block in re.split(r"\n\s*\n", body) if block.strip()]
    if not blocks:
        return 1.0
    chrome = sum(
        1
        for block in blocks
        if is_noise_block(block)
        or (len(block) < 35 and not re.search(r"[.!?।۔؟。！？]", block))
    )
    return chrome / len(blocks)


def candidate_score(candidate: dict[str, Any]) -> float:
    body = str(candidate.get("body") or "")
    method = str(candidate.get("method") or "")
    words = word_count(body)
    blocks = [block for block in re.split(r"\n\s*\n", body) if len(block.strip()) >= 40]
    density = float(candidate.get("link_density") or 0.0)
    score = min(len(body), 6000) + 4 * min(words, 1200) + 45 * min(len(blocks), 16)
    if method.startswith("jsonld.articleBody"):
        score += 800
    elif method.startswith("json.embedded.articleBody"):
        score += 650
    elif method == "dom.domain":
        score += 500
    elif method in {"dom.itemprop", "dom.article"}:
        score += 380
    elif method == "trafilatura.precision":
        score += 350
    elif method in {"trafilatura.default", "dom.main"}:
        score += 180
    elif method == "trafilatura.recall":
        score -= 80
    score -= int(density * 2600)
    score -= int(chrome_ratio(body) * 1500)
    score += min(float(candidate.get("structure_score") or 0), 8000) * 0.04
    if len(body) < MIN_BODY_CHARS:
        score -= 500
    if words < MIN_BODY_WORDS:
        score -= 300
    if looks_like_error_page(candidate.get("title"), body):
        score -= 5000
    if len(body) >= 500 and not re.search(r"[.!?।۔؟。！？]", body):
        score -= 700
    return score


def method_family(method: Any) -> str:
    value = str(method or "")
    if value.startswith("trafilatura"):
        return "trafilatura"
    if value.startswith("json"):
        return "json"
    if value.startswith("dom"):
        return "dom"
    return value.split(".", 1)[0] or "unknown"


def text_shingles(text: str, width: int = 5) -> set[str]:
    tokens = re.findall(r"\w+", text.lower(), flags=re.UNICODE)[:2400]
    if len(tokens) < width:
        return set(tokens)
    return {" ".join(tokens[index : index + width]) for index in range(len(tokens) - width + 1)}


def text_agreement(left: str, right: str) -> float:
    a = text_shingles(left)
    b = text_shingles(right)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    containment = overlap / max(min(len(a), len(b)), 1)
    jaccard = overlap / max(len(a | b), 1)
    return 0.75 * containment + 0.25 * jaccard


def merge_exact_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = normalized_key(candidate.get("body"))
        if not key:
            continue
        current = by_key.get(key)
        if current is None:
            current = dict(candidate)
            current["supporting_methods"] = [candidate.get("method")]
            by_key[key] = current
            merged.append(current)
            continue
        method = candidate.get("method")
        if method not in current["supporting_methods"]:
            current["supporting_methods"].append(method)
        if candidate_score(candidate) > candidate_score(current):
            support = current["supporting_methods"]
            metadata = {key: current.get(key) for key in ("title", "date", "author", "language")}
            current.clear()
            current.update(candidate)
            current["supporting_methods"] = support
            for field, value in metadata.items():
                if not current.get(field) and value:
                    current[field] = value
    return merged


def score_with_consensus(
    candidate: dict[str, Any], candidates: list[dict[str, Any]]
) -> tuple[float, float]:
    family = method_family(candidate.get("method"))
    by_family: dict[str, float] = {}
    for other in candidates:
        if other is candidate:
            continue
        other_family = method_family(other.get("method"))
        if other_family == family:
            continue
        agreement = text_agreement(str(candidate.get("body") or ""), str(other.get("body") or ""))
        by_family[other_family] = max(by_family.get(other_family, 0.0), agreement)
    methods = candidate.get("supporting_methods") or [candidate.get("method")]
    families = {method_family(method) for method in methods}
    bonus = sum(max(value - 0.25, 0) * 700 for value in by_family.values())
    bonus += max(len(methods) - 1, 0) * 70
    bonus += max(len(families) - 1, 0) * 180
    return candidate_score(candidate) + bonus, max(by_family.values(), default=0.0)


def extraction_confidence(candidate: dict[str, Any], agreement: float) -> float:
    body = str(candidate.get("body") or "")
    blocks = [block for block in re.split(r"\n\s*\n", body) if len(block.strip()) >= 40]
    methods = candidate.get("supporting_methods") or [candidate.get("method")]
    families = {method_family(method) for method in methods}
    confidence = 0.22
    confidence += 0.14 if len(body) >= MIN_BODY_CHARS else 0
    confidence += 0.12 if len(body) >= 600 else 0
    confidence += 0.10 if word_count(body) >= 120 else 0
    confidence += 0.08 if len(blocks) >= 3 else 0
    confidence += min(agreement, 0.8) * 0.22
    if str(candidate.get("method") or "").startswith(("jsonld.articleBody", "dom.domain", "dom.itemprop")):
        confidence += 0.10
    if len(families) >= 2:
        confidence += 0.14
    confidence -= min(float(candidate.get("link_density") or 0.0), 1.0) * 0.25
    confidence -= min(chrome_ratio(body), 1.0) * 0.25
    if looks_like_error_page(candidate.get("title"), body):
        confidence = 0.0
    return round(max(0.0, min(confidence, 0.99)), 3)


def extract_article(content: str, url: str | None = None) -> dict[str, Any]:
    soup = BeautifulSoup(content, "lxml")
    canonical_url = declared_page_url(soup, url)
    redirect_status = declared_redirect_status(soup, url)
    if redirect_status:
        return {
            "status": redirect_status,
            "title": extract_title(soup),
            "body": "",
            "method": None,
            "confidence": 0.0,
            "word_count": 0,
            "char_count": 0,
            "candidate_count": 0,
            "supporting_methods": [],
            "canonical_url": canonical_url,
        }

    title = extract_title(soup)
    candidates = trafilatura_candidates(content, url)
    candidates.extend(embedded_json_candidates(soup, title))
    candidates.extend(dom_candidates(soup, url, title))
    cleaned = [clean_candidate(candidate) for candidate in candidates]
    cleaned = [candidate for candidate in cleaned if candidate.get("body")]
    cleaned = merge_exact_candidates(cleaned)
    if not cleaned:
        return {
            "status": "extract_empty",
            "title": title,
            "body": "",
            "method": None,
            "confidence": 0.0,
            "word_count": 0,
            "char_count": 0,
            "candidate_count": 0,
            "supporting_methods": [],
            "canonical_url": canonical_url,
        }

    scored = []
    for candidate in cleaned:
        score, agreement = score_with_consensus(candidate, cleaned)
        candidate["score"] = score
        candidate["confidence"] = extraction_confidence(candidate, agreement)
        scored.append(candidate)
    best = max(scored, key=lambda candidate: candidate["score"])
    body = str(best.get("body") or "")
    words = word_count(body)
    if PARKED_DOMAIN_RE.search(f"{best.get('title') or ''} {body[:1200]}"):
        status = "domain_parked"
        body = ""
        words = 0
    elif looks_like_error_page(best.get("title"), body):
        status = "extract_empty"
        body = ""
        words = 0
    elif (
        len(body) < MIN_BODY_CHARS
        or words < MIN_BODY_WORDS
        or float(best.get("confidence") or 0) < 0.42
        or chrome_ratio(body) >= 0.35
    ):
        status = "extract_weak"
    else:
        status = "ok"
    return {
        "status": status,
        "title": best.get("title") or title,
        "body": body,
        "method": best.get("method"),
        "confidence": best.get("confidence"),
        "word_count": words,
        "char_count": len(body),
        "candidate_count": len(cleaned),
        "supporting_methods": best.get("supporting_methods") or [best.get("method")],
        "canonical_url": canonical_url,
        "date": best.get("date"),
        "author": best.get("author"),
        "language": best.get("language"),
    }


def extract_article_text(content: str, url: str | None = None) -> tuple[str, str]:
    """Compatibility wrapper for callers that only need title and body."""
    result = extract_article(content, url=url)
    return str(result.get("title") or ""), str(result.get("body") or "")
