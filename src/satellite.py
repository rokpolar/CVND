import ee
import pandas as pd
import numpy as np
import h5py
import json
import os
import warnings
warnings.filterwarnings('ignore')
from datetime import datetime, timedelta

from gee_config import initialize_gee
initialize_gee()

# ═══════════════════════════════════════════════════════════════════════════════
# satellite.py — CVND Flood Detection Pipeline
# ───────────────────────────────────────────────────────────────────────────────
# Track A — Otsu bi-temporal (S1 + S2) baseline
#   Output: data/flood_extent.csv
#
# Track B — SITS-Extreme-VAE data preparation
#   Output: data/sits_patches/<event_id>.h5
#   Next:   Upload to Google Drive → run sits_inference.ipynb on Colab GPU
#           → Download sits_vae_results.csv → merge into compute_pss.py
#
# Citation: Fang & Azizpour (WACV 2025) — MIT license
# ═══════════════════════════════════════════════════════════════════════════════

# ── Checkpoint paths ──────────────────────────────────────────────────────────
CHECKPOINT_A    = 'data/satellite_checkpoint_a.json'
CHECKPOINT_B    = 'data/satellite_checkpoint_b.json'

# ── Track B config ────────────────────────────────────────────────────────────
SITS_BANDS      = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12']
SITS_PATCH_SIZE = 64
SITS_N_PRE      = 6
SITS_NORM       = 10000.0
SITS_CLOUD_MAX  = 80
SITS_OUTPUT_DIR = 'data/sits_patches'


# ══════════════════════════════════════════════════════════════════════════════
# CHECKPOINT UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def load_checkpoint(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def save_checkpoint(data, path):
    with open(path, 'w') as f:
        json.dump(data, f)


# ══════════════════════════════════════════════════════════════════════════════
# TRACK A — OTSU BI-TEMPORAL BASELINE (S1 + S2)
# ══════════════════════════════════════════════════════════════════════════════

def _otsu_from_hist(h):
    """Otsu threshold + separability from GEE histogram dict."""
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
        w0  += counts[i] / total
        w1   = 1.0 - w0
        if w0 == 0 or w1 == 0:
            continue
        sum0 += counts[i] * buckets[i] / total
        mu0   = sum0 / w0
        mu1   = (total_mean - w0 * mu0) / w1
        var   = w0 * w1 * (mu0 - mu1) ** 2
        if var > best_var:
            best_var, best_t = var, buckets[i]
    sep = best_var / total_var
    return (float(best_t) if best_t is not None else None), sep


def otsu_threshold(image, region, scale=30, max_pixels=1e8):
    """Otsu on difference image. Falls back to 3.0 dB."""
    try:
        histogram = image.reduceRegion(
            reducer=ee.Reducer.histogram(255, 0.5),
            geometry=region, scale=scale,
            maxPixels=max_pixels, bestEffort=True
        ).getInfo()
        band      = list(histogram.keys())[0]
        hist_data = histogram.get(band)
        if not hist_data or 'histogram' not in hist_data:
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
        print(f"    WARN: Otsu failed ({e}) — fallback 3.0 dB")
        return 3.0


def otsu_backscatter_threshold(image, region, scale=30,
                               fallback=-16.0, lo=-20.0, hi=-13.0):
    """Otsu on post-event backscatter image (water=dark). Clamped to VV water range."""
    try:
        hist = image.reduceRegion(
            reducer=ee.Reducer.histogram(255, 0.5),
            geometry=region, scale=scale,
            maxPixels=1e8, bestEffort=True
        ).getInfo()
        band = list(hist.keys())[0]
        t, _ = _otsu_from_hist(hist.get(band))
    except Exception as e:
        print(f"    (backscatter Otsu failed: {e})")
        t = None
    if t is None or not (lo <= t <= hi):
        print(f"    (Otsu={t} outside [{lo},{hi}] → fallback {fallback} dB)")
        return fallback
    print(f"    (Otsu={t:.3f} dB in range)")
    return t


def check_image_count(collection, label, event_id, min_required=1):
    count = collection.size().getInfo()
    if count < min_required:
        print(f"    WARN [{event_id}] {label}: {count} images "
              f"(min {min_required})")
    return count


