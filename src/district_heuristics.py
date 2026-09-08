"""Small multilingual flood heuristic used by the district article pipeline.

The former state-event classifier bundled this deterministic filter with an
optional LLM batch workflow.  District collection only needs the bounded,
body-quality-aware heuristic, so it lives here without the state-event LLM
machinery.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from typing import Sequence


TEXT_CHAR_LIMIT = 4_000
TITLE_CHAR_LIMIT = 500
LEAD_CHAR_LIMIT = 1_000
KEYWORD_CONTEXT_RADIUS = 700
MAX_KEYWORD_CONTEXTS = 2
PRIMARY_BODY_STATUSES = frozenset({"ok"})
WEAK_BODY_STATUSES = frozenset({"extract_weak"})
ACCEPTED_BODY_STATUSES = PRIMARY_BODY_STATUSES | WEAK_BODY_STATUSES

FLOOD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "en": ("flash flood", "flash-flood", "floodwater", "flood water", "flooded", "flooding", "floods", "flood", "inundated", "inundation"),
    "ara": ("فيضان", "فيضانات", "سيول", "سيل"),
    "ben": ("বন্যা", "প্লাবন", "জলমগ্ন"),
    "guj": ("પૂરગ્રસ્ત", "પૂરની", "પૂર"),
    "hin": ("बाढ़", "बाढ", "जलमग्न", "सैलाब"),
    "kan": ("ಪ್ರವಾಹ", "ನೆರೆ", "ಜಲಾವೃತ"),
    "mal": ("വെള്ളപ്പൊക്കം", "പ്രളയം", "വെള്ളക്കെട്ട്"),
    "mar": ("पूरग्रस्त", "पुरामुळे", "महापूर", "जलमय", "पूर"),
    "nep": ("बाढी", "डुबान", "जलमग्न"),
    "ori": ("ବନ୍ୟାଜଳ", "ବନ୍ୟା", "ଜଳମଗ୍ନ"),
    "pan": ("ਹੜ੍ਹਾਂ", "ਹੜ੍ਹ", "ਹੜ"),
    "pus": ("سېلاب", "سیلاب"),
    "snd": ("ٻوڏ", "سيلاب", "سیلاب"),
    "tam": ("வெள்ளப்பெருக்கு", "வெள்ளம்", "நீரில் மூழ்க"),
    "tel": ("వరదలు", "వరద", "జలమయం"),
    "urd": ("سیلابی", "سیلاب", "طغیانی"),
}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _keyword_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    if re.fullmatch(r"[a-z0-9\- ]+", term):
        escaped = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return re.compile(escaped)


KEYWORD_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (language, term, _keyword_pattern(term))
    for language, terms in FLOOD_KEYWORDS.items()
    for term in (_normalize(item) for item in terms)
    if term
)


def keyword_occurrences(value: str) -> list[tuple[str, int, int]]:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    found: dict[str, tuple[int, int]] = {}
    for language, term, pattern in KEYWORD_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        label = f"{language}:{term}"
        span = (match.start(), match.end())
        if label not in found or span < found[label]:
            found[label] = span
    return [(label, *found[label]) for label in sorted(found, key=lambda item: (found[item][0], item))]


def build_context_excerpt(
    body_text: str,
    page_title: str | None,
    body_occurrences: Sequence[tuple[str, int, int]],
) -> str:
    sections: list[str] = []
    title = (page_title or "").strip()
    if title:
        sections.append(f"TITLE\n{title[:TITLE_CHAR_LIMIT]}")
    lead = body_text[:LEAD_CHAR_LIMIT].strip()
    if lead:
        sections.append(f"ARTICLE LEAD\n{lead}")
    search_text = unicodedata.normalize("NFKC", body_text).casefold()
    lead_labels = {label for label, _start, _end in keyword_occurrences(body_text[:LEAD_CHAR_LIMIT])}
    windows: list[tuple[int, int]] = []
    for label, start, end in body_occurrences:
        if label in lead_labels:
            continue
        window = (max(0, start - KEYWORD_CONTEXT_RADIUS), min(len(search_text), end + KEYWORD_CONTEXT_RADIUS))
        if windows and window[0] <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], window[1]))
        else:
            windows.append(window)
        if len(windows) >= MAX_KEYWORD_CONTEXTS:
            break
    for index, (start, end) in enumerate(windows, start=1):
        context = search_text[start:end].strip()
        if context:
            sections.append(f"MATCHED CONTEXT {index}\n{context}")
    return "\n\n".join(sections)[:TEXT_CHAR_LIMIT]


def classify_heuristic(
    document_status: str | None,
    body_text: str | None,
    page_title: str | None = None,
) -> tuple[str, str | None, list[str]]:
    """Return body-quality-aware status, bounded excerpt, and matched terms."""
    if document_status not in ACCEPTED_BODY_STATUSES or not body_text:
        return "no_body", None, []
    body_occurrences = keyword_occurrences(body_text)
    title_occurrences = keyword_occurrences(page_title or "")
    matches = sorted({label for label, _start, _end in itertools.chain(body_occurrences, title_occurrences)})
    excerpt = build_context_excerpt(body_text, page_title, body_occurrences)
    quality_prefix = "weak_" if document_status in WEAK_BODY_STATUSES else ""
    status = quality_prefix + ("keyword_match" if matches else "keyword_absent")
    return status, excerpt, matches
