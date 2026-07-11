import ee
import pandas as pd
import numpy as np
import h5py
import os
import warnings
warnings.filterwarnings('ignore')
from datetime import datetime, timedelta

from gee_config import initialize_gee

initialize_gee()

# ═══════════════════════════════════════════════════════════════════════════════
# satellite.py — CVND Flood Detection Pipeline
# ───────────────────────────────────────────────────────────────────────────────
# This file does TWO things when run:
#
#   TRACK A — Otsu bi-temporal (S1 + S2) baseline
#     Runs entirely on GEE. Fast. No GPU needed.
#     Output: data/flood_extent.csv
#
#   TRACK B — SITS-Extreme-VAE data preparation
#     Pulls Sentinel-2 time series, formats to RaVAEn patch spec (HDF5).
#     Output: data/sits_patches/<event_id>.h5
#     → Upload to Google Drive → run sits_inference.ipynb on Colab GPU
#     → Download sits_vae_results.csv → merge into pipeline
#
# Issue #14 asks for Track B (official pretrained checkpoint, not reimplemented).
# Track A is kept as the baseline for comparison (as specified in the issue).
# ═══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# SHARED CONFIG
# ══════════════════════════════════════════════════════════════════════════════

# ── Track B (SITS-VAE) config ─────────────────────────────────────────────────
SITS_BANDS      = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12']
SITS_PATCH_SIZE = 64        # 64x64 px @ 10m = 640m x 640m per patch
SITS_N_PRE      = 6         # monthly pre-event composites
SITS_NORM       = 10000.0   # S2 L2A scale factor → normalize to 0-1
SITS_CLOUD_MAX  = 80        # max cloud cover % per image
SITS_OUTPUT_DIR = 'data/sits_patches'


# ══════════════════════════════════════════════════════════════════════════════
# TRACK A — OTSU BI-TEMPORAL BASELINE (S1 + S2)
# Unchanged from previous version — kept as baseline per Issue #14
# ══════════════════════════════════════════════════════════════════════════════

def otsu_threshold(image, region, scale=30, max_pixels=1e8):
    """Compute Otsu threshold from GEE image histogram. Falls back to 3.0 dB."""
    try:
        histogram = image.reduceRegion(
            reducer=ee.Reducer.histogram(255, 0.5),
            geometry=region,
            scale=scale,
            maxPixels=max_pixels,
            bestEffort=True
        ).getInfo()

        band      = list(histogram.keys())[0]
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
            w0  += counts[i] / total
            w1   = 1.0 - w0
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
    total   = counts.sum()
    if total == 0:
        return None, 0.0
    total_mean = (counts * buckets).sum() / total
    total_var  = (counts * (buckets - total_mean) ** 2).sum() / total
    if total_var == 0:
        return None, 0.0
    w0, sum0, best_var, best_t = 0.0, 0.0, 0.0, None
    for i in range(len(counts)):
        w0 += counts[i] / total
        w1  = 1.0 - w0
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


def check_image_count(collection, label, event_id, min_required=1):
    count = collection.size().getInfo()
    if count < min_required:
        print(f"    WARN [{event_id}] {label}: only {count} images "
              f"(min required: {min_required}) — result may be unreliable")
    return count


def detect_flood_s2(region, start_date):
    """Sentinel-2 optical NDWI flood cross-check."""
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
    flood     = post_ndwi.gt(0).And(pre_ndwi.lte(0)).rename('flood')

    area    = flood.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region, scale=30, maxPixels=1e9)
    area_m2 = area.getInfo().get('flood', 0) or 0
    return round(area_m2 / 1e6, 2), n_post


def get_masks(region):
    """JRC permanent water + slope + India boundary masks."""
    srtm      = ee.Image('USGS/SRTMGL1_003')
    jrc       = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('occurrence')
    permanent = jrc.gte(50).unmask(0)
    flat      = ee.Terrain.slope(srtm).lt(5)
    india     = (ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017')
                 .filter(ee.Filter.eq('country_na', 'India')))
    return permanent, flat, india


