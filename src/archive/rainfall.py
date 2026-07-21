"""
CP-05b: Event rainfall (flood hazard signal, independent of water detection).

For each event, sums CHIRPS daily precipitation over the event window to get a
rainfall signal that works everywhere — including cities, where SAR/NDWI water
detection is blind to urban flooding. Outputs total and peak-daily rainfall.

CHIRPS DAILY: mm/day, ~0.05 deg, gauge+satellite blended, validated over India.

Run: python src/rainfall.py   ->  data/rainfall.csv
"""
import os

import ee
import pandas as pd

from gee_config import initialize_gee

initialize_gee()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
events = pd.read_csv(os.path.join(BASE, 'data', 'events.csv'))


def event_rainfall(row):
    bbox = [float(x) for x in row['bbox'].split(',')]
    region = ee.Geometry.Rectangle(bbox)
    start = ee.Date(row['start_date'])
    end = ee.Date(row['end_date']).advance(1, 'day')   # make end inclusive

    chirps = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
              .select('precipitation')
              .filterDate(start, end)
              .filterBounds(region))

    total = chirps.sum()   # per-pixel total mm over the window
    peak = chirps.max()    # per-pixel peak single-day mm

    total_mean = total.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=region,
        scale=5000, maxPixels=1e9).getInfo().get('precipitation', 0) or 0
    peak_max = peak.reduceRegion(
        reducer=ee.Reducer.max(), geometry=region,
        scale=5000, maxPixels=1e9).getInfo().get('precipitation', 0) or 0

    return round(total_mean, 1), round(peak_max, 1)


if __name__ == '__main__':
    print("=" * 55)
    print("CP-05b: EVENT RAINFALL (CHIRPS)")
    print("=" * 55)

    results = []
    for _, row in events.iterrows():
        try:
            total_mm, peak_mm = event_rainfall(row)
            print(f"[{row['event_id']}] {row['state']}: "
                  f"total {total_mm} mm (area mean) | peak {peak_mm} mm/day")
            results.append({'event_id': row['event_id'], 'state': row['state'],
                            'rain_total_mm': total_mm, 'rain_max_mm': peak_mm})
        except Exception as e:
            print(f"[{row['event_id']}] ERROR: {e}")
            results.append({'event_id': row['event_id'], 'state': row['state'],
                            'rain_total_mm': None, 'rain_max_mm': None})

    df = pd.DataFrame(results)
    print("\n" + df.to_string(index=False))

    out = os.path.join(BASE, 'data', 'rainfall.csv')
    df.to_csv(out, index=False)
    print(f"\nSAVED: {out}")
