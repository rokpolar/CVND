"""Conservative keys and schemas shared by district-level pipeline steps.

The normalizer deliberately does not apply fuzzy matching, transliteration, or
administrative-history changes.  Those operations can turn two real districts
into one key, so they belong in the explicit name crosswalk instead.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import quote, unquote


EVENT_DISTRICT_COLUMNS = [
    "event_district_id",
    "event_id",
    "source_record_id",
    "state",
    "district",
    "start_date",
    "end_date",
    "date_precision",
    "district_source",
    "aoi_level",
    "aoi_match_status",
]

COVARIATE_COLUMNS = [
    "state",
    "district",
    "census_district_code",
    "total_population",
    "urban_population",
    "rural_population",
    "urban_population_share",
    "census_year",
    "source",
    "match_status",
]

# These aliases only repair established spelling/label variants.  District
# names are intentionally not included: district changes and spelling changes
# must be recorded in data/raw/district_name_crosswalk.csv.
STATE_ALIASES = {
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "nct of delhi": "Delhi",
    "new delhi": "Delhi",
    "newdelhi": "Delhi",
    "jammu & kashmir": "Jammu and Kashmir",
    "jammu and kashmir": "Jammu and Kashmir",
    "jammu kashmir": "Jammu and Kashmir",
    "j & k": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "uttaranchal": "Uttarakhand",
}

_CANONICAL_STATE_NAMES = {
    name.casefold(): name
    for name in (
        "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
        "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
        "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Lakshadweep",
        "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
        "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim",
        "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
        "West Bengal", "Andaman and Nicobar Islands", "Dadra and Nagar Haveli",
        "Daman and Diu", "Dadra and Nagar Haveli and Daman and Diu",
    )
}


# Closed status vocabularies shared by every district step. resolve_aoi only
# ever writes "matched"; a registry "pending"/"unresolved" is not a match.
AOI_MATCHED = frozenset({"matched"})
SATELLITE_OBSERVED = frozenset({"observed"})

_BLANK_KEYS = {"", "nan", "none", "<na>", "nat"}


def analysis_key(row: Any) -> str:
    """Return the event-district key, or the parent event ID when it is blank.

    This is the only key helper: Track A/B caches, H5/NPZ file stems, the merge
    and the area table must agree on it exactly.
    """

    value = row.get("event_district_id") if hasattr(row, "get") else None
    if value is not None and str(value).strip().casefold() not in _BLANK_KEYS:
        return str(value)
    return str(row.get("event_id"))


def cache_stem(key: str) -> str:
    """Filesystem-safe, reversible file stem for an analysis key.

    District keys contain ``::``, which Windows rejects in file names. Percent-
    encoding every reserved character keeps H5/NPZ names portable.
    """

    return quote(str(key), safe="")


def key_from_stem(stem: str) -> str:
    return unquote(stem)


def normalize_name(value: Any) -> str:
    """Return a conservative comparison key for a geographic name.

    Only Unicode compatibility normalization, surrounding whitespace removal,
    internal whitespace compression, and case folding are applied.  Missing
    values return the empty string.  Punctuation and spelling are preserved.
    """

    if value is None:
        return ""
    try:
        # Avoid importing pandas merely to recognize its NA scalar.  The
        # string representations below also cover Excel's common NA markers.
        if value != value:  # NaN
            return ""
    except Exception:
        pass
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text or text.casefold() in {"nan", "none", "na", "n/a", "null", "<na>"}:
        return ""
    return re.sub(r"\s+", " ", text).casefold()


def normalize_state_name(value: Any) -> str:
    """Return a display-ready canonical state name for established aliases."""

    key = normalize_name(value)
    return _CANONICAL_STATE_NAMES.get(key, STATE_ALIASES.get(key, str(value).strip() if key else ""))


def district_key(value: Any) -> str:
    """Return a stable district component suitable for IDs and joins."""

    return normalize_name(value)


def make_event_district_id(event_id: Any, district: Any) -> str:
    """Build a deterministic, human-readable event × district identifier."""

    event = str(event_id).strip()
    district_part = district_key(district) or "district_missing"
    # Percent-encoding keeps the key readable while preserving distinctions
    # such as ``A B`` versus ``A_B`` that a whitespace-to-underscore slug would
    # collapse.  The same normalized input always produces the same ID.
    return f"{event}::{quote(district_part, safe='')}"


def is_missing_name(value: Any) -> bool:
    return not bool(normalize_name(value))
