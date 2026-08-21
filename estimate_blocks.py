"""Estimate download blocks per event (no download, state AOI bounds only).
Run: python estimate_blocks.py            # all events
     python estimate_blocks.py EVENT_ID [EVENT_ID ...]     # only these
"""
import sys
import os
import math
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
import satellite as sat   # importing runs initialize_gee()
from cvnd_layout import data_path

events = pd.read_csv(data_path("events"))
if sys.argv[1:]:
    events = events[events['event_id'].isin(sys.argv[1:])]

B = sat.SITS_BLOCK_PATCHES
P = sat.SITS_PATCH_SIZE
total = 0
print(f"{'event':<6}{'tiles':>12}{'blocks':>8}{'~min':>7}")
print("-" * 35)
for _, row in events.iterrows():
    try:
        region = sat.get_region(row)
        ring = region.bounds().coordinates().getInfo()[0]
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        clat = (min(lats) + max(lats)) / 2
        dlat = P * 10 / 110540.0
        dlon = P * 10 / (111320.0 * math.cos(math.radians(clat)))
        npx = int((max(lons) - min(lons)) / dlon)
        npy = int((max(lats) - min(lats)) / dlat)
        nb = math.ceil(npx / B) * math.ceil(npy / B)
        total += nb
        print(f"{row['event_id']:<6}{f'{npx}x{npy}':>12}{nb:>8}{nb * 14 // 60:>7}")
    except Exception as e:
        print(f"{row['event_id']:<6}  ERROR: {e}")

print("-" * 35)
print(f"TOTAL: {total} blocks  ~{total * 14 / 3600:.1f} h  (at ~14s/block)")
