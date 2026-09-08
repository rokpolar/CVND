# Earth Engine is intentionally imported without initializing a session.  This
# module is also imported by schema/unit tests and by the AOI metadata steps,
# neither of which should require credentials.
try:
    import ee
except ImportError:  # pragma: no cover - only exercised in minimal installs
    ee = None
import pandas as pd
import numpy as np
import h5py
import io
import math
import time
import requests
import json
import os
import re
import unicodedata
import warnings
from pathlib import Path

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

from gee_config import initialize_gee
from cvnd_layout import data_path


def ensure_gee() -> None:
    """Initialize Earth Engine only for a call that actually needs it."""
    if ee is None:
        raise RuntimeError("Earth Engine is required for satellite operations")
    initialize_gee()

# ═══════════════════════════════════════════════════════════════════════════════
# satellite.py — CVND Flood Detection Pipeline (optional; SKIP_GEE=1 by default)
# ───────────────────────────────────────────────────────────────────────────────
# Track A — Otsu bi-temporal (S1 + S2) baseline
#   Output: data/cache/district/flood_extent.csv (primary; state path is legacy)
#
# Track B — SITS-Extreme-VAE data preparation
#   Output: data/cache/district/sits_patches/<event_district_id>.h5
#   Next:   run src/run_sits_inference.py locally when the verified checkpoint
#           is available, then place score NPZs in data/cache/district/sits_scores/
#           → merge_results.py → district_flood_combined.csv → build_flood_area_table.py
#
# Citation: Fang & Azizpour (WACV 2025) — MIT license
# ═══════════════════════════════════════════════════════════════════════════════

# ── Checkpoint paths ──────────────────────────────────────────────────────────
CHECKPOINT_A    = str(data_path("district_satellite_checkpoint_a"))
CHECKPOINT_B    = str(data_path("district_satellite_checkpoint_b"))
FLOOD_EXTENT_CSV = str(data_path("district_flood_extent"))
EVENTS_CSV = str(data_path("event_districts"))
SITS_INDEX_CSV = str(data_path("district_sits_patches_index"))

# ── Track B config ────────────────────────────────────────────────────────────
SITS_BANDS      = ['B4', 'B3', 'B2', 'B8']   # RGB (B4,B3,B2) for the model + B8 for NDWI
SITS_PATCH_SIZE = 64
SITS_N_PRE      = 4          # baseline t1..t4 (same-season composites); t5 = event month
SITS_NORM       = 10000.0
SITS_CLOUD_MAX  = 80
SITS_OUTPUT_DIR = str(data_path("district_sits_patches"))

# Tiling (whole-district-AOI) settings
SITS_BLOCK_PATCHES = 16     # download block = 16*64 = 1024 px/side (keeps NPY request small)
SITS_KEEP_VALID    = 0.70   # keep a 64x64 tile only if >= this fraction is cloud/nodata-free in EVERY timestep


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


def _area_value_km2(stats: dict, band: str) -> float | None:
    """Convert a reduceRegion result while preserving null as no observation."""
    if not stats or stats.get(band) is None:
        return None
    return round(float(stats[band]) / 1e6, 2)


def detect_flood_s2(region, start_date):
    """Sentinel-2 NDWI. Returns (new_flood_km2, pre_water_km2, during_water_km2, n_imgs),
    or (None, None, None, 0) if cloud-blind (no post imagery)."""
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
        return None, None, None, 0
    n_pre = s2.filterDate(pre_start, pre_end).size().getInfo()
    if n_pre == 0:
        # A post image alone cannot identify *new* water; retaining None keeps
        # cloud/data absence distinct from an observed zero-area result.
        return None, None, None, n_post

    def ndwi_median(col):
        return col.map(lambda i: i.normalizedDifference(['B3', 'B8'])
                       .rename('ndwi')).median()

    pre_ndwi  = ndwi_median(s2.filterDate(pre_start, pre_end))
    post_ndwi = ndwi_median(post_col)

    def area_km2(mask):
        stats = (mask.rename('w').multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=region, scale=30, maxPixels=1e9)
            .getInfo())
        return _area_value_km2(stats, 'w')

    flood  = area_km2(post_ndwi.gt(0).And(pre_ndwi.lte(0)))   # new flood (during - pre)
    pre    = area_km2(pre_ndwi.gt(0))                          # water before the flood
    during = area_km2(post_ndwi.gt(0))                         # water during the flood
    return flood, pre, during, n_post


def get_masks(region):
    """JRC permanent water + slope<5° + India land boundary masks."""
    srtm      = ee.Image('USGS/SRTMGL1_003')
    jrc       = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('occurrence')
    permanent = jrc.gte(50).unmask(0)
    flat      = ee.Terrain.slope(srtm).lt(5)
    india     = (ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017')
                 .filter(ee.Filter.eq('country_na', 'India')))
    return permanent, flat, india


