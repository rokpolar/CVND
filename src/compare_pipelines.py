"""compare_pipelines.py — score OUR Earth Engine chain against Kuro Siwo's own
preprocessing, on the same ground, the same dates, and the same expert labels.

Why this and not validate_floodvit.py
-------------------------------------
validate_floodvit.py reads Kuro Siwo's finished GeoTIFFs, so it exercises only
preprocess() and predict(). It reported flood F1 0.701 and that settled the
normalisation, the channel order and the model loading -- but it never touched
the part of the pipeline that is ours alone:

    orbit and date selection, mosaicking of several frames, reprojection to UTM,
    the Lee filter (SNAP's Lee Sigma has no Earth Engine equivalent), the int16
    transfer encoding, and filling no-data.

Those run only on India, and India is where the model stops responding to floods
(6.4% of observed land called flood during the October 2025 Bihar flood, 7.3% in
the dry season). Either the chain is sound and the model does not transfer, or
the chain damages the input. Nothing measured so far separates those.

So: take a labelled Kuro Siwo sample, read its footprint and date straight out of
the GeoTIFF, pull the same place and dates through OUR chain, and score both
against the same expert labels. Same ground, same truth, one difference.

    ours much worse  -> the fault is in the Earth Engine chain, and fixing it
                        should bring India back
    both alike       -> the chain is sound and India is domain transfer

Run
---
    python src/compare_pipelines.py --data-root /content/kuro_sample \\
        --checkpoint /content/drive/MyDrive/cvnd_state/floodvit.pt \\
        --kuro-siwo-repo /content/KuroSiwo --device cuda --limit 40
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import floodvit_infer as fvi  # noqa: E402
import sar_patches as sp  # noqa: E402
import validate_floodvit as vf  # noqa: E402

# How far to look for a grid offset, in pixels. Earth Engine anchors its pixel
# grid to the CRS origin, not to the corner of the rectangle we ask for, so our
# download can land a few metres off the grid SNAP wrote their GeoTIFF on. Two
# pixels is already enough to wreck a per-pixel score against their labels.
SHIFT_SEARCH = 8


def _corr(x, y):
    """Pearson correlation over the pixels finite in both; NaN if too few."""
    m = np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 100:
        return float('nan')
    x, y = x[m], y[m]
    x = x - x.mean()
    y = y - y.mean()
    d = float(np.sqrt((x * x).sum() * (y * y).sum()))
    return float((x * y).sum() / d) if d else float('nan')


def best_shift(a, b, radius=SHIFT_SEARCH):
    """(dy, dx, r_best, r_zero) -- the offset at which b lines up with a.

    Both arrays are the POST acquisition. Ours is searched from their post date,
    so channel 0 is the same satellite pass over the same ground and the two
    should agree up to preprocessing. That makes this a clean test:

        (0, 0), r high      grids agree -- a bad score is NOT misalignment, so
                            the damage is in the chain itself
        (dy, dx) non-zero   our pixels sit off theirs by that much, and every
                            comparison against their labels scores wrong ground
        r low everywhere    not even the same acquisition -- our date or orbit
                            selection picked a different pass
    """
    H, W = a.shape
    # NaN, not -inf: a patch with no usable overlap must not come back looking
    # like a confident match at (0, 0) and inflate the aligned count.
    best = (0, 0, float('nan'))
    r_zero = float('nan')
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            i0, i1 = max(0, -dy), min(H, H - dy)
            j0, j1 = max(0, -dx), min(W, W - dx)
            if i1 - i0 < H // 2 or j1 - j0 < W // 2:
                continue
            r = _corr(a[i0:i1, j0:j1], b[i0 + dy:i1 + dy, j0 + dx:j1 + dx])
            if dy == 0 and dx == 0:
                r_zero = r
            if np.isfinite(r) and (not np.isfinite(best[2]) or r > best[2]):
                best = (dy, dx, r)
    return best[0], best[1], best[2], r_zero


def report_alignment(shifts):
    """Print what the offsets say, and return True if the grids agree."""
    from collections import Counter

    # A sample with no measurable overlap says nothing about the grid; counting
    # its placeholder (0, 0) would read as agreement.
    dropped = len(shifts) - len([s for s in shifts if np.isfinite(s[2])])
    shifts = [s for s in shifts if np.isfinite(s[2])]
    if dropped:
        print(f'\n{dropped} sample(s) had too little overlap to align')
    if not shifts:
        print('no sample could be aligned; nothing to say about the grid')
        return False

    dy = np.array([s[0] for s in shifts])
    dx = np.array([s[1] for s in shifts])
    r_best = np.array([s[2] for s in shifts])
    r_zero = np.array([s[3] for s in shifts])
    agree = int(((dy == 0) & (dx == 0)).sum())

    print(f'\ngrid alignment, post VV, ours vs theirs '
          f'(+/-{SHIFT_SEARCH}px, {len(shifts)} samples)')
    common = Counter(zip(dy.tolist(), dx.tolist())).most_common(3)
    print('  shifts: ' + ', '.join(f'(dy{d0:+d},dx{d1:+d}) x{n}'
                                   for (d0, d1), n in common))
    print(f'  aligned at (0,0): {agree}/{len(shifts)}')
    print(f'  correlation at (0,0) {np.nanmedian(r_zero):.3f}, '
          f'at best shift {np.nanmedian(r_best):.3f}')
    if max(abs(dy).max(), abs(dx).max()) >= SHIFT_SEARCH:
        print(f'  note: some samples peaked at the edge of the +/-{SHIFT_SEARCH}px '
              'window, so the real offset may be larger')

    aligned = agree >= 0.8 * len(shifts)
    if np.nanmedian(r_best) < 0.5:
        print('  -> low correlation even at the best shift: channel 0 is not the '
              'same acquisition as theirs. Date/orbit selection is the bug.')
    elif not aligned:
        print('  -> our download sits off their grid, so the scores below compare '
              'shifted ground and understate us. Fix with crsTransform.')
    else:
        print('  -> grids agree, so the gap below is real damage from the chain '
              '(Lee filter, mosaic, int16), not misalignment.')
    return aligned


def read_geo(path):
    """(crs, transform, width, height) of a GeoTIFF, without GDAL."""
    import rasterio
    with rasterio.open(path) as src:
        return str(src.crs), src.transform, src.width, src.height


def sample_footprint(sample_dir):
    """Where and when one Kuro Siwo sample was taken.

    The date is in the filename (MK0_MLU_<act>_<aoi>_<YYYYMMDD>.tif) and is the
    POST-event acquisition -- the reference the labels describe.
    """
    import ee

    mask_path = vf._find(sample_dir, 'MK0_MLU')
    crs, tr, w, h = read_geo(mask_path)
    x0, y0 = tr * (0, 0)
    x1, y1 = tr * (w, h)
    rect = ee.Geometry.Rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
                                 proj=ee.Projection(crs), geodesic=False)
    stem = os.path.basename(mask_path).rsplit('.', 1)[0]
    date = stem.split('_')[-1]
    return rect, f'{date[:4]}-{date[4:6]}-{date[6:]}', crs


def ours_for_sample(sample_dir, speckle=True):
    """Build the same patch through our Earth Engine chain.

    Their post date is the reference, so the search starts the day before it and
    the first pass found is that same acquisition.
    """
    import ee

    rect, post_date, crs = sample_footprint(sample_dir)
    start = ee.Date(post_date).advance(-1, 'day').format('YYYY-MM-dd').getInfo()
    sources, err = sp.orbit_sources(rect, start)
    if err:
        return None, err, post_date

    src = sources[0]
    images = [im.clip(rect) for im in src['images']]
    arrs = [sp._download_block(im, rect, speckle=speckle, crs=crs)
            for im in images]

    P = fvi.PATCH_PX
    H = min(a.shape[0] for a in arrs)
    W = min(a.shape[1] for a in arrs)
    if H < P or W < P:
        return None, f'downloaded {H}x{W}, need {P}x{P}', post_date

    chans, valid = [], None
    for a in arrs:
        bad = a['valid'][:P, :P] == 0
        valid = ~bad if valid is None else (valid & ~bad)
        for b in sp.SAR_POLARISATIONS:
            ch = a[b][:P, :P].astype(np.float32) / sp.SAR_SCALE_FACTOR
            ch[bad] = np.nan
            chans.append(ch)
    return np.stack(chans), valid, {'post_date': post_date,
                                    'orbit': src['orbit'],
                                    'meta': src['meta']}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data-root', required=True)
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--kuro-siwo-repo', required=True)
    p.add_argument('--device', default='cuda')
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--limit', type=int, default=40,
                   help='samples to compare; each needs its own Earth Engine '
                        'download, so keep it small')
    p.add_argument('--no-speckle-filter', action='store_true')
    args = p.parse_args()

    sat = sp._sat()
    if hasattr(sat, 'ensure_gee'):
        sat.ensure_gee()

    samples = vf.find_samples(args.data_root)[: args.limit]
    if not samples:
        sys.exit(f'no Kuro Siwo samples under {args.data_root}')
    print(f'samples: {len(samples)}')

    model = fvi.load_model(args.checkpoint, args.kuro_siwo_repo, args.device)

    theirs, ours, labels, valids, shifts = [], [], [], [], []
    skipped = {}
    for i, d in enumerate(samples, 1):
        try:
            t_patch, label, t_valid = vf.load_sample(d)
        except FileNotFoundError as e:
            skipped[str(e)] = skipped.get(str(e), 0) + 1
            continue
        try:
            o_patch, o_valid, info = ours_for_sample(
                d, speckle=not args.no_speckle_filter)
        except Exception as e:
            skipped[f'{type(e).__name__}: {e}'] = 1 + skipped.get(
                f'{type(e).__name__}: {e}', 0)
            continue
        if o_patch is None:
            skipped[str(o_valid)] = skipped.get(str(o_valid), 0) + 1
            continue
        if i <= 3:
            print(f"  {os.path.basename(d)[:8]}: post {info['post_date']} "
                  f"orbit {info['orbit']} | our dates {info['meta']}")

        # Both sides clamped the same way before correlating: ours is already
        # cut at CLAMP on download, so leaving theirs uncut would let bright
        # targets dominate the match and hide a real offset.
        shifts.append(best_shift(
            np.clip(t_patch[0, :fvi.PATCH_PX, :fvi.PATCH_PX], 0, fvi.CLAMP),
            np.clip(o_patch[0], 0, fvi.CLAMP)))

        # Both must be scored on the same pixels: theirs is the reference grid,
        # ours is resampled to the same footprint, and only pixels valid in both
        # are compared.
        both = t_valid[:fvi.PATCH_PX, :fvi.PATCH_PX] & o_valid
        theirs.append(t_patch[:, :fvi.PATCH_PX, :fvi.PATCH_PX])
        ours.append(o_patch)
        labels.append(label[:fvi.PATCH_PX, :fvi.PATCH_PX])
        valids.append(both)

    if not ours:
        print('nothing comparable:')
        for k, n in skipped.items():
            print(f'  {n}x {k}')
        sys.exit(1)
    if skipped:
        print('skipped:')
        for k, n in sorted(skipped.items(), key=lambda kv: -kv[1])[:5]:
            print(f'  {n}x {k}')

    label = np.stack(labels)
    valid = np.stack(valids)
    print(f'\ncompared on {len(ours)} samples, {int(valid.sum()):,} shared pixels')

    report_alignment(shifts)

    for name, batch in (('Kuro Siwo (SNAP)', np.stack(theirs)),
                        ('ours (Earth Engine)', np.stack(ours))):
        vv = batch[:, 0]
        print(f"\n{name}: VV median {np.nanmedian(vv):.4f} "
              f"p99 {np.nanpercentile(vv, 99):.4f} "
              f"nan {np.isnan(vv).mean() * 100:.1f}%")
        pred = fvi.predict(model, batch, device=args.device,
                           batch_size=args.batch_size)
        rows = score_rows(pred, label, valid)
        print(f"  {'class':<18}{'prec':>8}{'recall':>8}{'f1':>8}{'iou':>8}")
        for cls, r in rows.items():
            print(f"  {cls:<18}{r['precision']:>8.3f}{r['recall']:>8.3f}"
                  f"{r['f1']:>8.3f}{r['iou']:>8.3f}")


def score_rows(pred, label, valid):
    rows = vf.score(pred, label, valid)
    rows.pop('_pixels', None)
    return rows


if __name__ == '__main__':
    main()
