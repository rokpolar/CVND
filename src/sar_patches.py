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

Two deliberate differences from Kuro Siwo's own preprocessing
-------------------------------------------------------------
1. No speckle filter. Their SNAP graph applies Lee Sigma 3x3; Earth Engine has
   no Lee Sigma, and substituting a different filter would shift the value
   distribution the released normalisation constants were fitted on. Left off so
   the difference is a known, testable one rather than a hidden approximation.
2. GEE's S1_GRD_FLOAT is already orbit-corrected, thermal-noise-removed,
   border-noise-removed, calibrated and terrain-corrected against SRTM -- the
   same chain minus the filter.

Both belong in the paper's limitations until measured.

Output: one HDF5 per event under data/cache/sar_patches/<event_id>.h5
    patches (N, 6, 224, 224) float32   post VV,VH then pre1 VV,VH then pre2 VV,VH
    coords  (N, 4) float64             row, col, lat, lon
Run: python src/sar_patches.py --events E001 E002
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time

import h5py
import numpy as np
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ee  # noqa: E402

from cvnd_layout import data_path  # noqa: E402


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

OUTPUT_DIR = str(data_path("sar_patches"))
INDEX_CSV = str(data_path("sar_patches_index"))
CHECKPOINT = str(data_path("sar_checkpoint"))
EVENTS_CSV = str(data_path("events"))


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


def pick_triplet(region, start_date):
    """Choose (post_event, pre_event_1, pre_event_2) from ONE relative orbit.

    SAR backscatter depends on look direction and incidence angle, so comparing
    scenes from different relative orbits registers geometry as change. Kuro Siwo
    builds its triplets from a single track for this reason; anything else feeds
    the model a difference it was never trained to ignore.

    Returns (images, meta) with images ordered post, pre_event_1, pre_event_2
    to match the trainer's channel layout, or (None, reason) when the track has
    too few usable acquisitions.
    """
    col = sar_collection(region)
    post_col = (col.filterDate(ee.Date(start_date),
                               ee.Date(start_date).advance(POST_WINDOW_DAYS, 'day'))
                .sort('system:time_start'))
    if post_col.size().getInfo() == 0:
        return None, 'NO_POST_SCENE'

    post = ee.Image(post_col.first())
    info = post.getInfo()['properties']
    orbit = info['relativeOrbitNumber_start']
    passdir = info['orbitProperties_pass']
    post_ms = info['system:time_start']

    # same track only, strictly before onset
    pre_col = (col
               .filter(ee.Filter.eq('relativeOrbitNumber_start', orbit))
               .filter(ee.Filter.eq('orbitProperties_pass', passdir))
               .filterDate(ee.Date(start_date).advance(-PRE_SEARCH_DAYS, 'day'),
                           ee.Date(start_date))
               .sort('system:time_start', False))          # newest first
    n_pre = pre_col.size().getInfo()
    if n_pre < SAR_N_PRE:
        return None, f'ONLY_{n_pre}_PRE_SCENES_ON_ORBIT_{orbit}'

    pre_list = pre_col.toList(SAR_N_PRE)
    newest = ee.Image(pre_list.get(0))
    older = ee.Image(pre_list.get(1))

    def stamp(img):
        return img.getInfo()['properties']['system:time_start']

    # post first, matching the trainer's cat(post, pre1, pre2)
    meta = {
        'relative_orbit': int(orbit),
        'orbit_pass': passdir,
        'pre_1_date': _iso(stamp(older)),      # oldest first, matching the
        'pre_2_date': _iso(stamp(newest)),     # config's pre_event_1/2 order
        'post_date': _iso(post_ms),
        'post_lag_days': round((post_ms - stamp(newest)) / 86400000.0, 1),
        'n_pre_available': int(n_pre),
    }
    return [post, older, newest], meta


def _iso(ms):
    return pd.to_datetime(ms, unit='ms').strftime('%Y-%m-%d')


# ══════════════════════════════════════════════════════════════════════════════
# Download
# ══════════════════════════════════════════════════════════════════════════════

def _append(hdf, patches, coords):
    """Grow the resizable datasets by one block's worth of patches."""
    for name, val in (('patches', patches), ('coords', coords)):
        ds = hdf[name]
        n0 = ds.shape[0]
        ds.resize(n0 + val.shape[0], axis=0)
        ds[n0:] = val


def _download_block(image, region_block):
    """One block as NPY: VV, VH plus a validity band. Order-preserving."""
    valid = image.mask().reduce(ee.Reducer.min()).rename('valid').toByte()
    stack = image.select(SAR_POLARISATIONS).toFloat().addBands(valid)
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


