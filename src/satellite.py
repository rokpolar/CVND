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
from typing import NamedTuple

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

from gee_config import initialize_gee
from cvnd_layout import data_path
from district_keys import analysis_key, cache_stem
from flood_spec import (AOI_COLUMNS, IDENTITY_COLUMNS, SPEC, SPEC_VERSION,
                        TRACK_A_COLUMNS, otsu_from_histogram, spec_version)


def ensure_gee() -> None:
    """Initialize Earth Engine only for a call that actually needs it."""
    if ee is None:
        raise RuntimeError("Earth Engine is required for satellite operations")
    initialize_gee()

# ═══════════════════════════════════════════════════════════════════════════════
# satellite.py — CVND Flood Detection Pipeline (optional; SKIP_GEE=1 by default)
# ───────────────────────────────────────────────────────────────────────────────
# Every area is measured under flood_spec.SPEC: post [onset, onset+14d), pre
# [onset-30d, onset) median, max-water post composite, one eligibility mask
# (JRC permanent water, slope, India LSIB), pixelArea sums at 10 m, and the same
# new-water definition  water(post) AND NOT water(pre) AND eligible  for S1, S2
# NDWI and the SITS tiles.
#
# Track A — S1 (Otsu) + S2 NDWI new water over the district AOI, plus post-window
#   cloud QA. Output: data/cache/district/flood_extent.csv
#
# Track B — SITS-Extreme-VAE data preparation
#   Output: data/cache/district/sits_patches/<cache_stem(event_district_id)>.h5
#   Next:   run src/run_sits_inference.py locally when the verified checkpoint
#           is available → sits_scores/*.npz → merge_results.py
#           → district_flood_combined.csv → build_flood_area_table.py
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
SITS_PATCH_SIZE = SPEC.sits_patch_px
SITS_N_PRE      = SPEC.sits_n_pre  # baseline t1..t4 (same-season composites); t5 = post window
SITS_NORM       = 10000.0
SITS_OUTPUT_DIR = str(data_path("district_sits_patches"))

# Tiling (whole-district-AOI) settings
SITS_BLOCK_PATCHES = 16     # download block = 16*64 = 1024 px/side (keeps NPY request small)
SITS_KEEP_VALID    = SPEC.sits_keep_valid  # keep a tile only if >= this fraction is clear in EVERY timestep

# Per-tile measurement layers stored next to the model inputs.
NDWI_SCALE  = 10000
NDWI_NODATA = -32768
MASK_BITS   = 'bit0=eligible,bit1=valid_all'


# ══════════════════════════════════════════════════════════════════════════════
# CHECKPOINT UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def load_checkpoint(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f'{type(value).__name__} is not JSON serializable')

def save_checkpoint(data, path):
    with open(path, 'w') as f:
        json.dump(data, f, default=_json_default)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED MEASUREMENT HELPERS (one definition for Track A and Track B)
# ══════════════════════════════════════════════════════════════════════════════

def post_window(start, spec=SPEC):
    """[onset, onset + post_window_days): the same half-open window as the news."""
    onset = ee.Date(start)
    return onset, onset.advance(spec.post_window_days, 'day')


def pre_window(start, spec=SPEC):
    """[onset - pre_window_days, onset)."""
    onset = ee.Date(start)
    return onset.advance(-spec.pre_window_days, 'day'), onset


def measurement_mask(spec=SPEC):
    """Single-band ``eligible``: not JRC permanent water, flat, inside India."""
    permanent = (ee.Image(spec.jrc_asset).select('occurrence')
                 .gte(spec.jrc_permanent_occurrence_gte).unmask(0))
    flat = ee.Terrain.slope(ee.Image(spec.srtm_asset)).lt(spec.slope_max_deg)
    country = (ee.FeatureCollection(spec.lsib_asset)
               .filter(ee.Filter.eq('country_na', spec.lsib_country)))
    return permanent.Not().And(flat).clipToCollection(country).rename('eligible')


def _mask_s2_clouds(img, spec=SPEC):
    scl = img.select('SCL')
    keep = scl.neq(spec.s2_scl_exclude[0])
    for value in spec.s2_scl_exclude[1:]:
        keep = keep.And(scl.neq(value))
    return img.updateMask(keep)


def s2_collection(region, spec=SPEC):
    """Cloud-masked Sentinel-2 SR over the AOI (all bands)."""
    return (ee.ImageCollection(spec.s2_collection)
            .filterBounds(region)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', spec.s2_cloudy_pixel_pct_max))
            .map(lambda img: _mask_s2_clouds(img, spec)))


def s1_collection(region, spec=SPEC):
    """Sentinel-1 IW VV over the AOI, on every orbit direction in the spec."""
    return (ee.ImageCollection(spec.s1_collection)
            .filter(ee.Filter.eq('instrumentMode', 'IW'))
            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
            .filter(ee.Filter.inList('orbitProperties_pass', list(spec.s1_orbits)))
            .filterBounds(region))