def detect_flood_s2(region, start_date):
    """Sentinel-2 NDWI flood cross-check. Returns (area_km2 or None, n_imgs)."""
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
    """JRC permanent water + slope<5° + India land boundary masks."""
    srtm      = ee.Image('USGS/SRTMGL1_003')
    jrc       = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('occurrence')
    permanent = jrc.gte(50).unmask(0)
    flat      = ee.Terrain.slope(srtm).lt(5)
    india     = (ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017')
                 .filter(ee.Filter.eq('country_na', 'India')))
    return permanent, flat, india


def get_region(row):
    """이벤트 AOI = 이벤트 좌표를 포함하는 district(구) 경계 (FAO GAUL 2015 level-2).
    Track A(bi-temporal)와 Track B(SITS)가 공용으로 씀 → AOI 일관.
    (구버전은 느슨한 bbox: 주 크기라 홍수와 무관한 영역이 대부분이었음.)
    이름 매칭 대신 point-in-polygon으로 잡아 매칭 오류(Bengaluru/Bangalore 등)를 회피.
    """
    lon = float(row['lon'])
    lat = float(row['lat'])
    pt  = ee.Geometry.Point([lon, lat])
    return ee.FeatureCollection('FAO/GAUL/2015/level2').filterBounds(pt).geometry()


def detect_flood_baseline(row):
    """Track A: Otsu bi-temporal baseline (S1 SAR + S2 NDWI)."""
    event_id = row['event_id']
    state    = row['state']
    print(f"\n  [Track A] [{event_id}] {state} / {row['district']} "
          f"({row['start_date']})")

    try:
        bbox   = [float(x) for x in row['bbox'].split(',')]
        # region = ee.Geometry.Rectangle(bbox)   # (구버전) 느슨한 bbox
        region = get_region(row)                  # district 경계 (Track B와 공용)

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

        # S2 NDWI cross-check (independent)
        try:
            s2_area, s2_n = detect_flood_s2(region, row['start_date'])
        except Exception as e:
            print(f"    WARN S2: {e}")
            s2_area, s2_n = None, 0

        s2_str = f"{s2_area} km² ({s2_n} imgs)" if s2_area is not None \
                 else f"blind ({s2_n} imgs)"
        print(f"    S2 NDWI: {s2_str}")

        if pre_n == 0 or post_n == 0:
            # Use S2 if available, else None
            fallback = s2_area if (s2_area is not None and s2_area > 0) else None
            return {
                'event_id': event_id, 'state': state,
                'affected_area_km2': fallback,      # pipeline-standard column name
                'area_s1_km2': None,
                'area_s2_km2': s2_area,
                'pre_images': pre_n, 'post_images': post_n,
                's2_post_images': s2_n,
                'otsu_threshold_db': None,
                'baseline_status': 'SKIPPED_NO_S1_IMAGERY'
            }

        post_img  = post_col.select('VV').median()
        post_f    = post_img.focal_median(1, 'square')
        threshold = otsu_backscatter_threshold(post_f, region)
        water     = post_f.lt(threshold)

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
        print(f"    S1 Otsu ({threshold:.2f} dB): {area_km2} km²")

        # FIX: S2=0.0 (clear, no water) ≠ S2=None (cloud-blind)
        # Only prefer S2 if it actually detected water (>0)
        combined = s2_area if (s2_area is not None and s2_area > 0) else area_km2
        status   = 'OK' if (area_km2 > 0 or (s2_area or 0) > 0) else 'ZERO_AREA'

        print(f"    Combined area: {combined} km²  (status={status})")

        return {
            'event_id': event_id, 'state': state,
            'affected_area_km2': combined,          # pipeline-standard column name
            'area_s1_km2': area_km2,
            'area_s2_km2': s2_area,
            'pre_images': pre_n, 'post_images': post_n,
            's2_post_images': s2_n,
            'otsu_threshold_db': round(threshold, 3),
            'baseline_status': status
        }

    except Exception as e:
        print(f"    ERROR: {e}")
        return {
            'event_id': event_id, 'state': state,
            'affected_area_km2': None,
            'area_s1_km2': None, 'area_s2_km2': None,
            'pre_images': None, 'post_images': None,
            's2_post_images': None,
            'otsu_threshold_db': None,
            'baseline_status': f'ERROR: {e}'
        }


