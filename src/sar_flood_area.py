"""sar_flood_area.py — download SAR patches, run FloodViT, keep only the areas.

Storing the patches is not an option: 204 events over whole-state AOIs is about
2.3 million 224x224x6 float32 patches, roughly 3.9 TB. The patches themselves are
disposable -- what the study needs is one flood area per event. So each block is
downloaded, classified, counted, and discarded, and the run costs no disk.

State lives in --state-dir so a run can move between machines and accounts:
    <state-dir>/sar_progress/<event_id>.json   done blocks + running pixel counts
    <state-dir>/sar_flood_area.csv             finished events

Point --state-dir at a shared Google Drive folder and a Colab session that hits
its quota can be resumed from another account, or locally, with the same command.
Nothing else is carried between runs.

Colab:  python src/sar_flood_area.py --state-dir /content/drive/MyDrive/cvnd_state
Local:  python src/sar_flood_area.py --state-dir data/cache --device cpu

CPU works but is only sensible for a handful of events: this is ViT-Large.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import floodvit_infer as fvi  # noqa: E402
import sar_patches as sp  # noqa: E402
from cvnd_layout import data_path  # noqa: E402

RESULT_NAME = 'sar_flood_area.csv'
PROGRESS_DIR = 'sar_progress'

# Bump whenever a change makes previously computed areas incomparable, e.g. a new
# mask, a different scale, another checkpoint. Progress and results carry the
# version they were produced under, and anything older is recomputed instead of
# silently mixed with new numbers -- the exact failure this pipeline exists to
# remove. No manual deleting of state.
#   1: first streaming version, no terrain mask
#   2: slope < SLOPE_MAX_DEG gate; steep pixels excluded from counts and from
#      observed area (v1 reported 899 km2 of flood in Sikkim, which holds only
#      199 km2 of land under 5 degrees)
#   3: terrain mask downloaded as a band and applied only when counting, not to
#      the imagery -- v2 masked the imagery, so SAR_KEEP_VALID dropped every
#      patch in mountain states and Sikkim returned 0 km2 observed
METHOD_VERSION = 3


# ══════════════════════════════════════════════════════════════════════════════
# Portable state
# ══════════════════════════════════════════════════════════════════════════════

def progress_path(state_dir, event_id):
    return Path(state_dir) / PROGRESS_DIR / f'{event_id}.json'


def load_progress(state_dir, event_id):
    """Resume state for one event: which blocks are done and the counts so far."""
    p = progress_path(state_dir, event_id)
    if not p.exists():
        return _fresh_state()
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        print(f"  WARN unreadable progress for {event_id}; starting over")
        return load_progress(Path(state_dir) / '__missing__', event_id)
    if raw.get('method_version') != METHOD_VERSION:
        print(f"  {event_id}: state from method v{raw.get('method_version')} "
              f"!= v{METHOD_VERSION} -> recomputing")
        return _fresh_state()
    raw.setdefault('failed_blocks', [])
    raw.setdefault('total_blocks', None)
    return raw


def _fresh_state():
    return {'done_blocks': [], 'counts': _zero_counts(), 'patches': 0,
            'valid_px': 0, 'failed_blocks': [], 'total_blocks': None,
            'method_version': METHOD_VERSION}


def save_progress(state_dir, event_id, state):
    """Written after every block, so a killed session loses one block at most."""
    p = progress_path(state_dir, event_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(state))
    os.replace(tmp, p)


def _zero_counts():
    return {'no_water_px': 0, 'permanent_water_px': 0, 'flood_px': 0}


def append_result(state_dir, row):
    """Append one finished event, replacing any earlier row for it."""
    path = Path(state_dir) / RESULT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if path.exists():
        old = pd.read_csv(path)
        old = old[old['event_id'] != row['event_id']]
        df = pd.concat([old, df], ignore_index=True)
    df.sort_values('event_id').to_csv(path, index=False)
    return path


def finished_events(state_dir):
    """Events already done UNDER THE CURRENT METHOD. Rows from an older version
    are ignored so a method change re-runs them without anyone deleting files."""
    path = Path(state_dir) / RESULT_NAME
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    if 'method_version' not in df.columns:
        return set()
    df = df[df['method_version'] == METHOD_VERSION]
    return set(df['event_id'].astype(str))


def reset_event(state_dir, event_id):
    """Forget one event: drop its progress and its result row.

    Used by --force. Both have to go together -- leaving the result row would
    mark the event finished again on the next run, and leaving the progress file
    would resume on top of counts from the run being discarded.
    """
    progress_path(state_dir, event_id).unlink(missing_ok=True)
    path = Path(state_dir) / RESULT_NAME
    if path.exists():
        df = pd.read_csv(path)
        keep = df[df['event_id'].astype(str) != str(event_id)]
        if len(keep) != len(df):
            keep.to_csv(path, index=False)


# ══════════════════════════════════════════════════════════════════════════════
# One event
# ══════════════════════════════════════════════════════════════════════════════

def control_id(event_id, offset_days):
    """Id for a control run, kept distinct so it never passes as the real event."""
    return f"{event_id}#ctrl{offset_days:+d}d"


def shift_date(date_str, offset_days):
    return (pd.Timestamp(date_str) + pd.Timedelta(days=offset_days)).strftime('%Y-%m-%d')


def process_event(row, model, state_dir, device, batch_size, control_offset=None):
    """Stream one event's blocks through the model. Returns a result row or None.

    With control_offset set, the same AOI is measured at a shifted date. Same
    state, same tiling, same terrain gate -- only the imagery differs, so the two
    flood fractions are directly comparable.
    """
    row = row.copy()
    event_id = str(row['event_id'])
    if control_offset is not None:
        row['start_date'] = shift_date(row['start_date'], control_offset)
        event_id = control_id(event_id, control_offset)
    sat = sp._sat()
    if hasattr(sat, 'ensure_gee'):
        sat.ensure_gee()

    print(f"\n[{event_id}] {row['state']} — {row['start_date']}")
    region = sat.get_region(row)
    images, meta = sp.pick_triplet(region, row['start_date'])
    if images is None:
        print(f"  skip: {meta}")
        return {'event_id': event_id, 'state': row['state'],
                'status': f'SKIPPED: {meta}', 'flood_km2': None,
                'is_control': control_offset is not None,
                'control_offset_days': control_offset,
                'method_version': METHOD_VERSION}
    print(f"  orbit {meta['relative_orbit']} {meta['orbit_pass']} | "
          f"pre {meta['pre_1_date']}, {meta['pre_2_date']} -> "
          f"post {meta['post_date']}")

    images = [im.clip(region) for im in images]
    state = load_progress(state_dir, event_id)
    done = set(state['done_blocks'])
    counts = dict(state['counts'])
    failed = set(state['failed_blocks'])
    n_patches = state['patches']
    valid_px = state.get('valid_px', 0)
    if done:
        print(f"  resuming: {len(done)} blocks already classified")

    started = time.time()
    for block_id, patches, coords, valid in sp.iter_patch_blocks(
            images, region, done, flat=sp.terrain_mask()):
        if block_id == '__total__':
            state['total_blocks'] = patches
            continue
        if patches is None:                      # download failed; retry next run
            failed.add(block_id)
            continue
        if len(patches):
            pred = fvi.predict(model, patches, device=device, batch_size=batch_size)
            # Masked pixels (steep ground, missing data) still get a class, so
            # force them to "no water" before counting. Otherwise the terrain gate
            # would only shrink the patch set, not the false positives inside it.
            pred[~valid] = fvi.CLASS_NO_WATER
            for k, v in fvi.count_classes(pred).items():
                counts[k] += v
            n_patches += len(patches)
            valid_px += int(valid.sum())
        done.add(block_id)
        failed.discard(block_id)
        state.update({'done_blocks': sorted(done), 'counts': counts,
                      'patches': n_patches, 'valid_px': valid_px,
                      'failed_blocks': sorted(failed)})
        save_progress(state_dir, event_id, state)

    if failed:
        print(f"  {len(failed)} blocks failed -> event left open, re-run to finish")
        return None

    elapsed = time.time() - started
    flood_km2 = fvi.px_to_km2(counts['flood_px'], sp.SAR_SCALE_M)
    perm_km2 = fvi.px_to_km2(counts['permanent_water_px'], sp.SAR_SCALE_M)
    # Area actually classified = valid pixels, not whole patches. A patch kept at
    # 70% validity contributes only its valid part, so the flood fraction below is
    # over ground that was really observed.
    observed_km2 = fvi.px_to_km2(valid_px, sp.SAR_SCALE_M)
    print(f"  flood {flood_km2:.2f} km2 | permanent {perm_km2:.2f} km2 | "
          f"observed {observed_km2:.0f} km2 | {elapsed / 60:.1f} min")

    return {
        'event_id': event_id,
        'state': row['state'],
        'start_date': row['start_date'],
        'is_control': control_offset is not None,
        'control_offset_days': control_offset,
        'flood_km2': round(flood_km2, 3),
        'permanent_water_km2': round(perm_km2, 3),
        # area actually classified: patches dropped for missing data are not in it,
        # so flood_km2 is a count over observed_km2, not over the whole AOI
        'observed_km2': round(observed_km2, 1),
        'flood_frac_observed': (round(flood_km2 / observed_km2, 5)
                                if observed_km2 else None),
        'n_patches': n_patches,
        'flood_px': counts['flood_px'],
        'blocks_done': len(done),
        'slope_max_deg': sp.SLOPE_MAX_DEG,
        'method_version': METHOD_VERSION,
        'status': 'OK',
        **meta,
    }


# ══════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--state-dir', default=str(data_path('flood_extent').parent),
                   help='where progress and results live; point at shared Drive '
                        'in Colab so another account can resume')
    p.add_argument('--checkpoint', default='C:/KuroSiwo/checkpoints/floodvit.pt')
    p.add_argument('--kuro-siwo-repo', default='C:/KuroSiwo',
                   help='needed on sys.path: the checkpoint pickles its classes')
    p.add_argument('--device', default='cuda')
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--events', nargs='*', default=None)
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--control-offset-days', type=int, default=None,
                   help='run the same AOI shifted by this many days instead of '
                        'the real onset, e.g. -365 for the same week a year '
                        'earlier. Gives a no-flood baseline for the same terrain '
                        'and season, which is the only way to tell whether a '
                        'flood fraction is a signal or the model over-reading '
                        'unfamiliar ground. Written under a separate event id.')
    p.add_argument('--force', action='store_true',
                   help='recompute the selected events even if already finished, '
                        'discarding their saved progress. METHOD_VERSION handles '
                        'this automatically for method changes; use --force for '
                        'a one-off redo (a suspect result, a new checkpoint).')
    args = p.parse_args()

    events = pd.read_csv(data_path('events'))
    if args.events:
        events = events[events['event_id'].isin(args.events)]
    def run_id(ev):
        return (ev if args.control_offset_days is None
                else control_id(ev, args.control_offset_days))

    already = finished_events(args.state_dir)
    if args.force:
        for ev in events['event_id'].astype(str):
            reset_event(args.state_dir, run_id(ev))
        print(f"forced redo of {len(events)} event(s)")
    else:
        events = events[~events['event_id'].astype(str).map(run_id).isin(already)]
    if args.limit:
        events = events.head(args.limit)

    print(f"state dir : {args.state_dir}")
    print(f"finished  : {len(already)} | to process: {len(events)}")
    if events.empty:
        return

    model = fvi.load_model(args.checkpoint, args.kuro_siwo_repo, args.device)
    print(f"model     : {args.checkpoint} on {args.device}\n")

    for _, row in events.iterrows():
        try:
            result = process_event(row, model, args.state_dir,
                                   args.device, args.batch_size,
                                   control_offset=args.control_offset_days)
        except KeyboardInterrupt:
            print("\ninterrupted — progress saved, re-run to resume")
            return
        except Exception as e:
            print(f"  ERROR {row['event_id']}: {e}")
            continue
        if result is not None:
            out = append_result(args.state_dir, result)
    print(f"\nresults -> {Path(args.state_dir) / RESULT_NAME}")


if __name__ == '__main__':
    main()
