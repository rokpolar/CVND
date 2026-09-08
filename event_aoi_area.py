"""Resolve and measure event AOIs with explicit spatial provenance.

District rows use an exact India/state/district GAUL level-2 match. A failed
match is retained as ``aoi_match_status=failed`` and has no area; it is never
replaced with a state polygon. State rows remain available for legacy runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from cvnd_layout import data_path  # noqa: E402


def _key(row) -> str:
    value = row.get("event_district_id")
    if value is not None and str(value).strip() not in {"", "nan", "None"}:
        return str(value)
    return str(row.get("event_id"))


def _registry() -> pd.DataFrame:
    return pd.read_csv(data_path("event_districts"))


def resolve_rows(events: pd.DataFrame, sat_module) -> pd.DataFrame:
    """Resolve every registry row, preserving failures for QC and joins."""
    if hasattr(sat_module, "ensure_gee"):
        sat_module.ensure_gee()
    rows = []
    for _, row in events.iterrows():
        district_value = row.get("event_district_id")
        rec = {
            "event_district_id": district_value,
            "event_id": row.get("event_id"),
            "source_record_id": row.get("source_record_id"),
            "start_date": row.get("start_date"),
            "state": row.get("state"),
            "district": row.get("district"),
            "aoi_level": "district" if str(row.get("aoi_level", "")).lower() == "district"
            or (district_value is not None and str(district_value) not in {"", "nan", "None"})
            else "state",
            "aoi_source": None,
            "aoi_match_status": "failed",
            "geometry_id": None,
            "aoi_area_km2": None,
            "aoi_km2": None,
        }
        try:
            aoi = sat_module.resolve_aoi(row)
            rec.update({k: v for k, v in aoi.items() if k != "geometry"})
            rec["aoi_km2"] = rec["aoi_area_km2"]
        except Exception as exc:
            rec["aoi_error"] = str(exc)
            print(f"{_key(row)}: AOI failed: {exc}")
        else:
            print(f"{_key(row)}: {rec['aoi_area_km2']:.1f} km2 ({rec['aoi_level']})")
        rows.append(rec)
    return pd.DataFrame(rows)


def main(event_ids: list[str] | None = None) -> None:
    events = _registry()
    if event_ids:
        keys = events.apply(_key, axis=1)
        events = events[keys.isin(event_ids) | events["event_id"].astype(str).isin(event_ids)]

    # Defer the Earth Engine import and initialization to the actual AOI run.
    import satellite as sat

    output = data_path("district_aoi_area")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = resolve_rows(events, sat)
    result.to_csv(output, index=False)
    print(f"\nSaved -> {output} ({len(result)} events)")
    print(result["aoi_match_status"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main(sys.argv[1:])