def _ndwi(img, spec=SPEC):
    return img.normalizedDifference(list(spec.ndwi_bands)).rename('ndwi')


def ndwi_composites(pre_col, post_col, spec=SPEC):
    """(pre median NDWI, post NDWI composite). max_water keeps the wettest value."""
    pre = pre_col.map(lambda img: _ndwi(img, spec)).median()
    post = post_col.map(lambda img: _ndwi(img, spec))
    return pre, (post.max() if spec.post_composite == 'max_water' else post.median())


def _despeckle(img, spec=SPEC):
    return (img.select('VV')
            .focal_median(spec.s1_speckle_radius_px, 'square', 'pixels')
            .rename('VV'))


def _area_value_km2(stats: dict, band: str) -> float | None:
    """Convert a reduceRegion result while preserving null as no observation."""
    if not stats or stats.get(band) is None:
        return None
    return round(float(stats[band]) / 1e6, 4)


def reduce_areas_km2(masks: dict, region, spec=SPEC) -> dict:
    """pixelArea sum of each 0/1 mask at the spec scale → {name: km² | None}.

    bestEffort is off: a reduction that would need a coarser scale fails and
    leaves an ERROR row to retry instead of silently changing resolution.
    """
    names = list(masks)
    stack = ee.Image.cat([masks[name].rename(name) for name in names])
    stats = stack.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region, scale=spec.reduce_scale_m,
        maxPixels=spec.max_pixels, tileScale=spec.tile_scale, bestEffort=False,
    ).getInfo()
    return {name: _area_value_km2(stats, name) for name in names}


def otsu_backscatter_threshold(image, region, spec=SPEC):
    """Otsu on post-event VV backscatter (water = dark), clamped to the VV water
    range. Returns (threshold_db, fallback_used, separability)."""
    stats = image.reduceRegion(
        reducer=ee.Reducer.histogram(spec.otsu_bins, spec.otsu_bucket_db),
        geometry=region, scale=spec.reduce_scale_m, maxPixels=spec.max_pixels,
        tileScale=spec.tile_scale, bestEffort=False,
    ).getInfo() or {}
    hist = next(iter(stats.values()), None)
    if hist and 'histogram' in hist and 'bucketMeans' in hist:
        threshold, separability = otsu_from_histogram(hist['histogram'], hist['bucketMeans'])
    else:
        threshold, separability = None, 0.0
    if threshold is None or not (spec.otsu_lo_db <= threshold <= spec.otsu_hi_db):
        print(f"    (Otsu={threshold} outside [{spec.otsu_lo_db},{spec.otsu_hi_db}] "
              f"→ fallback {spec.otsu_fallback_db} dB)")
        return spec.otsu_fallback_db, True, separability
    print(f"    (Otsu={threshold:.3f} dB in range)")
    return threshold, False, separability


def s2_clear_fraction(post_col, region, spec=SPEC):
    """Fraction of the AOI seen cloud-free at least once in the post window."""
    bands = list(spec.ndwi_bands)
    clear = post_col.map(
        lambda img: img.select(bands).mask().reduce(ee.Reducer.min()).rename('clear')
    ).max()
    stats = clear.unmask(0).reduceRegion(
        reducer=ee.Reducer.mean(), geometry=region, scale=spec.qa_scale_m,
        maxPixels=spec.max_pixels, tileScale=spec.tile_scale, bestEffort=False,
    ).getInfo() or {}
    value = stats.get('clear')
    return None if value is None else float(value)


class TileGrid(NamedTuple):
    minx: float
    maxx: float
    miny: float
    maxy: float
    dlat: float
    dlon: float
    npx: int      # tiles wide
    npy: int      # tiles tall


def grid_from_bounds(minx, miny, maxx, maxy, spec=SPEC) -> TileGrid:
    # Approx degree grid for tiling. GEE's actual pixel grid may differ by <1px, so
    # tile coords (row/col/lat/lon) are approximate metadata; each tile is intact.
    clat = (miny + maxy) / 2.0
    size_m = spec.sits_patch_px * spec.sits_pixel_m
    dlat = size_m / 110540.0
    dlon = size_m / (111320.0 * math.cos(math.radians(clat)))
    return TileGrid(minx, maxx, miny, maxy, dlat, dlon,
                    int((maxx - minx) / dlon), int((maxy - miny) / dlat))