# ══════════════════════════════════════════════════════════════════════════════
# TRACK B — SITS-EXTREME-VAE DATA PREPARATION
# ══════════════════════════════════════════════════════════════════════════════

def _mask_s2_sits(img):
    scl  = img.select('SCL')
    keep = (scl.neq(3).And(scl.neq(8)).And(scl.neq(9))
            .And(scl.neq(10)).And(scl.neq(11)))
    return img.updateMask(keep)


def _get_s2_sits(region):
    return (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterBounds(region)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', SITS_CLOUD_MAX))
            .map(_mask_s2_sits)
            .select(SITS_BANDS))


def _monthly_composite_sits(s2, target_dt):
    start = ee.Date.fromYMD(target_dt.year, target_dt.month, 1)
    end   = start.advance(1, 'month')
    col   = s2.filterDate(start, end)
    n     = col.size().getInfo()
    if n == 0:
        return None, 0
    return col.median(), n


def _extract_patch_sits(image, lat, lon):
    """Extract (10, 64, 64) float32 patch centred on (lat, lon)."""
    half_m     = (SITS_PATCH_SIZE * 10) / 2
    point      = ee.Geometry.Point([lon, lat])
    patch_geom = point.buffer(half_m).bounds()
    n_px       = SITS_PATCH_SIZE * SITS_PATCH_SIZE

    try:
        data = image.reduceRegion(
            reducer   = ee.Reducer.toList(),
            geometry  = patch_geom,
            scale     = 10,
            maxPixels = n_px * 2
        ).getInfo()

        arrays = []
        for band in SITS_BANDS:
            vals = data.get(band, [])
            if len(vals) == 0:
                return None
            arr = np.array(vals, dtype=np.float32)
            if len(arr) < n_px:
                arr = np.pad(arr, (0, n_px - len(arr)), constant_values=0)
            arr = arr[:n_px].reshape(SITS_PATCH_SIZE, SITS_PATCH_SIZE)
            arrays.append(arr)

        patch = np.stack(arrays, axis=0)
        return np.clip(patch / SITS_NORM, 0, 1)

    except Exception as e:
        print(f"      Patch extraction failed: {e}")
        return None


