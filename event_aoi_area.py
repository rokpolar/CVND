"""Measure each canonical event's state-level AOI area through Earth Engine.

Run ``python event_aoi_area.py [EVENT_ID ...]``. The output contains
``event_id,aoi_km2`` and is consumed by ``src/merge_results.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import satellite as sat  # noqa: E402  (initializes Earth Engine)
from cvnd_layout import data_path  # noqa: E402


def main(event_ids: list[str] | None = None) -> None:
    events = pd.read_csv(data_path("events"))
    if event_ids:
        events = events[events["event_id"].isin(event_ids)]

    rows = []
    for _, row in events.iterrows():
        try:
            region = sat.get_region(row)
            km2 = region.area(maxError=1000).getInfo() / 1e6
            rows.append({"event_id": row["event_id"], "aoi_km2": round(km2, 1)})
            print(f"{row['event_id']}: {km2:.1f} km2")
        except Exception as exc:
            print(f"{row['event_id']}: ERROR {exc}")

    output = data_path("event_aoi_area")
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["event_id", "aoi_km2"]).to_csv(output, index=False)
    print(f"\nSaved -> {output} ({len(rows)} events)")


if __name__ == "__main__":
    main(sys.argv[1:])
