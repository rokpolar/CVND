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
    2,3  pre_event_1 VV, VH   (the pre-event pass CLOSER to the flood)
    4,5  pre_event_2 VV, VH   (the earlier one)

Which pre-event scene is which is not a naming detail: their own grid dictionary
(pickle/KuroV2_grid_dict.gz) carries a source_date per acquisition, and in all
31,707 records SL1 is NEWER than SL2 -- median gap 12 days, one repeat cycle.
Handing the model the older scene as pre_event_1 swaps channels 2,3 with 4,5.

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

from cvnd_config import MEDIA_WINDOW_DAYS  # noqa: E402



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
# Half of the 204 events outlast 14 days (median span 14.5, mean 35.2, max 167;
# 68 events run past 30 days and 19 past 90). Taking only the first pass after
# onset measured days 1-14 of a 74-day flood, and 21 events carry
# `start:month` precision so their start_date is the 1st of the month while the
# flood runs to the end of it. Worse, that error is not random: severe floods
# last longer, so the largest events were the most likely to be measured before
# their peak -- which pushes the severity proxy DOWN exactly where severity is
# highest and flattens the very relationship the study measures.
# So the window follows the event's own end_date, and several post-event passes
# are read rather than one.
# The ceiling is the media window, so severity and coverage describe the SAME
# period -- that equality is the whole comparison the study makes. It costs
# nothing: the number of downloads is SAR_MAX_POST either way, and the window only
# decides which passes those are. A shorter ceiling truncated severity for 56 of
# the 204 events (27.5%) while their coverage kept accumulating to day 93; at 93
# both sides truncate at the same place and only 16 events (7.8%) run past it.
POST_WINDOW_DAYS = 14         # minimum window, for events recorded as a single day
POST_WINDOW_CAP_DAYS = MEDIA_WINDOW_DAYS
SAR_MAX_POST = 3              # post-event passes read per orbit
PRE_SEARCH_DAYS = 90          # look this far back for the two pre-event scenes

# ── tiling ────────────────────────────────────────────────────────────────────
# 8*224 = 1792 px/side -> ~26 MB per timestep request, inside GEE's 48 MB limit.
# Fewer, larger requests: at 4 the same AOI needs ~425k blocks, at 8 only ~108k.
SAR_BLOCK_PATCHES = 8
# Patches below this are dropped. No-data is filled with the clamp before the
# model sees it, which is a guess either way, so the fewer such pixels the
# better; at 0.70 nearly a third of a patch could have been invented. Raised now
# that blocks tile exactly and only true AOI and swath edges fall short.
SAR_KEEP_VALID = 0.95

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
# The model clamps at 0.15 before normalising, so nothing above that survives
# anyway -- clamping here removes an overflow instead of losing information.
# Sigma0 reaches 225 over Bihar's built-up areas; at 1/10000 that wrapped past
# int16 and came back NEGATIVE, turning the brightest targets in the scene into
# the darkest, which reads as water. Clamped, the range fits with room to spare.
SAR_CLAMP = 0.15
SAR_SCALE_FACTOR = 200000        # 0.15 * 200000 = 30000 < 32767

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


def post_window_days(start_date, end_date=None, minimum=POST_WINDOW_DAYS,
                     cap=POST_WINDOW_CAP_DAYS):
    """How many days after onset to search for post-event passes.

    The event's own end_date sets it, floored at `minimum` so a one-day record
    still gets a pass at all (the repeat cycle is 12 days) and capped at the media
    window so severity and article counts describe the same period. The cap is not
    about cost: the number of downloads is SAR_MAX_POST either way.

    An absent or malformed end_date falls back to the minimum rather than
    guessing -- NaT, NaN, '' and unparseable strings all land there.
    """
    if end_date is None or (isinstance(end_date, float) and end_date != end_date):
        return minimum
    try:
        span = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    except (ValueError, TypeError):
        return minimum
    if span != span or span <= 0:
        return minimum
    return int(min(max(span, minimum), cap))


