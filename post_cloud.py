"""post_cloud.py — measure flood-date (post) cloud fraction per event, save to CSV.

For each event, builds the SAME post composite Track B uses for its t5 timestep
(S2_SR_HARMONIZED, [start, start+14d], cloud-masked, median) and measures what
fraction of the district polygon has valid (cloud-free) data. One reduceRegion
stat per event -- no pixel downloads, so the whole run is quick (like district_area.py).

Output: data/post_cloud.csv  (event_id, post_images, clear_pct, cloud_pct)
  clear_pct = % of district the post composite actually saw
  cloud_pct = 100 - clear_pct  -> merge routing: cloud_pct >= CLOUD_MAX_PCT (60) => S1

Run: python post_cloud.py            # all events (resumes: skips ones already in CSV)
     python post_cloud.py E01 E02    # subset
"""
import sys
import os
import pandas as pd
import ee

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
import satellite as sat   # importing runs initialize_gee()

OUT = 'data/post_cloud.csv'

events = pd.read_csv('data/events.csv')
if sys.argv[1:]:
    events = events[events['event_id'].isin(sys.argv[1:])]

# resume: skip events already measured
done = {}
if os.path.exists(OUT):
    prev = pd.read_csv(OUT)
    done = {r['event_id']: r for _, r in prev.iterrows()}
    print(f"resume: {len(done)} events already in {OUT}")

rows = list(done.values())
for _, row in events.iterrows():
    ev = row['event_id']
    if ev in done:
        continue
    try:
        region = sat.get_region(row)
        s2 = sat._get_s2_sits(region)
        post_col = s2.filterDate(ee.Date(row['start_date']),
                                 ee.Date(row['start_date']).advance(14, 'day'))
        post_n = post_col.size().getInfo()
        if post_n == 0:
            clear = 0.0                      # no imagery at all -> saw nothing
        else:
            post = post_col.median()
            # valid where every band is present (same rule as the patch download)
            valid = post.mask().reduce(ee.Reducer.min())
            # unmask(0) so cloud-masked ground counts as 0, then mean = clear fraction
            clear = valid.unmask(0).reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region,
                scale=200, maxPixels=1e9, bestEffort=True
            ).getInfo()
            clear = float(list(clear.values())[0] or 0.0)
        rec = {'event_id': ev, 'post_images': post_n,
               'clear_pct': round(clear * 100, 1),
               'cloud_pct': round((1 - clear) * 100, 1)}
        rows.append(rec)
        print(f"{ev}: imgs={post_n}  clear={rec['clear_pct']}%  cloud={rec['cloud_pct']}%")
    except Exception as e:
        print(f"{ev}: ERROR {e}")
        continue
    # save as we go so an interruption loses nothing
    pd.DataFrame(rows).to_csv(OUT, index=False)

pd.DataFrame(rows).to_csv(OUT, index=False)
print(f"\nSaved -> {OUT} ({len(rows)} events)")
