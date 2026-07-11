import ee
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

from gee_config import initialize_gee

initialize_gee()

# ═══════════════════════════════════════════════════════════════════════════════
# SITS-EXTREME UPGRADE
# ───────────────────────────────────────────────────────────────────────────────
# Original code used a single 30-day pre-event median (bi-temporal).
# Problem: a single median can't distinguish recurring seasonal water
# (rivers, rice paddies) from actual flood signal.
#
# SITS-Extreme fix: build a 12-month multi-temporal baseline from monthly
# medians, compute per-pixel mean and std of that baseline, then flag pixels
# where the post-event backscatter drops more than Z standard deviations
# below the baseline mean. This is an anomaly score — not a fixed threshold —
# so it adapts to each pixel's own historical behaviour.
#
# Result: fewer false positives on permanently wet areas, better detection
# of genuine flood anomalies especially in monsoon-season imagery.
# ═══════════════════════════════════════════════════════════════════════════════


# ── SITS-Extreme: build multi-temporal baseline ───────────────────────────────
def build_sits_baseline(region, event_start, n_months=12):
    """
    Build a per-pixel baseline from n_months of monthly Sentinel-1 medians
    BEFORE the event. Returns (mean_image, std_image).

    Each month contributes one median composite → stack of n_months images →
    per-pixel mean and std across that stack. This captures seasonal variation
    in backscatter so the anomaly detector knows what 'normal' looks like for
    each pixel across a full annual cycle.
    """
    print(f"    SITS: building {n_months}-month baseline...")

    monthly_images = []
    for m in range(n_months, 0, -1):
        month_start = ee.Date(event_start).advance(-m,       'month')
        month_end   = ee.Date(event_start).advance(-(m - 1), 'month')

        monthly_median = (
            ee.ImageCollection('COPERNICUS/S1_GRD')
            .filter(ee.Filter.eq('instrumentMode', 'IW'))
            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
            .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING'))
            .filterBounds(region)
            .filterDate(month_start, month_end)
            .select('VV')
            .median()
        )
        monthly_images.append(monthly_median)

    baseline_stack = ee.ImageCollection(monthly_images)

    baseline_mean = baseline_stack.mean().rename('baseline_mean')
    baseline_std  = baseline_stack.reduce(ee.Reducer.stdDev()).rename('baseline_std')

    return baseline_mean, baseline_std


# ── SITS-Extreme: anomaly-based flood detection ───────────────────────────────
def sits_extreme_flood(post_img, baseline_mean, baseline_std,
                       region, z_threshold=2.0, min_std_db=0.5):
    """
    Flag pixels where post-event backscatter is anomalously LOW compared to
    the multi-temporal baseline. Water = dark SAR backscatter.

    anomaly_score = (baseline_mean - post_img) / max(baseline_std, min_std_db)

    Pixels with anomaly_score > z_threshold are classified as flooded.

    z_threshold=2.0 means the pixel must drop >2 standard deviations below
    its own historical mean to be called flooded. Adjust down (1.5) to be
    more sensitive, up (2.5) to be more conservative.

    min_std_db guards against near-zero std on permanently stable pixels
    (e.g. urban concrete) where any tiny noise would produce a huge z-score.
    """
    # Speckle filter before anomaly computation
    post_filtered = post_img.focal_median(1, 'square')

    anomaly = (baseline_mean.subtract(post_filtered)
               .divide(baseline_std.max(min_std_db))
               .rename('anomaly_score'))

    flood_raw = anomaly.gt(z_threshold).rename('flood')
    return flood_raw, anomaly