GAUL_STATE_ALIASES = {
    'Odisha': 'Orissa',
    'Jammu and Kashmir': 'Jammu and Kashmir',
}


def _row_key(row) -> str:
    """Return the spatially scoped key while retaining state compatibility."""
    value = row.get('event_district_id') if hasattr(row, 'get') else None
    if value is not None and str(value).strip() and str(value) != 'nan':
        return str(value)
    return str(row.get('event_id'))


def _cache_identity_matches(entry, row) -> bool:
    """Reject cache entries for a reused key whose source row changed."""
    for field in ('event_id', 'source_record_id', 'state', 'district', 'start_date'):
        expected = row.get(field)
        cached = entry.get(field) if hasattr(entry, 'get') else None
        if cached is None or (isinstance(cached, float) and pd.isna(cached)):
            return False
        if str(cached).strip() != str(expected).strip():
            return False
    return True


def _h5_identity_matches(path, row) -> bool:
    """Check Track-B metadata before resuming a partial district cache."""
    try:
        with h5py.File(path, 'r') as handle:
            attrs = handle['meta'].attrs
            return all(str(attrs.get(field, '')).strip() == str(row.get(field, '')).strip()
                       for field in ('event_id', 'source_record_id', 'state', 'district', 'start_date'))
    except (OSError, KeyError, TypeError):
        return False


def _is_district_row(row) -> bool:
    level = str(row.get('aoi_level', '')).strip().lower()
    key = row.get('event_district_id') if hasattr(row, 'get') else None
    district = str(row.get('district', '')).strip()
    state = str(row.get('state', '')).strip()
    # The event-district key is authoritative even when the district happens
    # to have the same spelling as its state or is currently unresolved. Any
    # nonempty key must therefore stay on the level-2 path and may fail
    # explicitly; it must never trigger a state fallback.
    return level in {'district', 'level2', 'gaul2'} or (
        key is not None and str(key).strip().lower() not in {'', 'nan', 'none'}
    )


def _normalized_name(value: object) -> str:
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return re.sub(r'[\W_]+', ' ', text, flags=re.UNICODE).strip()


def _feature_collection_for_aoi(row):
    """Build an exact GAUL collection for a state or district AOI.

    District matching deliberately requires both ADM1 and ADM2.  We inspect the
    cardinality before returning a geometry so an absent or ambiguous district
    cannot silently fall back to a state polygon.
    """
    if ee is None:
        raise RuntimeError("Earth Engine is required to resolve an AOI")
    state = str(row.get('state', '')).strip()
    gaul_state = GAUL_STATE_ALIASES.get(state, state)
    if not state or state.lower() == 'nan':
        raise ValueError('state is missing')
    if _is_district_row(row):
        district = str(row.get('district', '')).strip()
        if not district or district.lower() in {'nan', 'missing', 'district_missing'}:
            raise ValueError('district is missing for district AOI')
        # GAUL's names are case-sensitive in ee.Filter.eq.  The first filter is
        # exact; a small deterministic case/space normalization is used only to
        # compare returned candidates, never to pick an arbitrary fuzzy match.
        collection = (ee.FeatureCollection('FAO/GAUL/2015/level2')
                      .filter(ee.Filter.eq('ADM0_NAME', 'India'))
                      .filter(ee.Filter.eq('ADM1_NAME', gaul_state)))
        candidates = collection.filter(ee.Filter.eq('ADM2_NAME', district))
        count = int(candidates.size().getInfo())
        if count != 1:
            # Some exports differ only in capitalization.  Accept a unique
            # normalized-name candidate, but keep state and level-2 constraints.
            all_candidates = collection.getInfo().get('features', [])
            matching = [f for f in all_candidates
                        if _normalized_name(f.get('properties', {}).get('ADM2_NAME'))
                        == _normalized_name(district)]
            if len(matching) != 1:
                raise ValueError(
                    f"district AOI match failed for {state}/{district}: {count} exact candidates"
                )
            gid = matching[0].get('properties', {}).get('ADM2_CODE')
            candidates = collection.filter(ee.Filter.eq('ADM2_CODE', gid)) if gid else None
            if candidates is None or int(candidates.size().getInfo()) != 1:
                raise ValueError(f"district AOI match is ambiguous for {state}/{district}")
        return candidates

    return (ee.FeatureCollection('FAO/GAUL/2015/level1')
            .filter(ee.Filter.eq('ADM0_NAME', 'India'))
            .filter(ee.Filter.eq('ADM1_NAME', gaul_state)))