def iter_patch_blocks(images, region, skip=frozenset()):
    """Yield (block_id, patches, coords) for each downloadable block of the AOI.

    A generator so the same tiling and download logic serves both consumers: the
    one that writes patches to disk and the one that runs them through FloodViT
    and throws them away. Storing every patch would need terabytes; streaming
    them needs none, and both paths must tile identically or their areas are not
    comparable.

    Blocks whose id is in `skip` are not re-downloaded (resume). A block that
    fails to download yields (block_id, None, None) so the caller can count it
    without marking it done.
    """
    ring = region.bounds().coordinates().getInfo()[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    minx, maxx, miny, maxy = min(lons), max(lons), min(lats), max(lats)
    dlat, dlon, npy_, npx_ = grid_dims(minx, miny, maxx, maxy,
                                       SAR_PATCH_SIZE, SAR_SCALE_M)
    P, B = SAR_PATCH_SIZE, SAR_BLOCK_PATCHES
    all_blocks = [(bi, bj) for bi in range(0, npy_, B) for bj in range(0, npx_, B)]

    def blk_geom(bi, bj):
        pi, pj = min(bi + B, npy_), min(bj + B, npx_)
        return ee.Geometry.Rectangle([minx + bj * dlon, maxy - pi * dlat,
                                      minx + pj * dlon, maxy - bi * dlat])

    feats = [ee.Feature(blk_geom(bi, bj), {'i': i})
             for i, (bi, bj) in enumerate(all_blocks)]
    inside = set(ee.FeatureCollection(feats).filterBounds(region)
                 .aggregate_array('i').getInfo())
    todo = [(i, bi, bj) for i, (bi, bj) in enumerate(all_blocks)
            if i in inside and i not in done_blocks]
    print(f"    tiling: {npx_}x{npy_} patches @{SAR_SCALE_M}m, "
          f"{len(inside)}/{len(all_blocks)} blocks in AOI, {len(todo)} to download")

    yield ('__total__', len(inside), len(todo))

    bar = tqdm(todo, desc='    downloading', unit='blk')
    for i, bi, bj in bar:
        pi, pj = min(bi + B, npy_), min(bj + B, npx_)
        lon0, lat_top = minx + bj * dlon, maxy - bi * dlat
        block = ee.Geometry.Rectangle([lon0, maxy - pi * dlat,
                                       minx + pj * dlon, lat_top])
        try:
            with ThreadPoolExecutor(max_workers=len(images)) as ex:
                arrs = list(ex.map(lambda im: _download_block(im, block), images))
        except Exception as e:
            bar.write(f"      block ({bi},{bj}) failed: {e}")
            yield (i, None, None)
            continue

        H = min(a.shape[0] for a in arrs)
        W = min(a.shape[1] for a in arrs)
        rows, cols = H // P, W // P

        batch, coords = [], []
        for r in range(rows):
            for c in range(cols):
                rs, cs = r * P, c * P
                if min(float(a['valid'][rs:rs + P, cs:cs + P].mean())
                       for a in arrs) < SAR_KEEP_VALID:
                    continue
                # (post VV,VH, pre1 VV,VH, pre2 VV,VH) -- the model's 6 channels
                chans = [a[b][rs:rs + P, cs:cs + P].astype(np.float32)
                         for a in arrs for b in SAR_POLARISATIONS]
                batch.append(np.stack(chans))
                coords.append([(bi + r) * P, (bj + c) * P,
                               lat_top - (r + 0.5) * dlat, lon0 + (c + 0.5) * dlon])

        # An empty (not None) array means "downloaded fine, nothing kept" --
        # e.g. an all-cloud/ocean block. None is reserved for download failure,
        # so a legitimately empty block is still marked done and never retried.
        if batch:
            yield (i, np.stack(batch), np.array(coords, dtype='float64'))
        else:
            yield (i,
                   np.empty((0, SAR_CHANNELS, P, P), dtype=np.float32),
                   np.empty((0, 4), dtype='float64'))
        bar.set_postfix(blk=i)


def _tile_region(images, region, hdf, done_blocks, blocks_ckpt):
    """Consume iter_patch_blocks, writing every kept patch to the open HDF5."""
    failed = 0
    total = 0
    for block_id, patches, coords in iter_patch_blocks(images, region, done_blocks):
        if block_id == '__total__':
            total = patches
            continue
        if patches is None:                 # download failed -> retry next run
            failed += 1
            continue
        if len(patches):
            _append(hdf, patches, coords)
        done_blocks.add(block_id)
        _sat()._save_block_progress(blocks_ckpt, done_blocks, total, failed)
    return hdf['patches'].shape[0], failed


def prepare_event(row):
    """Download one event's SAR patch stack. Returns (path, complete) or None."""
    sat = _sat()
    sat.ensure_gee() if hasattr(sat, 'ensure_gee') else None
    event_id, state = row['event_id'], row['state']
    print(f"\n  [SAR] [{event_id}] {state} — {row['start_date']}")

    region = sat.get_region(row)
    images, meta = pick_triplet(region, row['start_date'])
    if images is None:
        print(f"    -> skip: {meta}")
        return None, meta
    print(f"    orbit {meta['relative_orbit']} {meta['orbit_pass']} | "
          f"pre {meta['pre_1_date']}, {meta['pre_2_date']} -> post {meta['post_date']} "
          f"(+{meta['post_lag_days']}d)")

    images = [im.clip(region) for im in images]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f'{event_id}.h5')
    blocks_ckpt = out_path + '.blocks.json'
    P = SAR_PATCH_SIZE

    done_blocks = set()
    resume = os.path.exists(out_path) and os.path.exists(blocks_ckpt)
    if resume:
        done_blocks, prev_total = _sat()._load_block_progress(blocks_ckpt)
        print(f"    resuming: {len(done_blocks)}"
              f"{f'/{prev_total}' if prev_total else ''} blocks done")

    with h5py.File(out_path, 'a' if resume else 'w') as f:
        if not resume:
            f.create_dataset('patches', shape=(0, SAR_CHANNELS, P, P),
                             maxshape=(None, SAR_CHANNELS, P, P), dtype='float32',
                             chunks=(1, SAR_CHANNELS, P, P))
            f.create_dataset('coords', shape=(0, 4), maxshape=(None, 4), dtype='float64')
            g = f.create_group('meta')
            g.attrs['event_id'] = event_id
            g.attrs['state'] = str(state)
            g.attrs['start_date'] = row['start_date']
            g.attrs['channels'] = 'post_VV,post_VH,pre1_VV,pre1_VH,pre2_VV,pre2_VH'
            g.attrs['scale_m'] = SAR_SCALE_M
            g.attrs['patch_size'] = P
            g.attrs['scale'] = 'linear_sigma0'
            g.attrs['speckle_filter'] = 'none'
            for k, v in meta.items():
                g.attrs[k] = v
        n, failed = _tile_region(images, region, f, done_blocks, blocks_ckpt)

    complete = failed == 0
    if complete and os.path.exists(blocks_ckpt):
        os.remove(blocks_ckpt)
    print(f"    Saved: {out_path}  [{n} patches, {failed} blocks failed]")
    return (out_path, complete), meta


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--events', nargs='*', default=None, help='only these event_ids')
    p.add_argument('--checkpoint', default=None, help='checkpoint path (parallel runs)')
    p.add_argument('--index', default=None, help='index CSV path (parallel runs)')
    args = p.parse_args()

    ckpt_path = args.checkpoint or CHECKPOINT
    index_path = args.index or INDEX_CSV

    events = pd.read_csv(EVENTS_CSV)
    if args.events:
        events = events[events['event_id'].isin(args.events)]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for target in (ckpt_path, index_path):
        os.makedirs(os.path.dirname(target), exist_ok=True)

    done = _sat().load_checkpoint(ckpt_path)
    remaining = events[~events['event_id'].isin(set(done))]
    print(f"Already done: {len(done)} | Remaining: {len(remaining)}")

    for _, row in remaining.iterrows():
        ev = row['event_id']
        try:
            res, meta = prepare_event(row)
        except Exception as e:
            print(f"  ERROR {ev}: {e}")
            done[ev] = {'event_id': ev, 'h5_path': None, 'status': f'ERROR: {e}'}
            _sat().save_checkpoint(done, ckpt_path)
            continue
        if res is None:
            done[ev] = {'event_id': ev, 'h5_path': None, 'status': f'SKIPPED: {meta}'}
            _sat().save_checkpoint(done, ckpt_path)
            continue
        path, complete = res
        if not complete:
            print(f"  {ev}: incomplete -> will retry on re-run")
            continue
        done[ev] = {'event_id': ev, 'h5_path': path, 'status': 'OK', **meta}
        _sat().save_checkpoint(done, ckpt_path)

    if done:
        pd.DataFrame(list(done.values())).sort_values('event_id').to_csv(
            index_path, index=False)
        ok = sum(1 for v in done.values() if v.get('status') == 'OK')
        print(f"\nComplete: {ok}/{len(events)}   index -> {index_path}")


if __name__ == '__main__':
    main()
