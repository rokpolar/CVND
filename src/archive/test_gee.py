import ee
import pandas as pd
from datetime import datetime

from gee_config import initialize_gee

print("=" * 55)
print("CP-04: GEE CONNECTION + SENTINEL-1 ACCESS TEST")
print("=" * 55)

# --- Test 1: Basic initialization ---
print("\n[Test 1] Initializing GEE...")
try:
    initialize_gee()
    print("  OK  GEE initialized")
except Exception as e:
    print(f"  FAIL  GEE init error: {e}")
    print("\n  FIX:")
    print("    1. cp .env.example .env")
    print("    2. Set GEE_PROJECT_ID in .env")
    print("    3. Run 'earthengine authenticate' if not authenticated yet")
    print("    Project ID: https://code.earthengine.google.com/")
    exit(1)

# --- Test 2: Sentinel-1 collection exists and is accessible ---
print("\n[Test 2] Accessing Sentinel-1 GRD collection...")
try:
    s1 = ee.ImageCollection('COPERNICUS/S1_GRD')
    count = s1.limit(1).size().getInfo()
    print(f"  OK  Sentinel-1 GRD collection accessible (returned {count} image for limit test)")
except Exception as e:
    print(f"  FAIL  {e}")
    exit(1)

# --- Test 3: Pull one real pre/post image pair from the canonical registry ---
test_event = pd.read_csv('data/raw/events.csv').iloc[0]
test_start = datetime.strptime(test_event['start_date'], '%Y-%m-%d')
test_bbox = [float(value) for value in test_event['bbox'].split(',')]
print(f"\n[Test 3] Fetching Sentinel-1 pre/post pair for {test_event['event_id']} "
      f"({test_event['state']})...")
try:
    region = ee.Geometry.Rectangle(test_bbox)

    pre_start  = ee.Date((test_start - pd.Timedelta(days=30)).strftime('%Y-%m-%d'))
    pre_end    = ee.Date(test_event['start_date'])
    post_start = ee.Date(test_event['start_date'])
    post_end   = ee.Date((test_start + pd.Timedelta(days=7)).strftime('%Y-%m-%d'))

    s1_filtered = (ee.ImageCollection('COPERNICUS/S1_GRD')
        .filter(ee.Filter.eq('instrumentMode', 'IW'))
        .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
        .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING'))
        .filterBounds(region))

    pre_count  = s1_filtered.filterDate(pre_start, pre_end).size().getInfo()
    post_count = s1_filtered.filterDate(post_start, post_end).size().getInfo()

    print(f"  OK  Pre-event images found:  {pre_count}")
    print(f"  OK  Post-event images found: {post_count}")

    if pre_count == 0:
        print(f"  WARN  No pre-event images — flood detection will fail for {test_event['event_id']}")
        print("        This may mean GEE access is approved but data catalog is restricted.")
    if post_count == 0:
        print(f"  WARN  No post-event images — flood detection will fail for {test_event['event_id']}")

except Exception as e:
    print(f"  FAIL  {e}")
    exit(1)

# --- Test 4: WorldPop accessibility ---
print("\n[Test 4] Accessing WorldPop population dataset...")
try:
    worldpop = (ee.ImageCollection('WorldPop/GP/100m/pop')
        .filter(ee.Filter.eq('country', 'IND'))
        .filter(ee.Filter.eq('year', 2020))
        .first())
    band_names = worldpop.bandNames().getInfo()
    print(f"  OK  WorldPop accessible — bands: {band_names}")
except Exception as e:
    print(f"  FAIL  {e}")
    exit(1)

# --- Test 5: Quick Otsu threshold test (the fix for Bug 1) ---
print("\n[Test 5] Testing Otsu threshold computation...")
try:
    region_small = ee.Geometry.Rectangle([76.0, 9.5, 77.0, 10.5])

    pre_img  = (s1_filtered
        .filterDate(pre_start, pre_end)
        .select('VV')
        .median())
    post_img = (s1_filtered
        .filterDate(post_start, post_end)
        .select('VV')
        .median())

    diff = pre_img.subtract(post_img)

    # Otsu: compute histogram, find threshold automatically
    histogram = diff.reduceRegion(
        reducer=ee.Reducer.histogram(255, 0.5),
        geometry=region_small,
        scale=30,
        maxPixels=1e8
    )

    # Pull histogram from GEE and compute Otsu in Python
    hist_data = histogram.getInfo().get('VV')

    if hist_data and 'histogram' in hist_data:
        counts  = hist_data['histogram']
        buckets = hist_data['bucketMeans']

        # Otsu's method
        import numpy as np
        counts  = np.array(counts,  dtype=float)
        buckets = np.array(buckets, dtype=float)
        total   = counts.sum()
        best_thresh, best_var = 0, 0

        w0, sum0 = 0, 0
        total_mean = (counts * buckets).sum() / total

        for i in range(len(counts)):
            w0   += counts[i] / total
            w1    = 1 - w0
            if w0 == 0 or w1 == 0:
                continue
            sum0 += counts[i] * buckets[i] / total
            mu0   = sum0 / w0
            mu1   = (total_mean - sum0) / w1 if w1 > 0 else 0
            var   = w0 * w1 * (mu0 - mu1) ** 2
            if var > best_var:
                best_var    = var
                best_thresh = buckets[i]

        print(f"  OK  Otsu threshold computed: {best_thresh:.3f} dB")
        print(f"      (teammate's hardcoded value was 3.0 — compare above)")
    else:
        print("  WARN  Could not compute Otsu — histogram empty for test region")
        print("        This is OK if pre/post images are sparse; will handle in CP-05")

except Exception as e:
    print(f"  WARN  Otsu test skipped: {e}")
    print("        Non-fatal — will handle in CP-05")

print("\n" + "=" * 55)
print("CP-04 SUMMARY")
print("=" * 55)
print("If Tests 1-4 passed: CP-04 COMPLETE — ready for CP-05")
print("If any test FAILED:  paste full output and we fix before moving on")
print("=" * 55)