def detect_flood_baseline(row):
    """
    Track A: Otsu bi-temporal baseline.
    S1 SAR + S2 NDWI. Kept as baseline per Issue #14.
    """
    event_id = row['event_id']
    state    = row['state']
    print(f"\n  [Baseline] [{event_id}] {state}")

    try:
        bbox   = [float(x) for x in row['bbox'].split(',')]
        region = ee.Geometry.Rectangle(bbox)

        pre_start  = ee.Date(row['start_date']).advance(-30, 'day')
        pre_end    = ee.Date(row['start_date'])
        post_start = ee.Date(row['start_date'])
        post_end   = ee.Date(row['start_date']).advance(7, 'day')

        s1 = (ee.ImageCollection('COPERNICUS/S1_GRD')
              .filter(ee.Filter.eq('instrumentMode', 'IW'))
              .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
              .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING'))
              .filterBounds(region))

        pre_col  = s1.filterDate(pre_start, pre_end)
        post_col = s1.filterDate(post_start, post_end)
        pre_n    = check_image_count(pre_col,  'pre-event',  event_id)
        post_n   = check_image_count(post_col, 'post-event', event_id)

        try:
            s2_area, s2_n = detect_flood_s2(region, row['start_date'])
        except Exception as e:
            print(f"    WARN S2 failed: {e}")
            s2_area, s2_n = None, 0

        if s2_area is None:
            print(f"    S2 (NDWI): blind ({s2_n} imgs)")
        else:
            print(f"    S2 (NDWI): {s2_area} km² ({s2_n} cloud-free imgs)")

        if pre_n == 0 or post_n == 0:
            return {
                'event_id': event_id, 'state': state,
                'area_baseline_km2': s2_area, 'area_s2_km2': s2_area,
                'pre_images': pre_n, 'post_images': post_n,
                'otsu_threshold_db': None, 'baseline_status': 'SKIPPED_NO_IMAGERY'
            }

        post_img = post_col.select('VV').median()
        post_f   = post_img.focal_median(1, 'square')
        threshold = otsu_backscatter_threshold(post_f, region)
        water    = post_f.lt(threshold)

        permanent, flat, india = get_masks(region)
        flood_masked = (water.And(permanent.Not()).And(flat)
                        .clipToCollection(india).rename('flood'))

        pixel_area = flood_masked.multiply(ee.Image.pixelArea())
        area_stats = pixel_area.reduceRegion(
            reducer=ee.Reducer.sum(), geometry=region,
            scale=30, maxPixels=1e9
        )
        area_m2  = area_stats.getInfo().get('flood', 0) or 0
        area_km2 = round(area_m2 / 1e6, 2)
        print(f"    S1 (Otsu, threshold={threshold:.2f} dB): {area_km2} km²")

        combined = s2_area if s2_area is not None else area_km2
        status   = 'OK' if area_km2 > 0 else 'ZERO_AREA'

        return {
            'event_id': event_id, 'state': state,
            'area_baseline_km2': combined, 'area_s2_km2': s2_area,
            'pre_images': pre_n, 'post_images': post_n,
            'otsu_threshold_db': round(threshold, 3),
            'baseline_status': status
        }

    except Exception as e:
        print(f"    ERROR: {e}")
        return {
            'event_id': event_id, 'state': state,
            'area_baseline_km2': None, 'area_s2_km2': None,
            'pre_images': None, 'post_images': None,
            'otsu_threshold_db': None, 'baseline_status': f'ERROR: {e}'
        }


# ══════════════════════════════════════════════════════════════════════════════
# TRACK B — SITS-EXTREME-VAE DATA PREPARATION
# Formats Sentinel-2 time series patches to RaVAEn input spec for
# inference with pretrained checkpoint on Colab GPU.
#
# Input spec (RaVAEn / SITS-Extreme-VAE):
#   Bands     : B2 B3 B4 B5 B6 B7 B8 B8A B11 B12 (10 Sentinel-2 bands)
#   Patch size: 64 x 64 pixels at 10m resolution
#   Time series: 6 monthly pre-event composites + 1 post-event composite
#   Normalization: divide by 10000 → float32 in [0, 1]
#   HDF5 structure:
#     /pre   (6, 10, 64, 64)  — pre-event monthly composites
#     /post  (1, 10, 64, 64)  — post-event composite
#     /meta  attributes       — event_id, state, start_date, lat, lon
#
# Citation: Fang & Azizpour (WACV 2025) — MIT license, must cite.
# ══════════════════════════════════════════════════════════════════════════════

