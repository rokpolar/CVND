"""Resolve and measure event AOIs with explicit spatial provenance.

District rows use an exact India/state/district GAUL level-2 match. A failed
match is retained as ``aoi_match_status=failed`` and has no area; it is never
replaced with a state polygon. The area is geodesic (``geometry.area`` with the
spec's ``aoi_max_error_m``) and is the denominator of ``flood_ratio``.
"""

from __future__ import annotations

import sys
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from cvnd_layout import data_path
from district_keys import analysis_key
from flood_spec import SPEC_VERSION


def _registry() -> pd.DataFrame:
    return pd.read_csv(data_path("event_districts"))


def _resolve_one(row, sat_module) -> dict:
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
    return rec


def resolve_rows(events: pd.DataFrame, sat_module, workers: int = 4) -> pd.DataFrame:
    """Resolve every registry row, preserving failures for QC and joins.

    Rows are independent Earth Engine requests, resolved ``workers`` at a
    time; the output keeps registry order.
    """
    if hasattr(sat_module, "ensure_gee"):
        sat_module.ensure_gee()
    rows = [row for _, row in events.iterrows()]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return pd.DataFrame(list(pool.map(lambda row: _resolve_one(row, sat_module), rows)))


def _reusable_rows(events: pd.DataFrame, output) -> dict[str, dict]:
    """Reuse only matched AOIs with the exact current registry identity."""
    if not output.exists():
        return {}
    try:
        cached = pd.read_csv(output, dtype=str, keep_default_na=False)
    except (OSError, ValueError):
        return {}
    required = {'event_district_id', 'aoi_match_status', 'spec_version'}
    if not required.issubset(cached.columns) or cached.event_district_id.duplicated().any():
        return {}
    if not cached.spec_version.eq(SPEC_VERSION).all():
        return {}
    cached = cached.set_index('event_district_id')
    reusable = {}
    for _, row in events.iterrows():
        key = analysis_key(row)
        if key not in cached.index:
            continue
        previous = cached.loc[key]
        if previous.get('aoi_match_status') != 'matched':
            continue
        if any(str(previous.get(field, '')) != str(row.get(field, ''))
               for field in ('event_id', 'source_record_id', 'start_date', 'state', 'district')):
            continue
        # ``event_district_id`` is the dataframe index after ``set_index``;
        # put it back into the row before rebuilding the output table.
        reusable_row = previous.to_dict()
        reusable_row['event_district_id'] = key
        reusable[key] = reusable_row
    return reusable


def main(event_ids: list[str] | None = None) -> None:
    events = _registry()
    if event_ids:
        keys = events.apply(analysis_key, axis=1)
        events = events[keys.isin(event_ids) | events["event_id"].astype(str).isin(event_ids)]

    output = data_path("district_aoi")
    output.parent.mkdir(parents=True, exist_ok=True)
    reusable = {} if event_ids else _reusable_rows(events, output)
    keys = events.apply(analysis_key, axis=1)
    remaining = events.loc[~keys.isin(reusable)].copy()
    print(f"AOI cache: reusing {len(reusable)}/{len(events)} matched rows; "
          f"resolving {len(remaining)} rows")
    resolved = pd.DataFrame()
    if len(remaining):
        # Defer the Earth Engine import and initialization to actual AOI work.
        import satellite as sat
        resolved = resolve_rows(remaining, sat)
    rows = {**reusable, **{
        analysis_key(row): row.to_dict() for _, row in resolved.iterrows()
    }}
    result = pd.DataFrame([rows[analysis_key(row)] for _, row in events.iterrows()])
    fd, temporary = tempfile.mkstemp(prefix='.district-aoi-', suffix='.csv',
                                     dir=output.parent)
    try:
        os.close(fd)
        result.to_csv(temporary, index=False)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"\nSaved -> {output} ({len(result)} events, spec {SPEC_VERSION})")
    print(result["aoi_match_status"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main(sys.argv[1:])
