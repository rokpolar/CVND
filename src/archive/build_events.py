"""Validate the canonical event registry.

The event registry is maintained in ``data/raw/events.csv``.  This module is
kept as a compatibility entry point for the original event-builder command,
but it no longer contains an embedded seed event list.
"""

import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = ROOT / "data" / "raw" / "events.csv"
REQUIRED_COLUMNS = {
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
}
VALID_INCOME_GROUPS = {"High", "Middle", "Low"}
VALID_EVENT_SOURCES = {"manual_seed", "emdat_derived", "emdat_derived_legacy"}


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def validate_bbox(value: str) -> bool:
    try:
        lon_min, lat_min, lon_max, lat_max = (float(part) for part in value.split(","))
    except (TypeError, ValueError):
        return False

    return (
        68 <= lon_min <= 98
        and 68 <= lon_max <= 98
        and 6 <= lat_min <= 38
        and 6 <= lat_max <= 38
        and lon_min < lon_max
        and lat_min < lat_max
    )


def validate_events(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    event_ids = [row["event_id"] for row in rows]

    duplicates = [event_id for event_id, count in Counter(event_ids).items() if count > 1]
    if duplicates:
        errors.append(f"duplicate event_id values: {duplicates}")

    for row in rows:
        event_id = row["event_id"]
        try:
            if parse_date(row["end_date"]) < parse_date(row["start_date"]):
                errors.append(f"{event_id}: end_date precedes start_date")
        except ValueError:
            errors.append(f"{event_id}: invalid ISO date")

        if not validate_bbox(row["bbox"]):
            errors.append(f"{event_id}: invalid India bounding box")

        if row["income_group"] not in VALID_INCOME_GROUPS:
            errors.append(f"{event_id}: invalid income_group {row['income_group']!r}")

        if row["event_source"] not in VALID_EVENT_SOURCES:
            errors.append(f"{event_id}: invalid event_source {row['event_source']!r}")

    return errors


def main() -> int:
    if not EVENTS_PATH.exists():
        print(f"ERROR: canonical event registry not found: {EVENTS_PATH}")
        return 1

    with EVENTS_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            print(f"ERROR: events.csv is missing columns: {sorted(missing)}")
            return 1
        rows = list(reader)

    errors = validate_events(rows)

    print("CANONICAL EVENT REGISTRY VALIDATION")
    print(f"Path: {EVENTS_PATH}")
    print(f"Rows: {len(rows)}")
    print(f"Sources: {dict(Counter(row['event_source'] for row in rows))}")
    print(f"Date range: {min(row['start_date'] for row in rows)} to "
          f"{max(row['end_date'] for row in rows)}")

    if errors:
        print("VALIDATION FAILED:")
        for error in errors:
            print(f"  ERROR: {error}")
        return 1

    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