def _mask_s2_sits(img):
    """Cloud mask for SITS patch extraction."""
    scl  = img.select('SCL')
    keep = (scl.neq(3).And(scl.neq(8)).And(scl.neq(9))
            .And(scl.neq(10)).And(scl.neq(11)))
    return img.updateMask(keep)


def _get_s2_sits(region):
    """Sentinel-2 collection for SITS patch extraction (10 bands)."""
    return (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterBounds(region)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', SITS_CLOUD_MAX))
            .map(_mask_s2_sits)
            .select(SITS_BANDS))


def _monthly_composite_sits(s2, target_dt):
    """One monthly median composite for a given datetime."""
    start = ee.Date.fromYMD(target_dt.year, target_dt.month, 1)
    end   = start.advance(1, 'month')
    col   = s2.filterDate(start, end)
    n     = col.size().getInfo()
    if n == 0:
        return None, 0
    return col.median(), n


def _extract_patch_sits(image, lat, lon):
    """
    Extract 64x64 patch centred on (lat, lon) from a GEE image.
    Returns numpy array (10, 64, 64) normalized to [0,1], or zeros on failure.
    """
    half_m     = (SITS_PATCH_SIZE * 10) / 2
    point      = ee.Geometry.Point([lon, lat])
    patch_geom = point.buffer(half_m).bounds()

    try:
        data = image.reduceRegion(
            reducer   = ee.Reducer.toList(),
            geometry  = patch_geom,
            scale     = 10,
            maxPixels = SITS_PATCH_SIZE * SITS_PATCH_SIZE * 2
        ).getInfo()

        arrays = []
        n_px   = SITS_PATCH_SIZE * SITS_PATCH_SIZE
        for band in SITS_BANDS:
            vals = data.get(band, [])
            if len(vals) == 0:
                return None
            arr = np.array(vals, dtype=np.float32)
            if len(arr) < n_px:
                arr = np.pad(arr, (0, n_px - len(arr)), constant_values=0)
            arr = arr[:n_px].reshape(SITS_PATCH_SIZE, SITS_PATCH_SIZE)
            arrays.append(arr)

        patch = np.stack(arrays, axis=0)        # (10, 64, 64)
        patch = np.clip(patch / SITS_NORM, 0, 1)
        return patch

    except Exception as e:
        print(f"      Patch extraction failed: {e}")
        return None