def resolve_aoi(row) -> dict:
    """Resolve an event row to a strict AOI and provenance metadata.

    The returned geometry is a server-side EE geometry; callers that only need
    a status can catch the explicit ``ValueError`` without creating a fallback.
    """
    collection = _feature_collection_for_aoi(row)
    count = int(collection.size().getInfo())
    level = 'district' if _is_district_row(row) else 'state'
    if count != 1:
        raise ValueError(f"{level} AOI match failed: expected one feature, got {count}")
    feature = ee.Feature(collection.first())
    props = feature.toDictionary().getInfo()
    geometry = feature.geometry()
    identifier = props.get('ADM2_CODE' if level == 'district' else 'ADM1_CODE')
    if identifier is None:
        identifier = f"GAUL:India|{row.get('state')}|{row.get('district', '') if level == 'district' else ''}"
    return {
        'geometry': geometry,
        'aoi_level': level,
        'aoi_source': 'FAO/GAUL/2015/level2' if level == 'district' else 'FAO/GAUL/2015/level1',
        'aoi_match_status': 'matched',
        'geometry_id': str(identifier),
        'aoi_area_km2': float(geometry.area(maxError=1000).getInfo()) / 1e6,
    }


def get_region(row):
    """Return the strictly matched state or district GAUL geometry.

    State-level rows remain supported for legacy analyses; district rows never
    fall back to a state polygon when level-2 matching fails.
    """
    return resolve_aoi(row)['geometry']