# ── Otsu threshold (kept for fallback) ────────────────────────────────────────
def otsu_threshold(image, region, scale=30, max_pixels=1e8):
    try:
        histogram = image.reduceRegion(
            reducer=ee.Reducer.histogram(255, 0.5),
            geometry=region,
            scale=scale,
            maxPixels=max_pixels,
            bestEffort=True
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


def otsu_backscatter_threshold(image, region, scale=30,
                               fallback=-16.0, lo=-20.0, hi=-13.0):
    try:
        hist = image.reduceRegion(
            reducer=ee.Reducer.histogram(255, 0.5),
            geometry=region, scale=scale, maxPixels=1e8, bestEffort=True
        ).getInfo()
        band = list(hist.keys())[0]
        t, _ = _otsu_from_hist(hist.get(band))
    except Exception as e:
        print(f"    (backscatter Otsu failed: {e})")
        t = None
    if t is None or not (lo <= t <= hi):
        print(f"    (raw Otsu = {t} — outside [{lo}, {hi}] -> fallback {fallback})")
        return fallback
    print(f"    (raw Otsu = {t:.3f} — in range)")
    return t


def _otsu_from_hist(h):
    if not h or 'histogram' not in h or 'bucketMeans' not in h:
        return None, 0.0
    counts  = np.array(h['histogram'], dtype=float)
    buckets = np.array(h['bucketMeans'], dtype=float)
    total = counts.sum()
    if total == 0:
        return None, 0.0
    total_mean = (counts * buckets).sum() / total
    total_var  = (counts * (buckets - total_mean) ** 2).sum() / total
    if total_var == 0:
        return None, 0.0
    w0, sum0, best_var, best_t = 0.0, 0.0, 0.0, None
    for i in range(len(counts)):
        w0 += counts[i] / total
        w1 = 1.0 - w0
        if w0 == 0 or w1 == 0:
            continue
        sum0 += counts[i] * buckets[i] / total
        mu0 = sum0 / w0
        mu1 = (total_mean - w0 * mu0) / w1
        var = w0 * w1 * (mu0 - mu1) ** 2
        if var > best_var:
            best_var, best_t = var, buckets[i]
    sep = best_var / total_var
    return (float(best_t) if best_t is not None else None), sep


# ── Pre/post image quality check ──────────────────────────────────────────────
def check_image_count(collection, label, event_id, min_required=1):
    count = collection.size().getInfo()
    if count < min_required:
        print(f"    WARN [{event_id}] {label}: only {count} images "
              f"(min required: {min_required}) — result may be unreliable")
    return count


# ── Sentinel-2 optical NDWI cross-check (unchanged from original) ─────────────
def detect_flood_s2(region, start_date):
    pre_start  = ee.Date(start_date).advance(-30, 'day')
    pre_end    = ee.Date(start_date)
    post_start = ee.Date(start_date)
    post_end   = ee.Date(start_date).advance(7, 'day')

    def mask_clouds(img):
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
        return None, 0

    def ndwi_median(col):
        return col.map(lambda i: i.normalizedDifference(['B3', 'B8'])
                       .rename('ndwi')).median()

    pre_ndwi  = ndwi_median(s2.filterDate(pre_start, pre_end))
    post_ndwi = ndwi_median(post_col)
    flood = post_ndwi.gt(0).And(pre_ndwi.lte(0)).rename('flood')

    area = flood.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region, scale=30, maxPixels=1e9)
    area_m2 = area.getInfo().get('flood', 0) or 0
    return round(area_m2 / 1e6, 2), n_post


# ── Shared masks (JRC, slope, India boundary) ─────────────────────────────────
def get_masks(region):
    srtm      = ee.Image('USGS/SRTMGL1_003')
    jrc       = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('occurrence')
    permanent = jrc.gte(50).unmask(0)
    flat      = ee.Terrain.slope(srtm).lt(5)
    india     = (ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017')
                 .filter(ee.Filter.eq('country_na', 'India')))
    return permanent, flat, india


