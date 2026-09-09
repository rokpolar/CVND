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

    theirs, ours, labels, valids = [], [], [], []
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
                  f"orbit {info['orbit']} | their dates {info['meta']}")

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
