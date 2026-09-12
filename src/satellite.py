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

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from gee_config import initialize_gee
from cvnd_layout import data_path
from district_keys import analysis_key, cache_stem
from flood_spec import (AOI_COLUMNS, H5_LAYOUT_VERSION, IDENTITY_COLUMNS, SPEC,
                        SPEC_VERSION, TRACK_A_COLUMNS, ndwi_new_water,
                        otsu_from_histogram, s1_new_water, spec_version,
                        variant_spec)


def ensure_gee() -> None:
    """Initialize Earth Engine only for a call that actually needs it."""
    if ee is None:
        raise RuntimeError("Earth Engine is required for satellite operations")
    initialize_gee()

# ═══════════════════════════════════════════════════════════════════════════════
# satellite.py — CVND Flood Detection Pipeline (optional; SKIP_GEE=1 by default)
# ───────────────────────────────────────────────────────────────────────────────
# Every area is measured under flood_spec.SPEC on one pixel grid per district
# (the UTM zone of the AOI centroid, 10 m pixels snapped to the 640 m tile
# grid): post [onset, onset+14d), pre [onset-30d, onset) median, max-water post
# composite, one eligibility mask (JRC permanent water, slope, India LSIB),
# pixelArea sums, and the same new-water definition
#   water(post) AND NOT water(pre) AND eligible
# for S1, S2 NDWI and the SITS tiles. A Track A pixel and a Track B pixel are
# therefore the same pixel.
#
# Track A — S1 (Otsu) + S2 NDWI new water over the district AOI, the S2
#   observation footprint, S1 on that footprint and WorldCover strata, in one
#   reduction. Output: data/cache/district/flood_extent.csv
#   (--variant NAME runs a flood_spec.SPEC_VARIANTS sensitivity spec into
#   data/cache/district/variants/)
#
# Track B — SITS-Extreme-VAE data preparation, required for every district
#   Output: data/cache/district/sits_patches/<cache_stem(event_district_id)>.h5
#   Next:   src/run_sits_inference.py → sits_scores/*.npz → compare_tracks.py
#           → merge_results.py → build_flood_area_table.py
#
# Citation: Fang & Azizpour (WACV 2025) — MIT license
# ═══════════════════════════════════════════════════════════════════════════════

# ── Checkpoint paths ──────────────────────────────────────────────────────────
CHECKPOINT_A    = str(data_path("district_satellite_checkpoint_a"))
CHECKPOINT_B    = str(data_path("district_satellite_checkpoint_b"))
FLOOD_EXTENT_CSV = str(data_path("district_flood_extent"))
VARIANTS_DIR    = str(data_path("district_flood_extent_variants"))
EVENTS_CSV = str(data_path("event_districts"))
SITS_INDEX_CSV = str(data_path("district_sits_patches_index"))

# ── Track B config ────────────────────────────────────────────────────────────
SITS_BANDS      = ['B4', 'B3', 'B2', 'B8']   # RGB (B4,B3,B2) for the model + B8 for NDWI
SITS_PATCH_SIZE = SPEC.sits_patch_px
SITS_N_PRE      = SPEC.sits_n_pre  # baseline t1..t4 (same-season composites); t5 = post window
SITS_NORM       = 10000.0          # S2 L2A reflectance DN per unit reflectance
SITS_OUTPUT_DIR = str(data_path("district_sits_patches"))

# Tiling (whole-district-AOI) settings
SITS_BLOCK_PATCHES = 16     # download block = 16*64 = 1024 px/side (keeps NPY request small)
SITS_KEEP_VALID    = SPEC.sits_keep_valid  # keep a tile only if >= this fraction is clear in EVERY timestep

# Per-tile measurement layers stored next to the model inputs.
NDWI_SCALE  = 10000
NDWI_NODATA = -32768
S1_SCALE    = 100            # VV dB × 100
S1_NODATA   = -32768
LANDCOVER_NODATA = 0
MASK_BITS   = 'bit0=eligible,bit1=valid_all,bit2=inside_aoi'
# Per downloaded block, over every AOI pixel (not only retained tiles): the
# block-level sums reproduce Track A's AOI-wide areas from the downloaded
# pixels, which is the Track A / Track B identity check.
BLOCK_STATS_COLS = ('block_id', 'aoi_m2', 'eligible_m2', 'optical_observed_m2',
                    'ndwi_new_m2', 's1_new_m2')
TILE_DATASETS = ('pre', 'post', 'coords', 'mask', 'ndwi_ref', 's1_ref', 'landcover',
                 'pixel_area_m2', 'block_id')   # block_id is appended last


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
# MEASUREMENT GRID (one pixel grid per district for Track A and Track B)
# ══════════════════════════════════════════════════════════════════════════════

