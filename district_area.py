"""district_area.py — per-event district area (km2) via GEE, for merge flood_ratio.
Run: python district_area.py            # all events
     python district_area.py EVENT_ID [EVENT_ID ...]    # subset
Output: data/district_area.csv  (event_id, district_km2)
"""
import sys
import os
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
import satellite as sat   # importing runs initialize_gee()

events = pd.read_csv('data/raw/events.csv')
if sys.argv[1:]:
    events = events[events['event_id'].isin(sys.argv[1:])]

rows = []
for _, row in events.iterrows():
    try:
        region = sat.get_region(row)
        km2 = region.area(maxError=1000).getInfo() / 1e6
        rows.append({'event_id': row['event_id'], 'district_km2': round(km2, 1)})
        print(f"{row['event_id']}: {km2:.1f} km2")
    except Exception as e:
        print(f"{row['event_id']}: ERROR {e}")

pd.DataFrame(rows).to_csv('data/district_area.csv', index=False)
print(f"\nSaved -> data/district_area.csv ({len(rows)} events)")
