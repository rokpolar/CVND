#!/usr/bin/env python3
"""Build the canonical state-event registry from the official EM-DAT workbook.

The official workbook is the only event source. Each output row represents one
unique (EM-DAT DisNo., Indian state/UT) pair. Different EM-DAT records are never
merged, and no manually curated seed events are added.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from cvnd_layout import data_path


SOURCE_SHEET = "EM-DAT Data"
INFO_SHEET = "EM-DAT Info"


@dataclass(frozen=True)
class StateProfile:
    bbox: str
    income_group: str

    @property
    def latitude(self) -> float:
        lon_min, lat_min, lon_max, lat_max = map(float, self.bbox.split(","))
        return round((lat_min + lat_max) / 2, 3)

    @property
    def longitude(self) -> float:
        lon_min, lat_min, lon_max, lat_max = map(float, self.bbox.split(","))
        return round((lon_min + lon_max) / 2, 3)


# Bboxes are state-level analysis extents. Income groups are retained only for
# compatibility with the existing downstream stratification.
STATE_PROFILES: dict[str, StateProfile] = {
    "Andhra Pradesh": StateProfile("77.0,12.5,84.8,19.9", "Middle"),
    "Arunachal Pradesh": StateProfile("91.5,26.5,97.4,29.5", "Low"),
    "Assam": StateProfile("89.7,24.1,96.0,27.9", "Low"),
    "Bihar": StateProfile("83.3,24.3,88.3,27.5", "Low"),
    "Chhattisgarh": StateProfile("80.2,17.8,84.4,24.1", "Low"),
    "Delhi": StateProfile("76.8,28.4,77.6,28.9", "High"),
    "Goa": StateProfile("73.6,14.9,74.4,15.8", "High"),
    "Gujarat": StateProfile("68.2,20.1,74.5,24.7", "High"),
    "Haryana": StateProfile("74.5,27.7,77.6,30.9", "High"),
    "Himachal Pradesh": StateProfile("75.6,30.4,79.0,33.2", "Low"),
    "Jammu and Kashmir": StateProfile("73.7,32.3,80.4,36.6", "Low"),
    "Jharkhand": StateProfile("83.3,21.9,87.9,25.3", "Low"),
    "Karnataka": StateProfile("74.1,11.6,78.6,18.5", "High"),
    "Kerala": StateProfile("74.8,8.3,77.6,12.8", "Middle"),
    "Madhya Pradesh": StateProfile("74.0,21.9,82.8,26.9", "Low"),
    "Maharashtra": StateProfile("72.6,15.6,80.9,22.0", "High"),
    "Manipur": StateProfile("93.0,23.8,94.8,25.7", "Low"),
    "Meghalaya": StateProfile("89.8,25.0,92.8,26.1", "Low"),
    "Mizoram": StateProfile("92.2,21.9,93.5,24.6", "Low"),
    "Nagaland": StateProfile("93.3,25.2,95.3,27.1", "Low"),
    "Odisha": StateProfile("81.4,17.8,87.5,22.6", "Low"),
    "Puducherry": StateProfile("79.5,11.8,79.9,12.1", "Middle"),
    "Punjab": StateProfile("73.9,29.5,76.9,32.5", "Middle"),
    "Rajasthan": StateProfile("69.5,23.0,78.3,30.2", "Low"),
    "Sikkim": StateProfile("88.0,27.1,88.9,28.1", "Low"),
    "Tamil Nadu": StateProfile("76.2,8.0,80.4,13.6", "Middle"),
    "Telangana": StateProfile("77.2,15.8,81.3,19.9", "High"),
    "Tripura": StateProfile("91.2,22.9,92.3,24.6", "Low"),
    "Uttar Pradesh": StateProfile("77.1,23.8,84.7,30.5", "Low"),
    "Uttarakhand": StateProfile("77.6,28.7,81.1,31.5", "Low"),
    "West Bengal": StateProfile("85.8,21.5,89.9,27.5", "Middle"),
}


# GADM 4.1 state/UT codes used in the supplied 2026 EM-DAT export.
GADM_STATE_BY_NUMBER = {
    1: "Andaman and Nicobar Islands",
    2: "Andhra Pradesh",
    3: "Arunachal Pradesh",
    4: "Assam",
    5: "Bihar",
    6: "Chandigarh",
    7: "Chhattisgarh",
    8: "Dadra and Nagar Haveli and Daman and Diu",
    9: "Dadra and Nagar Haveli and Daman and Diu",
    10: "Goa",
    11: "Gujarat",
    12: "Haryana",
    13: "Himachal Pradesh",
    14: "Jammu and Kashmir",
    15: "Jharkhand",
    16: "Karnataka",
    17: "Kerala",
    18: "Lakshadweep",
    19: "Madhya Pradesh",
    20: "Maharashtra",
    21: "Manipur",
    22: "Meghalaya",
    23: "Mizoram",
    24: "Nagaland",
    25: "Delhi",
    26: "Odisha",
    27: "Puducherry",
    28: "Punjab",
    29: "Rajasthan",
    30: "Sikkim",
    31: "Tamil Nadu",
    32: "Telangana",
    33: "Tripura",
    34: "Uttar Pradesh",
    35: "Uttarakhand",
    36: "West Bengal",
}


STATE_ALIASES = {
    "Orissa": "Odisha",
    "NCT of Delhi": "Delhi",
    "New Delhi": "Delhi",
    "NewDelhi": "Delhi",
    "Madyah Pradesh": "Madhya Pradesh",
    "Madhya Pardesh": "Madhya Pradesh",
    "Maharasthra": "Maharashtra",
    "Maharashtraa": "Maharashtra",
    "Uttarakand": "Uttarakhand",
    "Uttaranchal": "Uttarakhand",
    "Bengale": "West Bengal",
    "Jammu & Kashmir": "Jammu and Kashmir",
    "Jammu Kashmir": "Jammu and Kashmir",
    "J & K": "Jammu and Kashmir",
    "J&K": "Jammu and Kashmir",
    "Jammu region": "Jammu and Kashmir",
}


DERIVED_COLUMNS = [
    "event_id",
    "state",
    "district",
    "disaster_type",
    "start_date",
    "end_date",
    "date_precision",
    "lat",
    "lon",
    "bbox",
    "aoi_level",
    "income_group",
    "event_source",
    "source_record_id",
    "state_resolution_source",
    "state_resolution_evidence",
]


def _json_units(value: Any) -> list[dict[str, Any]]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def normalize_state(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "Administrative unit not available":
        return None
    return STATE_ALIASES.get(text, text)


def _state_from_gadm_id(gid: Any) -> str | None:
    match = re.match(r"^IND\.(\d+)", str(gid or ""))
    if not match:
        return None
    return GADM_STATE_BY_NUMBER.get(int(match.group(1)))


def _location_patterns() -> list[tuple[re.Pattern[str], str]]:
    names = set(STATE_PROFILES) | set(STATE_ALIASES)
    patterns = []
    for name in sorted(names, key=len, reverse=True):
        canonical = STATE_ALIASES.get(name, name)
        patterns.append(
            (
                re.compile(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", re.IGNORECASE),
                canonical,
            )
        )
    return patterns


LOCATION_PATTERNS = _location_patterns()


def resolve_states(row: pd.Series) -> list[dict[str, Any]]:
    """Resolve every Indian state named by structured units or Location."""
    evidence: dict[str, list[str]] = defaultdict(list)
    districts: dict[str, list[str]] = defaultdict(list)

    for unit in _json_units(row.get("GADM Admin Units")):
        state = _state_from_gadm_id(unit.get("gid_2") or unit.get("gid_1"))
        if not state:
            state = normalize_state(unit.get("name_1"))
        if state in STATE_PROFILES:
            gid = unit.get("gid_2") or unit.get("gid_1") or ""
            marker = f"GADM:{gid}"
            if marker not in evidence[state]:
                evidence[state].append(marker)
            district = str(unit.get("name_2") or "").strip()
            if district and district != "Administrative unit not available" and district not in districts[state]:
                districts[state].append(district)

    legacy_districts: list[str] = []
    for unit in _json_units(row.get("Admin Units")):
        state = normalize_state(unit.get("adm1_name"))
        if state in STATE_PROFILES:
            marker = f"Admin Units:{unit.get('adm1_code', '')}"
            if marker not in evidence[state]:
                evidence[state].append(marker)
        district = str(unit.get("adm2_name") or "").strip()
        if district and district != "Administrative unit not available" and district not in legacy_districts:
            legacy_districts.append(district)

    location = str(row.get("Location") or "")
    for pattern, state in LOCATION_PATTERNS:
        if state in STATE_PROFILES and pattern.search(location):
            marker = f"Location:{pattern.pattern}"
            if marker not in evidence[state]:
                evidence[state].append(marker)

    # Legacy adm2 entries do not carry their state parent. They are safe to use
    # as a district label only when exactly one state was resolved.
    if len(evidence) == 1 and legacy_districts:
        only_state = next(iter(evidence))
        for district in legacy_districts:
            if district not in districts[only_state]:
                districts[only_state].append(district)

    resolved = []
    for state in sorted(evidence):
        sources = sorted({item.split(":", 1)[0] for item in evidence[state]})
        resolved.append(
            {
                "state": state,
                "district": districts[state][0] if districts[state] else state,
                "resolution_source": "|".join(sources),
                "resolution_evidence": json.dumps(evidence[state], ensure_ascii=False),
            }
        )
    return resolved


def _date_parts(row: pd.Series, prefix: str) -> tuple[date, str]:
    year = int(row[f"{prefix} Year"])
    month = int(row[f"{prefix} Month"])
    day_value = row[f"{prefix} Day"]
    if pd.isna(day_value):
        day = 1 if prefix == "Start" else calendar.monthrange(year, month)[1]
        precision = "month"
    else:
        day = int(day_value)
        precision = "day"
    return date(year, month, day), precision


def load_official_workbook(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = pd.read_excel(path, sheet_name=SOURCE_SHEET)
    info = pd.read_excel(path, sheet_name=INFO_SHEET, header=None)
    if data.empty:
        raise ValueError(f"{path} contains no rows in {SOURCE_SHEET!r}")
    if "DisNo." not in data.columns:
        raise ValueError(f"{path} is missing required column 'DisNo.'")
    if data["DisNo."].isna().any() or data["DisNo."].astype(str).duplicated().any():
        raise ValueError("Official EM-DAT DisNo. values must be complete and unique")
    return data, info


def build_state_events(base: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return full-fidelity state rows and the pipeline event registry."""
    source_columns = list(base.columns)
    records: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for _, row in base.iterrows():
        states = resolve_states(row)
        if not states:
            unresolved.append(str(row["DisNo."]))
            continue
        start_date, start_precision = _date_parts(row, "Start")
        end_date, end_precision = _date_parts(row, "End")
        if end_date < start_date:
            end_date = start_date
        precision = f"start:{start_precision}|end:{end_precision}"

        source_values = {column: row[column] for column in source_columns}
        for resolved in states:
            state = resolved["state"]
            profile = STATE_PROFILES[state]
            records.append(
                {
                    **source_values,
                    "state": state,
                    "district": resolved["district"],
                    "disaster_type": "flood",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "date_precision": precision,
                    "lat": profile.latitude,
                    "lon": profile.longitude,
                    "bbox": profile.bbox,
                    "aoi_level": "state",
                    "income_group": profile.income_group,
                    "event_source": "emdat_official_state",
                    "source_record_id": str(row["DisNo."]),
                    "state_resolution_source": resolved["resolution_source"],
                    "state_resolution_evidence": resolved["resolution_evidence"],
                }
            )

    if unresolved:
        raise ValueError(f"Could not resolve an Indian state for: {sorted(unresolved)}")

    full = pd.DataFrame(records)
    full = full.sort_values(["start_date", "source_record_id", "state"]).reset_index(drop=True)
    full.insert(len(source_columns), "event_id", [f"E{i:03d}" for i in range(1, len(full) + 1)])

    ordered = source_columns + DERIVED_COLUMNS
    full = full[ordered]
    if full.duplicated(["source_record_id", "state"]).any():
        duplicates = full.loc[
            full.duplicated(["source_record_id", "state"], keep=False),
            ["source_record_id", "state"],
        ]
        raise ValueError(f"Duplicate DisNo./state rows produced: {duplicates.to_dict('records')}")

    event_columns = [
        "event_id",
        "state",
        "district",
        "disaster_type",
        "start_date",
        "end_date",
        "lat",
        "lon",
        "bbox",
        "income_group",
        "event_source",
        "source_record_id",
        "aoi_level",
        "date_precision",
        "state_resolution_source",
    ]
    registry = full[event_columns].copy()
    return full, registry