def pick_posts(post_acqs, max_post=SAR_MAX_POST):
    """Up to `max_post` post-event passes spread across the window.

    Both ends are always included -- the first pass after onset and the last one
    inside the window -- with the rest spaced evenly between. Reading only the
    first pass is what measured the start of a flood instead of its peak.
    """
    if max_post < 1:
        raise ValueError('max_post must be at least 1')
    if len(post_acqs) <= max_post:
        return list(post_acqs)
    if max_post == 1:
        return [post_acqs[0]]
    last = len(post_acqs) - 1
    idx = sorted({int(round(i * last / (max_post - 1))) for i in range(max_post)})
    return [post_acqs[i] for i in idx]


def order_acquisitions(post_acqs, pre_acqs, max_post=SAR_MAX_POST):
    """(posts, pre_event_1, pre_event_2) out of two oldest-first lists.

    pre_event_1 is the LAST pass before onset and pre_event_2 the one before it.
    Kuro Siwo's own grid dictionary (pickle/KuroV2_grid_dict.gz) carries a
    source_date per acquisition and SL1 is newer than SL2 in all 31,707 records,
    median gap 12 days. Reversing the two hands the model the opposite of its
    training layout in channels 2,3 and 4,5, which produces a plausible but
    wrong mask with nothing to raise an error.

    Kept separate from orbit_sources so the rules can be tested without Earth
    Engine -- the pre-event order was wrong here for every India measurement
    taken up to method version 8.
    """
    return pick_posts(post_acqs, max_post), pre_acqs[-1], pre_acqs[-SAR_N_PRE]


def mosaic_acquisition(col, acq):
    """Every frame of one acquisition, joined into a single image."""
    _, first_ms, last_ms = acq
    return col.filterDate(ee.Date(first_ms - 1000),
                          ee.Date(last_ms + 1000)).mosaic()


