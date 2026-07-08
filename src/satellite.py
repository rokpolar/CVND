import ee
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

from gee_config import initialize_gee

initialize_gee()

# ── Otsu threshold ──────────────────────
def otsu_threshold(image, region, scale=30, max_pixels=1e8):
    """
    Compute Otsu's optimal threshold from the histogram of a GEE image.
    Uses bestEffort=True to handle large bounding boxes gracefully.
    Falls back to 3.0 dB if histogram is empty or computation fails.
    """
    try:
        histogram = image.reduceRegion(
            reducer=ee.Reducer.histogram(255, 0.5),
            geometry=region,
            scale=scale,
            maxPixels=max_pixels,
            bestEffort=True          # <-- fixes the Too many pixels error
        ).getInfo()

        band = list(histogram.keys())[0]
        hist_data = histogram.get(band)

        if not hist_data or 'histogram' not in hist_data:
            print("    WARN: Empty histogram — using fallback threshold 3.0 dB")
            return 3.0

        counts  = np.array(hist_data['histogram'], dtype=float)
        buckets = np.array(hist_data['bucketMeans'], dtype=float)
        total   = counts.sum()

        if total == 0:
            return 3.0

        best_thresh, best_var = 0.0, 0.0
        w0, sum0 = 0.0, 0.0
        total_mean = (counts * buckets).sum() / total

        for i in range(len(counts)):
            w0   += counts[i] / total
            w1    = 1.0 - w0
            if w0 == 0 or w1 == 0:
                continue
            sum0 += counts[i] * buckets[i] / total
            mu0   = sum0 / w0
            mu1   = (total_mean - w0 * mu0) / w1 if w1 > 0 else 0.0
            var   = w0 * w1 * (mu0 - mu1) ** 2
            if var > best_var:
                best_var    = var
                best_thresh = buckets[i]

        return float(best_thresh) if best_thresh > 0 else 3.0

    except Exception as e:
        print(f"    WARN: Otsu failed ({e}) — using fallback 3.0 dB")
        return 3.0


# ── Pre/post image quality check ─────────────────────────────────────────────
def check_image_count(collection, label, event_id, min_required=1):
    """Returns count; warns if below minimum."""
    count = collection.size().getInfo()
    if count < min_required:
        print(f"    WARN [{event_id}] {label}: only {count} images "
              f"(min required: {min_required}) — result may be unreliable")
    return count


# ── Sentinel-2 optical NDWI cross-check ──────────────────────────────────────
def detect_flood_s2(region, start_date):
    """
    Optical NDWI flood area (McFeeters NDWI = (B3-B8)/(B3+B8), water > 0).
    Water-specific, so it avoids the wet-soil over-detection that inflates the
    SAR result. Blind under cloud, so it COMPLEMENTS Sentinel-1, not replaces it.
    Returns (area_km2 or None, n_cloudfree_post_images).
    """
    pre_start  = ee.Date(start_date).advance(-30, 'day')
    pre_end    = ee.Date(start_date)
    post_start = ee.Date(start_date)
    post_end   = ee.Date(start_date).advance(7, 'day')

    def mask_clouds(img):
        # SCL: 3=cloud shadow, 8/9/10=cloud (med/high/cirrus), 11=snow -> drop.
        scl  = img.select('SCL')
        keep = (scl.neq(3).And(scl.neq(8)).And(scl.neq(9))
                .And(scl.neq(10)).And(scl.neq(11)))
        return img.updateMask(keep)

    s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
          .filterBounds(region)
          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80))
          .map(mask_clouds))

    post_col = s2.filterDate(post_start, post_end)
    n_post   = post_col.size().getInfo()
    if n_post == 0:
        return None, 0  # cloud-blind for this event

    def ndwi_median(col):
        return col.map(lambda i: i.normalizedDifference(['B3', 'B8'])
                       .rename('ndwi')).median()

    pre_ndwi  = ndwi_median(s2.filterDate(pre_start, pre_end))
    post_ndwi = ndwi_median(post_col)
    # Newly flooded = water now (NDWI>0) but not water before.
    flood = post_ndwi.gt(0).And(pre_ndwi.lte(0)).rename('flood')

    area = flood.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region, scale=30, maxPixels=1e9)
    area_m2 = area.getInfo().get('flood', 0) or 0
    return round(area_m2 / 1e6, 2), n_post