def prepare_sits_patch(row):
    """
    Track B: prepare one event's Sentinel-2 time series as HDF5 patch.
    Saves to data/sits_patches/<event_id>.h5
    Returns output path or None on failure.
    """
    event_id  = row['event_id']
    state     = row['state']
    lat       = float(row['lat'])
    lon       = float(row['lon'])
    start_str = row['start_date']

    print(f"\n  [SITS prep] [{event_id}] {state} — {start_str}")

    bbox     = [float(x) for x in row['bbox'].split(',')]
    region   = ee.Geometry.Rectangle(bbox)
    s2       = _get_s2_sits(region)
    event_dt = datetime.strptime(start_str, '%Y-%m-%d')
    zeros    = np.zeros((len(SITS_BANDS), SITS_PATCH_SIZE, SITS_PATCH_SIZE),
                        dtype=np.float32)

    # ── 6 monthly pre-event composites ───────────────────────────────────────
    pre_patches = []
    for m in range(SITS_N_PRE, 0, -1):
        target = event_dt - timedelta(days=30 * m)
        img, n = _monthly_composite_sits(s2, target)
        if img is None:
            print(f"    Pre -{m}mo: no imagery → zeros")
            pre_patches.append(zeros.copy())
            continue
        patch = _extract_patch_sits(img, lat, lon)
        if patch is None:
            print(f"    Pre -{m}mo: extraction failed → zeros")
            pre_patches.append(zeros.copy())
        else:
            print(f"    Pre -{m}mo: OK ({n} imgs)")
            pre_patches.append(patch)

    pre_array = np.stack(pre_patches, axis=0)   # (6, 10, 64, 64)

    # ── 1 post-event composite (0-14 days after event) ───────────────────────
    post_col = s2.filterDate(
        ee.Date(start_str),
        ee.Date(start_str).advance(14, 'day')
    )
    post_n = post_col.size().getInfo()

    if post_n == 0:
        print(f"    Post: no imagery → zeros")
        post_patch = zeros.copy()
    else:
        post_patch = _extract_patch_sits(post_col.median(), lat, lon)
        if post_patch is None:
            print(f"    Post: extraction failed → zeros")
            post_patch = zeros.copy()
        else:
            print(f"    Post: OK ({post_n} imgs)")

    post_array = post_patch[np.newaxis, ...]    # (1, 10, 64, 64)

    # ── Save HDF5 ─────────────────────────────────────────────────────────────
    os.makedirs(SITS_OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(SITS_OUTPUT_DIR, f'{event_id}.h5')

    with h5py.File(out_path, 'w') as f:
        f.create_dataset('pre',  data=pre_array,  dtype='float32')
        f.create_dataset('post', data=post_array, dtype='float32')
        m = f.create_group('meta')
        m.attrs['event_id']   = event_id
        m.attrs['state']      = state
        m.attrs['start_date'] = start_str
        m.attrs['lat']        = lat
        m.attrs['lon']        = lon
        m.attrs['bands']      = ','.join(SITS_BANDS)
        m.attrs['n_pre']      = SITS_N_PRE
        m.attrs['patch_size'] = SITS_PATCH_SIZE

    print(f"    Saved: {out_path}  "
          f"[pre {pre_array.shape}, post {post_array.shape}]")
    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 65)
    print("CVND SATELLITE PIPELINE")
    print("  Track A: Otsu bi-temporal baseline  → data/flood_extent.csv")
    print("  Track B: SITS-VAE patch preparation → data/sits_patches/")
    print("=" * 65)

    events = pd.read_csv('data/events.csv')

    # ── Track A: baseline flood detection ────────────────────────────────────
    print("\n" + "─" * 65)
    print("TRACK A — BI-TEMPORAL BASELINE (S1 Otsu + S2 NDWI)")
    print("─" * 65)
    baseline_results = []
    for _, row in events.iterrows():
        baseline_results.append(detect_flood_baseline(row))

    baseline_df = pd.DataFrame(baseline_results)
    os.makedirs('data', exist_ok=True)
    baseline_df.to_csv('data/flood_extent.csv', index=False)

    ok_b = baseline_df[baseline_df['baseline_status'].isin(['OK', 'ZERO_AREA'])]
    print(f"\nTrack A: {len(ok_b)}/{len(events)} events OK")
    print("Saved: data/flood_extent.csv")

    # ── Track B: SITS-VAE patch preparation ──────────────────────────────────
    print("\n" + "─" * 65)
    print("TRACK B — SITS-EXTREME-VAE PATCH PREPARATION")
    print(f"  Bands: {SITS_BANDS}")
    print(f"  Patch: {SITS_PATCH_SIZE}x{SITS_PATCH_SIZE}px @ 10m | "
          f"{SITS_N_PRE} pre-event months + 1 post")
    print(f"  Norm:  divide by {SITS_NORM}")
    print("─" * 65)

    sits_results = []
    for _, row in events.iterrows():
        try:
            path = prepare_sits_patch(row)
            sits_results.append({
                'event_id': row['event_id'], 'h5_path': path, 'status': 'OK'
            })
        except Exception as e:
            print(f"  ERROR on {row['event_id']}: {e}")
            sits_results.append({
                'event_id': row['event_id'], 'h5_path': None,
                'status': f'ERROR: {e}'
            })

    sits_df = pd.DataFrame(sits_results)
    sits_df.to_csv('data/sits_patches_index.csv', index=False)

    ok_s = sits_df[sits_df['status'] == 'OK']
    print(f"\nTrack B: {len(ok_s)}/{len(events)} patches prepared")
    print(f"Saved:  {SITS_OUTPUT_DIR}/")
    print(f"Index:  data/sits_patches_index.csv")

    # ── Final summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("DONE")
    print("=" * 65)
    print(f"Track A OK: {len(ok_b)}/{len(events)}  → data/flood_extent.csv")
    print(f"Track B OK: {len(ok_s)}/{len(events)}  → data/sits_patches/")
    print()
    print("Next steps:")
    print("  1. Upload data/sits_patches/ folder to Google Drive")
    print("  2. Open sits_inference.ipynb on Google Colab (T4 GPU)")
    print("  3. Download sits_vae_results.csv → place in data/")
    print("  4. Run compute_pss.py — it will auto-merge both tracks")