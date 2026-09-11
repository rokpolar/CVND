"""Phase -1 SITS feasibility gate: Earth Engine queries only, nothing downloaded.

For every registry event-district, and for two Sentinel-2 inputs -- the spec's
SR collection (``sr``) and the L1C archive masked with s2cloudless (``l1c``) --
this estimates under the current Track B rules:

  * image counts in the pre/post windows and the baseline months (and S1),
  * whether Track B would produce tiles: post and pre imagery, a clear
    baseline (satellite.choose_baseline on the same monthly scores) and at
    least one retained tile (every timestep >= sits_keep_valid clear),
  * the retained-tile footprint, its usable area (eligible, clear in every
    timestep, NDWI observed pre and post) and NDWI new water on it -- the
    footprint C of the Track A / Track B paired comparison,
  * download cost on a UTM 640 m tile grid (blocks, hours, H5 bytes).

Tile-scale quantities are computed at --fine-scale m (default 40, within EE
memory limits) and averaged to 640 m tiles, so they approximate Track B rather
than reproduce it. Darbhanga check against its real H5: 1,876 vs 1,930 tiles,
usable 401 vs 407.5 km², new water 81 vs 91.5 km². Rows without a resolvable
district are reported as AOI failures, never as SITS-unavailable.

Output: data/results/sits_feasibility.csv, sits_feasibility_summary.json
Run:    python src/sits_feasibility.py [--workers 8] [--events KEY ...]
        python src/sits_feasibility.py --summarize-only
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import satellite as sat  # noqa: E402
from cvnd_layout import data_path  # noqa: E402
from district_keys import analysis_key  # noqa: E402
from flood_spec import (CONVERTER_RULES, SPEC, SPEC_VERSION,  # noqa: E402
                        TEXT_DTYPES)

ee = sat.ee

PROBE_VERSION = 'feas-1'   # bump when the probe logic changes; resume ignores other versions
SOURCES = ('sr', 'l1c')
L1C_COLLECTION = 'COPERNICUS/S2_HARMONIZED'
CLOUD_PROB_COLLECTION = 'COPERNICUS/S2_CLOUD_PROBABILITY'
CLOUD_PROB_MAX = 40
TILE_M = SPEC.sits_patch_px * SPEC.sits_pixel_m
TILE_KM2 = TILE_M * TILE_M / 1e6
BLOCK_TILES = sat.SITS_BLOCK_PATCHES
BLOCK_SECONDS = 14            # observed Track B download time per block
GATE_MAX_UNAVAILABLE = 0.30
SR_GAP_LAST_YEAR = 2018       # S2 SR is sparse over India before late 2018
YEAR_CAUSE_SHARE = 0.5        # share of SR-unavailable rows in SR-gap years that makes the year the cause
MISSING_DISTRICTS = {'', 'nan', 'none', 'missing', 'district_missing'}

_P = SPEC.sits_patch_px
_NB = len(sat.SITS_BANDS)
# Bytes per retained tile, uncompressed.
H5_BYTES_PER_TILE = {
    # float32 pre/post, uint8 mask, int16 ndwi_ref, float64 coords, float32 area
    'current': 4 * (SPEC.sits_n_pre + 1) * _NB * _P * _P + _P * _P + 2 * 2 * _P * _P + 32 + 4,
    # uint16 pre/post, + int16 S1 pre/post, uint8 landcover, int32 block_id
    'planned': 2 * (SPEC.sits_n_pre + 1) * _NB * _P * _P + _P * _P + 2 * 2 * _P * _P
               + 2 * 2 * _P * _P + _P * _P + 32 + 4 + 4,
}

CSV_COLUMNS = [
    'event_district_id', 'event_id', 'state', 'district', 'start_date', 'year',
    'aoi_status', 'aoi_error', 'aoi_area_km2', 'eligible_km2', 'utm_epsg',
    'grid_tiles', 'grid_blocks', 's1_pre_images', 's1_post_images',
] + [f'{s}_{field}' for s in SOURCES for field in (
    'pre_images', 'post_images', 'baseline_candidates', 'baseline_months',
    'post_seen_frac', 'pre_seen_frac', 'optical_observed_frac', 'status', 'reason',
    'kept_tiles', 'kept_km2', 'usable_km2', 'usable_frac', 'new_water_c_km2',
    'fine_scale_m', 'error')] + ['probe_version', 'spec_version', 'elapsed_s']


# ══════════════════════════════════════════════════════════════════════════════
# Pure helpers (tested offline)
# ══════════════════════════════════════════════════════════════════════════════

def month_tag(year, month) -> str:
    return f'{year:04d}{month:02d}'


def grid_cost(minx, miny, maxx, maxy) -> dict:
    """Tile/block counts of the AOI bounding box on a 640 m metric grid."""
    clat = math.radians((miny + maxy) / 2)
    width_m = (maxx - minx) * 111320.0 * math.cos(clat)
    height_m = (maxy - miny) * 110540.0
    npx, npy = math.ceil(width_m / TILE_M), math.ceil(height_m / TILE_M)
    return {'grid_tiles': npx * npy,
            'grid_blocks': math.ceil(npx / BLOCK_TILES) * math.ceil(npy / BLOCK_TILES)}


def baseline_candidates(stats: dict, counts: dict, months_a, months_b):
    """Monthly scores from the stage-1 reduction as choose_baseline candidates."""
    def cands(months):
        out = []
        for year, month in months:
            tag = month_tag(year, month)
            clear = stats.get(f'clear_{tag}')
            if not counts.get(f'n_{tag}') or clear is None:
                continue   # no composite, as in satellite._monthly_composite_sits
            out.append((f'{year:04d}-{month:02d}', None, float(clear),
                        float(stats.get(f'water_{tag}') or 0.0)))
        return out
    return cands(months_a), cands(months_b)


def classify(n_pre, n_post, baseline, kept_tiles) -> tuple[str, str]:
    """Predicted sits_status and its reason, in pipeline order."""
    if not n_post:
        return 'unavailable', 'no_post_imagery'
    if not n_pre:
        return 'unavailable', 'no_pre_imagery'
    if baseline is None:
        return 'unavailable', 'no_clear_baseline'
    if kept_tiles is None:
        return 'error', 'tile_probe_failed'
    if kept_tiles < 0.5:
        return 'unavailable', 'no_retained_tiles'
    return 'ok', 'ok'


def _rate(num, den):
    return None if not den else round(num / den, 4)


def summarize(frame: pd.DataFrame, rules=CONVERTER_RULES) -> dict:
    """Per-source unavailability, paired-sample size and cost; plus the gate."""
    frame = frame.copy()
    matched = frame[frame['aoi_status'] == 'matched']
    summary = {
        'probe_version': PROBE_VERSION, 'spec_version': SPEC_VERSION,
        'rows': int(len(frame)),
        'aoi_status': {str(k): int(v) for k, v in frame['aoi_status'].value_counts().items()},
        'aoi_matched': int(len(matched)),
        'sources': {},
    }
    for source in SOURCES:
        status = matched[f'{source}_status']
        probed = matched[status.isin(['ok', 'unavailable'])]
        unavailable = probed[f'{source}_status'] == 'unavailable'
        new_water = pd.to_numeric(probed[f'{source}_new_water_c_km2'], errors='coerce')
        paired = probed[(probed[f'{source}_status'] == 'ok') & (new_water >= rules.min_area_km2)]
        ok = probed[probed[f'{source}_status'] == 'ok']
        kept = pd.to_numeric(ok[f'{source}_kept_tiles'], errors='coerce').fillna(0)
        blocks = pd.to_numeric(ok['grid_blocks'], errors='coerce').fillna(0)
        by_year = {}
        for year, s in probed.groupby('year')[f'{source}_status']:
            n_unavail = int((s == 'unavailable').sum())
            by_year[str(int(year))] = {'n': int(len(s)), 'unavailable': n_unavail,
                                       'rate': _rate(n_unavail, len(s))}
        by_state = {str(state): _rate(int((s == 'unavailable').sum()), len(s))
                    for state, s in probed.groupby('state')[f'{source}_status']}
        usable_frac = pd.to_numeric(ok[f'{source}_usable_frac'], errors='coerce')
        summary['sources'][source] = {
            'probed': int(len(probed)),
            'probe_errors': int((status == 'error').sum()),
            'unavailable': int(unavailable.sum()),
            'unavailable_rate': _rate(int(unavailable.sum()), len(probed)),
            'reasons': {str(k): int(v) for k, v in
                        probed.loc[unavailable, f'{source}_reason'].value_counts().items()},
            'by_year': by_year,
            'by_state_unavailable_rate': by_state,
            'usable_frac_quantiles': (None if usable_frac.dropna().empty else
                                      {str(q): round(float(usable_frac.quantile(q)), 4)
                                       for q in (0.1, 0.25, 0.5, 0.75, 0.9)}),
            'paired_sample': {'districts': int(len(paired)),
                              'states': int(paired['state'].nunique()),
                              'min_area_km2': rules.min_area_km2},
            'cost_ok_rows': {
                'blocks': int(blocks.sum()),
                'hours_at_block_seconds': round(float(blocks.sum()) * BLOCK_SECONDS / 3600, 1),
                'kept_tiles': int(kept.sum()),
                'h5_gb_current_layout': round(float(kept.sum()) * H5_BYTES_PER_TILE['current'] / 1e9, 1),
                'h5_gb_planned_layout_uncompressed':
                    round(float(kept.sum()) * H5_BYTES_PER_TILE['planned'] / 1e9, 1),
            },
        }
    both = matched[matched['sr_status'].isin(['ok', 'unavailable'])
                   & matched['l1c_status'].isin(['ok', 'unavailable'])]
    sr_unavail = both['sr_status'] == 'unavailable'
    rescued = sr_unavail & (both['l1c_status'] == 'ok')
    in_gap = sr_unavail & (pd.to_numeric(both['year'], errors='coerce') <= SR_GAP_LAST_YEAR)
    summary['sr_unavailable_rescued_by_l1c'] = {
        'sr_unavailable': int(sr_unavail.sum()), 'rescued': int(rescued.sum()),
        'share': _rate(int(rescued.sum()), int(sr_unavail.sum())),
    }
    summary['sr_unavailable_in_sr_gap_years'] = {
        'last_gap_year': SR_GAP_LAST_YEAR, 'rows': int(in_gap.sum()),
        'share': _rate(int(in_gap.sum()), int(sr_unavail.sum())),
    }
    summary['gate'] = gate_verdict(summary, rules)
    return summary


def gate_verdict(summary: dict, rules=CONVERTER_RULES) -> dict:
    """The plan's Phase -1 decision table; the user confirms before Phase 0.

    <= 30% SR-unavailable: proceed. Above that, if the SR-gap years explain
    most of it the year is the cause -> consider unifying on L1C (whose own
    residual rate is reported: Sentinel-2 itself is sparse before 2017, which
    no input choice fixes). Otherwise the cause is not the archive -> the
    user decides.
    """
    sr = summary['sources']['sr']
    rate = sr['unavailable_rate']
    year_share = summary['sr_unavailable_in_sr_gap_years']['share']
    if rate is None:
        verdict, source = 'no_data', 'sr'
    elif rate <= GATE_MAX_UNAVAILABLE:
        verdict, source = 'proceed', 'sr'
    elif year_share is not None and year_share >= YEAR_CAUSE_SHARE:
        verdict, source = 'consider_l1c', 'l1c'
    else:
        verdict, source = 'unavailable_not_year', 'sr'
    paired = summary['sources'][source]['paired_sample']
    sufficient = (paired['districts'] >= rules.min_districts
                  and paired['states'] >= rules.min_states)
    l1c_rate = summary['sources']['l1c']['unavailable_rate']
    return {
        'verdict': verdict,
        'basis_source': source,
        'sr_unavailable_rate': rate,
        'max_unavailable_rate': GATE_MAX_UNAVAILABLE,
        'sr_unavailable_share_in_gap_years': year_share,
        'l1c_unavailable_rate': l1c_rate,
        'l1c_still_above_max': bool(l1c_rate is not None and l1c_rate > GATE_MAX_UNAVAILABLE),
        'l1c_rescue_share': summary['sr_unavailable_rescued_by_l1c']['share'],
        'converter_sample': 'expected_sufficient' if sufficient else 'expected_insufficient',
        'paired_districts': paired['districts'],
        'paired_states': paired['states'],
        'min_districts': rules.min_districts,
        'min_states': rules.min_states,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Earth Engine probe
# ══════════════════════════════════════════════════════════════════════════════

def l1c_collection(region, spec=SPEC):
    """L1C (TOA) scenes with s2cloudless probability < CLOUD_PROB_MAX kept."""
    prob = ee.ImageCollection(CLOUD_PROB_COLLECTION).filterBounds(region)
    scenes = (ee.ImageCollection(L1C_COLLECTION).filterBounds(region)
              .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', spec.s2_cloudy_pixel_pct_max)))
    return scenes.linkCollection(prob, ['probability']).map(
        lambda img: img.select(sat.SITS_BANDS)
        .updateMask(img.select('probability').lt(CLOUD_PROB_MAX)))


def source_collection(region, source, spec=SPEC):
    if source == 'sr':
        return sat.s2_collection(region, spec).select(sat.SITS_BANDS)
    return l1c_collection(region, spec)


def _median_or_empty(col):
    empty = (ee.Image.constant([0] * len(sat.SITS_BANDS)).rename(sat.SITS_BANDS)
             .updateMask(ee.Image.constant(0)))
    return ee.Image(ee.Algorithms.If(col.size().gt(0), col.median(), empty))


def _seen(col, spec):
    """1 where the AOI was seen clear at least once in the collection."""
    bands = list(spec.ndwi_bands)
    seen = col.map(lambda img: img.select(bands).mask().reduce(ee.Reducer.min()))
    return ee.Image(ee.Algorithms.If(col.size().gt(0), seen.max(), ee.Image.constant(0))).unmask(0)


def _meta(region, start, spec):
    s1 = sat.s1_collection(region, spec)
    return ee.Dictionary({
        's1_pre': s1.filterDate(*sat.pre_window(start, spec)).size(),
        's1_post': s1.filterDate(*sat.post_window(start, spec)).size(),
        'bounds': region.bounds(1).coordinates(),
        'centroid': region.centroid(1).coordinates(),
    })


def _stage1(region, source, start, event_dt, months, spec, tile_scale):
    """Image counts and AOI-level fractions (monthly clear/water, pre/post
    seen, optical observed, eligible) for one source."""
    eligible = sat.measurement_mask(spec).unmask(0)
    col = source_collection(region, source, spec)
    bands, counts = [], {}
    for year, month in months:
        tag = month_tag(year, month)
        sub = col.filterDate(*sat.month_window(year, month, event_dt))
        comp = _median_or_empty(sub)
        bands.append(comp.mask().reduce(ee.Reducer.min()).rename(f'clear_{tag}'))
        bands.append(comp.normalizedDifference(list(spec.ndwi_bands))
                     .gt(spec.ndwi_water_gt).rename(f'water_{tag}'))
        counts[f'n_{tag}'] = sub.size()
    pre = col.filterDate(*sat.pre_window(start, spec))
    post = col.filterDate(*sat.post_window(start, spec))
    counts['n_pre'], counts['n_post'] = pre.size(), post.size()
    pre_seen, post_seen = _seen(pre, spec), _seen(post, spec)
    bands += [pre_seen.rename('pre_seen'), post_seen.rename('post_seen'),
              pre_seen.And(post_seen).And(eligible).rename('optical_observed'),
              eligible.rename('eligible')]
    stats = ee.Image.cat(bands).reduceRegion(
        reducer=ee.Reducer.mean(), geometry=region, scale=spec.qa_scale_m,
        maxPixels=spec.max_pixels, tileScale=tile_scale, bestEffort=False)
    return ee.Dictionary({'stats': stats, 'counts': ee.Dictionary(counts)})


def _stage2(region, col, start, event_dt, chosen, spec, crs, fine, tile_scale):
    """Retained-tile footprint, usable area and new water on it (km²)."""
    def tile_mean(img):
        return (img.reproject(crs=crs, scale=fine)
                .reduceResolution(ee.Reducer.mean(), maxPixels=(TILE_M // fine) ** 2)
                .reproject(crs=crs, scale=TILE_M))

    months = [tuple(int(x) for x in c[0].split('-')) for c in chosen]
    pre_col = col.filterDate(*sat.pre_window(start, spec))
    post_col = col.filterDate(*sat.post_window(start, spec))
    comps = [col.filterDate(*sat.month_window(y, m, event_dt)).median() for y, m in months]
    comps.append(post_col.median())
    valid = [c.clip(region).mask().reduce(ee.Reducer.min()).unmask(0) for c in comps]
    kept = tile_mean(valid[0]).gte(spec.sits_keep_valid)
    valid_all = valid[0]
    for v in valid[1:]:
        kept = kept.And(tile_mean(v).gte(spec.sits_keep_valid))
        valid_all = valid_all.And(v)
    pre_ndwi, post_ndwi = sat.ndwi_composites(pre_col, post_col, spec)
    observed = pre_ndwi.mask().And(post_ndwi.mask()).unmask(0)
    usable = valid_all.And(sat.measurement_mask(spec).unmask(0)).And(observed)
    cut = spec.ndwi_water_gt
    new_water = post_ndwi.gt(cut).And(pre_ndwi.lte(cut)).unmask(0).And(usable)
    stack = ee.Image.cat([kept.rename('kept'),
                          kept.multiply(tile_mean(usable)).rename('usable'),
                          kept.multiply(tile_mean(new_water)).rename('new_water')])
    stats = stack.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region, crs=crs, scale=TILE_M,
        maxPixels=spec.max_pixels, tileScale=tile_scale, bestEffort=False).getInfo() or {}
    return {k: (None if stats.get(k) is None else float(stats[k]) / 1e6)
            for k in ('kept', 'usable', 'new_water')}


def _escalating(fn, settings):
    """Run fn(*setting) through progressively lighter settings on EE memory /
    timeout errors; return (result, setting used)."""
    for i, setting in enumerate(settings):
        try:
            return _retrying(lambda: fn(*setting)), setting
        except Exception as exc:
            text = str(exc).lower()
            if i == len(settings) - 1 or not ('memory' in text or 'timed out' in text):
                raise


def _retrying(fn, attempts=3):
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:   # EE transport errors and 429s are transient
            text = str(exc).lower()
            transient = any(t in text for t in ('429', 'too many', 'quota', 'deadline',
                                                'unavailable', 'connection', 'reset'))
            if attempt == attempts - 1 or not transient:
                raise
            time.sleep(5 * 2 ** attempt)


def probe_district(row, spec=SPEC, fine_scale=40) -> dict:
    t0 = time.time()
    start = str(row['start_date'])
    event_dt = datetime.strptime(start, '%Y-%m-%d')
    rec = {'event_district_id': row.get('event_district_id'), 'event_id': row.get('event_id'),
           'state': row.get('state'), 'district': row.get('district'), 'start_date': start,
           'year': event_dt.year, 'probe_version': PROBE_VERSION, 'spec_version': SPEC_VERSION}
    if str(row.get('district', '')).strip().lower() in MISSING_DISTRICTS:
        return {**rec, 'aoi_status': 'unresolved', 'elapsed_s': 0.0}
    try:
        aoi = _retrying(lambda: sat.resolve_aoi(row, spec))
    except Exception as exc:
        return {**rec, 'aoi_status': 'failed', 'aoi_error': str(exc)[:300],
                'elapsed_s': round(time.time() - t0, 1)}
    region = aoi['geometry']
    rec.update(aoi_status='matched', aoi_area_km2=round(aoi['aoi_area_km2'], 3))

    months_a, months_b = sat.baseline_pool_months(event_dt, spec.sits_baseline_years)
    months = list(dict.fromkeys(months_a + months_b))
    meta = _retrying(lambda: _meta(region, start, spec).getInfo())
    (minx, miny), (maxx, maxy) = meta['bounds'][0][0], meta['bounds'][0][2]
    lon, lat = meta['centroid']
    crs = f'EPSG:{sat.utm_epsg(lon, lat)}'
    rec.update(grid_cost(minx, miny, maxx, maxy), utm_epsg=crs,
               s1_pre_images=meta['s1_pre'], s1_post_images=meta['s1_post'])

    for source in SOURCES:
        try:
            info, _ = _escalating(
                lambda ts: _stage1(region, source, start, event_dt, months, spec, ts).getInfo(),
                [(spec.tile_scale,), (16,)])
        except Exception as exc:
            rec.update({f'{source}_status': 'error', f'{source}_reason': 'aoi_probe_failed',
                        f'{source}_error': str(exc)[:300]})
            continue
        stats, counts = info['stats'] or {}, info['counts']
        eligible_frac = stats.get('eligible')
        if source == SOURCES[0] and eligible_frac is not None:
            rec['eligible_km2'] = round(float(eligible_frac) * aoi['aoi_area_km2'], 3)
        pool_a, pool_b = baseline_candidates(stats, counts, months_a, months_b)
        chosen = sat.choose_baseline(pool_a, pool_b, spec.sits_n_pre,
                                     spec.sits_baseline_min_clear)
        n_pre, n_post = int(counts['n_pre']), int(counts['n_post'])
        qualifying = sum(c[2] >= spec.sits_baseline_min_clear for c in pool_a + pool_b)
        rec.update({
            f'{source}_pre_images': n_pre, f'{source}_post_images': n_post,
            f'{source}_baseline_candidates': qualifying,
            f'{source}_baseline_months': None if chosen is None else '|'.join(c[0] for c in chosen),
            f'{source}_post_seen_frac': stats.get('post_seen'),
            f'{source}_pre_seen_frac': stats.get('pre_seen'),
            f'{source}_optical_observed_frac': stats.get('optical_observed'),
        })
        tiles = None
        if n_pre and n_post and chosen is not None:
            col = source_collection(region, source, spec)
            settings = [(fine_scale, spec.tile_scale), (fine_scale, 16)]
            if fine_scale < 80:
                settings.append((80, 16))
            try:
                tiles, (scale, _) = _escalating(
                    lambda fine, ts: _stage2(region, col, start, event_dt, chosen,
                                             spec, crs, fine, ts), settings)
                rec[f'{source}_fine_scale_m'] = scale
            except Exception as exc:
                rec[f'{source}_error'] = str(exc)[:300]
        kept_km2 = None if tiles is None else tiles['kept']
        kept_tiles = None if kept_km2 is None else kept_km2 / TILE_KM2
        status, reason = classify(n_pre, n_post, chosen, kept_tiles)
        rec.update({f'{source}_status': status, f'{source}_reason': reason})
        if tiles is not None:
            eligible_km2 = rec.get('eligible_km2')
            rec.update({
                f'{source}_kept_tiles': round(kept_tiles, 1),
                f'{source}_kept_km2': round(kept_km2, 3),
                f'{source}_usable_km2': round(tiles['usable'] or 0.0, 3),
                f'{source}_usable_frac': (round((tiles['usable'] or 0.0) / eligible_km2, 4)
                                          if eligible_km2 else None),
                f'{source}_new_water_c_km2': round(tiles['new_water'] or 0.0, 3),
            })
    rec['elapsed_s'] = round(time.time() - t0, 1)
    return rec


# ══════════════════════════════════════════════════════════════════════════════
# Driver
# ══════════════════════════════════════════════════════════════════════════════

def load_probes(path) -> dict:
    rows = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                errored = any(rec.get(f'{s}_status') == 'error' for s in SOURCES)
                # Rows with a failed probe are retried on the next run.
                if rec.get('probe_version') == PROBE_VERSION and not errored:
                    rows[analysis_key(rec)] = rec
    return rows


def write_outputs(probes: dict, registry: pd.DataFrame) -> dict:
    keys = [analysis_key(r) for _, r in registry.iterrows()]
    frame = pd.DataFrame([probes[k] for k in keys if k in probes]).reindex(columns=CSV_COLUMNS)
    csv_path = data_path('district_sits_feasibility')
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False)
    summary = summarize(frame)
    summary['registry_rows'] = int(len(registry))
    summary['probed_rows'] = int(len(frame))
    summary['fine_scale_note'] = ('tile quantities are estimates from a coarser grid '
                                  'averaged to 640 m tiles; Track B is not reproduced')
    summary['cloud_mask'] = {'sr': f'SCL exclude {list(SPEC.s2_scl_exclude)}',
                             'l1c': f's2cloudless probability < {CLOUD_PROB_MAX}'}
    summary['h5_bytes_per_tile'] = H5_BYTES_PER_TILE
    with open(data_path('district_sits_feasibility_summary'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2)
    print(f'Saved -> {csv_path} ({len(frame)} rows)')
    print(json.dumps(summary['gate'], indent=2))
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--events', nargs='*', help='event_district_ids or event_ids')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--fine-scale', type=int, default=40, choices=[20, 40, 80])
    parser.add_argument('--summarize-only', action='store_true')
    args = parser.parse_args(argv)

    registry = pd.read_csv(data_path('event_districts'), dtype=TEXT_DTYPES)
    checkpoint = data_path('district_sits_feasibility_checkpoint')
    probes = load_probes(checkpoint)
    if args.summarize_only:
        write_outputs(probes, registry)
        return 0

    todo = registry
    if args.events:
        keys = registry.apply(analysis_key, axis=1)
        todo = registry[keys.isin(args.events) | registry['event_id'].isin(args.events)]
    todo = [r for _, r in todo.iterrows() if analysis_key(r) not in probes]
    print(f'SITS feasibility probe {PROBE_VERSION}: {len(probes)} cached, {len(todo)} to probe '
          f'({args.workers} workers, fine scale {args.fine_scale} m)')
    if todo:
        sat.ensure_gee()
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=args.workers) as pool, \
                open(checkpoint, 'a', encoding='utf-8') as handle:
            futures = {pool.submit(probe_district, r, SPEC, args.fine_scale): analysis_key(r)
                       for r in todo}
            for i, future in enumerate(as_completed(futures), 1):
                key = futures[future]
                try:
                    rec = future.result()
                except Exception as exc:   # keep the run going; the row is retried next time
                    print(f'[{i}/{len(todo)}] {key}: probe failed: {exc}')
                    continue
                with lock:
                    handle.write(json.dumps(rec, default=str) + '\n')
                    handle.flush()
                probes[key] = rec
                print(f"[{i}/{len(todo)}] {key}: aoi={rec['aoi_status']} "
                      + ' '.join(f"{s}={rec.get(f'{s}_status')}/{rec.get(f'{s}_reason')}"
                                 for s in SOURCES)
                      + f" ({rec.get('elapsed_s')} s)")
    write_outputs(probes, registry)
    return 0


if __name__ == '__main__':
    sys.exit(main())