def tile_grid(region, spec=SPEC) -> TileGrid:
    ring = region.bounds().coordinates().getInfo()[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return grid_from_bounds(min(lons), min(lats), max(lons), max(lats), spec)


# ══════════════════════════════════════════════════════════════════════════════
# TRACK A — S1 + S2 NEW WATER OVER THE DISTRICT AOI
# ══════════════════════════════════════════════════════════════════════════════

def detect_flood_s2(region, start_date, eligible, spec=SPEC) -> dict:
    """Sentinel-2 NDWI new water. Areas are None (not zero) without post or pre
    imagery; cloud_pct is the share of the AOI never seen clear post-onset."""
    s2 = s2_collection(region, spec)
    pre_col = s2.filterDate(*pre_window(start_date, spec))
    post_col = s2.filterDate(*post_window(start_date, spec))
    n_post = int(post_col.size().getInfo())
    n_pre = int(pre_col.size().getInfo())
    result = {'area_s2_km2': None, 'ndwi_pre_water_km2': None,
              'ndwi_during_water_km2': None, 's2_pre_images': n_pre,
              's2_post_images': n_post, 'cloud_pct': 100.0}
    if n_post == 0:
        return result
    clear = s2_clear_fraction(post_col, region, spec)
    result['cloud_pct'] = None if clear is None else round((1 - clear) * 100, 1)
    if n_pre == 0:
        # A post image alone cannot identify *new* water; retaining None keeps
        # data absence distinct from an observed zero-area result.
        return result

    pre_ndwi, post_ndwi = ndwi_composites(pre_col, post_col, spec)
    water_gt = spec.ndwi_water_gt
    during = post_ndwi.gt(water_gt)
    flood = during.And(pre_ndwi.lte(water_gt)).And(eligible)
    areas = reduce_areas_km2({
        'flood': flood,
        'pre': pre_ndwi.gt(water_gt).And(eligible),
        'during': during.And(eligible),
    }, region, spec)
    result.update(area_s2_km2=areas['flood'], ndwi_pre_water_km2=areas['pre'],
                  ndwi_during_water_km2=areas['during'])
    return result


def detect_flood_s1(region, start_date, eligible, spec=SPEC) -> dict:
    """Sentinel-1 bi-temporal new water: dark in the post composite, not dark in
    the pre median, eligible. The Otsu threshold is taken on the post composite."""
    s1 = s1_collection(region, spec)
    pre_col = s1.filterDate(*pre_window(start_date, spec))
    post_col = s1.filterDate(*post_window(start_date, spec))
    n_pre = int(pre_col.size().getInfo())
    n_post = int(post_col.size().getInfo())
    result = {'area_s1_km2': None, 's1_pre_images': n_pre, 's1_post_images': n_post,
              'otsu_threshold_db': None, 'otsu_fallback_used': None,
              'otsu_separability': None, 's1_orbit': None}
    if n_post:
        passes = sorted(set(post_col.aggregate_array('orbitProperties_pass')
                            .distinct().getInfo() or []))
        result['s1_orbit'] = 'BOTH' if len(passes) > 1 else (passes[0] if passes else None)
    if n_pre == 0 or n_post == 0:
        return result

    post_speckle = post_col.map(lambda img: _despeckle(img, spec))
    post_vv = (post_speckle.min() if spec.post_composite == 'max_water'
               else post_speckle.median())
    pre_vv = pre_col.map(lambda img: _despeckle(img, spec)).median()
    threshold, fallback, separability = otsu_backscatter_threshold(post_vv, region, spec)
    flood = post_vv.lt(threshold).And(pre_vv.lt(threshold).Not()).And(eligible)
    result.update(
        area_s1_km2=reduce_areas_km2({'flood': flood}, region, spec)['flood'],
        otsu_threshold_db=round(float(threshold), 3),
        otsu_fallback_used=bool(fallback),
        otsu_separability=round(float(separability), 4),
    )
    return result


GAUL_STATE_ALIASES = {
    'Odisha': 'Orissa',
    'Jammu and Kashmir': 'Jammu and Kashmir',
}

_IDENTITY_FIELDS = ('event_id', 'source_record_id', 'state', 'district', 'start_date')


def _cache_identity_matches(entry, row) -> bool:
    """Reject cache entries for a reused key whose source row or spec changed."""
    cached_spec = entry.get('spec_version') if hasattr(entry, 'get') else None
    if str(cached_spec).strip() != SPEC_VERSION:
        return False
    for field in _IDENTITY_FIELDS:
        expected = row.get(field)
        cached = entry.get(field) if hasattr(entry, 'get') else None
        if cached is None or (isinstance(cached, float) and pd.isna(cached)):
            return False
        if str(cached).strip() != str(expected).strip():
            return False
    return True


def _h5_identity_matches(path, row) -> bool:
    """Check Track-B metadata and layout before resuming a partial district cache."""
    try:
        with h5py.File(path, 'r') as handle:
            attrs = handle['meta'].attrs
            if str(attrs.get('spec_version', '')).strip() != SPEC_VERSION:
                return False
            if not all(name in handle for name in ('mask', 'ndwi_ref', 'pixel_area_m2')):
                return False
            return all(str(attrs.get(field, '')).strip() == str(row.get(field, '')).strip()
                       for field in _IDENTITY_FIELDS)
    except (OSError, KeyError, TypeError):
        return False


def _is_district_row(row) -> bool:
    level = str(row.get('aoi_level', '')).strip().lower()
    key = row.get('event_district_id') if hasattr(row, 'get') else None
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


def _feature_collection_for_aoi(row, spec=SPEC):
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
        collection = (ee.FeatureCollection(spec.gaul_level2)
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


def resolve_aoi(row, spec=SPEC) -> dict:
    """Resolve an event row to a strict AOI and provenance metadata.

    The returned geometry is a server-side EE geometry; callers that only need
    a status can catch the explicit ``ValueError`` without creating a fallback.
    """
    collection = _feature_collection_for_aoi(row, spec)
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
        'aoi_source': spec.gaul_level2 if level == 'district' else 'FAO/GAUL/2015/level1',
        'aoi_match_status': 'matched',
        'geometry_id': str(identifier),
        'aoi_area_km2': float(geometry.area(maxError=spec.aoi_max_error_m).getInfo()) / 1e6,
    }


def get_region(row):
    """Return the strictly matched state or district GAUL geometry.

    District rows never fall back to a state polygon when level-2 matching fails.
    """
    return resolve_aoi(row)['geometry']


def _aoi_context(row, spec=SPEC) -> dict:
    level = 'district' if _is_district_row(row) else 'state'
    return {
        'event_district_id': row.get('event_district_id') if level == 'district' else None,
        'event_id': row.get('event_id'),
        'source_record_id': row.get('source_record_id'),
        'start_date': row.get('start_date'),
        'state': row.get('state'),
        'district': row.get('district', ''),
        'aoi_level': level,
        'aoi_source': spec.gaul_level2 if level == 'district' else 'FAO/GAUL/2015/level1',
        'aoi_match_status': 'failed',
        'geometry_id': None,
        'aoi_area_km2': None,
    }


def detect_flood_baseline(row, spec=SPEC):
    """Track A: S1 and S2 new water over the district AOI, under one spec.

    Both areas are reported side by side; choosing between them is the merge's
    job only. A zero is an observed value, not a status.
    """
    context = _aoi_context(row, spec)
    empty = {column: None for column in TRACK_A_COLUMNS}
    print(f"\n  [Track A] [{analysis_key(row)}] {row.get('state')}/{row.get('district', '')} "
          f"({context['aoi_level']} AOI) ({row.get('start_date')})")
    try:
        aoi = resolve_aoi(row, spec)
        region = aoi['geometry']
        context.update({k: v for k, v in aoi.items() if k != 'geometry'})
        eligible = measurement_mask(spec)
        measured = dict(empty)
        measured.update(detect_flood_s2(region, row['start_date'], eligible, spec))
        measured.update(detect_flood_s1(region, row['start_date'], eligible, spec))
        observed = (measured['area_s1_km2'] is not None
                    or measured['area_s2_km2'] is not None)
        measured['baseline_status'] = 'OK' if observed else 'NO_IMAGERY'
        print(f"    S1: {measured['area_s1_km2']} km² ({measured['s1_post_images']} post imgs, "
              f"{measured['s1_orbit']})  S2 NDWI: {measured['area_s2_km2']} km² "
              f"({measured['s2_post_images']} post imgs, cloud {measured['cloud_pct']}%)")
    except Exception as e:
        print(f"    ERROR: {e}")
        measured = dict(empty, baseline_status=f'ERROR: {e}')
    measured['spec_version'] = spec_version(spec)
    return {**context, **measured}


# ══════════════════════════════════════════════════════════════════════════════
# TRACK B — SITS-EXTREME-VAE DATA PREPARATION
# ══════════════════════════════════════════════════════════════════════════════

def _monthly_composite_sits(s2, target_dt):
    start = ee.Date.fromYMD(target_dt.year, target_dt.month, 1)
    end   = start.advance(1, 'month')
    col   = s2.filterDate(start, end)
    n     = col.size().getInfo()
    if n == 0:
        return None, 0
    return col.median(), n


def measurement_aux_image(s2, start, spec=SPEC):
    """Per-pixel measurement layers downloaded with every SITS block: eligibility,
    pixel area (m²) and pre/post NDWI ×1e4 on Track A's windows and composites."""
    pre_ndwi, post_ndwi = ndwi_composites(s2.filterDate(*pre_window(start, spec)),
                                          s2.filterDate(*post_window(start, spec)), spec)

    def scaled(img, name):
        return img.multiply(NDWI_SCALE).round().toInt16().unmask(NDWI_NODATA).rename(name)

    return ee.Image.cat([
        measurement_mask(spec).unmask(0).toByte().rename('eligible'),
        ee.Image.pixelArea().toFloat().rename('area'),
        scaled(pre_ndwi, 'ndwi_pre'),
        scaled(post_ndwi, 'ndwi_post'),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# Tile the whole district AOI into 64x64 patches
#   - getDownloadURL(NPY) block download -> preserves pixel order (fixes toList reshape bug)
#   - keep only tiles that are clear (cloud/nodata-free) in EVERY timestep (B is optical)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_npy(image, region_block, spec=SPEC):
    url = image.getDownloadURL({'region': region_block, 'scale': spec.sits_pixel_m,
                                'format': 'NPY'})
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=180)
            r.raise_for_status()
            return np.load(io.BytesIO(r.content))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def _download_block(image, region_block, spec=SPEC):
    """Download one block as NPY -> order-preserving structured array (bands + 'valid').
    valid = 1 only where every band is present (not cloud/nodata)."""
    valid = image.mask().reduce(ee.Reducer.min()).rename('valid').toByte()
    stack = image.select(SITS_BANDS).toInt16().addBands(valid)   # int16 keeps NPY under the 48MB request limit
    return _fetch_npy(stack, region_block, spec)


def _tiles_from_block(arrs, aux, spec=SPEC) -> dict:
    """Cut one downloaded block into the tiles that are clear enough in every
    model timestep. ``arrs`` are the timestep arrays (bands + 'valid'); ``aux``
    holds eligible/area/ndwi_pre/ndwi_post on the same grid."""
    P = spec.sits_patch_px
    H = min(a.shape[0] for a in [*arrs, aux])
    W = min(a.shape[1] for a in [*arrs, aux])
    out = {name: [] for name in ('pre', 'post', 'mask', 'ndwi_ref', 'pixel_area_m2', 'rc')}
    for r in range(H // P):
        for c in range(W // P):
            win = (slice(r * P, (r + 1) * P), slice(c * P, (c + 1) * P))
            valid = [a['valid'][win].astype(bool) for a in arrs]
            if min(float(v.mean()) for v in valid) < spec.sits_keep_valid:
                continue
            stacks = [np.clip(np.stack([a[b][win] for b in SITS_BANDS]).astype(np.float32)
                              / SITS_NORM, 0, 1) for a in arrs]      # (nbands,64,64)
            out['pre'].append(np.stack(stacks[:spec.sits_n_pre]))  # (4,4,64,64)
            out['post'].append(np.stack(stacks[spec.sits_n_pre:]))  # (1,4,64,64)
            valid_all = np.logical_and.reduce(valid)
            eligible = aux['eligible'][win].astype(bool)
            out['mask'].append(eligible.astype(np.uint8) | (valid_all.astype(np.uint8) << 1))
            out['ndwi_ref'].append(np.stack([aux['ndwi_pre'][win],
                                             aux['ndwi_post'][win]]).astype(np.int16))
            out['pixel_area_m2'].append(np.float32(np.mean(aux['area'][win])))
            out['rc'].append((r, c))
    return out


def _append_h5(f, batch: dict):
    """Append this block's patch batch to the open hdf5's resizable datasets."""
    for name, val in batch.items():
        ds = f[name]
        n0 = ds.shape[0]
        ds.resize(n0 + val.shape[0], axis=0)
        ds[n0:] = val


def _tile_region(images, aux, region, hdf, done_blocks, blocks_ckpt, spec=SPEC):
    """Tile the district AOI into 64x64 tiles, download block by block, keep only
    tiles that are clear in every timestep, and append them to the open hdf5.
    Skips blocks already in done_blocks and records each finished block to blocks_ckpt
    (block-level resume). Returns (patches in the hdf5, failed blocks)."""
    grid = tile_grid(region, spec)
    P = spec.sits_patch_px
    B = SITS_BLOCK_PATCHES
    all_blocks = [(bi, bj) for bi in range(0, grid.npy, B) for bj in range(0, grid.npx, B)]

    def _blk_bounds(bi, bj):
        pi = min(bi + B, grid.npy)
        pj = min(bj + B, grid.npx)
        return [grid.minx + bj * grid.dlon, grid.maxy - pi * grid.dlat,
                grid.minx + pj * grid.dlon, grid.maxy - bi * grid.dlat]

    # Only download blocks intersecting the district AOI (skip bbox corners outside it).
    feats = [ee.Feature(ee.Geometry.Rectangle(_blk_bounds(bi, bj)), {'i': i})
             for i, (bi, bj) in enumerate(all_blocks)]
    inside = set(ee.FeatureCollection(feats).filterBounds(region)
                 .aggregate_array('i').getInfo())
    todo = [(i, bi, bj) for i, (bi, bj) in enumerate(all_blocks)
            if i in inside and i not in done_blocks]
    print(f"    tiling: {grid.npx}x{grid.npy} tiles (@{spec.sits_pixel_m}m), "
          f"{len(inside)}/{len(all_blocks)} blocks in district AOI, {len(todo)} to download")
    bar = tqdm(todo, desc='    downloading', unit='blk')
    failed = 0
    for i, bi, bj in bar:
        lon0, lat_bot, lon1, lat_top = _blk_bounds(bi, bj)
        block = ee.Geometry.Rectangle([lon0, lat_bot, lon1, lat_top])
        try:
            # model timesteps + measurement layers of this block, concurrently
            with ThreadPoolExecutor(max_workers=len(images) + 1) as ex:
                futures = [ex.submit(_download_block, im, block, spec) for im in images]
                futures.append(ex.submit(_fetch_npy, aux, block, spec))
                arrs = [fut.result() for fut in futures]
        except Exception as e:
            bar.write(f"      block ({bi},{bj}) download failed: {e}")
            failed += 1
            continue

        tiles = _tiles_from_block(arrs[:-1], arrs[-1], spec)
        if tiles['rc']:
            coords = [[(bi + r) * P, (bj + c) * P,
                       lat_top - (r + 0.5) * grid.dlat, lon0 + (c + 0.5) * grid.dlon]
                      for r, c in tiles['rc']]
            _append_h5(hdf, {
                'pre': np.stack(tiles['pre']),
                'post': np.stack(tiles['post']),
                'coords': np.array(coords, dtype='float64'),
                'mask': np.stack(tiles['mask']),
                'ndwi_ref': np.stack(tiles['ndwi_ref']),
                'pixel_area_m2': np.array(tiles['pixel_area_m2'], dtype='float32'),
            })
        done_blocks.add(i)
        with open(blocks_ckpt, 'w') as cf:
            json.dump(sorted(done_blocks), cf)
        bar.set_postfix(kept=hdf['pre'].shape[0])
    return hdf['pre'].shape[0], failed


def _ndwi_water_frac(img, region, spec=SPEC):
    """Fraction of the district AOI's valid pixels with NDWI above the water cut."""
    water = _ndwi(img, spec).gt(spec.ndwi_water_gt)
    return water.reduceRegion(reducer=ee.Reducer.mean(), geometry=region,
                              scale=spec.qa_scale_m, maxPixels=spec.max_pixels,
                              bestEffort=False).values().get(0)


def _pick_baseline(s2, region, event_dt, n_pre=SITS_N_PRE, n_years=3, min_clear=0.5,
                   spec=SPEC):
    """Baseline t1..t4 (VAE input only): prefer CLOUD-FREE, same-season, recent
    composites; if not enough, fall back to the event year's clear months; keep a
    mix of the clearest and driest.
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
                 .reduceRegion(reducer=ee.Reducer.mean(), geometry=region,
                               scale=spec.qa_scale_m, maxPixels=spec.max_pixels,
                               bestEffort=False).get('c'))
        info = ee.Dictionary({'clear': clear,
                              'water': _ndwi_water_frac(img, region, spec)}).getInfo()
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


def sits_h5_path(key) -> str:
    return os.path.join(SITS_OUTPUT_DIR, f'{cache_stem(key)}.h5')


def prepare_sits_patch(row, spec=SPEC):
    """Track B: tile the district AOI and save the time series to HDF5.
    Each patch = (pre: 4x4x64x64, post: 1x4x64x64) model inputs plus the
    measurement layers mask (bit0 eligible, bit1 valid_all), ndwi_ref (pre/post
    NDWI ×1e4) and pixel_area_m2; coords=(row,col,lat,lon).
    Baseline t1..t4 = clear/dry same-season composites (VAE input), t5 = post median."""
    key = analysis_key(row)
    event_id  = row['event_id']
    state     = row['state']
    start_str = row['start_date']
    print(f"\n  [Track B] [{key}] {state}/{row.get('district', '')} district AOI — {start_str}")

    aoi      = resolve_aoi(row, spec)
    region   = aoi['geometry']
    s2       = s2_collection(region, spec).select(SITS_BANDS)
    event_dt = datetime.strptime(start_str, '%Y-%m-%d')

    baseline = _pick_baseline(s2, region, event_dt, spec=spec)
    if baseline is None:
        print("    -> not enough clear baseline candidates -> skip")
        return None
    images = [b[1] for b in baseline]
    tags = [f"{b[0]}(c{b[2]:.2f}/w{b[3]:.2f})" for b in baseline]

    post_col = s2.filterDate(*post_window(start_str, spec))
    post_n = post_col.size().getInfo()
    if post_n == 0:
        print("    -> no post imagery -> skip")
        return None
    pre_n = s2.filterDate(*pre_window(start_str, spec)).size().getInfo()
    if pre_n == 0:
        print("    -> no pre-window imagery (no NDWI new-water reference) -> skip")
        return None
    images.append(post_col.median())   # model input t5 (RGB), not an area
    tags.append(f'post({post_n})')
    print("    timesteps: " + " | ".join(tags))

    images = [im.clip(region) for im in images]   # outside the district AOI is masked
    aux = measurement_aux_image(s2, start_str, spec)

    os.makedirs(SITS_OUTPUT_DIR, exist_ok=True)
    out_path = sits_h5_path(key)
    blocks_ckpt = out_path + '.blocks.json'
    P, B = spec.sits_patch_px, len(SITS_BANDS)

    # Block-level resume: continue if a partial h5 + its block checkpoint both exist
    done_blocks = set()
    resume = os.path.exists(out_path) and os.path.exists(blocks_ckpt)
    if resume and not _h5_identity_matches(out_path, row):
        print("    cache identity/spec changed or metadata incomplete -> restarting H5")
        resume = False
    if resume:
        with open(blocks_ckpt) as bf:
            done_blocks = set(json.load(bf))
        print(f"    resuming: {len(done_blocks)} blocks already done")

    with h5py.File(out_path, 'a' if resume else 'w') as f:
        if not resume:
            n_pre = spec.sits_n_pre
            f.create_dataset('pre',  shape=(0, n_pre, B, P, P),
                             maxshape=(None, n_pre, B, P, P), dtype='float32',
                             chunks=(1, n_pre, B, P, P))
            f.create_dataset('post', shape=(0, 1, B, P, P),
                             maxshape=(None, 1, B, P, P), dtype='float32',
                             chunks=(1, 1, B, P, P))
            f.create_dataset('coords', shape=(0, 4), maxshape=(None, 4), dtype='float64')
            f.create_dataset('mask', shape=(0, P, P), maxshape=(None, P, P),
                             dtype='uint8', chunks=(1, P, P))
            f.create_dataset('ndwi_ref', shape=(0, 2, P, P), maxshape=(None, 2, P, P),
                             dtype='int16', chunks=(1, 2, P, P))
            f.create_dataset('pixel_area_m2', shape=(0,), maxshape=(None,), dtype='float32')
            meta = f.create_group('meta')
            meta.attrs['event_id']    = event_id
            meta.attrs['event_district_id'] = str(row.get('event_district_id', ''))
            meta.attrs['source_record_id'] = str(row.get('source_record_id', ''))
            meta.attrs['state']       = state
            meta.attrs['district']    = str(row['district'])
            meta.attrs['start_date']  = start_str
            meta.attrs['geometry_id'] = str(aoi['geometry_id'])
            meta.attrs['bands']       = ','.join(SITS_BANDS)
            meta.attrs['n_pre']       = n_pre
            meta.attrs['patch_size']  = P
            meta.attrs['coords_cols'] = 'row,col,lat,lon'
            meta.attrs['spec_version'] = spec_version(spec)
            meta.attrs['ndwi_scale']  = NDWI_SCALE
            meta.attrs['ndwi_nodata'] = NDWI_NODATA
            meta.attrs['mask_bits']   = MASK_BITS
        n, failed = _tile_region(images, aux, region, f, done_blocks, blocks_ckpt, spec)

    complete = (failed == 0)
    # drop the block checkpoint only if every block succeeded; otherwise keep it so a
    # re-run resumes and retries the failed blocks
    if complete and os.path.exists(blocks_ckpt):
        os.remove(blocks_ckpt)
    print(f"    Saved: {out_path}  [{n} clear patches, {failed} blocks failed]")
    return out_path, complete


def _track_b_entry(row, h5_path, status):
    return {'event_district_id': row.get('event_district_id'),
            'event_id': row['event_id'], 'source_record_id': row.get('source_record_id'),
            'state': row.get('state'), 'district': row.get('district'),
            'start_date': row.get('start_date'), 'h5_path': h5_path, 'status': status,
            'spec_version': SPEC_VERSION}


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
                        help='Only run these event_district_ids or event_ids. Default: all')
    parser.add_argument('--reverse', action='store_true',
                        help='Process events last-to-first (last event -> first event)')
    args = parser.parse_args()

    print("=" * 65)
    print("CVND SATELLITE PIPELINE")
    print(f"  Running: Track {args.track.upper()}  |  spec {SPEC_VERSION}")
    print("=" * 65)

    ensure_gee()

    events = pd.read_csv(EVENTS_CSV)
    events['_analysis_key'] = events.apply(analysis_key, axis=1)
    event_by_key = {analysis_key(row): row for _, row in events.iterrows()}
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
        print("TRACK A — S1 OTSU + S2 NDWI NEW WATER (one measurement spec)")
        print("─" * 65)

        completed_a = load_checkpoint(CHECKPOINT_A)
        stale_a = [key for key, entry in completed_a.items()
                   if key not in event_by_key or not _cache_identity_matches(entry, event_by_key[key])
                   or str(entry.get('baseline_status', entry.get('status', ''))).startswith('ERROR')]
        for key in stale_a:
            del completed_a[key]
        if stale_a:
            print(f"Discarded {len(stale_a)} stale Track-A cache entries (identity, spec or ERROR)")

        # Seed with existing flood_extent.csv if checkpoint is empty
        if not completed_a and os.path.exists(FLOOD_EXTENT_CSV):
            existing = pd.read_csv(FLOOD_EXTENT_CSV)
            # Only rows measured under a recorded spec can be reused
            if 'spec_version' in existing.columns:
                for _, r in existing.iterrows():
                    key = analysis_key(r)
                    if key in event_by_key and _cache_identity_matches(r, event_by_key[key]) and not str(r.get('baseline_status', '')).startswith('ERROR'):
                        completed_a[key] = r.to_dict()
                save_checkpoint(completed_a, CHECKPOINT_A)
                print(f"Seeded {len(completed_a)} events from existing "
                      f"flood_extent.csv")

        track_a_columns = list(IDENTITY_COLUMNS + AOI_COLUMNS + TRACK_A_COLUMNS)
        done_a     = set(completed_a.keys())
        remaining_a = events[~events['_analysis_key'].isin(done_a)]
        print(f"Already done: {len(done_a)} | Remaining: {len(remaining_a)}\n")

        for i, (_, row) in enumerate(remaining_a.iterrows(), 1):
            result = detect_flood_baseline(row)
            completed_a[analysis_key(row)] = result
            save_checkpoint(completed_a, CHECKPOINT_A)

            if (len(done_a) + i) % 10 == 0:
                pd.DataFrame(list(completed_a.values())).reindex(columns=track_a_columns).to_csv(
                    FLOOD_EXTENT_CSV, index=False)
                print(f"  >> Track A checkpoint: "
                      f"{len(done_a)+i}/{len(events)} done")

        df_a = pd.DataFrame(list(completed_a.values())).reindex(columns=track_a_columns)
        sort_cols = [c for c in ['event_district_id', 'event_id'] if c in df_a.columns]
        if sort_cols:
            df_a = df_a.sort_values(sort_cols, na_position='last').reset_index(drop=True)
        df_a.to_csv(FLOOD_EXTENT_CSV, index=False)

        in_run = df_a.apply(analysis_key, axis=1).isin(set(events['_analysis_key']))
        ok_a = df_a[in_run & df_a['baseline_status'].isin(['OK', 'NO_IMAGERY'])]
        print(f"\nTrack A complete: {len(ok_a)}/{len(events)} events "
              f"(ERROR rows are retried on the next run)")
        print(f"Saved: {FLOOD_EXTENT_CSV}")
        print(df_a[['event_district_id', 'area_s1_km2', 'area_s2_km2', 'cloud_pct',
                    'baseline_status']].to_string(index=False))

    # ── Track B ───────────────────────────────────────────────────────────────
    if args.track in ('B', 'both'):
        print("\n" + "─" * 65)
        print("TRACK B — SITS-EXTREME-VAE PATCH PREPARATION")
        print(f"  Bands: {SITS_BANDS}")
        print(f"  Patch: {SITS_PATCH_SIZE}×{SITS_PATCH_SIZE}px @ {SPEC.sits_pixel_m}m | "
              f"{SITS_N_PRE} pre-event months + 1 post ({SPEC.post_window_days} d)")
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
            print(f"Discarded {len(stale_b)} stale Track-B cache entries (identity, spec or ERROR)")
        done_b      = set(completed_b.keys())
        remaining_b = events[~events['_analysis_key'].isin(done_b)]
        print(f"Already done: {len(done_b)} | Remaining: {len(remaining_b)}\n")

        for _, row in remaining_b.iterrows():
            ev = analysis_key(row)
            try:
                res = prepare_sits_patch(row)
            except Exception as e:
                print(f"  ERROR {ev}: {e}")
                completed_b[ev] = _track_b_entry(row, None, f'ERROR: {e}')
                save_checkpoint(completed_b, CHECKPOINT_B)
                continue
            if res is None:                        # no clear baseline / no imagery -> don't retry
                completed_b[ev] = _track_b_entry(row, None, 'SKIPPED_NO_IMAGERY')
                save_checkpoint(completed_b, CHECKPOINT_B)
                continue
            path, complete = res
            if not complete:                       # some blocks failed -> NOT marked done, retry next run
                print(f"  {ev}: incomplete (failed blocks) -> will retry on re-run")
                continue
            completed_b[ev] = _track_b_entry(row, path, 'OK')
            save_checkpoint(completed_b, CHECKPOINT_B)

        df_b = pd.DataFrame(list(completed_b.values()))
        sort_cols = [c for c in ['event_district_id', 'event_id'] if c in df_b.columns]
        if sort_cols:
            df_b = df_b.sort_values(sort_cols, na_position='last').reset_index(drop=True)
        df_b.to_csv(SITS_INDEX_CSV, index=False)

        in_run = df_b.apply(analysis_key, axis=1).isin(set(events['_analysis_key'])) if len(df_b) else []
        ok_b = df_b[in_run & (df_b['status'] == 'OK')] if len(df_b) else df_b
        print(f"\nTrack B complete: {len(ok_b)}/{len(events)} patches")
        print(f"Index: {SITS_INDEX_CSV}")
        print(f"\nNext steps:")
        print('  1. Run src/run_sits_inference.py locally when the verified checkpoint is available.')
        print(f"  2. Score NPZs are written to {data_path('district_sits_scores')}/")
        print(f"  3. Run merge_results.py → build_flood_area_table.py → join_district_flood_articles.py")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("DONE")
    print("=" * 65)