# ── Core flood detection for one event ───────────────────────────────────────
def detect_flood(row, z_threshold=2.0, n_baseline_months=12):
    event_id = row['event_id']
    state    = row['state']
    print(f"\n[{event_id}] {state} / {row['district']} "
          f"({row['start_date']} → {row['end_date']})")

    try:
        bbox   = [float(x) for x in row['bbox'].split(',')]
        region = ee.Geometry.Rectangle(bbox)

        post_start = ee.Date(row['start_date'])
        post_end   = ee.Date(row['start_date']).advance(7, 'day')

        # ── Sentinel-1 post-event image ───────────────────────────────────────
        s1 = (ee.ImageCollection('COPERNICUS/S1_GRD')
              .filter(ee.Filter.eq('instrumentMode', 'IW'))
              .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
              .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING'))
              .filterBounds(region))

        post_col = s1.filterDate(post_start, post_end)
        post_n   = check_image_count(post_col, 'post-event', event_id)

        # ── Sentinel-2 optical NDWI (independent cross-check) ─────────────────
        try:
            s2_area, s2_n = detect_flood_s2(region, row['start_date'])
        except Exception as e:
            print(f"    WARN [{event_id}] S2 failed: {e}")
            s2_area, s2_n = None, 0
        if s2_area is None:
            print(f"    S2 (NDWI): blind — no cloud-free image ({s2_n} imgs)")
        else:
            print(f"    S2 (NDWI): {s2_area} km²  ({s2_n} cloud-free imgs)")

        if post_n == 0:
            print(f"    SKIP: no post-event imagery")
            return {
                'event_id': event_id, 'state': state,
                'affected_area_km2': s2_area,
                'area_sits_km2': None, 'area_s2_km2': s2_area,
                'post_images': post_n, 's2_post_images': s2_n,
                'z_threshold': z_threshold,
                'baseline_months': n_baseline_months,
                'status': 'SKIPPED_NO_IMAGERY'
            }

        post_img = post_col.select('VV').median()

        # ── SITS-Extreme: multi-temporal baseline ─────────────────────────────
        try:
            baseline_mean, baseline_std = build_sits_baseline(
                region, row['start_date'], n_months=n_baseline_months
            )

            flood_sits, anomaly_img = sits_extreme_flood(
                post_img, baseline_mean, baseline_std,
                region, z_threshold=z_threshold
            )

            # Apply masks: permanent water, slope, India boundary
            permanent, flat, india = get_masks(region)
            flood_masked = (flood_sits
                            .And(permanent.Not())
                            .And(flat)
                            .clipToCollection(india)
                            .rename('flood'))

            # Compute flooded area
            pixel_area = flood_masked.multiply(ee.Image.pixelArea())
            area_stats = pixel_area.reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=region, scale=30, maxPixels=1e9
            )
            sits_area_m2 = area_stats.getInfo().get('flood', 0) or 0
            sits_area_km2 = round(sits_area_m2 / 1e6, 2)

            print(f"    SITS-Extreme (z>{z_threshold}, {n_baseline_months}mo baseline): "
                  f"{sits_area_km2} km²")

            sits_status = 'OK' if sits_area_km2 > 0 else 'ZERO_AREA'

        except Exception as e:
            print(f"    WARN: SITS-Extreme failed ({e}) — falling back to Otsu")
            # ── Fallback: original Otsu bi-temporal (kept as safety net) ──────
            post_f    = post_img.focal_median(1, 'square')
            threshold = otsu_backscatter_threshold(post_f, region)
            water     = post_f.lt(threshold)

            permanent, flat, india = get_masks(region)
            flood_masked = (water
                            .And(permanent.Not())
                            .And(flat)
                            .clipToCollection(india)
                            .rename('flood'))

            pixel_area = flood_masked.multiply(ee.Image.pixelArea())
            area_stats = pixel_area.reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=region, scale=30, maxPixels=1e9
            )
            sits_area_m2  = area_stats.getInfo().get('flood', 0) or 0
            sits_area_km2 = round(sits_area_m2 / 1e6, 2)
            sits_status = 'FALLBACK_OTSU'
            print(f"    Fallback Otsu: {sits_area_km2} km²")

        # ── Final combined area ───────────────────────────────────────────────
        # S2 NDWI is cloud-limited but more accurate when available.
        # SITS-Extreme handles cloud-covered events S2 can't see.
        # Priority: S2 if available, else SITS-Extreme.
        combined_area = s2_area if s2_area is not None else sits_area_km2

        if combined_area == 0 or combined_area is None:
            print(f"    WARN: 0 km² — possible cloud cover, z too high, "
                  f"or event outside bbox")

        return {
            'event_id':          event_id,
            'state':             state,
            'affected_area_km2': combined_area,
            'area_sits_km2':     sits_area_km2,
            'area_s2_km2':       s2_area,
            'post_images':       post_n,
            's2_post_images':    s2_n,
            'z_threshold':       z_threshold,
            'baseline_months':   n_baseline_months,
            'status':            sits_status
        }

    except Exception as e:
        print(f"    ERROR: {e}")
        return {
            'event_id':          event_id,
            'state':             state,
            'affected_area_km2': None,
            'area_sits_km2':     None,
            'area_s2_km2':       None,
            'post_images':       None,
            's2_post_images':    None,
            'z_threshold':       z_threshold,
            'baseline_months':   n_baseline_months,
            'status':            f'ERROR: {e}'
        }


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    print("CP-05: SITS-EXTREME MULTI-TEMPORAL FLOOD DETECTION")
    print("=" * 60)
    print("Method: 12-month per-pixel baseline → z-score anomaly detection")
    print("Fallback: Otsu bi-temporal (if SITS baseline fails)")
    print("Cross-check: Sentinel-2 NDWI (when cloud-free)")
    print("=" * 60)

    # ── Tunable parameters ────────────────────────────────────────────────────
    Z_THRESHOLD      = 2.0   # lower = more sensitive, higher = more conservative
    N_BASELINE_MONTHS = 12   # months of history for baseline (6 min, 12 recommended)

    events  = pd.read_csv('data/events.csv')
    results = []

    for _, row in events.iterrows():
        result = detect_flood(row,
                              z_threshold=Z_THRESHOLD,
                              n_baseline_months=N_BASELINE_MONTHS)
        results.append(result)

    df = pd.DataFrame(results)

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(df[['event_id', 'state', 'area_sits_km2', 'area_s2_km2',
              'post_images', 'z_threshold', 'status']].to_string(index=False))

    ok       = df[df['status'].isin(['OK', 'ZERO_AREA'])]
    fallback = df[df['status'] == 'FALLBACK_OTSU']
    skipped  = df[df['status'] == 'SKIPPED_NO_IMAGERY']
    errors   = df[df['status'].str.startswith('ERROR', na=False)]

    print(f"\nProcessed      : {len(df)} events")
    print(f"SITS-Extreme OK: {len(ok)}")
    print(f"Fallback Otsu  : {len(fallback)}")
    print(f"Skipped        : {len(skipped)}  (no imagery)")
    print(f"Errors         : {len(errors)}")

    if len(ok) + len(fallback) < 6:
        print("\nWARN: Fewer than 6 usable events — review before proceeding.")

    os.makedirs('data', exist_ok=True)
    df.to_csv('data/flood_extent.csv', index=False)
    print(f"\nSAVED: data/flood_extent.csv")

    if len(ok) + len(fallback) == 0:
        print("\nFAIL: No events returned valid flood area. "
              "Paste output above and debug before proceeding.")
    else:
        print(f"\nCP-05 COMPLETE — ready for CP-06")
        print(f"Tip: if areas seem too large, raise Z_THRESHOLD to 2.5")
        print(f"Tip: if too many zeros, lower Z_THRESHOLD to 1.5")