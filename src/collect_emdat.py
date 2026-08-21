#!/usr/bin/env python3
"""Download EM-DAT records through the official GraphQL API.

The API returns snake_case fields. This collector writes a portal-compatible
staging CSV for comparison with the canonical official workbook. It never
promotes or replaces ``EM-DAT-BASE.xlsx`` automatically.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cvnd_layout import ROOT, data_path


API_URL = "https://api.emdat.be/v1"
DEFAULT_METADATA = data_path("emdat_meta")

API_FIELDS = (
    "disno",
    "classif_key",
    "group",
    "subgroup",
    "type",
    "subtype",
    "external_ids",
    "name",
    "iso",
    "country",
    "subregion",
    "region",
    "location",
    "origin",
    "associated_types",
    "ofda_response",
    "appeal",
    "declaration",
    "aid_contribution",
    "magnitude",
    "magnitude_scale",
    "latitude",
    "longitude",
    "river_basin",
    "start_year",
    "start_month",
    "start_day",
    "end_year",
    "end_month",
    "end_day",
    "total_deaths",
    "no_injured",
    "no_affected",
    "no_homeless",
    "total_affected",
    "reconstr_dam",
    "reconstr_dam_adj",
    "insur_dam",
    "insur_dam_adj",
    "total_dam",
    "total_dam_adj",
    "cpi",
    "admin_units",
    "entry_date",
    "last_update",
)

# Keep this order identical to the existing EM-DAT portal export. Fields that
# are not exposed by the documented API are retained as blank compatibility
# columns rather than silently changing the downstream schema.
PORTAL_COLUMNS: tuple[tuple[str, str | None], ...] = (
    ("DisNo.", "disno"),
    ("Historic", None),
    ("Classification Key", "classif_key"),
    ("Disaster Group", "group"),
    ("Disaster Subgroup", "subgroup"),
    ("Disaster Type", "type"),
    ("Disaster Subtype", "subtype"),
    ("External IDs", "external_ids"),
    ("Event Name", "name"),
    ("ISO", "iso"),
    ("Country", "country"),
    ("Subregion", "subregion"),
    ("Region", "region"),
    ("Location", "location"),
    ("Origin", "origin"),
    ("Associated Types", "associated_types"),
    ("OFDA/BHA Response", "ofda_response"),
    ("Appeal", "appeal"),
    ("Declaration", "declaration"),
    ("AID Contribution ('000 US$)", "aid_contribution"),
    ("Magnitude", "magnitude"),
    ("Magnitude Scale", "magnitude_scale"),
    ("Latitude", "latitude"),
    ("Longitude", "longitude"),
    ("River Basin", "river_basin"),
    ("Start Year", "start_year"),
    ("Start Month", "start_month"),
    ("Start Day", "start_day"),
    ("End Year", "end_year"),
    ("End Month", "end_month"),
    ("End Day", "end_day"),
    ("Total Deaths", "total_deaths"),
    ("No. Injured", "no_injured"),
    ("No. Affected", "no_affected"),
    ("No. Homeless", "no_homeless"),
    ("Total Affected", "total_affected"),
    ("Reconstruction Costs ('000 US$)", "reconstr_dam"),
    ("Reconstruction Costs, Adjusted ('000 US$)", "reconstr_dam_adj"),
    ("Insured Damage ('000 US$)", "insur_dam"),
    ("Insured Damage, Adjusted ('000 US$)", "insur_dam_adj"),
    ("Total Damage ('000 US$)", "total_dam"),
    ("Total Damage, Adjusted ('000 US$)", "total_dam_adj"),
    ("CPI", "cpi"),
    ("Admin Units", "admin_units"),
    ("GADM Admin Units", None),
    ("Entry Date", "entry_date"),
    ("Last Update", "last_update"),
)


def _graphql_string(value: str) -> str:
    """Return a JSON-escaped string, which is also a GraphQL string literal."""
    return json.dumps(value, ensure_ascii=True)


def build_query(
    from_year: int,
    to_year: int,
    iso_codes: list[str],
    classifications: list[str],
    include_historic: bool,
    limit: int,
    offset: int,
) -> str:
    """Build one documented public_emdat paginated query."""
    if from_year > to_year:
        raise ValueError("from_year must be less than or equal to to_year")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset cannot be negative")
    normalized_iso = [code.upper() for code in iso_codes]
    if not normalized_iso or any(not re.fullmatch(r"[A-Z]{3}", code) for code in normalized_iso):
        raise ValueError("ISO filters must be three-letter country codes, for example IND")
    if not classifications or any(not re.fullmatch(r"[A-Za-z0-9_*?-]+", item) for item in classifications):
        raise ValueError("classification filters contain an unsupported character")

    iso_literal = ", ".join(_graphql_string(code) for code in normalized_iso)
    classif_literal = ", ".join(_graphql_string(item) for item in classifications)
    fields = "\n        ".join(API_FIELDS)
    historic = "true" if include_historic else "false"
    return f"""query CvndEmdat {{
  api_version
  public_emdat(
    cursor: {{limit: {limit}, offset: {offset}}}
    filters: {{
      from: {from_year}
      to: {to_year}
      iso: [{iso_literal}]
      classif: [{classif_literal}]
      include_hist: {historic}
    }}
  ) {{
    total_available
    info {{ timestamp version filters cursor }}
    data {{
        {fields}
    }}
  }}
}}"""


def parse_payload(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Validate a raw GraphQL response and return API version and result."""
    if payload.get("errors"):
        messages = "; ".join(str(item.get("message", item)) for item in payload["errors"])
        raise RuntimeError(f"EM-DAT GraphQL error: {messages}")
    root = payload.get("data", payload)
    if not isinstance(root, dict) or not isinstance(root.get("public_emdat"), dict):
        raise RuntimeError("EM-DAT response does not contain data.public_emdat")
    return root.get("api_version"), root["public_emdat"]


