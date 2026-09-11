"""Resolve and measure event AOIs with explicit spatial provenance.

District rows use an exact India/state/district GAUL level-2 match. A failed
match is retained as ``aoi_match_status=failed`` and has no area; it is never
replaced with a state polygon. The area is geodesic (``geometry.area`` with the
spec's ``aoi_max_error_m``) and is the denominator of ``flood_ratio``.
"""

from __future__ import annotations

import sys

import pandas as pd

from cvnd_layout import data_path
from district_keys import analysis_key
from flood_spec import SPEC_VERSION


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
            "spec_version": SPEC_VERSION,
        }
        try:
            aoi = sat_module.resolve_aoi(row)
            rec.update({k: v for k, v in aoi.items() if k != "geometry"})
        except Exception as exc:
            rec["aoi_error"] = str(exc)
            print(f"{analysis_key(row)}: AOI failed: {exc}")
        else:
            print(f"{analysis_key(row)}: {rec['aoi_area_km2']:.1f} km2 ({rec['aoi_level']})")
        rows.append(rec)
    return pd.DataFrame(rows)


def main(event_ids: list[str] | None = None) -> None:
    events = _registry()
    if event_ids:
        keys = events.apply(analysis_key, axis=1)
        events = events[keys.isin(event_ids) | events["event_id"].astype(str).isin(event_ids)]

    # Defer the Earth Engine import and initialization to the actual AOI run.
    import satellite as sat

    output = data_path("district_aoi")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = resolve_rows(events, sat)
    result.to_csv(output, index=False)
    print(f"\nSaved -> {output} ({len(result)} events, spec {SPEC_VERSION})")
    print(result["aoi_match_status"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main(sys.argv[1:])