def detect_flood_baseline(row):
    """Track A: Otsu bi-temporal baseline (S1 SAR + S2 NDWI)."""
    event_id = row['event_id']
    state    = row['state']
    key      = _row_key(row)
    district = row.get('district', '')
    level    = 'district' if _is_district_row(row) else 'state'
    print(f"\n  [Track A] [{key}] {state}/{district} ({level} AOI) "
          f"({row['start_date']})")

    context = {
        'event_district_id': row.get('event_district_id') if level == 'district' else None,
        'event_id': event_id,
        'source_record_id': row.get('source_record_id'),
        'start_date': row.get('start_date'),
        'state': state,
        'district': district,
        'aoi_level': level,
        'aoi_source': 'FAO/GAUL/2015/level2' if level == 'district' else 'FAO/GAUL/2015/level1',
        'aoi_match_status': 'failed',
        'geometry_id': None,
        'aoi_area_km2': None,
    }

    try:
        # bbox   = [float(x) for x in row['bbox'].split(',')]   # old loose state bbox
        # region = ee.Geometry.Rectangle(bbox)                  # (old) loose bbox
        aoi = resolve_aoi(row)
        region = aoi['geometry']
        context.update({k: v for k, v in aoi.items() if k != 'geometry'})

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
            s2_area, s2_pre, s2_during, s2_n = detect_flood_s2(region, row['start_date'])
        except Exception as e:
            print(f"    WARN S2: {e}")
            s2_area, s2_pre, s2_during, s2_n = None, None, None, 0

        s2_str = f"{s2_area} km² ({s2_n} imgs)" if s2_area is not None \
                 else f"blind ({s2_n} imgs)"
        print(f"    S2 NDWI: {s2_str}")

        if pre_n == 0 or post_n == 0:
            # Use S2 if available, else None
            fallback = s2_area if (s2_area is not None and s2_area > 0) else None
            return {
                **context,
                'affected_area_km2': fallback,      # pipeline-standard column name
                'area_s1_km2': None,
                'area_s2_km2': s2_area,
                'ndwi_flood_area_km2': s2_area,       # NDWI new-flood area
                'ndwi_pre_water_km2': s2_pre,         # NDWI water before the flood
                'ndwi_during_water_km2': s2_during,   # NDWI water during the flood
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
        area_values = area_stats.getInfo()
        area_km2 = _area_value_km2(area_values, 'flood')
        print(f"    S1 Otsu ({threshold:.2f} dB): {area_km2} km²")

        # FIX: S2=0.0 (clear, no water) ≠ S2=None (cloud-blind)
        # Only prefer S2 if it actually detected water (>0)
        combined = s2_area if s2_area is not None else area_km2
        status   = 'OK' if combined is not None and combined > 0 else (
            'ZERO_AREA' if combined is not None else 'FAILED_NO_VALID_PIXELS'
        )

        print(f"    Combined area: {combined} km²  (status={status})")

        return {
            **context,
            'affected_area_km2': combined,          # pipeline-standard column name
            'area_s1_km2': area_km2,
            'area_s2_km2': s2_area,
            'ndwi_flood_area_km2': s2_area,         # NDWI new-flood area
            'ndwi_pre_water_km2': s2_pre,           # NDWI water before the flood
            'ndwi_during_water_km2': s2_during,     # NDWI water during the flood
            'pre_images': pre_n, 'post_images': post_n,
            's2_post_images': s2_n,
            'otsu_threshold_db': round(threshold, 3),
            'baseline_status': status
        }

    except Exception as e:
        print(f"    ERROR: {e}")
        return {
            **context,
            'affected_area_km2': None,
            'area_s1_km2': None, 'area_s2_km2': None,
            'ndwi_flood_area_km2': None,
            'ndwi_pre_water_km2': None,
            'ndwi_during_water_km2': None,
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


# ══ (OLD) center single-patch method — superseded by full-AOI tiling. Kept for reference ══
_OLD_CENTER_PATCH_CODE = r'''
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
    analysis_key = _row_key(row)
    state     = row['state']
    lat       = float(row['lat'])
    lon       = float(row['lon'])
    start_str = row['start_date']
    print(f"\n  [Track B] [{event_id}] {state} — {start_str}")

    bbox     = [float(x) for x in row['bbox'].split(',')]
    # region   = ee.Geometry.Rectangle(bbox)   # (old) loose bbox
    region   = get_region(row)                  # state AOI (shared with Track A)
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
'''  # ══ (end of OLD) ══


# ══════════════════════════════════════════════════════════════════════════════
# Tile the whole state AOI into 64x64 patches
#   - getDownloadURL(NPY) block download -> preserves pixel order (fixes toList reshape bug)
#   - keep only tiles that are clear (cloud/nodata-free) in EVERY timestep (B is optical)
# ══════════════════════════════════════════════════════════════════════════════

def _download_block(image, region_block):
    """Download one block as NPY -> order-preserving structured array (bands + 'valid').
    valid = 1 only where every band is present (not cloud/nodata)."""
    valid = image.mask().reduce(ee.Reducer.min()).rename('valid').toByte()
    stack = image.select(SITS_BANDS).toInt16().addBands(valid)   # int16 keeps NPY under the 48MB request limit
    url = stack.getDownloadURL({'region': region_block, 'scale': 10, 'format': 'NPY'})
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=180)
            r.raise_for_status()
            return np.load(io.BytesIO(r.content))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def _append_h5(f, pre, post, coord):
    """Append this block's patch batch to the open hdf5's resizable datasets."""
    for name, val in (('pre', pre), ('post', post), ('coords', coord)):
        ds = f[name]
        n0 = ds.shape[0]
        ds.resize(n0 + val.shape[0], axis=0)
        ds[n0:] = val


def _tile_region(images, region, hdf, done_blocks, blocks_ckpt):
    """Tile the state AOI into 64x64 tiles, download block by block, keep only
    tiles that are clear in every timestep, and append them to the open hdf5.
    Skips blocks already in done_blocks and records each finished block to blocks_ckpt
    (block-level resume). Returns the total number of patches in the hdf5."""
    ring = region.bounds().coordinates().getInfo()[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    minx, maxx = min(lons), max(lons)
    miny, maxy = min(lats), max(lats)
    clat = (miny + maxy) / 2.0
    # Approx degree grid for tiling. GEE's actual pixel grid may differ by <1px, so the
    # stored coords (row/col/lat/lon) are approximate metadata; each 64x64 patch itself is intact.
    dlat = SITS_PATCH_SIZE * 10 / 110540.0
    dlon = SITS_PATCH_SIZE * 10 / (111320.0 * math.cos(math.radians(clat)))
    npy = int((maxy - miny) / dlat)   # tiles tall
    npx = int((maxx - minx) / dlon)   # tiles wide
    P = SITS_PATCH_SIZE
    all_blocks = [(bi, bj) for bi in range(0, npy, SITS_BLOCK_PATCHES)
                  for bj in range(0, npx, SITS_BLOCK_PATCHES)]

    def _blk_geom(bi, bj):
        pi = min(bi + SITS_BLOCK_PATCHES, npy)
        pj = min(bj + SITS_BLOCK_PATCHES, npx)
        return ee.Geometry.Rectangle([minx + bj * dlon, maxy - pi * dlat,
                                      minx + pj * dlon, maxy - bi * dlat])

    # Only download blocks intersecting the state AOI (skip bbox corners outside it).
    feats = [ee.Feature(_blk_geom(bi, bj), {'i': i}) for i, (bi, bj) in enumerate(all_blocks)]
    inside = set(ee.FeatureCollection(feats).filterBounds(region)
                 .aggregate_array('i').getInfo())
    todo = [(i, bi, bj) for i, (bi, bj) in enumerate(all_blocks)
            if i in inside and i not in done_blocks]
    print(f"    tiling: {npx}x{npy} tiles (@10m), "
          f"{len(inside)}/{len(all_blocks)} blocks in state AOI, {len(todo)} to download")
    bar = tqdm(todo, desc='    downloading', unit='blk')
    failed = 0
    for i, bi, bj in bar:
        pi = min(bi + SITS_BLOCK_PATCHES, npy)
        pj = min(bj + SITS_BLOCK_PATCHES, npx)
        lon0, lon1 = minx + bj * dlon, minx + pj * dlon
        lat_top, lat_bot = maxy - bi * dlat, maxy - pi * dlat
        block = ee.Geometry.Rectangle([lon0, lat_bot, lon1, lat_top])
        try:
            # download the 5 timesteps of this block concurrently (order preserved)
            with ThreadPoolExecutor(max_workers=len(images)) as ex:
                arrs = list(ex.map(lambda im: _download_block(im, block), images))
        except Exception as e:
            bar.write(f"      block ({bi},{bj}) download failed: {e}")
            failed += 1
            continue

        H = min(a.shape[0] for a in arrs)
        W = min(a.shape[1] for a in arrs)
        ny, nx = H // P, W // P

        b_pre, b_post, b_coord = [], [], []
        for r in range(ny):
            for c in range(nx):
                rs, cs = r * P, c * P
                # keep only tiles clear enough in EVERY timestep
                vfr = [float(a['valid'][rs:rs+P, cs:cs+P].mean()) for a in arrs]
                if min(vfr) < SITS_KEEP_VALID:
                    continue
                stacks = []
                for a in arrs:
                    bands = np.stack([a[b][rs:rs+P, cs:cs+P] for b in SITS_BANDS]).astype(np.float32)
                    stacks.append(np.clip(bands / SITS_NORM, 0, 1))  # (nbands,64,64)
                b_pre.append(np.stack(stacks[:SITS_N_PRE]))           # (4,10,64,64)
                b_post.append(np.stack(stacks[SITS_N_PRE:]))          # (1,10,64,64)
                plat = lat_top - (r + 0.5) * dlat
                plon = lon0 + (c + 0.5) * dlon
                b_coord.append([(bi+r)*P, (bj+c)*P, plat, plon])

        if b_pre:
            _append_h5(hdf, np.stack(b_pre), np.stack(b_post),
                       np.array(b_coord, dtype='float64'))
        done_blocks.add(i)
        with open(blocks_ckpt, 'w') as cf:
            json.dump(sorted(done_blocks), cf)
        bar.set_postfix(kept=hdf['pre'].shape[0])
    return hdf['pre'].shape[0], failed


def _ndwi_water_frac(img, region):
    """Fraction of the state AOI's valid pixels with NDWI>0 (water)."""
    water = img.normalizedDifference(['B3', 'B8']).gt(0)
    return water.reduceRegion(ee.Reducer.mean(), region, scale=100,
                              maxPixels=1e9, bestEffort=True).values().get(0)


# ── (OLD) driest-only baseline — replaced by _pick_baseline (clear-first). Kept for reference ──
_OLD_DRY_BASELINE = r'''
def _dry_baseline(s2, region, event_dt, n_pre=SITS_N_PRE, n_years=6):
    """Baseline t1..t4 = the n_pre 'driest' SAME-SEASON composites (all before the event)."""
    cand = []
    for yr in range(event_dt.year - n_years, event_dt.year + 1):
        for off in (-2, -1, 0, 1, 2):
            y, mo = yr, event_dt.month + off
            if mo < 1:
                y, mo = y - 1, mo + 12
            elif mo > 12:
                y, mo = y + 1, mo - 12
            if datetime(y, mo, 15) >= event_dt:
                continue
            img, _ = _monthly_composite_sits(s2, datetime(y, mo, 15))
            if img is None:
                continue
            wf = _ndwi_water_frac(img, region).getInfo()
            if wf is None:
                continue
            cand.append((f"{y:04d}-{mo:02d}", img, float(wf)))
    print(f"    baseline candidates found: {len(cand)}")
    if len(cand) < n_pre:
        return None
    cand.sort(key=lambda c: c[2])
    return sorted(cand[:n_pre], key=lambda c: c[0])
'''  # ── (end of OLD) ──


def _pick_baseline(s2, region, event_dt, n_pre=SITS_N_PRE, n_years=3, min_clear=0.5):
    """Baseline t1..t4: prefer CLOUD-FREE, same-season, recent composites; if not enough,
    fall back to the event year's clear months; keep a mix of the clearest and driest.
      pool A (preferred) = same calendar month +/-1 over the previous n_years
      pool B (fallback)  = the event year's months before the event
    Each candidate is scored by clear fraction (non-cloud) and NDWI water fraction (dryness).
    Returns [(date_str, img, clear_frac, water_frac)] date-sorted, or None."""

    def score(y, mo):
        if mo < 1:
            y, mo = y - 1, mo + 12
        elif mo > 12:
            y, mo = y + 1, mo - 12
        if datetime(y, mo, 15) >= event_dt:
            return None
        img, _ = _monthly_composite_sits(s2, datetime(y, mo, 15))
        if img is None:
            return None
        clear = (img.mask().reduce(ee.Reducer.min()).rename('c')
                 .reduceRegion(ee.Reducer.mean(), region, 100,
                               maxPixels=1e9, bestEffort=True).get('c'))
        info = ee.Dictionary({'clear': clear,
                              'water': _ndwi_water_frac(img, region)}).getInfo()
        if info.get('clear') is None:
            return None
        return (f"{y:04d}-{mo:02d}", img,
                float(info['clear']), float(info.get('water') or 0.0))

    def gather(pairs):
        out = []
        for y, mo in pairs:
            c = score(y, mo)
            if c is not None:
                out.append(c)
        return out

    # pool A: same month +/-1 over the previous n_years (same season, preferred)
    poolA = [(yr, event_dt.month + off)
             for yr in range(event_dt.year - n_years, event_dt.year)
             for off in (-1, 0, 1)]
    cands = [c for c in gather(poolA) if c[2] >= min_clear]

    # pool B fallback: the event year's clear months (before the event)
    if len(cands) < n_pre:
        seen = {c[0] for c in cands}
        poolB = [(event_dt.year, mo) for mo in range(1, 13)]
        cands += [c for c in gather(poolB) if c[2] >= min_clear and c[0] not in seen]

    print(f"    baseline candidates (clear>={min_clear}): {len(cands)}")
    if len(cands) < n_pre:
        return None

    # diversity: take the 2 clearest, then fill with the driest (dedup by date)
    chosen, seen = [], set()
    for c in sorted(cands, key=lambda x: -x[2])[:2] + sorted(cands, key=lambda x: x[3]):
        if c[0] in seen:
            continue
        chosen.append(c)
        seen.add(c[0])
        if len(chosen) == n_pre:
            break
    return sorted(chosen, key=lambda c: c[0])   # date ascending -> t1..t4


def prepare_sits_patch(row):
    """Track B: tile the state AOI and save the time series to HDF5.
    Each patch = (pre: 4x10x64x64, post: 1x10x64x64), coords=(row,col,lat,lon).
    Baseline t1..t4 = driest same-season composites (removes seasonal change), t5 = event."""
    event_id  = row['event_id']
    state     = row['state']
    start_str = row['start_date']
    print(f"\n  [Track B] [{analysis_key}] {state}/{row.get('district', '')} AOI — {start_str}")

    region   = get_region(row)
    s2       = _get_s2_sits(region)
    event_dt = datetime.strptime(start_str, '%Y-%m-%d')

    # Timesteps: t1..t4 = driest same-season composites (same month +/-1 over prior years),
    #            t5 = event-month post. Same-season baseline removes seasonal change.
    baseline = _pick_baseline(s2, region, event_dt)
    if baseline is None:
        print("    -> not enough clear baseline candidates -> skip")
        return None
    images = [b[1] for b in baseline]
    tags = [f"{b[0]}(c{b[2]:.2f}/w{b[3]:.2f})" for b in baseline]

    post_col = s2.filterDate(ee.Date(start_str), ee.Date(start_str).advance(14, 'day'))
    post_n = post_col.size().getInfo()
    if post_n == 0:
        print("    -> no post imagery -> skip")
        return None
    images.append(post_col.median())
    tags.append(f'post({post_n})')
    print("    timesteps: " + " | ".join(tags))

    images = [im.clip(region) for im in images]   # outside the state AOI is masked

    os.makedirs(SITS_OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(SITS_OUTPUT_DIR, f'{analysis_key}.h5')
    blocks_ckpt = out_path + '.blocks.json'
    P, B = SITS_PATCH_SIZE, len(SITS_BANDS)

    # Block-level resume: continue if a partial h5 + its block checkpoint both exist
    done_blocks = set()
    resume = os.path.exists(out_path) and os.path.exists(blocks_ckpt)
    if resume and not _h5_identity_matches(out_path, row):
        print("    cache identity changed or metadata incomplete -> restarting H5")
        resume = False
    if resume:
        with open(blocks_ckpt) as bf:
            done_blocks = set(json.load(bf))
        print(f"    resuming: {len(done_blocks)} blocks already done")

    with h5py.File(out_path, 'a' if resume else 'w') as f:
        if not resume:
            f.create_dataset('pre',  shape=(0, SITS_N_PRE, B, P, P),
                             maxshape=(None, SITS_N_PRE, B, P, P), dtype='float32',
                             chunks=(1, SITS_N_PRE, B, P, P))
            f.create_dataset('post', shape=(0, 1, B, P, P),
                             maxshape=(None, 1, B, P, P), dtype='float32',
                             chunks=(1, 1, B, P, P))
            f.create_dataset('coords', shape=(0, 4), maxshape=(None, 4), dtype='float64')
            meta = f.create_group('meta')
            meta.attrs['event_id']    = event_id
            meta.attrs['event_district_id'] = str(row.get('event_district_id', ''))
            meta.attrs['source_record_id'] = str(row.get('source_record_id', ''))
            meta.attrs['state']       = state
            meta.attrs['district']    = str(row['district'])
            meta.attrs['start_date']  = start_str
            meta.attrs['geometry_id'] = str(row.get('geometry_id', ''))
            meta.attrs['bands']       = ','.join(SITS_BANDS)
            meta.attrs['n_pre']       = SITS_N_PRE
            meta.attrs['patch_size']  = P
            meta.attrs['coords_cols'] = 'row,col,lat,lon'
        n, failed = _tile_region(images, region, f, done_blocks, blocks_ckpt)

    complete = (failed == 0)
    # drop the block checkpoint only if every block succeeded; otherwise keep it so a
    # re-run resumes and retries the failed blocks
    if complete and os.path.exists(blocks_ckpt):
        os.remove(blocks_ckpt)
    print(f"    Saved: {out_path}  [{n} clear patches, {failed} blocks failed]")
    return out_path, complete


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--track', choices=['A', 'B', 'both'],
                        default='both',
                        help='Which track to run (default: both)')
    parser.add_argument('--events', nargs='*', default=None,
                        help='Only run these event_ids (e.g. --events EVENT_ID). Default: all')
    parser.add_argument('--reverse', action='store_true',
                        help='Process events last-to-first (last event -> first event)')
    args = parser.parse_args()

    print("=" * 65)
    print("CVND SATELLITE PIPELINE")
    print(f"  Running: Track {args.track.upper()}")
    print("=" * 65)

    ensure_gee()

    events = pd.read_csv(EVENTS_CSV)
    events['_analysis_key'] = events.apply(_row_key, axis=1)
    event_by_key = {_row_key(row): row for _, row in events.iterrows()}
    if args.events:
        events = events[events['_analysis_key'].isin(args.events) | events['event_id'].isin(args.events)]
        print(f"  Filtered to events: {args.events}")
    if args.reverse:
        events = events.iloc[::-1]
        print("  Reverse order: last -> first")
    for target in (CHECKPOINT_A, CHECKPOINT_B, FLOOD_EXTENT_CSV, SITS_INDEX_CSV):
        os.makedirs(os.path.dirname(target), exist_ok=True)
    os.makedirs(SITS_OUTPUT_DIR, exist_ok=True)

    # ── Track A ───────────────────────────────────────────────────────────────
    if args.track in ('A', 'both'):
        print("\n" + "─" * 65)
        print("TRACK A — BI-TEMPORAL BASELINE (S1 Otsu + S2 NDWI)")
        print("─" * 65)

        completed_a = load_checkpoint(CHECKPOINT_A)
        stale_a = [key for key, entry in completed_a.items()
                   if key not in event_by_key or not _cache_identity_matches(entry, event_by_key[key])
                   or str(entry.get('baseline_status', entry.get('status', ''))).startswith('ERROR')]
        for key in stale_a:
            del completed_a[key]
        if stale_a:
            print(f"Discarded {len(stale_a)} stale Track-A cache entries")

        # Seed with existing flood_extent.csv if checkpoint is empty
        if not completed_a and os.path.exists(FLOOD_EXTENT_CSV):
            existing = pd.read_csv(FLOOD_EXTENT_CSV)
            # Only seed if it has the new column schema
            if 'affected_area_km2' in existing.columns:
                for _, r in existing.iterrows():
                    key = _row_key(r)
                    if key in event_by_key and _cache_identity_matches(r, event_by_key[key]) and not str(r.get('baseline_status', '')).startswith('ERROR'):
                        completed_a[key] = r.to_dict()
                save_checkpoint(completed_a, CHECKPOINT_A)
                print(f"Seeded {len(completed_a)} events from existing "
                      f"flood_extent.csv")

        done_a     = set(completed_a.keys())
        remaining_a = events[~events['_analysis_key'].isin(done_a)]
        print(f"Already done: {len(done_a)} | Remaining: {len(remaining_a)}\n")

        for i, (_, row) in enumerate(remaining_a.iterrows(), 1):
            result = detect_flood_baseline(row)
            completed_a[_row_key(row)] = result
            save_checkpoint(completed_a, CHECKPOINT_A)

            if (len(done_a) + i) % 10 == 0:
                pd.DataFrame(list(completed_a.values())).to_csv(
                    FLOOD_EXTENT_CSV, index=False)
                print(f"  >> Track A checkpoint: "
                      f"{len(done_a)+i}/{len(events)} done")

        df_a = pd.DataFrame(list(completed_a.values()))
        sort_cols = [c for c in ['event_district_id', 'event_id'] if c in df_a.columns]
        if sort_cols:
            df_a = df_a.sort_values(sort_cols, na_position='last').reset_index(drop=True)
        df_a.to_csv(FLOOD_EXTENT_CSV, index=False)

        ok_a = df_a[df_a['baseline_status'].isin(['OK', 'ZERO_AREA',
                                                   'SKIPPED_NO_S1_IMAGERY'])]
        print(f"\nTrack A complete: {len(ok_a)}/{len(events)} events")
        print(f"Saved: {FLOOD_EXTENT_CSV}")
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
        stale_b = [key for key, entry in completed_b.items()
                   if key not in event_by_key or not _cache_identity_matches(entry, event_by_key[key])
                   or str(entry.get('baseline_status', entry.get('status', ''))).startswith('ERROR')]
        for key in stale_b:
            del completed_b[key]
        if stale_b:
            print(f"Discarded {len(stale_b)} stale Track-B cache entries")
        done_b      = set(completed_b.keys())
        remaining_b = events[~events['_analysis_key'].isin(done_b)]
        print(f"Already done: {len(done_b)} | Remaining: {len(remaining_b)}\n")

        for _, row in remaining_b.iterrows():
            ev = _row_key(row)
            try:
                res = prepare_sits_patch(row)
            except Exception as e:
                print(f"  ERROR {ev}: {e}")
                completed_b[ev] = {'event_district_id': row.get('event_district_id'),
                                   'event_id': row['event_id'], 'source_record_id': row.get('source_record_id'),
                                   'state': row.get('state'), 'district': row.get('district'),
                                   'start_date': row.get('start_date'), 'h5_path': None,
                                   'status': f'ERROR: {e}'}
                save_checkpoint(completed_b, CHECKPOINT_B)
                continue
            if res is None:                        # no clear baseline / no post -> cloudy, don't retry
                completed_b[ev] = {'event_district_id': row.get('event_district_id'),
                                   'event_id': row['event_id'], 'source_record_id': row.get('source_record_id'),
                                   'state': row.get('state'), 'district': row.get('district'),
                                   'start_date': row.get('start_date'), 'h5_path': None,
                                   'status': 'SKIPPED_CLOUDY'}
                save_checkpoint(completed_b, CHECKPOINT_B)
                continue
            path, complete = res
            if not complete:                       # some blocks failed -> NOT marked done, retry next run
                print(f"  {ev}: incomplete (failed blocks) -> will retry on re-run")
                continue
            completed_b[ev] = {'event_district_id': row.get('event_district_id'),
                               'event_id': row['event_id'], 'source_record_id': row.get('source_record_id'),
                               'state': row.get('state'), 'district': row.get('district'),
                               'start_date': row.get('start_date'), 'h5_path': path, 'status': 'OK'}
            save_checkpoint(completed_b, CHECKPOINT_B)

        df_b = pd.DataFrame(list(completed_b.values()))
        sort_cols = [c for c in ['event_district_id', 'event_id'] if c in df_b.columns]
        if sort_cols:
            df_b = df_b.sort_values(sort_cols, na_position='last').reset_index(drop=True)
        df_b.to_csv(SITS_INDEX_CSV, index=False)

        ok_b = df_b[df_b['status'] == 'OK']
        print(f"\nTrack B complete: {len(ok_b)}/{len(events)} patches")
        print(f"Index: {SITS_INDEX_CSV}")
        print(f"\nNext steps:")
        print(f"  1. Upload {SITS_OUTPUT_DIR}/ to Google Drive")
        print('  2. Run src/run_sits_inference.py locally when the verified checkpoint is available.')
        print(f"  3. Place score NPZs in {data_path('district_sits_scores')}/")
        print(f"  4. Run merge_results.py → build_flood_area_table.py → join_district_flood_articles.py")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("DONE")
    print("=" * 65)
