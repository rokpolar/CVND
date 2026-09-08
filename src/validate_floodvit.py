"""validate_floodvit.py — check our inference against Kuro Siwo's own labelled data.

Why
---
On Bihar the model reports 6-8% of observed land as flood whether or not there
was a flood: 7.16% in March (dry season, flooding physically impossible), 7.58%
during the record September 2024 Kosi flood, 6.24% during the October 2025 event.
The output does not respond to flooding at all.

Two explanations fit that, and they lead in opposite directions:

  A. our pipeline feeds the model something subtly wrong, or
  B. the released checkpoint does not transfer to Indian terrain.

This script separates them. It runs OUR preprocessing and OUR predict() over
Kuro Siwo's own test patches, which come with expert labels. If the reported F1
(~0.80 flood, mIoU 0.76 for their best model) is roughly reproduced, our
inference path is sound and the problem is domain transfer. If it is not, the
fault is on our side and no amount of re-running India will help.

Deliberately imports floodvit_infer rather than reimplementing: testing a copy
of the code would prove nothing about the code that produces our results.

Data
----
Needs a few Kuro Siwo test patches on disk. Each sample is a directory holding
    MS1_IVV*, MS1_IVH*   post-event (their "master")
    SL1_IVV*, SL1_IVH*   pre_event_1
    SL2_IVV*, SL2_IVH*   pre_event_2
    MK0_MLU*             label: 0 no water, 1 permanent water, 2 flood
    MK0_MNA*             valid-pixel mask
Grab a handful from the GRD archive:
    https://www.dropbox.com/scl/fo/xc69aclh0q4lykd22ynkb/...

Run
---
    python src/validate_floodvit.py --data-root /content/kuro_sample \\
        --checkpoint /content/drive/MyDrive/cvnd_state/floodvit.pt \\
        --kuro-siwo-repo /content/KuroSiwo --device cuda
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import floodvit_infer as fvi  # noqa: E402

# Their label masks use 3 for invalid; the trainer passes ignore_index=3 to every
# metric, so those pixels must be excluded here too or the scores are not
# comparable to the paper's.
IGNORE_INDEX = 3

BAND_FILES = [('MS1_IVV', 'MS1_IVH'),      # post   -> channels 0,1
              ('SL1_IVV', 'SL1_IVH'),      # pre_1  -> channels 2,3
              ('SL2_IVV', 'SL2_IVH')]      # pre_2  -> channels 4,5


def _read(path):
    import cv2 as cv
    img = cv.imread(path, cv.IMREAD_ANYDEPTH)
    if img is None:
        raise FileNotFoundError(path)
    return img.astype(np.float32)


def _find(sample_dir, prefix):
    hits = [p for p in glob.glob(os.path.join(sample_dir, '*'))
            if os.path.basename(p).startswith(prefix) and not p.endswith('.xml')]
    if not hits:
        raise FileNotFoundError(f'{prefix}* not in {sample_dir}')
    return hits[0]


def load_sample(sample_dir):
    """One Kuro Siwo sample as (patch (6,H,W), label (H,W), valid (H,W))."""
    chans = [_read(_find(sample_dir, p)) for pair in BAND_FILES for p in pair]
    patch = np.stack(chans)
    label = _read(_find(sample_dir, 'MK0_MLU')).astype(np.int64)
    valid = _read(_find(sample_dir, 'MK0_MNA')) == 1
    return patch, label, valid


def find_samples(root):
    """Directories that hold a full sample. The archive nests by activation."""
    out = []
    for dirpath, _, files in os.walk(root):
        if any(f.startswith('MK0_MLU') for f in files) and \
           any(f.startswith('MS1_IVV') for f in files):
            out.append(dirpath)
    return sorted(out)


def score(pred, label, valid):
    """Per-class precision/recall/F1 and IoU over valid, non-ignored pixels."""
    keep = valid & (label != IGNORE_INDEX)
    p, t = pred[keep], label[keep]
    rows = {}
    for name, cid in (('no_water', fvi.CLASS_NO_WATER),
                      ('permanent_water', fvi.CLASS_PERMANENT_WATER),
                      ('flood', fvi.CLASS_FLOOD)):
        tp = int(((p == cid) & (t == cid)).sum())
        fp = int(((p == cid) & (t != cid)).sum())
        fn = int(((p != cid) & (t == cid)).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        rows[name] = {
            'precision': prec,
            'recall': rec,
            'f1': 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
            'iou': tp / (tp + fp + fn) if tp + fp + fn else 0.0,
            'n_true': int((t == cid).sum()),
            'n_pred': int((p == cid).sum()),
        }
    rows['_pixels'] = int(keep.sum())
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data-root', required=True,
                   help='directory holding Kuro Siwo sample folders')
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--kuro-siwo-repo', required=True)
    p.add_argument('--device', default='cuda')
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--limit', type=int, default=None)
    args = p.parse_args()

    samples = find_samples(args.data_root)
    if args.limit:
        samples = samples[: args.limit]
    if not samples:
        sys.exit(f'no Kuro Siwo samples under {args.data_root} '
                 '(looking for folders with MK0_MLU* and MS1_IVV*)')
    print(f'samples: {len(samples)}')

    model = fvi.load_model(args.checkpoint, args.kuro_siwo_repo, args.device)

    patches, labels, valids = [], [], []
    for d in samples:
        try:
            a, b, c = load_sample(d)
        except FileNotFoundError as e:
            print(f'  skip {d}: {e}')
            continue
        patches.append(a)
        labels.append(b)
        valids.append(c)
    if not patches:
        sys.exit('no complete samples loaded')

    x = np.stack(patches)
    print(f'input {x.shape}  raw VV median {np.nanmedian(x[:, 0]):.4f} '
          f'(Kuro Siwo train mean {fvi.MEAN[0]})')

    pred = fvi.predict(model, x, device=args.device, batch_size=args.batch_size)
    rows = score(pred, np.stack(labels), np.stack(valids))

    print(f"\nscored over {rows.pop('_pixels'):,} valid pixels")
    print(f"{'class':<18}{'prec':>8}{'recall':>8}{'f1':>8}{'iou':>8}"
          f"{'true px':>12}{'pred px':>12}")
    for name, r in rows.items():
        print(f"{name:<18}{r['precision']:>8.3f}{r['recall']:>8.3f}"
              f"{r['f1']:>8.3f}{r['iou']:>8.3f}{r['n_true']:>12,}{r['n_pred']:>12,}")

    f1 = rows['flood']['f1']
    print("\npaper's best (UNet-ResNet50): flood F1 0.801, mIoU 0.762")
    if f1 >= 0.6:
        print(f"flood F1 {f1:.3f} -- inference path reproduces their data, so the "
              "India result is domain transfer, not a bug in this pipeline.")
    else:
        print(f"flood F1 {f1:.3f} -- the model does not work even on the data it "
              "was trained and evaluated on, so the fault is on our side: "
              "preprocessing, channel order, or how the checkpoint is loaded.")


if __name__ == '__main__':
    main()