def orbit_sources(region, start_date, end_date=None, max_post=SAR_MAX_POST):
    """Post-event passes plus two pre-event scenes, per relative orbit.

    No single orbit covers a large AOI. Over Bihar the best reaches 66% of the
    state and the orbit that happens to pass first after onset reaches 15%, so
    measuring from one orbit measures a slice and calls it the state. Backscatter
    depends on look direction, so orbits cannot be merged into one timestep
    either -- each keeps its own scenes, and blocks are assigned to whichever
    orbit sees them.

    `end_date` opens the post-event window to the length of the event; without
    it the window is POST_WINDOW_DAYS, which measured the first two weeks of
    floods that ran for months.

    Returns (sources, error). Sources are ordered by coverage, largest first;
    each is {'orbit', 'pass', 'posts', 'pres', 'footprint',
    'coverage_km2', 'meta'} -- `posts` is up to max_post post-event images,
    oldest first, and `pres` is [pre_event_1, pre_event_2].
    """
    col = sar_collection(region)
    win = post_window_days(start_date, end_date)
    window = col.filterDate(ee.Date(start_date),
                            ee.Date(start_date).advance(win, 'day'))
    orbits = sorted(set(window.aggregate_array('relativeOrbitNumber_start')
                        .getInfo() or []))
    if not orbits:
        # Say WHICH reason. 42 of the 204 events fall in 2015-2016, when
        # Sentinel-1 was a single satellite with thinner coverage of India, and a
        # bare NO_POST_SCENE cannot distinguish "nothing flew over" from "it flew
        # but recorded VV only" -- the model needs VH, so the second is a hard
        # limit of the data and the first might be fixed by a wider window.
        # Only runs on the failure path, so it costs nothing in the normal case.
        try:
            vv_only = (ee.ImageCollection('COPERNICUS/S1_GRD_FLOAT')
                       .filter(ee.Filter.eq('instrumentMode', 'IW'))
                       .filterBounds(region)
                       .filterDate(ee.Date(start_date),
                                   ee.Date(start_date).advance(win, 'day'))
                       .size().getInfo())
        except Exception:
            vv_only = None
        if vv_only:
            return [], (f'NO_DUAL_POL ({vv_only} IW scene(s) in the window, none '
                        'with both VV and VH; FloodViT needs VH)')
        return [], f'NO_POST_SCENE (no IW scene in {win} days)'

    sources, shortfall = [], []
    for orbit in orbits:
        track = col.filter(ee.Filter.eq('relativeOrbitNumber_start', orbit))
        post_acqs = acquisitions(
            track.filterDate(ee.Date(start_date),
                             ee.Date(start_date).advance(win, 'day')))
        pre_track = track.filterDate(
            ee.Date(start_date).advance(-PRE_SEARCH_DAYS, 'day'),
            ee.Date(start_date))
        pre_acqs = acquisitions(pre_track)
        if not post_acqs or len(pre_acqs) < SAR_N_PRE:
            # Recorded so the failure message below can name the reason: a
            # missing post pass and a missing pre-event baseline need different
            # answers (a wider post window vs a longer PRE_SEARCH_DAYS).
            shortfall.append(f'orbit {int(orbit)}: '
                             f'{len(post_acqs)} post, {len(pre_acqs)} pre '
                             f'(need {SAR_N_PRE})')
            continue

        posts, pre_1, pre_2 = order_acquisitions(post_acqs, pre_acqs, max_post)
        # The first post pass's footprint bounds what this orbit can measure.
        # Later passes of the same relative orbit repeat the same track, and a
        # patch is kept only where every pass is valid, so frame-edge drift
        # narrows the count rather than inventing coverage.
        post = posts[0]
        foot = (track.filterDate(ee.Date(post[1] - 1000), ee.Date(post[2] + 1000))
                .geometry().dissolve(1000).intersection(region, 1000))
        sources.append({
            'orbit': int(orbit),
            'pass': ee.Image(track.first()).get('orbitProperties_pass').getInfo(),
            'posts': [mosaic_acquisition(track, p) for p in posts],
            'pres': [mosaic_acquisition(pre_track, pre_1),
                     mosaic_acquisition(pre_track, pre_2)],
            'footprint': foot,
            'coverage_km2': foot.area(1000).getInfo() / 1e6,
            # post_lag_days is the gap to the LAST pre-event pass, which is the
            # baseline the change is measured against -- pre_event_1 now that
            # the two are the right way round.
            'meta': {'pre_1_date': pre_1[0], 'pre_2_date': pre_2[0],
                     'post_date': post[0],
                     # every pass read, so a reported area can be traced to the
                     # dates it was measured on rather than just the first one
                     'post_dates': [p[0] for p in posts],
                     'n_post': len(posts),
                     'window_days': win,
                     'post_lag_days': (pd.Timestamp(post[0])
                                       - pd.Timestamp(pre_1[0])).days},
        })

    if not sources:
        return [], (f'NO_USABLE_ORBIT (checked {len(orbits)}; '
                    f'{"; ".join(shortfall[:4])})')
    # Best-covering orbit first, earliest post pass as the tie-break.
    #
    # Up to method version 9 this was the other way round: earliest post date
    # led, because an orbit whose single post pass fell ten days after onset
    # measured water that had already moved, and orbit 121 saw 59% of Bihar one
    # day after onset. With several passes read per orbit across the whole event
    # window, every orbit now samples the same period, so that reason is gone --
    # and coverage-first keeps more of the AOI under one viewing geometry, which
    # is the remaining thing that differs between orbits.
    sources.sort(key=lambda d: (-d['coverage_km2'], d['meta']['post_date']))
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


def utm_crs(region):
    """EPSG code of the UTM zone under the AOI centroid.

    mosaic() drops the source projection: the result reports EPSG:4326 with a
    1-degree transform, so getDownloadURL(scale=10) lays down a grid that is
    square in DEGREES. At Bihar's latitude that is 9.93 m north-south but 9.02 m
    east-west -- 89.6 m2 per pixel instead of 100, an 11% area error that grows
    with latitude -- and it resamples the native UTM 10 m imagery onto a skewed
    grid before the model and the speckle filter ever see it. Requesting an
    explicit metric CRS restores true 10 m pixels.
    """
    c = region.centroid(1000).coordinates().getInfo()
    zone = int((c[0] + 180) / 6) + 1
    return f"EPSG:{326 if c[1] >= 0 else 327}{zone:02d}"


def terrain_mask():
    """Land flat enough to pond water. See SLOPE_MAX_DEG for why this is needed."""
    return ee.Terrain.slope(ee.Image('USGS/SRTMGL1_003')).lt(SLOPE_MAX_DEG)