def fetch_all(
    fetch_page: Callable[[str], dict[str, Any]],
    *,
    from_year: int,
    to_year: int,
    iso_codes: list[str],
    classifications: list[str],
    include_historic: bool,
    page_size: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch all pages and return records plus API provenance."""
    rows: list[dict[str, Any]] = []
    offset = 0
    total_available: int | None = None
    api_version: str | None = None
    last_info: dict[str, Any] = {}

    while True:
        query = build_query(
            from_year,
            to_year,
            iso_codes,
            classifications,
            include_historic,
            page_size,
            offset,
        )
        page_api_version, result = parse_payload(fetch_page(query))
        api_version = page_api_version or api_version
        page = result.get("data") or []
        if not isinstance(page, list):
            raise RuntimeError("EM-DAT public_emdat.data is not a list")
        if any(not isinstance(row, dict) for row in page):
            raise RuntimeError("EM-DAT returned a non-object record")

        if total_available is None:
            raw_total = result.get("total_available")
            total_available = int(raw_total) if raw_total is not None else None
        if isinstance(result.get("info"), dict):
            last_info = result["info"]
        rows.extend(page)

        if not page or len(page) < page_size:
            break
        if total_available is not None and len(rows) >= total_available:
            break
        offset += len(page)

    metadata = {
        "api_version": api_version,
        "dataset_version": last_info.get("version"),
        "api_timestamp": last_info.get("timestamp"),
        "api_processed_filters": last_info.get("filters"),
        "api_last_cursor": last_info.get("cursor"),
        "total_available": total_available,
        "rows_fetched": len(rows),
    }
    return rows, metadata


def serialize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def portal_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        heading: serialize_cell(row.get(api_field)) if api_field else ""
        for heading, api_field in PORTAL_COLUMNS
    }


def _atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as handle:
            tmp_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=[heading for heading, _ in PORTAL_COLUMNS])
            writer.writeheader()
            writer.writerows(portal_row(row) for row in rows)
        os.replace(tmp_name, path)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            tmp_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _load_api_key() -> str:
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv(ROOT / ".env")
    api_key = os.getenv("EMDAT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "EMDAT_API_KEY is missing. Copy .env.example to .env and add your EM-DAT API key."
        )
    return api_key


def _requests_fetcher(api_key: str, timeout: float) -> Callable[[str], dict[str, Any]]:
    try:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
    except ImportError as exc:
        raise RuntimeError("Install project dependencies with: pip install -r requirements.txt") from exc

    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))

    def fetch(query: str) -> dict[str, Any]:
        response = session.get(
            API_URL,
            json={"query": query},
            headers={"Authorization": api_key, "Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("EM-DAT returned a non-object JSON response")
        return payload

    return fetch


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-year", type=int, default=2015)
    parser.add_argument("--to-year", type=int, default=2026)
    parser.add_argument("--iso", nargs="+", default=["IND"], help="ISO-3 codes (default: IND)")
    parser.add_argument(
        "--classif",
        nargs="+",
        default=["nat-hyd-flo-*"],
        help="EM-DAT classification filters (default: nat-hyd-flo-*)",
    )
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--exclude-historic", action="store_true")
    parser.add_argument("--output", type=Path, default=data_path("emdat_api_csv"))
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing output files")
    parser.add_argument("--dry-run", action="store_true", help="Print the first query without contacting EM-DAT")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        first_query = build_query(
            args.from_year,
            args.to_year,
            args.iso,
            args.classif,
            not args.exclude_historic,
            args.page_size,
            0,
        )
        if args.dry_run:
            print(first_query)
            return 0

        existing = [path for path in (args.output, args.metadata) if path.exists()]
        if existing and not args.overwrite:
            names = ", ".join(str(path) for path in existing)
            raise RuntimeError(f"output already exists: {names}; pass --overwrite to replace it")

        api_key = _load_api_key()
        rows, api_meta = fetch_all(
            _requests_fetcher(api_key, args.timeout),
            from_year=args.from_year,
            to_year=args.to_year,
            iso_codes=args.iso,
            classifications=args.classif,
            include_historic=not args.exclude_historic,
            page_size=args.page_size,
        )
        _atomic_write_csv(args.output, rows)
        digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
        metadata = {
            "source": "EM-DAT public GraphQL API",
            "endpoint": API_URL,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "filters": {
                "from": args.from_year,
                "to": args.to_year,
                "iso": [item.upper() for item in args.iso],
                "classif": args.classif,
                "include_hist": not args.exclude_historic,
            },
            "page_size": args.page_size,
            "output": str(args.output),
            "output_sha256": digest,
            **api_meta,
        }
        _atomic_write_json(args.metadata, metadata)
        print(f"Wrote {len(rows)} rows to {args.output}")
        print(f"Wrote provenance to {args.metadata}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
