"""sar_patches.py — Sentinel-1 patch preparation for the Kuro Siwo FloodViT model.

Why this replaces the optical Track B
-------------------------------------
The SITS optical pipeline only runs where the flood date was cloud-free, so the
AI contributed to some events and not others -- and which ones was decided by
cloud cover, which tracks monsoon intensity and therefore flood severity. SAR
sees through cloud, so a radar model runs on every event and that selection
disappears.

Model contract (read from the released checkpoint, not guessed)
---------------------------------------------------------------
`floodvit.pt` stores its own config:  image_size 224, num_channels 6,
num_classes 3 (no water / permanent water / flood).

Channel order is POST FIRST -- not what data_config.json's `inputs` list
suggests. training/segmentation_trainer.py builds the tensor as
    cat(post, pre_event_1, pre_event_2)
and SSLDataset does the same (`cat((flood, pre_event_1, pre_event_2))`).
That `inputs` list selects WHICH acquisitions to use, not their order.
So the six channels are:
    0,1  post_event  VV, VH
    2,3  pre_event_1 VV, VH   (older pre-event scene)
    4,5  pre_event_2 VV, VH   (newer pre-event scene)

Values are LINEAR sigma0, not dB: Kuro Siwo's SNAP graph sets
`outputImageScaleInDb=false`, and its normalisation (mean [0.0953, 0.0264],
clamp 0.15) only makes sense on a linear scale. So this module pulls
COPERNICUS/S1_GRD_FLOAT, which is already linear, rather than S1_GRD (dB).

Difference from Kuro Siwo's own preprocessing
---------------------------------------------
Their SNAP graph applies Lee Sigma 3x3; Earth Engine has no Lee Sigma, so
lee_filter() below is the classic Lee filter it derives from. Everything else
matches: GEE's S1_GRD_FLOAT is already orbit-corrected, thermal-noise-removed,
border-noise-removed, calibrated and terrain-corrected against SRTM.

This module only acquires and tiles. It does not store patches: at whole-state
AOIs that is ~3.9 TB, and the areas are what the study needs. sar_flood_area.py
consumes iter_patch_blocks(), classifies each block and discards it.
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ee  # noqa: E402



def _sat():
    """Import satellite.py lazily.

    Importing it runs initialize_gee() at module scope, so a top-level import
    here would make this module unimportable without Earth Engine credentials --
    and with it the pure helpers below untestable. Deferred to first use; the
    runtime path is unchanged.
    """
    import satellite
    return satellite

# ── Kuro Siwo FloodViT contract ───────────────────────────────────────────────
SAR_PATCH_SIZE = 224          # floodvit.pt configs['image_size']
SAR_POLARISATIONS = ['VV', 'VH']
SAR_N_PRE = 2                 # pre_event_1, pre_event_2
SAR_SCALE_M = 10              # SNAP graph: pixelSpacingInMeter 10.0
SAR_CHANNELS = (SAR_N_PRE + 1) * len(SAR_POLARISATIONS)   # 6

# ── acquisition search windows ────────────────────────────────────────────────
POST_WINDOW_DAYS = 14         # first usable acquisition after onset
PRE_SEARCH_DAYS = 90          # look this far back for the two pre-event scenes

# ── tiling ────────────────────────────────────────────────────────────────────
# 8*224 = 1792 px/side -> ~26 MB per timestep request, inside GEE's 48 MB limit.
# Fewer, larger requests: at 4 the same AOI needs ~425k blocks, at 8 only ~108k.
SAR_BLOCK_PATCHES = 8
SAR_KEEP_VALID = 0.70         # keep a patch only if this fraction is valid in EVERY scene

# ── terrain gate ──────────────────────────────────────────────────────────────
# FloodViT was trained on Kuro Siwo's 43 events, which do not include Himalayan
# terrain. On steep slopes radar shadow returns almost no signal and reads as
# dark -- indistinguishable from water to the model. Measured on Sikkim (E104):
# it reported 899 km2 of flood where the state holds only 199 km2 of land under
# 5 degrees, i.e. most of the "flood" was on slopes that cannot pond water.
# The same 5-degree threshold the optical path already used.
SLOPE_MAX_DEG = 5

# ── speckle ───────────────────────────────────────────────────────────────────
# Kuro Siwo's SNAP graph applies Lee Sigma 3x3 before training. Earth Engine has
# no Lee Sigma, so this is the classic Lee filter it derives from -- same window,
# same multiplicative-noise model. Feeding unfiltered imagery leaves speckle
# darkening random pixels, which the model reads as water: measured on Sikkim, it
# called 30% of flat ground flood in a year with no flood at all.
# ENL for Sentinel-1 IW GRD is about 4.4 looks.
SPECKLE_WINDOW = 3
SPECKLE_ENL = 4.4

# ── transfer encoding ─────────────────────────────────────────────────────────
# Linear sigma0 sits in roughly [0, 1] and is clamped at 0.15 before the model,
# so int16 at 1/10000 resolves it to 0.0001 -- about 0.005 of the normalisation
# std, below anything the model can notice. Same trick the optical pipeline
# already used (SITS_NORM). It also keeps the request well inside GEE's 48 MiB
# cap: the Lee filter's float64 output reached 72 MB and every block failed.
SAR_SCALE_FACTOR = 10000

# ══════════════════════════════════════════════════════════════════════════════
# Acquisition selection
# ══════════════════════════════════════════════════════════════════════════════

def sar_collection(region):
    """Linear-sigma0 GRD, IW mode, both polarisations present."""
    return (ee.ImageCollection('COPERNICUS/S1_GRD_FLOAT')
            .filter(ee.Filter.eq('instrumentMode', 'IW'))
            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
            .filterBounds(region))


def acquisitions(col, gap_hours=2):
    """Distinct acquisitions, oldest first, as (label, first_ms, last_ms).

    Grouped by time gap, not by calendar date. Sentinel-1 records one scene per
    frame and a 250 km swath does not cover a large state, so a single pass over
    Bihar arrives as two scenes seconds apart -- treating scenes as timesteps
    once picked two frames of the SAME pass as pre_event_1 and pre_event_2, with
    no time difference between them at all. Calendar dates are not safe either:
    those two Bihar frames land at 00:03 and 00:04 UTC, so a pass twenty minutes
    earlier would straddle midnight and split into two "dates".
    """
    stamps = sorted(col.aggregate_array('system:time_start').getInfo() or [])
    groups = []
    for ms in stamps:
        if groups and ms - groups[-1][-1] <= gap_hours * 3600_000:
            groups[-1].append(ms)
        else:
            groups.append([ms])
    return [(pd.to_datetime(g[0], unit='ms').strftime('%Y-%m-%d'), g[0], g[-1])
            for g in groups]


def mosaic_acquisition(col, acq):
    """Every frame of one acquisition, joined into a single image."""
    _, first_ms, last_ms = acq
    return col.filterDate(ee.Date(first_ms - 1000),
                          ee.Date(last_ms + 1000)).mosaic()


def orbit_sources(region, start_date):
    """One before/after triplet per relative orbit that can supply three passes.

    No single orbit covers a large AOI. Over Bihar the best reaches 66% of the
    state and the orbit that happens to pass first after onset reaches 15%, so
    measuring from one orbit measures a slice and calls it the state. Backscatter
    depends on look direction, so orbits cannot be merged into one timestep
    either -- each keeps its own triplet, and blocks are assigned to whichever
    orbit sees them.

    Returns (sources, error). Sources are ordered by post-event date, earliest
    first; each is {'orbit', 'pass', 'images', 'footprint', 'coverage_km2',
    'meta'} with images ordered post, pre_event_1, pre_event_2.
    """
    col = sar_collection(region)
    window = col.filterDate(ee.Date(start_date),
                            ee.Date(start_date).advance(POST_WINDOW_DAYS, 'day'))
    orbits = sorted(set(window.aggregate_array('relativeOrbitNumber_start')
                        .getInfo() or []))
    if not orbits:
        return [], 'NO_POST_SCENE'

    sources = []
    for orbit in orbits:
        track = col.filter(ee.Filter.eq('relativeOrbitNumber_start', orbit))
        post_acqs = acquisitions(
            track.filterDate(ee.Date(start_date),
                             ee.Date(start_date).advance(POST_WINDOW_DAYS, 'day')))
        pre_track = track.filterDate(
            ee.Date(start_date).advance(-PRE_SEARCH_DAYS, 'day'),
            ee.Date(start_date))
        pre_acqs = acquisitions(pre_track)
        if not post_acqs or len(pre_acqs) < SAR_N_PRE:
            continue

        post, pre_1, pre_2 = post_acqs[0], pre_acqs[-SAR_N_PRE], pre_acqs[-1]
        # The post pass's own footprint bounds what this orbit can measure.
        foot = (track.filterDate(ee.Date(post[1] - 1000), ee.Date(post[2] + 1000))
                .geometry().dissolve(1000).intersection(region, 1000))
        sources.append({
            'orbit': int(orbit),
            'pass': ee.Image(track.first()).get('orbitProperties_pass').getInfo(),
            'images': [mosaic_acquisition(track, post),
                       mosaic_acquisition(pre_track, pre_1),
                       mosaic_acquisition(pre_track, pre_2)],
            'footprint': foot,
            'coverage_km2': foot.area(1000).getInfo() / 1e6,
            'meta': {'pre_1_date': pre_1[0], 'pre_2_date': pre_2[0],
                     'post_date': post[0],
                     'post_lag_days': (pd.Timestamp(post[0])
                                       - pd.Timestamp(pre_2[0])).days},
        })

    if not sources:
        return [], f'NO_USABLE_ORBIT (checked {len(orbits)})'
    # Earliest post-event pass first, coverage only as a tie-break. Sorting by
    # coverage alone hands most of Bihar to orbit 85, whose post pass is ten days
    # after onset -- by then the water has moved. Orbit 121 sees 59% of the state
    # one day after onset, so timing has to lead.
    sources.sort(key=lambda d: (d['meta']['post_date'], -d['coverage_km2']))
    return sources, None


# ══════════════════════════════════════════════════════════════════════════════
# Download
# ══════════════════════════════════════════════════════════════════════════════

def lee_filter(img, window=SPECKLE_WINDOW, enl=SPECKLE_ENL):
    """Classic Lee speckle filter on linear-power SAR.

    Speckle is multiplicative, so the filter blends the local mean toward the raw
    pixel by how much of the local variance looks like real signal rather than
    noise. Flat, uniform ground is smoothed hard (b -> 0) while edges and bright
    targets keep their value (b -> 1), which is why a plain blur is not a
    substitute.
    """
    bands = img.bandNames()
    k = ee.Kernel.square(window // 2)
    mean = img.reduceNeighborhood(ee.Reducer.mean(), k).rename(bands)
    var = img.reduceNeighborhood(ee.Reducer.variance(), k).rename(bands)

    sigma_v2 = 1.0 / enl                       # noise variance of unit-mean speckle
    var_signal = (var.subtract(mean.pow(2).multiply(sigma_v2))
                  .divide(1.0 + sigma_v2).max(0))
    b = var_signal.divide(var.max(1e-12))
    return mean.add(b.multiply(img.subtract(mean))).rename(bands)


def terrain_mask():
    """Land flat enough to pond water. See SLOPE_MAX_DEG for why this is needed."""
    return ee.Terrain.slope(ee.Image('USGS/SRTMGL1_003')).lt(SLOPE_MAX_DEG)


def _download_block(image, region_block, extra=None, speckle=True):
    """One block as NPY: VV, VH plus a validity band, and `extra` bands if given.

    Order-preserving. `extra` carries the terrain mask on the first request only,
    so the static mask costs no separate round trip.
    """
    valid = image.mask().reduce(ee.Reducer.min()).rename('valid').toByte()
    sar = image.select(SAR_POLARISATIONS).toFloat()
    if speckle:
        sar = lee_filter(sar)
    # int16 transfer encoding; decoded on arrival. See SAR_SCALE_FACTOR.
    stack = sar.multiply(SAR_SCALE_FACTOR).toInt16().addBands(valid)
    if extra is not None:
        stack = stack.addBands(extra.toByte())
    url = stack.getDownloadURL({'region': region_block,
                                'scale': SAR_SCALE_M, 'format': 'NPY'})
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=300)
            r.raise_for_status()
            return np.load(io.BytesIO(r.content))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def tile_grid(region, patch_px=SAR_PATCH_SIZE, scale_m=SAR_SCALE_M):
    """Degree-space tile grid over the AOI bounds. Pure geometry -- unit tested."""
    ring = region.bounds().coordinates().getInfo()[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return grid_dims(min(lons), min(lats), max(lons), max(lats), patch_px, scale_m)


def grid_dims(minx, miny, maxx, maxy, patch_px, scale_m):
    """Return (dlat, dlon, n_rows, n_cols) for the patch grid. No Earth Engine."""
    clat = (miny + maxy) / 2.0
    dlat = patch_px * scale_m / 110540.0
    dlon = patch_px * scale_m / (111320.0 * math.cos(math.radians(clat)))
    return dlat, dlon, int((maxy - miny) / dlat), int((maxx - minx) / dlon)


def iter_patch_blocks(sources, region, skip=frozenset(), flat=None, speckle=True):
    """Yield (block_id, patches, coords, valid) per downloadable block of the AOI.

    A generator so the same tiling and download logic serves both consumers: the
    one that writes patches to disk and the one that runs them through FloodViT
    and throws them away. Storing every patch would need terabytes; streaming
    them needs none, and both paths must tile identically or their areas are not
    comparable.

    `speckle` applies the Lee filter to match Kuro Siwo's own preprocessing.
    Left switchable so its effect can be measured rather than assumed.

    `sources` is the per-orbit list from orbit_sources(). Each block is served by
    the best-covering orbit that sees it, so one AOI can span several orbits
    without any block being measured twice or from mixed viewing geometry.

    `flat` is a terrain mask downloaded as an extra band, NOT applied to the
    imagery. Patches are kept on data coverage alone; the returned `valid` mask
    is then narrowed to flat ground so the caller counts only pixels that could
    actually hold water. Blocks with no flat ground at all are never requested.

    Blocks whose id is in `skip` are not re-downloaded (resume). A block that
    fails to download yields (block_id, None, None, None) so the caller can
    count it without marking it done.
    """
    # NOT updateMask: masking the imagery would make steep pixels *invalid*, and
    # SAR_KEEP_VALID then throws away any patch that is mostly slope. A 224 px
    # patch is 2.24 km across and Sikkim's 199 km2 of flat land is strung along
    # valleys, so no patch reaches 70% flat and every one is dropped (measured:
    # 0 patches kept). "Did the satellite see this pixel" and "can this pixel
    # hold water" are different questions -- the first decides whether a patch is
    # usable, the second only which pixels count.
    ring = region.bounds().coordinates().getInfo()[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    minx, maxx, miny, maxy = min(lons), max(lons), min(lats), max(lats)
    dlat, dlon, npy_, npx_ = grid_dims(minx, miny, maxx, maxy,
                                       SAR_PATCH_SIZE, SAR_SCALE_M)
    P, B = SAR_PATCH_SIZE, SAR_BLOCK_PATCHES
    flat_band = None if flat is None else flat.rename('flat').unmask(0).toByte()
    all_blocks = [(bi, bj) for bi in range(0, npy_, B) for bj in range(0, npx_, B)]

    def blk_geom(bi, bj):
        pi, pj = min(bi + B, npy_), min(bj + B, npx_)
        return ee.Geometry.Rectangle([minx + bj * dlon, maxy - pi * dlat,
                                      minx + pj * dlon, maxy - bi * dlat])

    feats = [ee.Feature(blk_geom(bi, bj), {'i': i})
             for i, (bi, bj) in enumerate(all_blocks)]
    fc = ee.FeatureCollection(feats).filterBounds(region)
    if flat is not None:
        # Drop blocks with no flat ground at all -- in mountain states most of the
        # AOI is like this, so it removes download time as well as false positives.
        # One batched reduceRegions, not one call per block.
        fc = (flat.rename('f').unmask(0)
              .reduceRegions(fc, ee.Reducer.max(), 200)
              .filter(ee.Filter.gt('max', 0)))

    # Assign each block to the orbit that sees it, best-covering orbit first, so
    # every block is measured from a single consistent viewing geometry and no
    # block is measured twice where footprints overlap.
    assigned, claimed = {}, set()
    for si, src in enumerate(sources):
        ids = set(fc.filterBounds(src['footprint']).aggregate_array('i').getInfo())
        for i in ids - claimed:
            assigned[i] = si
        claimed |= ids
    inside = set(assigned)
    todo = [(i, bi, bj) for i, (bi, bj) in enumerate(all_blocks)
            if i in inside and i not in skip]
    per_orbit = {src['orbit']: sum(1 for v in assigned.values() if v == si)
                 for si, src in enumerate(sources)}
    print(f"    tiling: {npx_}x{npy_} patches @{SAR_SCALE_M}m, "
          f"{len(inside)} blocks assigned across {len(sources)} orbit(s) "
          f"{per_orbit}, {len(todo)} to download")

    yield ('__total__', len(inside), len(todo), None)

    bar = tqdm(todo, desc='    downloading', unit='blk')
    for i, bi, bj in bar:
        pi, pj = min(bi + B, npy_), min(bj + B, npx_)
        lon0, lat_top = minx + bj * dlon, maxy - bi * dlat
        block = ee.Geometry.Rectangle([lon0, maxy - pi * dlat,
                                       minx + pj * dlon, lat_top])
        images = sources[assigned[i]]['images']
        try:
            with ThreadPoolExecutor(max_workers=len(images)) as ex:
                arrs = list(ex.map(
                    lambda p: _download_block(
                        p[1], block,
                        extra=flat_band if p[0] == 0 else None,
                        speckle=speckle),
                    enumerate(images)))
        except Exception as e:
            bar.write(f"      block ({bi},{bj}) failed: {e}")
            yield (i, None, None, None)
            continue

        H = min(a.shape[0] for a in arrs)
        W = min(a.shape[1] for a in arrs)
        rows, cols = H // P, W // P

        batch, coords, valids = [], [], []
        for r in range(rows):
            for c in range(cols):
                rs, cs = r * P, c * P
                vmask = np.logical_and.reduce(
                    [a['valid'][rs:rs + P, cs:cs + P] > 0 for a in arrs])
                if vmask.mean() < SAR_KEEP_VALID:      # data coverage only
                    continue
                if flat_band is not None:              # then narrow to flat ground
                    vmask = vmask & (arrs[0]['flat'][rs:rs + P, cs:cs + P] > 0)
                # (post VV,VH, pre1 VV,VH, pre2 VV,VH) -- the model's 6 channels
                # back to linear sigma0 from the int16 transfer encoding
                chans = [a[b][rs:rs + P, cs:cs + P].astype(np.float32)
                         / SAR_SCALE_FACTOR
                         for a in arrs for b in SAR_POLARISATIONS]
                batch.append(np.stack(chans))
                valids.append(vmask)
                coords.append([(bi + r) * P, (bj + c) * P,
                               lat_top - (r + 0.5) * dlat, lon0 + (c + 0.5) * dlon])

        # An empty (not None) array means "downloaded fine, nothing kept" --
        # e.g. an all-cloud/ocean block. None is reserved for download failure,
        # so a legitimately empty block is still marked done and never retried.
        if batch:
            yield (i, np.stack(batch), np.array(coords, dtype='float64'),
                   np.stack(valids))
        else:
            yield (i,
                   np.empty((0, SAR_CHANNELS, P, P), dtype=np.float32),
                   np.empty((0, 4), dtype='float64'),
                   np.empty((0, P, P), dtype=bool))
        bar.set_postfix(blk=i)