# ── Core flood detection for one event ───────────────────────────────────────
def detect_flood(row):
    event_id = row['event_id']
    state    = row['state']
    print(f"\n[{event_id}] {state} / {row['district']} "
          f"({row['start_date']} → {row['end_date']})")

    try:
        bbox   = [float(x) for x in row['bbox'].split(',')]
        region = ee.Geometry.Rectangle(bbox)

        # Date windows: 30-day pre, 7-day post
        pre_start  = ee.Date(row['start_date']).advance(-30, 'day')
        pre_end    = ee.Date(row['start_date'])
        post_start = ee.Date(row['start_date'])
        post_end   = ee.Date(row['start_date']).advance(7, 'day')

        # Sentinel-1 IW VV DESCENDING
        s1 = (ee.ImageCollection('COPERNICUS/S1_GRD')
              .filter(ee.Filter.eq('instrumentMode', 'IW'))
              .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
              .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING'))
              .filterBounds(region))

        pre_col  = s1.filterDate(pre_start,  pre_end)
        post_col = s1.filterDate(post_start, post_end)

        pre_n  = check_image_count(pre_col,  'pre-event',  event_id)
        post_n = check_image_count(post_col, 'post-event', event_id)

        # Sentinel-2 optical NDWI cross-check (independent of S1 availability)
        try:
            s2_area, s2_n = detect_flood_s2(region, row['start_date'])
        except Exception as e:
            print(f"    WARN [{event_id}] S2 failed: {e}")
            s2_area, s2_n = None, 0
        if s2_area is None:
            print(f"    S2 (NDWI): blind — no cloud-free image ({s2_n} imgs)")
        else:
            print(f"    S2 (NDWI): {s2_area} km²  ({s2_n} cloud-free imgs)")

        # Flag events with zero images — cannot compute flood extent
        if pre_n == 0 or post_n == 0:
            print(f"    SKIP: insufficient imagery (pre={pre_n}, post={post_n})")
            return {
                'event_id': event_id, 'state': state,
                'affected_area_km2': None,
                'area_s1_km2': None, 'area_s2_km2': s2_area,
                'pre_images': pre_n, 'post_images': post_n,
                's2_post_images': s2_n,
                'otsu_threshold_db': None, 'status': 'SKIPPED_NO_IMAGERY'
            }

        pre_img  = pre_col.select('VV').median()
        post_img = post_col.select('VV').median()
        diff     = pre_img.subtract(post_img)

        # Otsu threshold (per-event, fixes Bug 1)
        threshold = otsu_threshold(diff, region)
        print(f"    Otsu threshold: {threshold:.3f} dB  "
              f"(pre={pre_n} imgs, post={post_n} imgs)")

        # Apply threshold — pixels where backscatter dropped more than threshold
        flood_mask = diff.gt(threshold)

        # Compute flooded area in km²
        pixel_area = flood_mask.multiply(ee.Image.pixelArea())
        area_stats = pixel_area.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=region,
            scale=30,
            maxPixels=1e9
        )
        area_m2  = area_stats.getInfo().get('VV', 0) or 0
        area_km2 = round(area_m2 / 1e6, 2)

        print(f"    Flooded area: {area_km2} km²")

        status = 'OK'
        if area_km2 == 0:
            print(f"    WARN: 0 km² detected — possible cloud cover, "
                  f"low threshold, or event outside bbox")
            status = 'ZERO_AREA'

        return {
            'event_id': event_id, 'state': state,
            'affected_area_km2': area_km2,          # = S1 (downstream uses this)
            'area_s1_km2': area_km2, 'area_s2_km2': s2_area,
            'pre_images': pre_n, 'post_images': post_n,
            's2_post_images': s2_n,
            'otsu_threshold_db': round(threshold, 3),
            'status': status
        }

    except Exception as e:
        print(f"    ERROR: {e}")
        return {
            'event_id': event_id, 'state': state,
            'affected_area_km2': None,
            'pre_images': None, 'post_images': None,
            'otsu_threshold_db': None, 'status': f'ERROR: {e}'
        }


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 55)
    print("CP-05: SENTINEL-1 + SENTINEL-2 FLOOD DETECTION")
    print("=" * 55)

    events  = pd.read_csv('data/events.csv')
    results = []

    for _, row in events.iterrows():
        result = detect_flood(row)
        results.append(result)

    df = pd.DataFrame(results)

    print("\n" + "=" * 55)
    print("RESULTS SUMMARY")
    print("=" * 55)
    print(df[['event_id', 'state', 'area_s1_km2', 'area_s2_km2',
              's2_post_images', 'otsu_threshold_db', 'status']].to_string(index=False))

    # Stats
    ok      = df[df['status'].isin(['OK', 'ZERO_AREA'])]
    skipped = df[df['status'] == 'SKIPPED_NO_IMAGERY']
    errors  = df[df['status'].str.startswith('ERROR', na=False)]

    print(f"\nProcessed : {len(df)} events")
    print(f"OK        : {len(ok)}")
    print(f"Skipped   : {len(skipped)}  (no imagery)")
    print(f"Errors    : {len(errors)}")

    if len(ok) < 6:
        print("\nWARN: Fewer than 6 usable events — pipeline may be "
              "underpowered. We will review before proceeding.")

    os.makedirs('data', exist_ok=True)
    df.to_csv('data/flood_extent.csv', index=False)
    print(f"\nSAVED: data/flood_extent.csv")

    # Hard stop if too many failures
    if len(ok) == 0:
        print("\nFAIL: No events returned valid flood area. "
              "Do not proceed — paste output and we debug.")
    else:
        print("\nCP-05 COMPLETE — ready for CP-06")