def prepare_sits_patch(row):
    """Track B: prepare one event's S2 time series as HDF5 patch."""
    event_id  = row['event_id']
    state     = row['state']
    lat       = float(row['lat'])
    lon       = float(row['lon'])
    start_str = row['start_date']
    print(f"\n  [Track B] [{event_id}] {state} — {start_str}")

    bbox     = [float(x) for x in row['bbox'].split(',')]
    # region   = ee.Geometry.Rectangle(bbox)   # (구버전) 느슨한 bbox
    region   = get_region(row)                  # district 경계 (Track A와 공용)
    s2       = _get_s2_sits(region)
    event_dt = datetime.strptime(start_str, '%Y-%m-%d')
    zeros    = np.zeros((len(SITS_BANDS), SITS_PATCH_SIZE, SITS_PATCH_SIZE),
                        dtype=np.float32)

    # 6 monthly pre-event composites
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

    # 1 post-event composite (0-14 days after)
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

    # Save HDF5
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
          f"[pre={pre_array.shape}, post={post_array.shape}]")
    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--track', choices=['A', 'B', 'both'],
                        default='both',
                        help='Which track to run (default: both)')
    args = parser.parse_args()

    print("=" * 65)
    print("CVND SATELLITE PIPELINE")
    print(f"  Running: Track {args.track.upper()}")
    print("=" * 65)

    events = pd.read_csv('data/events.csv')
    os.makedirs('data', exist_ok=True)

    # ── Track A ───────────────────────────────────────────────────────────────
    if args.track in ('A', 'both'):
        print("\n" + "─" * 65)
        print("TRACK A — BI-TEMPORAL BASELINE (S1 Otsu + S2 NDWI)")
        print("─" * 65)

        completed_a = load_checkpoint(CHECKPOINT_A)

        # Seed with existing flood_extent.csv if checkpoint is empty
        if not completed_a and os.path.exists('data/flood_extent.csv'):
            existing = pd.read_csv('data/flood_extent.csv')
            # Only seed if it has the new column schema
            if 'affected_area_km2' in existing.columns:
                for _, r in existing.iterrows():
                    completed_a[r['event_id']] = r.to_dict()
                save_checkpoint(completed_a, CHECKPOINT_A)
                print(f"Seeded {len(completed_a)} events from existing "
                      f"flood_extent.csv")

        done_a     = set(completed_a.keys())
        remaining_a = events[~events['event_id'].isin(done_a)]
        print(f"Already done: {len(done_a)} | Remaining: {len(remaining_a)}\n")

        for i, (_, row) in enumerate(remaining_a.iterrows(), 1):
            result = detect_flood_baseline(row)
            completed_a[row['event_id']] = result
            save_checkpoint(completed_a, CHECKPOINT_A)

            if (len(done_a) + i) % 10 == 0:
                pd.DataFrame(list(completed_a.values())).to_csv(
                    'data/flood_extent.csv', index=False)
                print(f"  >> Track A checkpoint: "
                      f"{len(done_a)+i}/{len(events)} done")

        df_a = pd.DataFrame(list(completed_a.values()))
        df_a = df_a.sort_values('event_id').reset_index(drop=True)
        df_a.to_csv('data/flood_extent.csv', index=False)

        ok_a = df_a[df_a['baseline_status'].isin(['OK', 'ZERO_AREA',
                                                   'SKIPPED_NO_S1_IMAGERY'])]
        print(f"\nTrack A complete: {len(ok_a)}/{len(events)} events")
        print(f"Saved: data/flood_extent.csv")
        print(df_a[['event_id', 'state', 'affected_area_km2',
                     'area_s1_km2', 'area_s2_km2',
                     'baseline_status']].to_string(index=False))

    # ── Track B ───────────────────────────────────────────────────────────────
    if args.track in ('B', 'both'):
        print("\n" + "─" * 65)
        print("TRACK B — SITS-EXTREME-VAE PATCH PREPARATION")
        print(f"  Bands: {SITS_BANDS}")
        print(f"  Patch: {SITS_PATCH_SIZE}×{SITS_PATCH_SIZE}px @ 10m | "
              f"{SITS_N_PRE} pre-event months + 1 post")
        print(f"  Norm:  ÷{SITS_NORM} → float32 [0,1]")
        print(f"  Spec:  RaVAEn / Fang & Azizpour WACV 2025")
        print("─" * 65)

        completed_b = load_checkpoint(CHECKPOINT_B)
        done_b      = set(completed_b.keys())
        remaining_b = events[~events['event_id'].isin(done_b)]
        print(f"Already done: {len(done_b)} | Remaining: {len(remaining_b)}\n")

        for _, row in remaining_b.iterrows():
            try:
                path = prepare_sits_patch(row)
                result = {'event_id': row['event_id'],
                          'h5_path': path, 'status': 'OK'}
            except Exception as e:
                print(f"  ERROR {row['event_id']}: {e}")
                result = {'event_id': row['event_id'],
                          'h5_path': None, 'status': f'ERROR: {e}'}
            completed_b[row['event_id']] = result
            save_checkpoint(completed_b, CHECKPOINT_B)

        df_b = pd.DataFrame(list(completed_b.values()))
        df_b = df_b.sort_values('event_id').reset_index(drop=True)
        df_b.to_csv('data/sits_patches_index.csv', index=False)

        ok_b = df_b[df_b['status'] == 'OK']
        print(f"\nTrack B complete: {len(ok_b)}/{len(events)} patches")
        print(f"Index: data/sits_patches_index.csv")
        print(f"\nNext steps:")
        print(f"  1. Upload data/sits_patches/ to Google Drive")
        print(f"  2. Run sits_inference.ipynb on Colab (T4 GPU)")
        print(f"  3. Download sits_vae_results.csv → place in data/")
        print(f"  4. compute_pss.py will auto-merge both tracks")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("DONE")
    print("=" * 65)