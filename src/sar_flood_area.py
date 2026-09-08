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

# Recorded with every result so a number can be traced to how it was measured.
# It does NOT decide what re-runs -- that is --force, so re-measuring stays a
# deliberate act. A run that finds several versions in one file says so, because
# areas from different methods are not comparable, which is the failure this
# pipeline exists to remove.
#   1: first streaming version, no terrain mask
#   2: slope < SLOPE_MAX_DEG gate; steep pixels excluded from counts and from
#      observed area (v1 reported 899 km2 of flood in Sikkim, which holds only
#      199 km2 of land under 5 degrees)
#   3: terrain mask downloaded as a band and applied only when counting, not to
#      the imagery -- v2 masked the imagery, so SAR_KEEP_VALID dropped every
#      patch in mountain states and Sikkim returned 0 km2 observed
#   4: Lee 3x3 speckle filter, matching Kuro Siwo's SNAP preprocessing. Without
#      it speckle darkens random pixels and the model reads them as water
#   5: int16 transfer encoding (float64 from the Lee filter exceeded GEE's
#      48 MiB request cap and every block failed)
#   6: timesteps are DATES, mosaicking every frame of that date. A 250 km swath
#      does not cover a large state -- one frame held 7% of Bihar, and one pass
#      is stored as two scenes, so v5 picked two frames of the same pass as the
#      two pre-event timesteps. Also refuses to record an event as finished
#      unless every block in its AOI was classified.
#   7: blocks assigned per relative orbit. One orbit covers at most 66% of
#      Bihar and the orbit passing first after onset covered 15%, so v6 measured
#      a slice and reported it as the state. Acquisitions are also grouped by
#      time gap rather than calendar date (two Bihar frames land at 00:03 and
#      00:04 UTC, so a slightly earlier pass would split across midnight).
METHOD_VERSION = 7


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
        # Block counts and masks differ between versions, so resuming on top of
        # them would blend two methods inside one event. The event restarts; the
        # decision to re-measure a *finished* event is --force.
        print(f"  {event_id}: partial state from method "
              f"v{raw.get('method_version')} != v{METHOD_VERSION} -> restarting")
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
    """Every event with a result row, whatever method version produced it.

    Re-measuring is --force, not something a version bump does behind your back:
    a long run should not silently restart because a constant changed. Mixing is
    surfaced instead -- see stale_versions().
    """
    path = Path(state_dir) / RESULT_NAME
    if not path.exists():
        return set()
    return set(pd.read_csv(path)['event_id'].astype(str))


def stale_versions(state_dir):
    """Ids whose result came from a different method version. Empty is good."""
    path = Path(state_dir) / RESULT_NAME
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if 'method_version' not in df.columns:
        return {'(no version recorded)': sorted(df['event_id'].astype(str))}
    old = df[df['method_version'] != METHOD_VERSION]
    return {v: sorted(g['event_id'].astype(str))
            for v, g in old.groupby('method_version')}


def drop_result(state_dir, event_id):
    """Remove only the result row, keeping the per-block progress.

    For an event whose result is wrong but whose downloaded blocks are still
    valid -- a run that reached 96% and died before writing, say. Deleting the
    progress too would throw away an hour of classified blocks for nothing.
    """
    path = Path(state_dir) / RESULT_NAME
    if not path.exists():
        return False
    df = pd.read_csv(path)
    keep = df[df['event_id'].astype(str) != str(event_id)]
    if len(keep) == len(df):
        return False
    keep.to_csv(path, index=False)
    return True


def reset_event(state_dir, event_id):
    """Forget one event completely: progress and result row.

    Used by --force, for when the measurement itself changed. Both have to go
    together -- leaving the result row would mark the event finished again on
    the next run, and leaving the progress would resume on top of counts from
    the run being discarded. Use --redo when the blocks are still good.
    """
    progress_path(state_dir, event_id).unlink(missing_ok=True)
    drop_result(state_dir, event_id)


def reset_summary(state_dir, ids):
    """Delete the given ids (or everything) and report what went.

    Deleting by hand is easy to get half right -- removing the result row but
    leaving the progress file makes the next run resume on top of counts it was
    meant to discard, and the reverse silently marks the event finished again.
    """
    if len(ids) == 1 and ids[0] == 'all':
        path = Path(state_dir) / RESULT_NAME
        known = sorted(pd.read_csv(path)['event_id'].astype(str)) if path.exists() else []
        for p in (Path(state_dir) / PROGRESS_DIR).glob('*.json'):
            known.append(p.stem)
        ids = sorted(set(known))

    lines = []
    for ev in ids:
        had_progress = progress_path(state_dir, ev).exists()
        path = Path(state_dir) / RESULT_NAME
        had_result = (path.exists()
                      and str(ev) in set(pd.read_csv(path)['event_id'].astype(str)))
        reset_event(state_dir, ev)
        what = ', '.join(w for w, ok in
                         (('progress', had_progress), ('result', had_result)) if ok)
        lines.append(f"  {ev}: {what or 'nothing to delete'}")
    header = f"reset {len(ids)} id(s)"
    return "\n".join([header] + lines)


