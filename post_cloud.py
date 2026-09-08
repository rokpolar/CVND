"""Measure flood-date optical availability for each event AOI.

The same 14-day post-event window and cloud mask used by the SITS preparation
are applied. Every registry row is retained, including explicit AOI/query
failures, so missing observations cannot become a zero flood area downstream.
"""

from __future__ import annotations

import os
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


def measure(events: pd.DataFrame, sat_module, ee_module) -> pd.DataFrame:
    """Return cloud metadata for events, with status rows for failures."""
    if hasattr(sat_module, "ensure_gee"):
        sat_module.ensure_gee()
    rows = []
    for _, row in events.iterrows():
        key = _key(row)
        rec = {
            "event_district_id": row.get("event_district_id"),
            "event_id": row.get("event_id"),
            "source_record_id": row.get("source_record_id"),
            "start_date": row.get("start_date"),
            "state": row.get("state"),
            "district": row.get("district"),
            "aoi_level": row.get("aoi_level", "district"),
            "query_status": "failed",
            "post_images": None,
            "clear_pct": None,
            "cloud_pct": None,
        }
        try:
            region = sat_module.get_region(row)
            s2 = sat_module._get_s2_sits(region)
            post_col = s2.filterDate(
                ee_module.Date(row["start_date"]),
                ee_module.Date(row["start_date"]).advance(14, "day"),
            )
            post_n = int(post_col.size().getInfo())
            if post_n == 0:
                clear = 0.0
            else:
                post = post_col.median()
                valid = post.mask().reduce(ee_module.Reducer.min())
                values = valid.unmask(0).reduceRegion(
                    reducer=ee_module.Reducer.mean(), geometry=region,
                    scale=200, maxPixels=1e9, bestEffort=True,
                ).getInfo()
                clear = float(list(values.values())[0] or 0.0)
            rec.update({
                "query_status": "ok",
                "post_images": post_n,
                "clear_pct": round(clear * 100, 1),
                "cloud_pct": round((1 - clear) * 100, 1),
            })
            print(f"{key}: imgs={post_n} clear={rec['clear_pct']}%")
        except Exception as exc:
            rec["error"] = str(exc)
            print(f"{key}: ERROR {exc}")
        rows.append(rec)
    return pd.DataFrame(rows)


def main(event_ids: list[str] | None = None) -> None:
    events = pd.read_csv(data_path("event_districts"))
    if event_ids:
        keys = events.apply(_key, axis=1)
        events = events[keys.isin(event_ids) | events["event_id"].astype(str).isin(event_ids)]

    # Imports are deferred so importing this module has no GEE side effects.
    import ee
    import satellite as sat

    output = data_path("district_post_cloud")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = measure(events, sat, ee)
    result.to_csv(output, index=False)
    print(f"\nSaved -> {output} ({len(result)} events)")


if __name__ == "__main__":
    main(sys.argv[1:])