def utm_epsg(lon, lat) -> int:
    """EPSG code of the UTM zone containing (lon, lat)."""
    zone = min(60, max(1, int((lon + 180) // 6) + 1))
    return (32600 if lat >= 0 else 32700) + zone


class MeasurementGrid(NamedTuple):
    """A district's pixel grid. Pixels are square ``pixel_m`` metres in a UTM
    CRS; the tile grid (``npx`` × ``npy`` tiles of ``patch_px``) starts at the
    north-west corner (x0, y0) and covers the whole AOI bounding box."""
    crs: str
    x0: float
    y0: float
    pixel_m: int
    patch_px: int
    npx: int
    npy: int

    @property
    def tile_m(self) -> int:
        return self.pixel_m * self.patch_px

    def transform(self, col_px=0, row_px=0) -> list:
        """crsTransform whose origin is the corner of pixel (row_px, col_px)."""
        return [self.pixel_m, 0, self.x0 + col_px * self.pixel_m,
                0, -self.pixel_m, self.y0 - row_px * self.pixel_m]

    def block(self, bi, bj, block_tiles) -> tuple:
        """(row_px, col_px, height_px, width_px) of the block at tile (bi, bj)."""
        height = min(block_tiles, self.npy - bi) * self.patch_px
        width = min(block_tiles, self.npx - bj) * self.patch_px
        return bi * self.patch_px, bj * self.patch_px, height, width

    def rect(self, row_px, col_px, height_px, width_px) -> list:
        """[xmin, ymin, xmax, ymax] of a pixel window in the grid CRS."""
        xmin = self.x0 + col_px * self.pixel_m
        ymax = self.y0 - row_px * self.pixel_m
        return [xmin, ymax - height_px * self.pixel_m, xmin + width_px * self.pixel_m, ymax]

    def sub_rects(self, side_m) -> list:
        """Grid-aligned rectangles of ``side_m`` covering the tile grid. Their
        edges are pixel edges, so each pixel centre lies in exactly one."""
        side_px = side_m // self.pixel_m
        rows, cols = self.npy * self.patch_px, self.npx * self.patch_px
        return [self.rect(r, c, min(side_px, rows - r), min(side_px, cols - c))
                for r in range(0, rows, side_px) for c in range(0, cols, side_px)]


def grid_from_utm_bounds(crs, minx, miny, maxx, maxy, spec=SPEC) -> MeasurementGrid:
    step = spec.sits_pixel_m
    tile = spec.sits_patch_px * step
    x0 = math.floor(minx / step) * step
    y0 = math.ceil(maxy / step) * step
    npx = max(1, math.ceil((maxx - x0) / tile))
    npy = max(1, math.ceil((y0 - miny) / tile))
    return MeasurementGrid(crs, float(x0), float(y0), step, spec.sits_patch_px, npx, npy)


def measurement_grid(region, spec=SPEC) -> MeasurementGrid:
    lon, lat = region.centroid(1).coordinates().getInfo()
    crs = f'EPSG:{utm_epsg(lon, lat)}'
    ring = region.bounds(1, ee.Projection(crs)).coordinates().getInfo()[0]
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return grid_from_utm_bounds(crs, min(xs), min(ys), max(xs), max(ys), spec)


def grid_rectangle(grid, bounds):
    return ee.Geometry.Rectangle(bounds, ee.Projection(grid.crs), False)


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


def pre_reference_col(col, start, spec=SPEC):
    """Images of the pre reference: the pre window (pre30d), or the post
    window's calendar days in each of the previous pre_reference_years
    (same_season_3y), which makes recurring seasonal water not new."""
    if spec.pre_reference == 'pre30d':
        return col.filterDate(*pre_window(start, spec))
    onset = ee.Date(start)
    windows = [ee.Filter.date(onset.advance(-k, 'year'),
                              onset.advance(-k, 'year').advance(spec.post_window_days, 'day'))
               for k in range(1, spec.pre_reference_years + 1)]
    return col.filter(ee.Filter.Or(*windows))


def measurement_mask(spec=SPEC):
    """Single-band ``eligible``: not JRC permanent water, flat, inside India."""
    permanent = (ee.Image(spec.jrc_asset).select('occurrence')
                 .gte(spec.jrc_permanent_occurrence_gte).unmask(0))
    flat = ee.Terrain.slope(ee.Image(spec.srtm_asset)).lt(spec.slope_max_deg)
    country = (ee.FeatureCollection(spec.lsib_asset)
               .filter(ee.Filter.eq('country_na', spec.lsib_country)))
    return permanent.Not().And(flat).clipToCollection(country).rename('eligible')


def landcover(spec=SPEC):
    """ESA WorldCover class (single static year) for the paired-comparison strata."""
    return ee.ImageCollection(spec.worldcover_asset).first().select('Map').rename('landcover')


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
    """The spec's water index (NDWI or MNDWI), named 'ndwi'."""
    return img.normalizedDifference(list(spec.water_bands)).rename('ndwi')


def ndwi_composites(pre_col, post_col, spec=SPEC):
    """(pre median NDWI, post NDWI composite). max_water keeps the wettest value."""
    pre = pre_col.map(lambda img: _ndwi(img, spec)).median()
    post = post_col.map(lambda img: _ndwi(img, spec))
    return pre, (post.max() if spec.post_composite == 'max_water' else post.median())


def _despeckle(img, spec=SPEC):
    return (img.select('VV')
            .focal_median(spec.s1_speckle_radius_px, 'square', 'pixels')
            .rename('VV'))


def s1_composites(pre_col, post_col, spec=SPEC):
    """(pre median VV, post VV composite), despeckled. max_water keeps the darkest."""
    post = post_col.map(lambda img: _despeckle(img, spec))
    pre = pre_col.map(lambda img: _despeckle(img, spec)).median()
    return pre, (post.min() if spec.post_composite == 'max_water' else post.median())


def _seen(col, spec=SPEC):
    """1 where the AOI was seen clear at least once in a non-empty collection."""
    bands = list(spec.water_bands)
    return (col.map(lambda img: img.select(bands).mask().reduce(ee.Reducer.min())).max()
            .gt(0).unmask(0))


def _area_value_km2(stats: dict, band: str) -> float | None:
    """Convert a reduceRegion result while preserving null as no observation."""
    if not stats or stats.get(band) is None:
        return None
    return round(float(stats[band]) / 1e6, 4)


def _limit_error(exc) -> bool:
    text = str(exc).lower()
    return any(t in text for t in ('timed out', 'memory limit', 'too many pixels',
                                   'too much memory', 'out of memory'))


def error_kind(exc) -> str:
    text = str(exc).lower()
    if 'timed out' in text:
        return 'timeout'
    if 'memory' in text:
        return 'memory'
    return 'other'


def _reduce_region(image, reducer, geometry, grid, spec):
    return image.reduceRegion(
        reducer=reducer, geometry=geometry, crs=grid.crs, crsTransform=grid.transform(),
        maxPixels=spec.max_pixels, tileScale=spec.tile_scale, bestEffort=False,
    ).getInfo() or {}


def _sum_parts(parts):
    out = {}
    for part in parts:
        for band, value in part.items():
            if value is None:
                out.setdefault(band, None)
            else:
                out[band] = (out.get(band) or 0.0) + float(value)
    return out


def _histogram_parts(parts):
    out = {}
    for part in parts:
        for band, hist in part.items():
            if not hist:
                continue
            arr = np.asarray(hist, dtype=float)
            if band in out:
                arr = np.column_stack([out[band][:, 0], out[band][:, 1] + arr[:, 1]])
            out[band] = arr
    return {band: arr.tolist() for band, arr in out.items()}


def reduce_grid(image, reducer, region, grid, spec, combine):
    """reduceRegion over the AOI on the district grid, never at a coarser
    scale (bestEffort off). When the whole AOI exceeds Earth Engine limits it
    is summed over grid-aligned sub-rectangles instead: the same pixels at the
    same scale, combined with ``combine``."""
    try:
        return _reduce_region(image, reducer, region, grid, spec)
    except Exception as exc:
        if not _limit_error(exc):
            raise
    rects = grid.sub_rects(spec.reduce_split_m)
    print(f"    (whole-AOI reduction hit an Earth Engine limit -> {len(rects)} sub-rectangles)")
    parts = [_reduce_region(image, reducer,
                            region.intersection(grid_rectangle(grid, rect), ee.ErrorMargin(1)),
                            grid, spec)
             for rect in rects]
    return combine(parts)


def reduce_areas_km2(masks: dict, region, grid, spec=SPEC) -> dict:
    """pixelArea sum of each 0/1 mask on the district grid → {name: km² | None}.

    Unweighted: a pixel counts whole. A weighted sum multiplies each value by
    its mask weight, and reprojected masks (JRC, LSIB) carry fractional
    weights -- the eligible area came out 19% short of the same pixels
    downloaded for Track B.
    """
    names = list(masks)
    stack = ee.Image.cat([masks[name].rename(name) for name in names])
    stats = reduce_grid(stack.multiply(ee.Image.pixelArea()), ee.Reducer.sum().unweighted(),
                        region, grid, spec, _sum_parts)
    return {name: _area_value_km2(stats, name) for name in names}


def otsu_backscatter_threshold(image, region, grid, spec=SPEC):
    """Otsu on post-event VV backscatter (water = dark), clamped to the VV water
    range. Returns (threshold_db, fallback_used, separability)."""
    reducer = ee.Reducer.fixedHistogram(spec.otsu_hist_min_db, spec.otsu_hist_max_db,
                                        spec.otsu_buckets).unweighted()   # pixel counts
    stats = reduce_grid(image.select('VV'), reducer, region, grid, spec, _histogram_parts)
    hist = stats.get('VV')
    if hist:
        arr = np.asarray(hist, dtype=float)
        threshold, separability = otsu_from_histogram(arr[:, 1], arr[:, 0] + spec.otsu_bucket_db / 2)
    else:
        threshold, separability = None, 0.0
    if threshold is None or not (spec.otsu_lo_db <= threshold <= spec.otsu_hi_db):
        print(f"    (Otsu={threshold} outside [{spec.otsu_lo_db},{spec.otsu_hi_db}] "
              f"→ fallback {spec.otsu_fallback_db} dB)")
        return spec.otsu_fallback_db, True, separability
    print(f"    (Otsu={threshold:.3f} dB in range)")
    return threshold, False, separability


# ══════════════════════════════════════════════════════════════════════════════
# TRACK A — S1 + S2 NEW WATER OVER THE DISTRICT AOI
# ══════════════════════════════════════════════════════════════════════════════

def _date_from_ms(value):
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).strftime('%Y-%m-%d')


def track_a_measure(region, start, grid, spec=SPEC) -> dict:
    """S1 and S2 NDWI new water, the S2 observation footprint, S1 on it and the
    WorldCover strata over the district AOI, in one reduction on the grid.

    Areas are None (not zero) when a sensor lacks pre or post imagery. cloud_pct
    is the share of the AOI never seen clear post-onset (legacy routing only).
    """
    eligible = measurement_mask(spec)
    s2, s1 = s2_collection(region, spec), s1_collection(region, spec)
    s2_pre, s2_post = pre_reference_col(s2, start, spec), s2.filterDate(*post_window(start, spec))
    s1_pre, s1_post = pre_reference_col(s1, start, spec), s1.filterDate(*post_window(start, spec))
    info = ee.Dictionary({
        's2_pre': s2_pre.size(), 's2_post': s2_post.size(),
        's1_pre': s1_pre.size(), 's1_post': s1_post.size(),
        's1_passes': s1_post.aggregate_array('orbitProperties_pass').distinct(),
        's2_first': s2_post.aggregate_min('system:time_start'),
        's1_first': s1_post.aggregate_min('system:time_start'),
    }).getInfo() or {}
    n = {key: int(info.get(key) or 0) for key in ('s2_pre', 's2_post', 's1_pre', 's1_post')}
    passes = sorted(set(info.get('s1_passes') or []))
    result = {column: None for column in TRACK_A_COLUMNS}
    result.update(
        s2_pre_images=n['s2_pre'], s2_post_images=n['s2_post'],
        s1_pre_images=n['s1_pre'], s1_post_images=n['s1_post'],
        s1_orbit=('BOTH' if len(passes) > 1 else passes[0]) if passes else None,
        first_post_date_s2=_date_from_ms(info.get('s2_first')),
        first_post_date_s1=_date_from_ms(info.get('s1_first')),
        grid_crs=grid.crs, cloud_pct=100.0,
    )

    lc = landcover(spec)
    builtup = lc.eq(spec.worldcover_builtup).And(eligible)
    masks = {'aoi': ee.Image.constant(1), 'eligible': eligible, 'builtup': builtup,
             'cropland': lc.eq(spec.worldcover_cropland).And(eligible)}
    ndwi_flood = observed = None
    if n['s2_post']:
        masks['post_seen'] = _seen(s2_post, spec)
    if n['s2_pre'] and n['s2_post']:
        pre_ndwi, post_ndwi = ndwi_composites(s2_pre, s2_post, spec)
        cut = spec.ndwi_water_gt
        observed = pre_ndwi.mask().And(post_ndwi.mask()).And(eligible)
        during = post_ndwi.gt(cut)
        ndwi_flood = during.And(pre_ndwi.lte(cut)).And(eligible)
        masks.update(ndwi_flood=ndwi_flood, ndwi_pre=pre_ndwi.gt(cut).And(eligible),
                     ndwi_during=during.And(eligible), optical_observed=observed,
                     ndwi_builtup=ndwi_flood.And(builtup))
    if n['s1_pre'] and n['s1_post']:
        pre_vv, post_vv = s1_composites(s1_pre, s1_post, spec)
        threshold, fallback, separability = otsu_backscatter_threshold(post_vv, region, grid, spec)
        s1_flood = post_vv.lt(threshold).And(pre_vv.lt(threshold).Not()).And(eligible)
        masks.update(s1_flood=s1_flood, s1_builtup=s1_flood.And(builtup))
        if ndwi_flood is not None:
            masks.update(s1_on_optical=s1_flood.And(observed),
                         s1_ndwi_both=s1_flood.And(ndwi_flood))
        result.update(otsu_threshold_db=round(float(threshold), 3),
                      otsu_fallback_used=bool(fallback),
                      otsu_separability=round(float(separability), 4))

    areas = reduce_areas_km2({name: mask.unmask(0) for name, mask in masks.items()},
                             region, grid, spec)
    aoi_km2, eligible_km2 = areas.get('aoi'), areas.get('eligible')
    result.update(grid_aoi_km2=aoi_km2, eligible_km2=eligible_km2,
                  builtup_km2=areas.get('builtup'), cropland_km2=areas.get('cropland'))
    if areas.get('post_seen') is not None and aoi_km2:
        result['cloud_pct'] = round((1 - areas['post_seen'] / aoi_km2) * 100, 1)
    if ndwi_flood is not None:
        result.update(area_s2_km2=areas['ndwi_flood'], ndwi_pre_water_km2=areas['ndwi_pre'],
                      ndwi_during_water_km2=areas['ndwi_during'],
                      optical_observed_km2=areas['optical_observed'],
                      ndwi_builtup_km2=areas['ndwi_builtup'])
        if areas['optical_observed'] is not None and eligible_km2:
            result['optical_observed_frac'] = round(areas['optical_observed'] / eligible_km2, 4)
    if 's1_flood' in masks:
        result.update(area_s1_km2=areas['s1_flood'], s1_builtup_km2=areas['s1_builtup'],
                      s1_on_optical_km2=areas.get('s1_on_optical'),
                      s1_ndwi_both_km2=areas.get('s1_ndwi_both'))
    return result


# GAUL 2015 predates Odisha's renaming and Telangana's creation (its districts
# are filed under Andhra Pradesh). Registry states map to these ADM1 names.
GAUL_STATE_ALIASES = {
    'Odisha': 'Orissa',
    'Telangana': 'Andhra Pradesh',
}
# GAUL 2015 codes these outside ADM0 'India' with no district units, so their
# district rows fail explicitly instead of matching nothing.
GAUL_UNAVAILABLE_STATES = frozenset({'Jammu and Kashmir', 'Ladakh'})
# ADM1_NAME values of FAO/GAUL/2015/level2 with ADM0_NAME 'India' (snapshot).
GAUL_2015_INDIA_ADM1 = frozenset({
    'Andaman and Nicobar', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar',
    'Chandigarh', 'Chhattisgarh', 'Dadra and Nagar Haveli', 'Daman and Diu', 'Delhi',
    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand', 'Karnataka', 'Kerala',
    'Lakshadweep', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram',
    'Nagaland', 'Orissa', 'Puducherry', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu',
    'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
})

_IDENTITY_FIELDS = ('event_id', 'source_record_id', 'state', 'district', 'start_date')


def _cache_identity_matches(entry, row, expected_version=SPEC_VERSION) -> bool:
    """Reject cache entries for a reused key whose source row or spec changed."""
    cached_spec = entry.get('spec_version') if hasattr(entry, 'get') else None
    if str(cached_spec).strip() != expected_version:
        return False
    for field in _IDENTITY_FIELDS:
        expected = row.get(field)
        cached = entry.get(field) if hasattr(entry, 'get') else None
        if cached is None or (isinstance(cached, float) and pd.isna(cached)):
            return False
        if str(cached).strip() != str(expected).strip():
            return False
    if entry.get('aoi_match_status') == 'matched':
        from boundary_recovery import cache_reference_matches
        if not cache_reference_matches(entry, row):
            return False
    return True


def _h5_identity_matches(path, row, grid=None) -> bool:
    """Check Track-B metadata, layout and grid before resuming a partial cache."""
    try:
        with h5py.File(path, 'r') as handle:
            attrs = handle['meta'].attrs
            if str(attrs.get('spec_version', '')).strip() != SPEC_VERSION:
                return False
            if str(attrs.get('layout_version', '')).strip() != H5_LAYOUT_VERSION:
                return False
            if not all(name in handle for name in TILE_DATASETS + ('block_stats',)):
                return False
            if grid is not None and (str(attrs.get('crs', '')) != grid.crs or
                                     list(attrs.get('grid', [])) != [grid.x0, grid.y0, grid.npx, grid.npy]):
                return False
            from boundary_recovery import cache_reference_matches
            if not cache_reference_matches(attrs, row):
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
    # explicitly.
    return level in {'district', 'level2', 'gaul2'} or (
        key is not None and str(key).strip().lower() not in {'', 'nan', 'none'}
    )


def _normalized_name(value: object) -> str:
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return re.sub(r'[\W_]+', ' ', text, flags=re.UNICODE).strip()


def _feature_collection_for_aoi(row, spec=SPEC):
    """Build an exact GAUL level-2 collection for a district AOI.

    Matching requires both ADM1 and ADM2. We inspect the cardinality before
    returning a geometry so an absent or ambiguous district fails explicitly.
    """
    if ee is None:
        raise RuntimeError("Earth Engine is required to resolve an AOI")
    state = str(row.get('state', '')).strip()
    if not state or state.lower() == 'nan':
        raise ValueError('state is missing')
    if not _is_district_row(row):
        raise ValueError('only district AOIs are measured; the row has no event_district_id')
    if state in GAUL_UNAVAILABLE_STATES:
        raise ValueError(f'{state} has no district units in {spec.gaul_level2}')
    gaul_state = GAUL_STATE_ALIASES.get(state, state)
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
                    if _normalized_name(f.get('properties', {}).get('ADM2_NAME')).replace(' ', '')
                    == _normalized_name(district).replace(' ', '')]
        if len(matching) != 1:
            raise ValueError(
                f"district AOI match failed for {state}/{district}: {count} exact candidates"
            )
        gid = matching[0].get('properties', {}).get('ADM2_CODE')
        candidates = collection.filter(ee.Filter.eq('ADM2_CODE', gid)) if gid else None
        if candidates is None or int(candidates.size().getInfo()) != 1:
            raise ValueError(f"district AOI match is ambiguous for {state}/{district}")
    return candidates


def resolve_aoi(row, spec=SPEC) -> dict:
    """Resolve an event-district row to a strict AOI and provenance metadata.

    The returned geometry is a server-side EE geometry; callers that only need
    a status can catch the explicit ``ValueError`` without creating a fallback.
    """
    if _is_district_row(row):
        from boundary_recovery import resolve_reference_aoi
        # An explicit, pinned district manifest; never a parent-state fallback.
        # Same resolver is used by metadata, Track A and Track B.
        reference = resolve_reference_aoi(row, ee, spec)
        if reference is not None:
            return reference
    collection = _feature_collection_for_aoi(row, spec)
    count = int(collection.size().getInfo())
    if count != 1:
        raise ValueError(f"district AOI match failed: expected one feature, got {count}")
    feature = ee.Feature(collection.first())
    props = feature.toDictionary().getInfo()
    geometry = feature.geometry()
    identifier = props.get('ADM2_CODE')
    if identifier is None:
        identifier = f"GAUL:India|{row.get('state')}|{row.get('district', '')}"
    return {
        'geometry': geometry,
        'aoi_level': 'district',
        'aoi_source': spec.gaul_level2,
        'aoi_match_status': 'matched',
        'geometry_id': str(identifier),
        'aoi_area_km2': float(geometry.area(maxError=spec.aoi_max_error_m).getInfo()) / 1e6,
    }


def get_region(row):
    """Return the strictly matched district GAUL geometry."""
    return resolve_aoi(row)['geometry']


def _aoi_context(row, spec=SPEC) -> dict:
    return {
        'event_district_id': row.get('event_district_id'),
        'event_id': row.get('event_id'),
        'source_record_id': row.get('source_record_id'),
        'start_date': row.get('start_date'),
        'state': row.get('state'),
        'district': row.get('district', ''),
        'aoi_level': 'district',
        'aoi_source': spec.gaul_level2,
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
          f"({row.get('start_date')})")
    try:
        aoi = resolve_aoi(row, spec)
    except Exception as e:
        print(f"    AOI ERROR: {e}")
        return {**context, **empty, 'baseline_status': f'ERROR: {e}', 'error_kind': 'aoi',
                'spec_version': spec_version(spec)}
    context.update({k: v for k, v in aoi.items() if k != 'geometry'})
    try:
        region = aoi['geometry']
        grid = measurement_grid(region, spec)
        measured = track_a_measure(region, row['start_date'], grid, spec)
        observed = (measured['area_s1_km2'] is not None
                    or measured['area_s2_km2'] is not None)
        measured['baseline_status'] = 'OK' if observed else 'NO_IMAGERY'
        print(f"    S1: {measured['area_s1_km2']} km² ({measured['s1_post_images']} post imgs, "
              f"{measured['s1_orbit']})  S2 NDWI: {measured['area_s2_km2']} km² "
              f"({measured['s2_post_images']} post imgs, observed "
              f"{measured['optical_observed_frac']} of eligible)")
    except Exception as e:
        print(f"    ERROR: {e}")
        measured = dict(empty, baseline_status=f'ERROR: {e}', error_kind=error_kind(e))
    measured['spec_version'] = spec_version(spec)
    return {**context, **measured}


# ══════════════════════════════════════════════════════════════════════════════
# TRACK B — SITS-EXTREME-VAE DATA PREPARATION
# ══════════════════════════════════════════════════════════════════════════════

def _norm_month(year, month):
    if month < 1:
        return year - 1, month + 12
    if month > 12:
        return year + 1, month - 12
    return year, month


def baseline_pool_months(event_dt, n_years):
    """Candidate (year, month) composites for the SITS baseline t1..t4.

    pool A (preferred) = the same calendar month ±1 in each of the previous
    n_years; pool B (fallback) = the event year's months before the onset
    month. A month qualifies only if it ends before the onset month begins: an
    onset-month composite would mix post-onset scenes into the baseline.
    """
    onset = (event_dt.year, event_dt.month)
    pool_a = [_norm_month(year, event_dt.month + offset)
              for year in range(event_dt.year - n_years, event_dt.year)
              for offset in (-1, 0, 1)]
    pool_b = [(event_dt.year, month) for month in range(1, event_dt.month)]
    return [m for m in pool_a if m < onset], pool_b


def month_window(year, month, event_dt):
    """[month start, min(month end, onset)) as ISO dates."""
    start = datetime(year, month, 1)
    next_year, next_month = _norm_month(year, month + 1)
    end = min(datetime(next_year, next_month, 1), event_dt)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def choose_baseline(pool_a, pool_b, n_pre, min_clear):
    """Pick t1..t4 from scored candidates ``(tag, payload, clear, water)``.

    Pool A months at ``clear >= min_clear`` come first; pool B fills in only
    when pool A is short. Of the qualifying months take the two clearest, then
    the driest (lowest NDWI water fraction). Returns them date-sorted, or None.
    """
    cands = [c for c in pool_a if c[2] >= min_clear]
    if len(cands) < n_pre:
        seen = {c[0] for c in cands}
        cands += [c for c in pool_b if c[2] >= min_clear and c[0] not in seen]
    if len(cands) < n_pre:
        return None
    chosen, seen = [], set()
    for c in sorted(cands, key=lambda x: -x[2])[:2] + sorted(cands, key=lambda x: x[3]):
        if c[0] in seen:
            continue
        chosen.append(c)
        seen.add(c[0])
        if len(chosen) == n_pre:
            break
    return sorted(chosen, key=lambda c: c[0])


def _monthly_composite_sits(s2, year, month, event_dt):
    col = s2.filterDate(*month_window(year, month, event_dt))
    n = col.size().getInfo()
    if n == 0:
        return None, 0
    return col.median(), n


def t5_composite(post_col, spec=SPEC):
    """Model input t5. Under max_water each pixel takes the reflectance of its
    wettest post observation -- the scene the NDWI max comes from -- so the
    model sees the same post state the area is measured on."""
    if spec.post_composite == 'max_water':
        return (post_col.map(lambda img: img.addBands(_ndwi(img, spec)))
                .qualityMosaic('ndwi').select(SITS_BANDS))
    return post_col.median().select(SITS_BANDS)


def _constant_band(value, name):
    return ee.Image.constant(value).toInt16().rename(name)


def measurement_aux_image(s2, s1, region, start, spec=SPEC, with_s1=True):
    """Per-pixel measurement layers downloaded with every SITS block, on Track
    A's windows, composites and grid: eligibility, AOI membership, pixel area
    (m²), pre/post NDWI ×1e4, despeckled pre/post S1 VV (dB ×100) and the
    WorldCover class. ``s2`` must carry the water-index bands."""
    pre_ndwi, post_ndwi = ndwi_composites(pre_reference_col(s2, start, spec),
                                          s2.filterDate(*post_window(start, spec)), spec)

    def scaled(img, factor, nodata, name):
        return img.multiply(factor).round().toInt16().unmask(nodata).rename(name)

    if with_s1:
        pre_vv, post_vv = s1_composites(pre_reference_col(s1, start, spec),
                                        s1.filterDate(*post_window(start, spec)), spec)
        s1_bands = [scaled(pre_vv, S1_SCALE, S1_NODATA, 's1_pre'),
                    scaled(post_vv, S1_SCALE, S1_NODATA, 's1_post')]
    else:
        s1_bands = [_constant_band(S1_NODATA, 's1_pre'), _constant_band(S1_NODATA, 's1_post')]
    return ee.Image.cat([
        measurement_mask(spec).unmask(0).toByte().rename('eligible'),
        ee.Image.constant(1).clip(region).unmask(0).toByte().rename('inside'),
        ee.Image.pixelArea().toFloat().rename('area'),
        scaled(pre_ndwi, NDWI_SCALE, NDWI_NODATA, 'ndwi_pre'),
        scaled(post_ndwi, NDWI_SCALE, NDWI_NODATA, 'ndwi_post'),
        *s1_bands,
        landcover(spec).unmask(LANDCOVER_NODATA).toByte().rename('landcover'),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# Tile the whole district AOI into 64x64 patches on the district grid
#   - blocks are downloaded as NPY with an explicit crs_transform + dimensions,
#     so every block is exactly a whole number of tiles on the grid
#   - keep only tiles that are clear (cloud/nodata-free) in EVERY timestep
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_npy(image, grid, row_px, col_px, height, width):
    params = {'crs': grid.crs, 'crs_transform': grid.transform(col_px, row_px),
              'dimensions': f'{width}x{height}', 'format': 'NPY'}
    for attempt in range(4):
        try:
            r = requests.get(image.getDownloadURL(params), timeout=180)
            r.raise_for_status()
            arr = np.load(io.BytesIO(r.content))
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    if arr.shape != (height, width):
        raise ValueError(f'block download returned {arr.shape}, expected {(height, width)}')
    return arr


def _download_block(image, grid, row_px, col_px, height, width):
    """One block as NPY -> order-preserving structured array (bands + 'valid').
    valid = 1 only where every band is present (not cloud/nodata)."""
    valid = image.mask().reduce(ee.Reducer.min()).rename('valid').toByte()
    stack = image.select(SITS_BANDS).toInt16().addBands(valid)   # int16 keeps NPY under the 48MB request limit
    return _fetch_npy(stack, grid, row_px, col_px, height, width)


def block_stats(aux, s1_threshold_db, spec=SPEC) -> list:
    """AOI-wide sums (m²) of one block: aoi, eligible, optical observed, NDWI
    and S1 new water -- Track A's definitions on the downloaded pixels."""
    area = aux['area'].astype(np.float64)
    inside = aux['inside'].astype(bool)
    eligible = aux['eligible'].astype(bool) & inside
    ndwi_new, observed = ndwi_new_water(aux['ndwi_pre'], aux['ndwi_post'], NDWI_NODATA,
                                        NDWI_SCALE, spec)
    s1_new = s1_new_water(aux['s1_pre'], aux['s1_post'], S1_NODATA, S1_SCALE, s1_threshold_db)
    s1_m2 = float(area[s1_new & eligible].sum()) if s1_threshold_db is not None else np.nan
    return [float(area[inside].sum()), float(area[eligible].sum()),
            float(area[observed & eligible].sum()), float(area[ndwi_new & eligible].sum()),
            s1_m2]


def _tiles_from_block(arrs, aux, spec=SPEC) -> dict:
    """Cut one downloaded block into the tiles that are clear enough in every
    model timestep. ``arrs`` are the timestep arrays (bands + 'valid'); ``aux``
    holds the measurement layers on the same grid."""
    P = spec.sits_patch_px
    shapes = {a.shape for a in [*arrs, aux]}
    if len(shapes) != 1:
        raise ValueError(f'timestep and measurement blocks differ in shape: {sorted(shapes)}')
    H, W = aux.shape
    valid = [a['valid'].astype(bool) for a in arrs]
    valid_all = np.logical_and.reduce(valid)
    bits = (aux['eligible'].astype(np.uint8) | (valid_all.astype(np.uint8) << 1)
            | (aux['inside'].astype(np.uint8) << 2))

    def reflectance(a, win):
        return np.stack([np.clip(a[b][win], 0, None).astype(np.uint16) for b in SITS_BANDS])

    out = {name: [] for name in ('pre', 'post', 'mask', 'ndwi_ref', 's1_ref', 'landcover',
                                 'pixel_area_m2', 'rc')}
    for r in range(H // P):
        for c in range(W // P):
            win = (slice(r * P, (r + 1) * P), slice(c * P, (c + 1) * P))
            if min(float(v[win].mean()) for v in valid) < spec.sits_keep_valid:
                continue
            out['pre'].append(np.stack([reflectance(a, win) for a in arrs[:spec.sits_n_pre]]))
            out['post'].append(np.stack([reflectance(a, win) for a in arrs[spec.sits_n_pre:]]))
            out['mask'].append(bits[win])
            out['ndwi_ref'].append(np.stack([aux['ndwi_pre'][win], aux['ndwi_post'][win]]).astype(np.int16))
            out['s1_ref'].append(np.stack([aux['s1_pre'][win], aux['s1_post'][win]]).astype(np.int16))
            out['landcover'].append(aux['landcover'][win].astype(np.uint8))
            out['pixel_area_m2'].append(np.float32(np.mean(aux['area'][win])))
            out['rc'].append((r, c))
    return out


def _append_h5(f, batch: dict):
    """Append this block's patch batch to the open hdf5's resizable datasets,
    in the given order (callers put block_id last)."""
    for name, val in batch.items():
        ds = f[name]
        n0 = ds.shape[0]
        ds.resize(n0 + val.shape[0], axis=0)
        ds[n0:] = val


def truncate_to_done(hdf, done_blocks) -> int:
    """Drop tiles and block stats appended after the last recorded block.

    Tiles are appended block by block with ``block_id`` written last, and a
    block is recorded done only after its append, so the valid tiles are the
    leading run whose block_id is done and every dataset is cut to that
    length. Returns the number of tiles dropped.
    """
    done = np.array(sorted(done_blocks), dtype=np.int64)
    ids = hdf['block_id'][:]
    ok = np.isin(ids, done)
    n = len(ids) if ok.all() else int(np.argmin(ok))
    if ok[n:].any():
        raise ValueError('H5 tiles of a recorded block follow an unrecorded one; rebuild the H5')
    dropped = max(hdf[name].shape[0] for name in TILE_DATASETS) - n
    for name in TILE_DATASETS:
        if hdf[name].shape[0] != n:
            hdf[name].resize(n, axis=0)
    stats = hdf['block_stats']
    ok = np.isin(stats[:, 0].astype(np.int64), done) if stats.shape[0] else np.array([], bool)
    m = len(ok) if ok.all() else int(np.argmin(ok))
    if ok[m:].any():
        raise ValueError('H5 block stats of a recorded block follow an unrecorded one; rebuild the H5')
    if stats.shape[0] != m:
        stats.resize(m, axis=0)
    return dropped


def _tile_region(images, aux, region, grid, hdf, done_blocks, blocks_ckpt,
                 s1_threshold_db, spec=SPEC):
    """Tile the district AOI on its grid, download block by block, keep only
    tiles that are clear in every timestep, and append them to the open hdf5.
    Skips blocks already in done_blocks and records each finished block to
    blocks_ckpt (block-level resume). Returns (patches in the hdf5, failed blocks)."""
    P, B = spec.sits_patch_px, SITS_BLOCK_PATCHES
    all_blocks = [(bi, bj) for bi in range(0, grid.npy, B) for bj in range(0, grid.npx, B)]

    # Only download blocks intersecting the district AOI (skip bbox corners outside it).
    feats = [ee.Feature(grid_rectangle(grid, grid.rect(*grid.block(bi, bj, B))), {'i': i})
             for i, (bi, bj) in enumerate(all_blocks)]
    inside = set(ee.FeatureCollection(feats).filterBounds(region)
                 .aggregate_array('i').getInfo())
    todo = [(i, bi, bj) for i, (bi, bj) in enumerate(all_blocks)
            if i in inside and i not in done_blocks]
    print(f"    tiling: {grid.npx}x{grid.npy} tiles on {grid.crs} (@{grid.pixel_m}m), "
          f"{len(inside)}/{len(all_blocks)} blocks in district AOI, {len(todo)} to download")
    bar = tqdm(todo, desc='    downloading', unit='blk')
    failed = 0
    for i, bi, bj in bar:
        window = grid.block(bi, bj, B)
        try:
            # model timesteps + measurement layers of this block, concurrently
            with ThreadPoolExecutor(max_workers=len(images) + 1) as ex:
                futures = [ex.submit(_download_block, im, grid, *window) for im in images]
                futures.append(ex.submit(_fetch_npy, aux, grid, *window))
                arrs = [fut.result() for fut in futures]
        except Exception as e:
            bar.write(f"      block ({bi},{bj}) download failed: {e}")
            failed += 1
            continue

        tiles = _tiles_from_block(arrs[:-1], arrs[-1], spec)
        if tiles['rc']:
            row0, col0 = window[0], window[1]
            coords = [[row0 + r * P, col0 + c * P,
                       grid.x0 + (col0 + (c + 0.5) * P) * grid.pixel_m,
                       grid.y0 - (row0 + (r + 0.5) * P) * grid.pixel_m]
                      for r, c in tiles['rc']]
            _append_h5(hdf, {
                'pre': np.stack(tiles['pre']),
                'post': np.stack(tiles['post']),
                'coords': np.array(coords, dtype='float64'),
                'mask': np.stack(tiles['mask']),
                'ndwi_ref': np.stack(tiles['ndwi_ref']),
                's1_ref': np.stack(tiles['s1_ref']),
                'landcover': np.stack(tiles['landcover']),
                'pixel_area_m2': np.array(tiles['pixel_area_m2'], dtype='float32'),
                'block_id': np.full(len(tiles['rc']), i, dtype='int32'),
            })
        _append_h5(hdf, {'block_stats': np.array([[i] + block_stats(arrs[-1], s1_threshold_db, spec)])})
        hdf.flush()
        done_blocks.add(i)
        # Atomic replace: an interruption leaves the previous block list intact.
        with open(blocks_ckpt + '.tmp', 'w') as cf:
            json.dump(sorted(done_blocks), cf)
        os.replace(blocks_ckpt + '.tmp', blocks_ckpt)
        bar.set_postfix(kept=hdf['pre'].shape[0])
    return hdf['pre'].shape[0], failed


def _qa_mean(image, region, grid, spec=SPEC):
    return image.reduceRegion(reducer=ee.Reducer.mean(), geometry=region, crs=grid.crs,
                              scale=spec.qa_scale_m, maxPixels=spec.max_pixels,
                              tileScale=spec.tile_scale, bestEffort=False)


def _pick_baseline(s2, region, event_dt, grid, spec=SPEC):
    """Baseline t1..t4 (VAE input only): cloud-free, same-season, recent monthly
    composites scored by AOI clear fraction and NDWI water fraction (dryness);
    see baseline_pool_months and choose_baseline.
    Returns [(date_str, img, clear_frac, water_frac)] date-sorted, or None."""
    n_pre, min_clear = spec.sits_n_pre, spec.sits_baseline_min_clear

    def score(y, mo):
        img, _ = _monthly_composite_sits(s2, y, mo, event_dt)
        if img is None:
            return None
        clear = _qa_mean(img.mask().reduce(ee.Reducer.min()).rename('c'), region, grid, spec).get('c')
        water = _qa_mean(_ndwi(img, spec).gt(spec.ndwi_water_gt), region, grid, spec).values().get(0)
        info = ee.Dictionary({'clear': clear, 'water': water}).getInfo()
        if info.get('clear') is None:
            return None
        return (f"{y:04d}-{mo:02d}", img,
                float(info['clear']), float(info.get('water') or 0.0))

    def gather(months):
        return [c for c in (score(y, mo) for y, mo in months) if c is not None]

    months_a, months_b = baseline_pool_months(event_dt, spec.sits_baseline_years)
    pool_a = gather(months_a)
    # Pool B is scored only when pool A is short (it is only read then).
    short = sum(c[2] >= min_clear for c in pool_a) < n_pre
    pool_b = gather(months_b) if short else []
    chosen = choose_baseline(pool_a, pool_b, n_pre, min_clear)
    print(f"    baseline: {'none' if chosen is None else [c[0] for c in chosen]} "
          f"(clear>={min_clear})")
    return chosen


def sits_h5_path(key) -> str:
    return os.path.join(SITS_OUTPUT_DIR, f'{cache_stem(key)}.h5')


def _create_h5(f, row, aoi, grid, spec, s1_threshold_db, s1_fallback):
    P, B, n_pre = spec.sits_patch_px, len(SITS_BANDS), spec.sits_n_pre
    packed = {'compression': 'gzip', 'compression_opts': 4, 'shuffle': True}
    f.create_dataset('pre', shape=(0, n_pre, B, P, P), maxshape=(None, n_pre, B, P, P),
                     dtype='uint16', chunks=(1, n_pre, B, P, P), **packed)
    f.create_dataset('post', shape=(0, 1, B, P, P), maxshape=(None, 1, B, P, P),
                     dtype='uint16', chunks=(1, 1, B, P, P), **packed)
    f.create_dataset('coords', shape=(0, 4), maxshape=(None, 4), dtype='float64')
    f.create_dataset('mask', shape=(0, P, P), maxshape=(None, P, P), dtype='uint8',
                     chunks=(1, P, P), **packed)
    f.create_dataset('ndwi_ref', shape=(0, 2, P, P), maxshape=(None, 2, P, P),
                     dtype='int16', chunks=(1, 2, P, P), **packed)
    f.create_dataset('s1_ref', shape=(0, 2, P, P), maxshape=(None, 2, P, P),
                     dtype='int16', chunks=(1, 2, P, P), **packed)
    f.create_dataset('landcover', shape=(0, P, P), maxshape=(None, P, P), dtype='uint8',
                     chunks=(1, P, P), **packed)
    f.create_dataset('pixel_area_m2', shape=(0,), maxshape=(None,), dtype='float32')
    f.create_dataset('block_id', shape=(0,), maxshape=(None,), dtype='int32')
    f.create_dataset('block_stats', shape=(0, len(BLOCK_STATS_COLS)),
                     maxshape=(None, len(BLOCK_STATS_COLS)), dtype='float64')
    meta = f.create_group('meta')
    for field in ('event_id', 'source_record_id', 'state', 'district', 'start_date'):
        meta.attrs[field] = str(row.get(field, ''))
    meta.attrs['event_district_id'] = str(row.get('event_district_id', ''))
    meta.attrs['geometry_id'] = str(aoi['geometry_id'])
    meta.attrs['bands'] = ','.join(SITS_BANDS)
    meta.attrs['reflectance'] = f'uint16 DN, reflectance x {int(SITS_NORM)}'
    meta.attrs['n_pre'] = n_pre
    meta.attrs['patch_size'] = P
    meta.attrs['coords_cols'] = 'row_px,col_px,x,y'
    meta.attrs['crs'] = grid.crs
    meta.attrs['grid'] = [grid.x0, grid.y0, grid.npx, grid.npy]
    meta.attrs['pixel_m'] = grid.pixel_m
    meta.attrs['spec_version'] = spec_version(spec)
    meta.attrs['layout_version'] = H5_LAYOUT_VERSION
    meta.attrs['ndwi_scale'] = NDWI_SCALE
    meta.attrs['ndwi_nodata'] = NDWI_NODATA
    meta.attrs['s1_scale'] = S1_SCALE
    meta.attrs['s1_nodata'] = S1_NODATA
    meta.attrs['s1_threshold_db'] = np.nan if s1_threshold_db is None else float(s1_threshold_db)
    meta.attrs['s1_otsu_fallback'] = bool(s1_fallback)
    meta.attrs['landcover_asset'] = spec.worldcover_asset
    meta.attrs['landcover_nodata'] = LANDCOVER_NODATA
    meta.attrs['mask_bits'] = MASK_BITS
    meta.attrs['block_stats_cols'] = ','.join(BLOCK_STATS_COLS)


def _skip(reason):
    print(f"    -> {reason} -> skip")
    return {'status': 'SKIPPED_NO_IMAGERY', 'reason': reason, 'path': None,
            'complete': True, 'kept_tiles': 0}


def prepare_sits_patch(row, spec=SPEC):
    """Track B: tile the district AOI and save the time series to HDF5.
    Each patch = (pre: 4x4x64x64, post: 1x4x64x64) uint16 model inputs plus the
    measurement layers mask (bit0 eligible, bit1 valid_all, bit2 inside AOI),
    ndwi_ref (pre/post NDWI ×1e4), s1_ref (pre/post VV dB ×100), landcover,
    pixel_area_m2 and block_id; coords=(row_px, col_px, x, y) on the grid.
    Baseline t1..t4 = clear/dry same-season composites (VAE input), t5 = the
    post state the NDWI max is taken from.

    Returns {'status', 'reason', 'path', 'complete', 'kept_tiles'}; status
    SKIPPED_NO_IMAGERY is a data condition (SITS unavailable), not a failure.
    """
    key = analysis_key(row)
    start_str = row['start_date']
    print(f"\n  [Track B] [{key}] {row['state']}/{row.get('district', '')} district AOI - {start_str}")

    aoi = resolve_aoi(row, spec)
    region = aoi['geometry']
    grid = measurement_grid(region, spec)
    s2_all = s2_collection(region, spec)
    s2 = s2_all.select(SITS_BANDS)
    s1 = s1_collection(region, spec)
    event_dt = datetime.strptime(start_str, '%Y-%m-%d')

    post_all = s2_all.filterDate(*post_window(start_str, spec))
    s1_pre, s1_post = pre_reference_col(s1, start_str, spec), s1.filterDate(*post_window(start_str, spec))
    counts = ee.Dictionary({'post': post_all.size(),
                            'pre': pre_reference_col(s2, start_str, spec).size(),
                            's1_pre': s1_pre.size(), 's1_post': s1_post.size()}).getInfo()
    if not counts.get('post'):
        return _skip('no_post_imagery')
    if not counts.get('pre'):
        return _skip('no_pre_imagery')
    baseline = _pick_baseline(s2, region, event_dt, grid, spec)
    if baseline is None:
        return _skip('no_clear_baseline')

    with_s1 = bool(counts.get('s1_pre')) and bool(counts.get('s1_post'))
    s1_threshold, s1_fallback = None, False
    if with_s1:
        _, post_vv = s1_composites(s1_pre, s1_post, spec)
        s1_threshold, s1_fallback, _ = otsu_backscatter_threshold(post_vv, region, grid, spec)

    images = [b[1] for b in baseline] + [t5_composite(post_all, spec)]
    tags = [f"{b[0]}(c{b[2]:.2f}/w{b[3]:.2f})" for b in baseline] + [f"post({counts['post']})"]
    print("    timesteps: " + " | ".join(tags))
    images = [im.clip(region) for im in images]   # outside the district AOI is masked
    aux = measurement_aux_image(s2_all, s1, region, start_str, spec, with_s1=with_s1)

    os.makedirs(SITS_OUTPUT_DIR, exist_ok=True)
    out_path = sits_h5_path(key)
    blocks_ckpt = out_path + '.blocks.json'

    # Block-level resume: continue if a partial h5 + its block checkpoint both exist
    done_blocks = set()
    resume = os.path.exists(out_path) and os.path.exists(blocks_ckpt)
    if resume and not _h5_identity_matches(out_path, row, grid):
        print("    cache identity/spec/layout/grid changed -> restarting H5")
        resume = False
    if resume:
        with open(blocks_ckpt) as bf:
            done_blocks = set(json.load(bf))

    with h5py.File(out_path, 'a' if resume else 'w') as f:
        if resume:
            dropped = truncate_to_done(f, done_blocks)
            print(f"    resuming: {len(done_blocks)} blocks already done"
                  + (f", dropped {dropped} tiles of an unrecorded block" if dropped else ''))
        else:
            _create_h5(f, row, aoi, grid, spec, s1_threshold, s1_fallback)
            # The block checkpoint marks the H5 partial from creation on, so an
            # interruption before the first block is never read as complete.
            with open(blocks_ckpt, 'w') as cf:
                json.dump([], cf)
        n, failed = _tile_region(images, aux, region, grid, f, done_blocks, blocks_ckpt,
                                 s1_threshold, spec)

    complete = (failed == 0)
    # drop the block checkpoint only if every block succeeded; otherwise keep it so a
    # re-run resumes and retries the failed blocks
    if complete and os.path.exists(blocks_ckpt):
        os.remove(blocks_ckpt)
    print(f"    Saved: {out_path}  [{n} clear patches, {failed} blocks failed]")
    return {'status': 'OK', 'reason': 'ok' if n else 'no_retained_tiles', 'path': out_path,
            'complete': complete, 'kept_tiles': int(n)}


def _track_b_entry(row, h5_path, status, reason=None, kept_tiles=None):
    return {'event_district_id': row.get('event_district_id'),
            'event_id': row['event_id'], 'source_record_id': row.get('source_record_id'),
            'state': row.get('state'), 'district': row.get('district'),
            'start_date': row.get('start_date'), 'h5_path': h5_path, 'status': status,
            'reason': reason, 'kept_tiles': kept_tiles, 'spec_version': SPEC_VERSION}


def write_sits_index(completed_b) -> pd.DataFrame:
    """The Track B index merge_results reads; rewritten after every district."""
    df_b = pd.DataFrame(list(completed_b.values()))
    sort_cols = [c for c in ['event_district_id', 'event_id'] if c in df_b.columns]
    if sort_cols:
        df_b = df_b.sort_values(sort_cols, na_position='last').reset_index(drop=True)
    df_b.to_csv(SITS_INDEX_CSV, index=False)
    return df_b


def track_a_paths(variant=None):
    """(checkpoint, flood_extent CSV) of the primary spec or a sensitivity variant."""
    if not variant:
        return CHECKPOINT_A, FLOOD_EXTENT_CSV
    return (os.path.join(VARIANTS_DIR, f'satellite_checkpoint_a.{variant}.json'),
            os.path.join(VARIANTS_DIR, f'flood_extent.{variant}.csv'))


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--track', choices=['A', 'B', 'both'],
                        default='both',
                        help='Which track to run (default: both; Track B is required for every district)')
    parser.add_argument('--events', nargs='*', default=None,
                        help='Only run these event_district_ids or event_ids. Default: all')
    parser.add_argument('--reverse', action='store_true',
                        help='Process events last-to-first (last event -> first event)')
    parser.add_argument('--variant', default=None,
                        help='Track A only: run a flood_spec.SPEC_VARIANTS sensitivity spec')
    parser.add_argument('--workers', type=int, default=4,
                        help='Track A districts measured concurrently (default: 4)')
    args = parser.parse_args()
    if args.variant and args.track != 'A':
        parser.error('--variant runs Track A only; pass --track A')
    run_spec = variant_spec(args.variant) if args.variant else SPEC
    run_version = spec_version(run_spec)

    print("=" * 65)
    print("CVND SATELLITE PIPELINE")
    print(f"  Running: Track {args.track.upper()}  |  spec {run_version}"
          + (f" (variant {args.variant})" if args.variant else ''))
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
    checkpoint_a, extent_csv = track_a_paths(args.variant)
    for target in (checkpoint_a, CHECKPOINT_B, extent_csv, SITS_INDEX_CSV):
        os.makedirs(os.path.dirname(target), exist_ok=True)
    os.makedirs(SITS_OUTPUT_DIR, exist_ok=True)

    # ── Track A ───────────────────────────────────────────────────────────────
    if args.track in ('A', 'both'):
        print("\n" + "─" * 65)
        print("TRACK A — S1 OTSU + S2 NDWI NEW WATER (one measurement spec)")
        print("─" * 65)

        completed_a = load_checkpoint(checkpoint_a)
        stale_a = [key for key, entry in completed_a.items()
                   if key not in event_by_key
                   or not _cache_identity_matches(entry, event_by_key[key], run_version)
                   or str(entry.get('baseline_status', entry.get('status', ''))).startswith('ERROR')]
        for key in stale_a:
            del completed_a[key]
        if stale_a:
            print(f"Discarded {len(stale_a)} stale Track-A cache entries (identity, spec or ERROR)")

        # Seed with an existing flood_extent CSV if the checkpoint is empty
        if not completed_a and os.path.exists(extent_csv):
            existing = pd.read_csv(extent_csv)
            # Only rows measured under a recorded spec can be reused
            if 'spec_version' in existing.columns:
                for _, r in existing.iterrows():
                    key = analysis_key(r)
                    if (key in event_by_key
                            and _cache_identity_matches(r, event_by_key[key], run_version)
                            and not str(r.get('baseline_status', '')).startswith('ERROR')):
                        completed_a[key] = r.to_dict()
                save_checkpoint(completed_a, checkpoint_a)
                print(f"Seeded {len(completed_a)} events from existing {extent_csv}")

        track_a_columns = list(IDENTITY_COLUMNS + AOI_COLUMNS + TRACK_A_COLUMNS)
        done_a     = set(completed_a.keys())
        remaining_a = events[~events['_analysis_key'].isin(done_a)]
        print(f"Already done: {len(done_a)} | Remaining: {len(remaining_a)}\n")

        # Districts are independent Earth Engine requests; results are written
        # by this thread only, one checkpoint save per finished district.
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(detect_flood_baseline, row, run_spec): analysis_key(row)
                       for _, row in remaining_a.iterrows()}
            for i, future in enumerate(as_completed(futures), 1):
                completed_a[futures[future]] = future.result()
                save_checkpoint(completed_a, checkpoint_a)

                if (len(done_a) + i) % 10 == 0:
                    pd.DataFrame(list(completed_a.values())).reindex(columns=track_a_columns).to_csv(
                        extent_csv, index=False)
                    print(f"  >> Track A checkpoint: "
                          f"{len(done_a)+i}/{len(events)} done")

        df_a = pd.DataFrame(list(completed_a.values())).reindex(columns=track_a_columns)
        sort_cols = [c for c in ['event_district_id', 'event_id'] if c in df_a.columns]
        if sort_cols:
            df_a = df_a.sort_values(sort_cols, na_position='last').reset_index(drop=True)
        df_a.to_csv(extent_csv, index=False)

        in_run = df_a.apply(analysis_key, axis=1).isin(set(events['_analysis_key']))
        ok_a = df_a[in_run & df_a['baseline_status'].isin(['OK', 'NO_IMAGERY'])]
        print(f"\nTrack A complete: {len(ok_a)}/{len(events)} events "
              f"(ERROR rows are retried on the next run)")
        print(f"Saved: {extent_csv}")
        print(df_a[['event_district_id', 'area_s1_km2', 'area_s2_km2', 'optical_observed_frac',
                    'baseline_status']].to_string(index=False))

    # ── Track B ───────────────────────────────────────────────────────────────
    if args.track in ('B', 'both'):
        print("\n" + "─" * 65)
        print("TRACK B — SITS-EXTREME-VAE PATCH PREPARATION")
        print(f"  Bands: {SITS_BANDS}")
        print(f"  Patch: {SITS_PATCH_SIZE}×{SITS_PATCH_SIZE}px @ {SPEC.sits_pixel_m}m UTM | "
              f"{SITS_N_PRE} pre-event months + 1 post ({SPEC.post_window_days} d)")
        print(f"  Store: uint16 DN (÷{SITS_NORM} = reflectance), gzip")
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
                completed_b[ev] = _track_b_entry(row, None, f'ERROR: {e}', error_kind(e))
                save_checkpoint(completed_b, CHECKPOINT_B)
                write_sits_index(completed_b)
                continue
            if not res['complete']:                # some blocks failed -> NOT marked done, retry next run
                print(f"  {ev}: incomplete (failed blocks) -> will retry on re-run")
                continue
            completed_b[ev] = _track_b_entry(row, res['path'], res['status'], res['reason'],
                                             res['kept_tiles'])
            save_checkpoint(completed_b, CHECKPOINT_B)
            write_sits_index(completed_b)

        df_b = write_sits_index(completed_b)

        in_run = df_b.apply(analysis_key, axis=1).isin(set(events['_analysis_key'])) if len(df_b) else []
        ok_b = df_b[in_run & (df_b['status'] == 'OK')] if len(df_b) else df_b
        print(f"\nTrack B complete: {len(ok_b)}/{len(events)} patches")
        print(f"Index: {SITS_INDEX_CSV}")
        print(f"\nNext steps:")
        print('  1. Run src/run_sits_inference.py locally when the verified checkpoint is available.')
        print(f"  2. Score NPZs are written to {data_path('district_sits_scores')}/")
        print(f"  3. Run compare_tracks.py → merge_results.py → build_flood_area_table.py")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("DONE")
    print("=" * 65)