# ══════════════════════════════════════════════════════════════════════════════
# One event
# ══════════════════════════════════════════════════════════════════════════════

def control_id(event_id, offset_days):
    """Id for a control run, kept distinct so it never passes as the real event."""
    return f"{event_id}#ctrl{offset_days:+d}d"


def shift_date(date_str, offset_days):
    return (pd.Timestamp(date_str) + pd.Timedelta(days=offset_days)).strftime('%Y-%m-%d')


def process_event(row, model, state_dir, device, batch_size, control_offset=None,
                  speckle=True):
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
    sources, err = sp.orbit_sources(region, row['start_date'])
    if err:
        print(f"  skip: {err}")
        return {'event_id': event_id, 'state': row['state'],
                'status': f'SKIPPED: {err}', 'flood_km2': None,
                'is_control': control_offset is not None,
                'control_offset_days': control_offset,
                'method_version': METHOD_VERSION}
    for s in sources:
        m = s['meta']
        print(f"  orbit {s['orbit']:>3} {s['pass']:<10} {s['coverage_km2']:>8,.0f} km2 | "
              f"pre {m['pre_1_date']}, {m['pre_2_date']} -> post {m['post_date']}")

    for s in sources:
        s['images'] = [im.clip(region) for im in s['images']]
    state = load_progress(state_dir, event_id)
    done = set(state['done_blocks'])
    counts = dict(state['counts'])
    failed = set(state['failed_blocks'])
    n_patches = state['patches']
    valid_px = state.get('valid_px', 0)
    if done:
        print(f"  resuming: {len(done)} blocks already classified")

    started = time.time()
    total_blocks = state.get('total_blocks')
    for block_id, patches, coords, valid in sp.iter_patch_blocks(
            sources, region, done, flat=sp.terrain_mask(), speckle=speckle):
        if block_id == '__total__':
            total_blocks = patches
            state['total_blocks'] = total_blocks
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

    # An event is finished only when every block in its AOI has been classified.
    # Without this check a session killed mid-download leaves the blocks it did
    # reach marked done, the next run sees nothing left to do, and a partial area
    # is written as a final result -- which is how Sikkim was once recorded as
    # complete with 0 km2 observed.
    if not total_blocks:
        print("  no blocks in AOI -> nothing measurable, leaving open")
        return None
    if len(done) < total_blocks:
        print(f"  only {len(done)}/{total_blocks} blocks classified -> "
              f"event left open, re-run to finish")
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
        'blocks_total': total_blocks,
        'slope_max_deg': sp.SLOPE_MAX_DEG,
        'speckle_filter': 'lee3x3' if speckle else 'none',
        'method_version': METHOD_VERSION,
        'status': 'OK',
        # One AOI can need several orbits; record which, and the dates of the
        # best-covering one, so a result can be traced back to its imagery.
        'orbits': '|'.join(str(s['orbit']) for s in sources),
        'n_orbits': len(sources),
        # Blocks come from different orbits, so post-event imagery is not one
        # date. Record the span: a wide one means parts of the AOI were seen days
        # apart, which matters while water is receding.
        'post_date_first': min(s['meta']['post_date'] for s in sources),
        'post_date_last': max(s['meta']['post_date'] for s in sources),
        **sources[0]['meta'],
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
    p.add_argument('--no-speckle-filter', action='store_true',
                   help='skip the Lee filter. Kuro Siwo trained on speckle-'
                        'filtered imagery, so this is for measuring the effect '
                        'of the filter, not for production runs.')
    p.add_argument('--control-offset-days', type=int, default=None,
                   help='run the same AOI shifted by this many days instead of '
                        'the real onset, e.g. -365 for the same week a year '
                        'earlier. Gives a no-flood baseline for the same terrain '
                        'and season, which is the only way to tell whether a '
                        'flood fraction is a signal or the model over-reading '
                        'unfamiliar ground. Written under a separate event id.')
    p.add_argument('--reset', nargs='+', metavar='ID',
                   help='delete saved progress and results for these ids, then '
                        'exit without running. Ids are as they appear in the '
                        'results file, so control runs are given in full, e.g. '
                        '"E104#ctrl-365d". Pass "all" to clear everything.')
    p.add_argument('--redo', action='store_true',
                   help='drop the result row but keep downloaded progress, then '
                        'carry on from where the blocks left off. For a run that '
                        'died before writing its result. --force instead throws '
                        'the blocks away too, which is only right when the '
                        'measurement changed.')
    p.add_argument('--force', action='store_true',
                   help='recompute the selected events even if already finished, '
                        'discarding their saved progress. METHOD_VERSION handles '
                        'this automatically for method changes; use --force for '
                        'a one-off redo (a suspect result, a new checkpoint).')
    args = p.parse_args()

    if args.reset:
        print(f"state dir : {args.state_dir}")
        print(reset_summary(args.state_dir, args.reset))
        return

    events = pd.read_csv(data_path('events'))
    if args.events:
        events = events[events['event_id'].isin(args.events)]
    def run_id(ev):
        return (ev if args.control_offset_days is None
                else control_id(ev, args.control_offset_days))

    already = finished_events(args.state_dir)
    if args.force or args.redo:
        kept = 0
        for ev in events['event_id'].astype(str):
            rid = run_id(ev)
            if args.force:
                reset_event(args.state_dir, rid)
            else:
                drop_result(args.state_dir, rid)
                kept += progress_path(args.state_dir, rid).exists()
        if args.force:
            print(f"forced redo of {len(events)} event(s), progress discarded")
        else:
            print(f"redoing {len(events)} event(s), progress kept for {kept}")
    else:
        events = events[~events['event_id'].astype(str).map(run_id).isin(already)]
    if args.limit:
        events = events.head(args.limit)

    print(f"state dir : {args.state_dir}")
    print(f"finished  : {len(already)} | to process: {len(events)}")
    stale = stale_versions(args.state_dir)
    if stale:
        n = sum(len(v) for v in stale.values())
        print(f"WARN {n} result(s) measured by another method version "
              f"{ {k: len(v) for k, v in stale.items()} }; areas from different "
              f"methods are not comparable. Re-measure with --force.")
    if events.empty:
        print_results(args.state_dir)
        return

    model = fvi.load_model(args.checkpoint, args.kuro_siwo_repo, args.device)
    print(f"model     : {args.checkpoint} on {args.device}\n")

    for _, row in events.iterrows():
        try:
            result = process_event(row, model, args.state_dir,
                                   args.device, args.batch_size,
                                   control_offset=args.control_offset_days,
                                   speckle=not args.no_speckle_filter)
        except KeyboardInterrupt:
            print("\ninterrupted — progress saved, re-run to resume")
            return
        except Exception as e:
            print(f"  ERROR {row['event_id']}: {e}")
            continue
        if result is not None:
            append_result(args.state_dir, result)
    print_results(args.state_dir)


