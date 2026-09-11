"""Estimate Track B download blocks per event-district (no download; AOI bounds only).
Run: python src/estimate_blocks.py                      # every registry row
     python src/estimate_blocks.py KEY [KEY ...]        # event_district_ids or event_ids
"""
import math
import sys

import pandas as pd

import satellite as sat
from cvnd_layout import data_path
from district_keys import analysis_key


def main(keys):
    events = pd.read_csv(data_path("event_districts"))
    if keys:
        analysis_keys = events.apply(analysis_key, axis=1)
        events = events[analysis_keys.isin(keys) | events["event_id"].astype(str).isin(keys)]
    sat.ensure_gee()

    B = sat.SITS_BLOCK_PATCHES
    total = 0
    print(f"{'event_district_id':<40}{'tiles':>12}{'blocks':>8}{'~min':>7}")
    print("-" * 67)
    for _, row in events.iterrows():
        key = analysis_key(row)
        try:
            grid = sat.tile_grid(sat.get_region(row))
            nb = math.ceil(grid.npx / B) * math.ceil(grid.npy / B)
            total += nb
            print(f"{key:<40}{f'{grid.npx}x{grid.npy}':>12}{nb:>8}{nb * 14 // 60:>7}")
        except Exception as e:
            print(f"{key:<40}  ERROR: {e}")

    print("-" * 67)
    print(f"TOTAL: {total} blocks  ~{total * 14 / 3600:.1f} h  (at ~14s/block)")


if __name__ == "__main__":
    main(sys.argv[1:])