def build_summary(base_path: Path, base: pd.DataFrame, full: pd.DataFrame) -> dict[str, Any]:
    coverage = (
        full.groupby("source_record_id", sort=True)
        .agg(
            state_count=("state", "size"),
            states=("state", lambda values: "|".join(sorted(values))),
            resolution_sources=(
                "state_resolution_source",
                lambda values: "|".join(sorted({part for value in values for part in value.split("|")})),
            ),
        )
        .reset_index()
    )
    locations = base.set_index(base["DisNo."].astype(str))["Location"].fillna("").astype(str)
    coverage["location"] = coverage["source_record_id"].map(locations)
    return {
        "source_file": base_path.name,
        "source_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        "source_records": int(len(base)),
        "source_columns": int(len(base.columns)),
        "state_event_rows": int(len(full)),
        "unique_states": int(full["state"].nunique()),
        "all_source_records_covered": bool(full["source_record_id"].nunique() == len(base)),
        "algorithm": (
            "one row per unique DisNo./Indian state; union of GADM Admin Units, "
            "Admin Units, and explicit state names in Location; no cross-DisNo. merge; no manual seeds"
        ),
        "coverage": coverage.to_dict(orient="records"),
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=data_path("emdat_base"))
    parser.add_argument("--events-output", type=Path, default=data_path("events"))
    parser.add_argument("--full-output", type=Path, help="Optional full-fidelity state-event CSV")
    parser.add_argument("--summary-output", type=Path, help="Optional derivation summary JSON")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        base, _info = load_official_workbook(args.base)
        full, registry = build_state_events(base)
        summary = build_summary(args.base, base, full)
        print(f"Official source records: {len(base)}")
        print(f"Original columns preserved: {len(base.columns)}")
        print(f"State-event rows: {len(full)}")
        print(f"Unique states/UTs: {full['state'].nunique()}")
        if args.dry_run:
            return 0

        args.events_output.parent.mkdir(parents=True, exist_ok=True)
        registry.to_csv(args.events_output, index=False)
        print(f"Wrote event registry: {args.events_output}")
        if args.full_output:
            args.full_output.parent.mkdir(parents=True, exist_ok=True)
            full.to_csv(args.full_output, index=False)
            print(f"Wrote full state rows: {args.full_output}")
        if args.summary_output:
            args.summary_output.parent.mkdir(parents=True, exist_ok=True)
            args.summary_output.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Wrote derivation summary: {args.summary_output}")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
