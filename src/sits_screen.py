"""Track B screen: will a Track B download give this district a usable SITS value?

Track B already checks, before downloading anything, that a district has post
and pre imagery (B1, B2) and a clear baseline (B3). What it could only learn
after downloading is whether the retained tiles leave enough usable pixels:
merge_results uses SITS only when usable pixels cover at least
``SPEC.sits_usable_min_frac`` of the eligible AOI, otherwise the district is
measured by Track A anyway and the download was spent for nothing.

The screen runs B1-B3 exactly as Track B does, then evaluates the retained-tile
rule and the usable-pixel area server-side on the district grid, and records
one row per district in ``data/cache/district/sits_screen.csv``. Nothing is
downloaded and no Track B artifact is touched.

This module holds the pure part (tile rule, aggregation, decision, table IO);
``satellite.screen_sits_patch`` does the Earth Engine part.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cvnd_layout import data_path  # noqa: E402
from district_keys import analysis_key  # noqa: E402
from flood_spec import SPEC, TEXT_DTYPES, stale_spec_mask  # noqa: E402

SCREEN_VERSION = 'screen-1'
SCREEN_CSV = str(data_path('district_sits_screen'))

IDENTITY_COLUMNS = ('event_district_id', 'event_id', 'source_record_id', 'state',
                    'district', 'start_date', 'geometry_id')
SCREEN_COLUMNS = IDENTITY_COLUMNS + (
    # sits_expected: Track B would yield a SITS value the merge uses.
    # track_a_expected: it would not (screen_reason says why).
    # error: the screen could not be evaluated; retried on the next run.
    'screen_result', 'screen_reason',
    'post_images', 'pre_images', 'baseline_months',
    'blocks', 'kept_tiles', 'usable_km2', 'eligible_km2', 'usable_frac', 'usable_min_frac',
    'tile_selection_rule', 'grid_crs', 'spec_version', 'screen_version',
)
SCREEN_RESULTS = ('sits_expected', 'track_a_expected', 'error')
SCREEN_REASONS = ('ok', 'no_post_imagery', 'no_pre_imagery', 'no_clear_baseline',
                  'no_retained_tiles', 'no_usable_pixels', 'usable_below_min')
SCREEN_DTYPES = {**TEXT_DTYPES, **{c: str for c in (
    'screen_result', 'screen_reason', 'baseline_months', 'tile_selection_rule',
    'grid_crs', 'screen_version')}}


# ── the tile rule and the district decision ───────────────────────────────────

def retained_tile_ids(grouped_by_time: dict, n_timesteps: int, keep_valid: float) -> set:
    """Tiles whose valid fraction reaches ``keep_valid`` in every timestep.

    ``grouped_by_time[str(i)]['groups']`` is a grouped mean reduction for
    timestep i: [{'tile': id, 'mean': fraction}, ...]. This is the rule
    ``satellite._tiles_from_block`` applies to downloaded blocks.
    """
    qualifying = None
    for i in range(n_timesteps):
        groups = (grouped_by_time.get(str(i)) or {}).get('groups') or []
        timestep = {int(item['tile']) for item in groups
                    if float(item.get('mean', 0.0)) >= keep_valid}
        qualifying = timestep if qualifying is None else qualifying & timestep
        if not qualifying:
            return set()
    return qualifying or set()


def summarize_blocks(block_stats, n_timesteps: int, keep_valid: float) -> dict:
    """District totals from per-block screen reductions.

    Each item holds the per-timestep grouped valid means ('0'..'n-1'), the
    grouped usable-pixel area per tile ('usable', m²) and the eligible area of
    the block ('eligible', m²). Blocks are whole tiles on one grid, so each
    tile id appears in exactly one block.
    """
    kept, usable_m2, eligible_m2 = 0, 0.0, 0.0
    for stats in block_stats:
        tiles = retained_tile_ids(stats, n_timesteps, keep_valid)
        usable_by_tile = {int(g['tile']): float(g.get('sum') or 0.0)
                          for g in ((stats.get('usable') or {}).get('groups') or [])}
        kept += len(tiles)
        usable_m2 += sum(usable_by_tile.get(tile, 0.0) for tile in tiles)
        eligible_m2 += float((stats.get('eligible') or {}).get('eligible') or 0.0)
    return {'kept_tiles': kept, 'usable_km2': usable_m2 / 1e6, 'eligible_km2': eligible_m2 / 1e6}


def screen_decision(post_images, pre_images, baseline_found, kept_tiles=None,
                    usable_km2=None, eligible_km2=None, spec=SPEC):
    """(screen_result, screen_reason, usable_frac) in Track B / merge order.

    B1-B3 are Track B's own pre-download checks. The last two mirror what the
    merge does with a measured district: no usable pixel -> unavailable, and a
    usable share below sits_usable_min_frac -> Track A. Without an eligible
    area the merge cannot apply the share rule and keeps SITS; so does this.
    """
    if not post_images:
        return 'track_a_expected', 'no_post_imagery', None
    if not pre_images:
        return 'track_a_expected', 'no_pre_imagery', None
    if not baseline_found:
        return 'track_a_expected', 'no_clear_baseline', None
    if not kept_tiles:
        return 'track_a_expected', 'no_retained_tiles', None
    if not usable_km2:
        return 'track_a_expected', 'no_usable_pixels', 0.0 if eligible_km2 else None
    frac = usable_km2 / eligible_km2 if eligible_km2 else None
    if frac is not None and frac < spec.sits_usable_min_frac:
        return 'track_a_expected', 'usable_below_min', frac
    return 'sits_expected', 'ok', frac


# ── table IO (row upsert, like sits_measure) ──────────────────────────────────

def _read(path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=SCREEN_DTYPES, float_precision='round_trip')
    return frame.reindex(columns=list(SCREEN_COLUMNS))


def upsert_screen(rows, path=None) -> pd.DataFrame:
    """Replace the given districts' rows; keep every other row verbatim."""
    path = Path(path or SCREEN_CSV)
    incoming = pd.DataFrame(list(rows), columns=list(SCREEN_COLUMNS))
    if path.exists():
        existing = _read(path)
        if len(existing) and len(incoming):
            replaced = set(incoming.apply(analysis_key, axis=1))
            existing = existing.loc[~existing.apply(analysis_key, axis=1).isin(replaced)]
        frame = pd.concat([existing, incoming], ignore_index=True)
    else:
        frame = incoming
    for column in ('post_images', 'pre_images', 'blocks', 'kept_tiles'):
        frame[column] = pd.to_numeric(frame[column], errors='coerce').round().astype('Int64')
    if len(frame):
        frame = frame.sort_values(['event_district_id', 'event_id'], na_position='last')
    frame = frame.reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)
    return frame


def load_screen(path=None) -> dict:
    """Screen rows under the current spec and screen version, by analysis key."""
    path = str(path or SCREEN_CSV)
    if not os.path.exists(path):
        return {}
    frame = _read(path)
    current = ~stale_spec_mask(frame) & frame['screen_version'].astype('string').eq(SCREEN_VERSION).fillna(False)
    return {analysis_key(row): row for _, row in frame.loc[current].iterrows()}


def summary(rows) -> pd.DataFrame:
    """Counts by result and reason, with the year split the plan is judged on."""
    frame = pd.DataFrame(list(rows.values()) if isinstance(rows, dict) else rows)
    if frame.empty:
        return frame
    year = pd.to_datetime(frame['start_date'], errors='coerce').dt.year
    frame = frame.assign(years=year.le(2018).map({True: '<=2018', False: '>=2019'}))
    return pd.crosstab([frame['screen_result'], frame['screen_reason']], frame['years'], margins=True)