SUMMARY_COLS = ['event_id', 'state', 'start_date', 'flood_km2', 'observed_km2',
                'flood_frac_observed', 'blocks_done', 'is_control',
                'method_version', 'status']


def print_results(state_dir):
    """Show the table at the end of a run.

    Printing only the file path means a disconnected Colab session takes the
    numbers with it: the run finished, but nobody saw what it produced.
    """
    path = Path(state_dir) / RESULT_NAME
    print(f"\nresults -> {path}")
    if not path.exists():
        return
    df = pd.read_csv(path)
    cols = [c for c in SUMMARY_COLS if c in df.columns]
    print(df[cols].to_string(index=False))
    if {'is_control', 'flood_frac_observed'} <= set(df.columns):
        _print_control_comparison(df)


def _print_control_comparison(df):
    """Event flood fraction against its own no-flood baseline.

    The fraction alone says nothing: FloodViT called 46% of flat Sikkim flooded
    during an event and 35% a year earlier with no flood at all. Only the gap
    between the two is evidence that the model saw the event.
    """
    ctrl = df[df['is_control'].fillna(False).astype(bool)]
    rows = []
    for _, c in ctrl.iterrows():
        base = str(c['event_id']).split('#')[0]
        ev = df[(df['event_id'].astype(str) == base)
                & (~df['is_control'].fillna(False).astype(bool))]
        if ev.empty:
            continue
        e = ev.iloc[0]
        gap = None
        if pd.notna(e['flood_frac_observed']) and pd.notna(c['flood_frac_observed']):
            gap = round(e['flood_frac_observed'] - c['flood_frac_observed'], 4)
        rows.append({'event_id': base, 'state': e.get('state'),
                     'event_frac': e['flood_frac_observed'],
                     'control_frac': c['flood_frac_observed'], 'gap': gap})
    if rows:
        print("\nevent vs control (a high fraction means nothing without the gap):")
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == '__main__':
    main()