def _download_block(image, region_block, extra=None, speckle=True, crs=None):
    """One block as NPY: VV, VH plus a validity band, and `extra` bands if given.

    Order-preserving. `extra` carries the terrain mask on the first request only,
    so the static mask costs no separate round trip.
    """
    img = image.select(SAR_POLARISATIONS)
    if crs:
        # Pin the grid before anything reads neighbours or masks: reduceNeighborhood
        # works in the image's projection, so on a mosaic's default 1-degree grid a
        # "3x3" window is not 3x3 native pixels. Pinned here rather than on the SAR
        # bands alone so the validity mask is resampled on the same grid as the
        # values it describes -- otherwise the two disagree along swath edges and
        # pixels get counted as observed that were not.
        img = img.setDefaultProjection(crs, None, SAR_SCALE_M)
    # Validity from the polarisations actually used. S1_GRD_FLOAT also carries an
    # `angle` band whose coverage differs, and including it mislabels good pixels.
    valid = img.mask().reduce(ee.Reducer.min()).rename('valid').toByte()
    sar = img.toFloat()
    if speckle:
        sar = lee_filter(sar)          # filter the real values, then clamp
    # int16 transfer encoding; decoded on arrival. See SAR_CLAMP/SAR_SCALE_FACTOR.
    stack = (sar.clamp(0.0, SAR_CLAMP)
             .multiply(SAR_SCALE_FACTOR).toInt16().addBands(valid))
    if extra is not None:
        stack = stack.addBands(extra.toByte())
    params = {'region': region_block, 'scale': SAR_SCALE_M, 'format': 'NPY'}
    if crs:
        params['crs'] = crs
    url = stack.getDownloadURL(params)
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=300)
            r.raise_for_status()
            return np.load(io.BytesIO(r.content))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def grid_dims(minx, miny, maxx, maxy, patch_px=SAR_PATCH_SIZE,
              scale_m=SAR_SCALE_M):
    """(rows, cols) of patches over a projected-metre bounding box.

    Metres in, metres out: no latitude term, because the grid now lives in the
    same UTM CRS the imagery is requested in. The degree-space version this
    replaces needed 110540/111320 approximations and still produced blocks whose
    projected footprints overlapped.
    """
    side = patch_px * scale_m
    return int((maxy - miny) / side), int((maxx - minx) / side)


def iter_patch_blocks(sources, region, skip=frozenset(), flat=None, speckle=True):
    """Yield (block_id, batches, coords, valid) per downloadable block of the AOI.

    `batches` is one (n_patches, 6, 224, 224) array per post-event pass, all over
    the same patches in the same order, sharing `coords` and `valid`. The caller
    classifies each and keeps the largest flood it saw: reading only the first
    pass after onset measured the start of a flood rather than its peak, and half
    of the events last longer than the old 14-day window.


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
    # The grid is laid out in the SAME metric CRS the blocks are downloaded in.
    # Building it in degrees instead made each block a lat/lon rectangle whose
    # UTM bounding box overlaps its neighbours', so adjacent blocks could count
    # the same ground twice and leave slivers uncounted between them. In UTM the
    # blocks tile exactly and every patch is exactly 224 * 10 m on a side.
    P, B = SAR_PATCH_SIZE, SAR_BLOCK_PATCHES
    crs = utm_crs(region)
    proj = ee.Projection(crs)
    ring = region.bounds(1, proj).coordinates().getInfo()[0]
    xs = [pt[0] for pt in ring]
    ys = [pt[1] for pt in ring]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    patch_m = P * SAR_SCALE_M
    npy_ = int((maxy - miny) / patch_m)
    npx_ = int((maxx - minx) / patch_m)
    flat_band = None if flat is None else flat.rename('flat').unmask(0).toByte()
    all_blocks = [(bi, bj) for bi in range(0, npy_, B) for bj in range(0, npx_, B)]

    def blk_geom(bi, bj):
        pi, pj = min(bi + B, npy_), min(bj + B, npx_)
        return ee.Geometry.Rectangle(
            [minx + bj * patch_m, maxy - pi * patch_m,
             minx + pj * patch_m, maxy - bi * patch_m],
            proj=proj, geodesic=False)

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
    print(f"    tiling: {npx_}x{npy_} patches @{SAR_SCALE_M}m {crs}, "
          f"{len(inside)} blocks assigned across {len(sources)} orbit(s) "
          f"{per_orbit}, {len(todo)} to download")

    yield ('__total__', len(inside), len(todo), None)

    bar = tqdm(todo, desc='    downloading', unit='blk')
    for i, bi, bj in bar:
        x0, y_top = minx + bj * patch_m, maxy - bi * patch_m
        block = blk_geom(bi, bj)
        src = sources[assigned[i]]
        images = list(src['posts']) + list(src['pres'])
        n_post = len(src['posts'])
        try:
            with ThreadPoolExecutor(max_workers=len(images)) as ex:
                arrs = list(ex.map(
                    lambda p: _download_block(
                        p[1], block,
                        extra=flat_band if p[0] == 0 else None,
                        speckle=speckle, crs=crs),
                    enumerate(images)))
        except Exception as e:
            bar.write(f"      block ({bi},{bj}) failed: {e}")
            yield (i, None, None, None)
            continue

        H = min(a.shape[0] for a in arrs)
        W = min(a.shape[1] for a in arrs)
        rows, cols = H // P, W // P
        pres = arrs[n_post:]

        def _chan(a, rs, cs):
            """One acquisition's VV,VH for a patch, no-data as NaN.

            Back to linear sigma0 from the int16 transfer encoding. Masked pixels
            arrive as the int16 sentinel, which decodes to -3.2768 and then clips
            to 0 -- the darkest possible value, which is exactly what water looks
            like to the model. Kuro Siwo fills no-data with the clamp instead
            (nan_to_num(image, CLAMP)) and preprocess() does the same with NaN,
            so hand it NaN rather than a fake dark pixel.
            """
            bad = a['valid'][rs:rs + P, cs:cs + P] == 0
            out = []
            for b in SAR_POLARISATIONS:
                ch = a[b][rs:rs + P, cs:cs + P].astype(np.float32)
                ch /= SAR_SCALE_FACTOR
                ch[bad] = np.nan
                out.append(ch)
            return out

        # One batch per post-event pass; the two pre-event scenes are shared, so
        # each batch is (that post VV,VH, pre1 VV,VH, pre2 VV,VH) -- the model's
        # six channels. The caller reads the same ground at several dates and
        # keeps the largest flood it saw, instead of whatever the first pass
        # after onset happened to catch.
        batches = [[] for _ in range(n_post)]
        coords, valids = [], []
        for r in range(rows):
            for c in range(cols):
                rs, cs = r * P, c * P
                # Validity across EVERY pass, so all post dates describe the same
                # ground and their flood counts are comparable to each other.
                vmask = np.logical_and.reduce(
                    [a['valid'][rs:rs + P, cs:cs + P] > 0 for a in arrs])
                if vmask.mean() < SAR_KEEP_VALID:      # data coverage only
                    continue
                if flat_band is not None:              # then narrow to flat ground
                    vmask = vmask & (arrs[0]['flat'][rs:rs + P, cs:cs + P] > 0)
                pre_ch = [ch for a in pres for ch in _chan(a, rs, cs)]
                for k in range(n_post):
                    batches[k].append(np.stack(_chan(arrs[k], rs, cs) + pre_ch))
                valids.append(vmask)
                # row, col in the AOI-wide patch grid, then the patch centre in
                # projected metres (crs is recorded on the run, not per patch)
                coords.append([(bi + r) * P, (bj + c) * P,
                               y_top - (r + 0.5) * patch_m,
                               x0 + (c + 0.5) * patch_m])

        # An empty (not None) array means "downloaded fine, nothing kept" --
        # e.g. an all-cloud/ocean block. None is reserved for download failure,
        # so a legitimately empty block is still marked done and never retried.
        if coords:
            yield (i, [np.stack(b) for b in batches],
                   np.array(coords, dtype='float64'), np.stack(valids))
        else:
            yield (i,
                   [np.empty((0, SAR_CHANNELS, P, P), dtype=np.float32)],
                   np.empty((0, 4), dtype='float64'),
                   np.empty((0, P, P), dtype=bool))
        bar.set_postfix(blk=i)
