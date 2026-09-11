"""Paired Track A / Track B comparison and the S1 -> SITS-NDWI converter decision.

Track A NDWI and Track B SITS-NDWI are the same estimator (same composites,
threshold, eligibility and -- since both use the district's UTM grid -- the
same pixels), so a difference between them is a bug, not something to
convert. The *identity check* rebuilds Track A's AOI-wide NDWI new water from
the downloaded Track B pixels (H5 block_stats, every AOI pixel of every block)
and compares it with Track A's reduction.

The converter question is S1 vs optical on one footprint C: eligible, inside
the AOI, clear in every SITS timestep, NDWI observed pre and post, on the
retained tiles (the usable pixels of run_sits_inference). On C this module
reports per district and pooled: log ratio r_d = log((S1 + o) / (T + o)) with
T the SITS-NDWI target (flood_spec.ConverterRules.target), Bland-Altman on
logs, Deming, Lin's CCC, pixel IoU / kappa / omission / commission, a joint
Wald heterogeneity test, and the SITS gate retention g = gated / full. The
pre-registered flood_spec.CONVERTER_RULES then decide:
  insufficient  fewer than min_districts (A_ndwi(C) >= min_area_km2) or min_states
  identity      TOST-equivalent, no heterogeneity (HC3-F), IoU >= iou_min
  linear        not equivalent, no heterogeneity, narrow Deming slope CI:
                log-log Deming, leave-one-state-out CV error reported
  stratified    otherwise, a log-linear model with built-up / cropland shares
                if its LOSO-CV median |log error| <= log(cv_tolerance_ratio)
  excluded      otherwise: districts SITS cannot measure leave the primary
Track A's own footprint pairs (S1 vs NDWI on its optical_observed pixels) are
reported alongside as the larger, Track-B-free sample.

Outputs: data/results/track_agreement.csv, track_agreement_summary.json,
         s1_to_sits_converter.json (read by merge_results.py)
Run:     python src/compare_tracks.py        (numpy / pandas / scipy; no GEE)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone

import h5py
import numpy as np
import pandas as pd
from scipy.stats import f as f_dist

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_results  # noqa: E402
import s1_converter  # noqa: E402
from cvnd_layout import data_path  # noqa: E402
from district_keys import analysis_key, cache_stem  # noqa: E402
from flood_spec import (CONVERTER_RULES, CONVERTER_RULES_VERSION, SPEC,  # noqa: E402
                        SPEC_VERSION)

AGREEMENT_CSV = str(data_path('track_agreement'))
SUMMARY_JSON = str(data_path('track_agreement_summary'))
BLOCK_COLUMNS = ('block_id', 'aoi_m2', 'eligible_m2', 'optical_observed_m2',
                 'ndwi_new_m2', 's1_new_m2')
HETEROGENEITY_COVARIATES = ('builtup_frac_c', 'cropland_frac_c', 's1_post_images',
                            'orbit_ascending', 'orbit_descending', 'recent_2022',
                            'cloud_pct', 'otsu_fallback')
STRATA_COVARIATES = ('builtup_frac', 'cropland_frac')


# ══════════════════════════════════════════════════════════════════════════════
# Pure statistics (tested offline)
# ══════════════════════════════════════════════════════════════════════════════

def log_ratio(x, y, offset):
    return np.log((np.asarray(x, float) + offset) / (np.asarray(y, float) + offset))


def deming(x, y, delta=1.0) -> tuple[float, float]:
    """Deming slope and intercept of y on x with error-variance ratio delta."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    xm, ym = x.mean(), y.mean()
    sxx, syy = ((x - xm) ** 2).mean(), ((y - ym) ** 2).mean()
    sxy = ((x - xm) * (y - ym)).mean()
    if sxy == 0:
        return float('nan'), float('nan')
    slope = (syy - delta * sxx + np.sqrt((syy - delta * sxx) ** 2 + 4 * delta * sxy ** 2)) / (2 * sxy)
    return float(slope), float(ym - slope * xm)


def bland_altman_log(x, y, offset) -> dict:
    d = log_ratio(x, y, offset)
    bias, sd = float(d.mean()), float(d.std(ddof=1)) if len(d) > 1 else float('nan')
    return {'bias': bias, 'sd': sd, 'loa_low': bias - 1.96 * sd, 'loa_high': bias + 1.96 * sd}


def lin_ccc(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    cov = ((x - x.mean()) * (y - y.mean())).mean()
    return float(2 * cov / (x.var() + y.var() + (x.mean() - y.mean()) ** 2))


def cluster_bootstrap(stat, groups, reps, seed) -> np.ndarray:
    """Statistic ``stat(indices)`` over resampled clusters (states)."""
    groups = np.asarray(groups)
    labels = np.unique(groups)
    members = [np.flatnonzero(groups == g) for g in labels]
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for i in range(reps):
        picked = rng.integers(0, len(labels), len(labels))
        out[i] = stat(np.concatenate([members[j] for j in picked]))
    return out


def tost_log_ratio(r, groups, bound, alpha, reps, seed) -> dict:
    """Equivalence of the median log ratio to 0 within ±bound: the (1 - 2 alpha)
    state-cluster bootstrap CI of the median lies inside (-bound, bound)."""
    r = np.asarray(r, float)
    draws = cluster_bootstrap(lambda idx: np.median(r[idx]), groups, reps, seed)
    lo, hi = np.quantile(draws, [alpha, 1 - alpha])
    return {'median': float(np.median(r)), 'ci_low': float(lo), 'ci_high': float(hi),
            'bound': float(bound), 'equivalent': bool(lo > -bound and hi < bound)}


def pixel_agreement(s1, ndwi, both, usable) -> dict:
    """Area-based agreement of S1 and NDWI new water on the same pixels."""
    union = s1 + ndwi - both
    a, b, c = both, s1 - both, ndwi - both
    d = usable - a - b - c
    po = (a + d) / usable if usable else float('nan')
    pe = (((a + b) * (a + c) + (c + d) * (b + d)) / usable ** 2) if usable else float('nan')
    return {
        'iou': float(both / union) if union > 0 else float('nan'),
        'kappa': float((po - pe) / (1 - pe)) if usable and pe < 1 else float('nan'),
        'omission': float(c / ndwi) if ndwi > 0 else float('nan'),
        'commission': float(b / s1) if s1 > 0 else float('nan'),
    }


def wald_heterogeneity(r, covariates: pd.DataFrame, groups, min_clusters) -> dict:
    """Joint test that no covariate shifts r: OLS with a robust covariance,
    Wald / q referred to F. HC3 with F(q, n - k) below ``min_clusters``
    states; CR1 by state with F(q, G - 1) from there. (HC1 with chi² rejects
    pure noise 20-37% of the time at nominal 10% for n = 48-98 and eight
    covariates; HC3-F holds 8.5-11%.) Constant covariates are dropped; an
    untestable design returns p None."""
    X = covariates.astype(float)
    X = X.loc[:, X.nunique() > 1]
    n, k = len(X), X.shape[1] + 1
    q = k - 1
    result = {'covariates': list(X.columns), 'n': int(n), 'stat': None, 'df': [int(q), None],
              'p': None, 'cov_type': None}
    if q == 0 or n <= k + 1:
        return result
    design = np.column_stack([np.ones(n), X.to_numpy()])
    if np.linalg.matrix_rank(design) < k:
        return result
    r = np.asarray(r, float)
    bread = np.linalg.inv(design.T @ design)
    beta = bread @ design.T @ r
    e = r - design @ beta
    groups = np.asarray(groups)
    labels = np.unique(groups)
    if len(labels) >= min_clusters:
        scores = np.array([design[groups == g].T @ e[groups == g] for g in labels])
        cov = (len(labels) / (len(labels) - 1) * (n - 1) / (n - k)) * bread @ (scores.T @ scores) @ bread
        dof, result['cov_type'] = len(labels) - 1, 'CR1_state_F'
    else:
        leverage = np.einsum('ij,jk,ik->i', design, bread, design)
        weights = (e / (1 - leverage)) ** 2
        cov = bread @ ((design * weights[:, None]).T @ design) @ bread
        dof, result['cov_type'] = n - k, 'HC3_F'
    slopes, v = beta[1:], cov[1:, 1:]
    try:
        stat = float(slopes @ np.linalg.solve(v, slopes)) / q
    except np.linalg.LinAlgError:
        return result
    result.update(stat=stat, df=[int(q), int(dof)], p=float(f_dist.sf(stat, q, dof)),
                  coefficients=dict(zip(X.columns, map(float, slopes))))
    return result


def _ols(X, y):
    design = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    return beta


def loso_errors(fit, predict, frame, groups) -> np.ndarray:
    """Leave-one-state-out prediction errors y - y_hat (log scale)."""
    groups = np.asarray(groups)
    errors = np.empty(len(frame))
    for g in np.unique(groups):
        held = groups == g
        model = fit(frame.loc[~held])
        errors[held] = frame.loc[held, 'y'].to_numpy() - predict(model, frame.loc[held])
    return errors


def fit_deming(frame):
    slope, intercept = deming(frame['x'], frame['y'])
    return {'slope': slope, 'intercept': intercept}


def predict_deming(model, frame):
    return model['intercept'] + model['slope'] * frame['x'].to_numpy()


def fit_strata(frame):
    beta = _ols(frame[['x', *STRATA_COVARIATES]].to_numpy(float), frame['y'].to_numpy(float))
    return dict(zip(('const', 'log_s1', *STRATA_COVARIATES), map(float, beta)))


def predict_strata(model, frame):
    return (model['const'] + model['log_s1'] * frame['x'].to_numpy()
            + sum(model[c] * frame[c].to_numpy(float) for c in STRATA_COVARIATES))


def _cv_summary(errors, tolerance_ratio) -> dict:
    abs_err = np.abs(errors)
    return {'median_abs_log_error': float(np.median(abs_err)),
            'median_ratio_error': float(np.exp(np.median(abs_err))),
            'tolerance_ratio': tolerance_ratio,
            'within_tolerance': bool(np.median(abs_err) <= np.log(tolerance_ratio))}


def converter_decision(pairs: pd.DataFrame, rules=CONVERTER_RULES) -> dict:
    """Apply the pre-registered rules to the paired districts."""
    o = rules.log_offset_km2
    usable = pairs[pairs['identity_ok'].astype(bool)
                   & (pairs['ndwi_c_km2'] >= rules.min_area_km2)].copy()
    target_col = 'route_c_km2' if rules.target == 'sits_route' else 'ndwi_c_km2'
    out = {'rules': asdict(rules), 'target_column': target_col,
           'n_districts': int(len(usable)), 'n_states': int(usable['state'].nunique()),
           'fit_keys': sorted(usable['event_district_id'].astype(str))}
    if out['n_districts'] < rules.min_districts or out['n_states'] < rules.min_states:
        out.update(decision='insufficient',
                   reason=f"{out['n_districts']} districts / {out['n_states']} states < "
                          f"{rules.min_districts} / {rules.min_states}")
        return out
    usable['x'] = np.log(usable['s1_c_km2'] + o)
    usable['y'] = np.log(usable[target_col] + o)
    r = (usable['x'] - usable['y']).to_numpy()
    groups = usable['state'].to_numpy()
    tost = tost_log_ratio(r, groups, np.log(rules.equivalence_ratio), rules.alpha,
                          rules.bootstrap_reps, rules.seed)
    het = wald_heterogeneity(r, usable[list(HETEROGENEITY_COVARIATES)], groups,
                             rules.wald_cluster_min_states)
    pooled = pixel_agreement(*(float(usable[c].sum()) for c in
                               ('s1_c_km2', 'ndwi_c_km2', 'both_c_km2', 'usable_km2')))
    dem = fit_deming(usable)
    idx_frame = usable.reset_index(drop=True)
    slopes = cluster_bootstrap(lambda idx: deming(idx_frame['x'].to_numpy()[idx],
                                                  idx_frame['y'].to_numpy()[idx])[0],
                               groups, rules.bootstrap_reps, rules.seed)
    slope_ci = [float(v) for v in np.nanquantile(slopes, [rules.alpha / 2, 1 - rules.alpha / 2])]
    homogeneous = het['p'] is not None and het['p'] > rules.heterogeneity_p
    out.update(tost=tost, heterogeneity=het, pooled_pixel=pooled,
               deming={**dem, 'slope_ci': slope_ci})
    if tost['equivalent'] and homogeneous and pooled['iou'] >= rules.iou_min:
        out.update(decision='identity', model={'type': 'identity'},
                   reason='equivalent within ±log(%.2f), homogeneous, IoU %.2f'
                          % (rules.equivalence_ratio, pooled['iou']))
        return out
    if (not tost['equivalent'] and homogeneous
            and slope_ci[1] - slope_ci[0] <= rules.deming_slope_ci_max_width):
        cv = _cv_summary(loso_errors(fit_deming, predict_deming, usable, groups),
                         rules.cv_tolerance_ratio)
        out.update(decision='linear', cv=cv,
                   model={'type': 'deming_loglog', 'offset_km2': o, **dem},
                   reason='not equivalent, homogeneous, narrow Deming slope CI')
        return out
    strata = usable.dropna(subset=list(STRATA_COVARIATES))
    cv = _cv_summary(loso_errors(fit_strata, predict_strata, strata, strata['state'].to_numpy()),
                     rules.cv_tolerance_ratio)
    out['cv'] = cv
    why = ('heterogeneous' if not homogeneous else
           'IoU %.2f < %.2f' % (pooled['iou'], rules.iou_min) if tost['equivalent'] else
           'Deming slope CI too wide')
    if cv['within_tolerance']:
        out.update(decision='stratified', reason=f'{why}; stratified LOSO-CV within tolerance',
                   model={'type': 'ols_loglog_strata', 'offset_km2': o, 'coef': fit_strata(strata)})
    else:
        out.update(decision='excluded', reason=f'{why}; stratified LOSO-CV error '
                                               f'{cv["median_ratio_error"]:.2f}x > {rules.cv_tolerance_ratio}x')
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Per-district pairs
# ══════════════════════════════════════════════════════════════════════════════

def h5_summary(path) -> dict:
    """Identity inputs from a Track B H5: block sums, duplicates, pixel area."""
    if not os.path.exists(path):
        return {'h5_status': 'missing'}
    with h5py.File(path, 'r') as hdf:
        stats = hdf['block_stats'][:]
        coords = hdf['coords'][:]
        area = hdf['pixel_area_m2'][:]
        threshold = float(hdf['meta'].attrs.get('s1_threshold_db', np.nan))
    sums = dict(zip(BLOCK_COLUMNS[1:], stats[:, 1:].sum(axis=0) / 1e6)) if len(stats) else {}
    tiles = pd.DataFrame(coords[:, :2]) if len(coords) else pd.DataFrame(columns=[0, 1])
    return {
        'h5_status': 'ok',
        'n_blocks': int(len(stats)),
        'duplicate_blocks': int(len(stats) - len(np.unique(stats[:, 0]))) if len(stats) else 0,
        'n_tiles': int(len(coords)),
        'duplicate_tiles': int(tiles.duplicated().sum()),
        'pixel_area_min_m2': float(area.min()) if len(area) else None,
        'pixel_area_max_m2': float(area.max()) if len(area) else None,
        'blocks_aoi_km2': sums.get('aoi_m2'), 'blocks_eligible_km2': sums.get('eligible_m2'),
        'blocks_observed_km2': sums.get('optical_observed_m2'),
        'blocks_ndwi_km2': sums.get('ndwi_new_m2'), 'blocks_s1_km2': sums.get('s1_new_m2'),
        'threshold_b_db': threshold if np.isfinite(threshold) else None,
    }


def _rel_err(a, b):
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b):
        return None
    return abs(a - b) / max(abs(a), 1.0)


def _num(value):
    value = merge_results._value(value)
    return None if value is None else float(value)


def district_pair(a, archive, h5, rules=CONVERTER_RULES, spec=SPEC) -> dict:
    """One district's identity check and paired areas on footprint C."""
    key = analysis_key(a)
    area = archive['tile_area_km2'] / spec.sits_patch_pixels   # km² per pixel, per tile
    sits = merge_results._sits_candidates(archive, spec)
    route = merge_results.route_area(merge_results.Candidates(
        aoi_matched=True, sits_status='ok', sits_full_km2=sits.get('sits_ndwi_full_km2'),
        sits_gated_km2=sits.get('sits_ndwi_gated_km2'), sits_method=sits.get('sits_method'),
        sits_s1_usable_km2=sits.get('sits_s1_usable_km2')), spec) if sits else None
    usable_px = archive['usable_px']

    def km2(name):
        return float((archive[name] * area).sum())

    usable_km2 = km2('usable_px')
    ndwi_c, s1_c, both_c = km2('ndwi_flood'), km2('s1_flood'), km2('both_flood')
    track_a_ndwi, track_a_s1 = _num(a.get('area_s2_km2')), _num(a.get('area_s1_km2'))
    threshold_a = _num(a.get('otsu_threshold_db'))
    eligible = _num(a.get('eligible_km2'))
    orbit = str(a.get('s1_orbit') or '')
    identity = _rel_err(track_a_ndwi, h5.get('blocks_ndwi_km2'))
    row = {
        'event_district_id': key, 'event_id': a.get('event_id'), 'state': a.get('state'),
        'district': a.get('district'), 'start_date': a.get('start_date'),
        'year': int(str(a.get('start_date'))[:4]),
        **h5,
        'track_a_ndwi_km2': track_a_ndwi, 'identity_rel_err': identity,
        'identity_ok': bool(identity is not None and identity <= rules.identity_tolerance
                            and h5.get('duplicate_tiles', 1) == 0
                            and h5.get('duplicate_blocks', 1) == 0),
        'track_a_s1_km2': track_a_s1,
        's1_identity_rel_err': _rel_err(track_a_s1, h5.get('blocks_s1_km2')),
        'grid_aoi_km2': _num(a.get('grid_aoi_km2')),
        'aoi_coverage_rel_err': _rel_err(_num(a.get('grid_aoi_km2')), h5.get('blocks_aoi_km2')),
        'threshold_a_db': threshold_a,
        'threshold_match': (threshold_a is not None and h5.get('threshold_b_db') is not None
                            and abs(threshold_a - h5['threshold_b_db']) < 1e-3),
        'usable_km2': usable_km2,
        'usable_frac': usable_km2 / eligible if eligible else None,
        'ndwi_c_km2': ndwi_c, 's1_c_km2': s1_c, 'both_c_km2': both_c,
        'gated_c_km2': sits.get('sits_ndwi_gated_km2'),
        'route_c_km2': None if route is None else route.combined_km2,
        'route_c_source': None if route is None else route.satellite_source,
        'sits_method': sits.get('sits_method'),
        'gate_retention': (sits['sits_ndwi_gated_km2'] / sits['sits_ndwi_full_km2']
                           if sits and sits['sits_ndwi_full_km2'] > 0 else None),
        'builtup_frac_c': km2('builtup_px') / usable_km2 if usable_km2 else None,
        'cropland_frac_c': km2('cropland_px') / usable_km2 if usable_km2 else None,
        'ndwi_builtup_c_km2': km2('ndwi_flood_builtup'),
        's1_builtup_c_km2': km2('s1_flood_builtup'),
        'builtup_frac': (_num(a.get('builtup_km2')) or 0.0) / eligible if eligible else None,
        'cropland_frac': (_num(a.get('cropland_km2')) or 0.0) / eligible if eligible else None,
        's1_post_images': _num(a.get('s1_post_images')),
        'orbit_ascending': float(orbit == 'ASCENDING'),
        'orbit_descending': float(orbit == 'DESCENDING'),
        'recent_2022': float(int(str(a.get('start_date'))[:4]) >= 2022),
        'cloud_pct': _num(a.get('cloud_pct')),
        'otsu_fallback': float(str(a.get('otsu_fallback_used')).lower() == 'true'),
        'n_tiles_archive': int(len(usable_px)),
    }
    row.update({f'{k}_c': v for k, v in pixel_agreement(s1_c, ndwi_c, both_c, usable_km2).items()})
    row['log_ratio_c'] = (float(log_ratio(s1_c, row['route_c_km2'], rules.log_offset_km2))
                          if row['route_c_km2'] is not None else None)
    row['log_ratio_c_full'] = float(log_ratio(s1_c, ndwi_c, rules.log_offset_km2))
    return row


def track_a_footprint_pairs(track_a: dict, rules=CONVERTER_RULES) -> dict:
    """S1 vs NDWI on Track A's optical_observed pixels, for every Track A row."""
    rows = []
    for a in track_a.values():
        s1, ndwi, both = (_num(a.get(c)) for c in ('s1_on_optical_km2', 'area_s2_km2',
                                                    's1_ndwi_both_km2'))
        observed = _num(a.get('optical_observed_km2'))
        if None in (s1, ndwi, both, observed):
            continue
        rows.append({'state': a.get('state'), 's1': s1, 'ndwi': ndwi, 'both': both,
                     'observed': observed})
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {'n_districts': 0}
    paired = frame[frame['ndwi'] >= rules.min_area_km2]
    out = {'n_districts': int(len(frame)), 'n_with_ndwi_ge_min': int(len(paired)),
           'n_states': int(paired['state'].nunique()) if len(paired) else 0,
           'pooled_pixel': pixel_agreement(*(float(frame[c].sum()) for c in
                                             ('s1', 'ndwi', 'both', 'observed')))}
    if len(paired) >= 2:
        r = log_ratio(paired['s1'], paired['ndwi'], rules.log_offset_km2)
        out.update(median_log_ratio=float(np.median(r)),
                   bland_altman=bland_altman_log(paired['s1'], paired['ndwi'], rules.log_offset_km2),
                   ccc_log=lin_ccc(np.log(paired['s1'] + rules.log_offset_km2),
                                   np.log(paired['ndwi'] + rules.log_offset_km2)))
    return out


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def summarize(pairs: pd.DataFrame, decision: dict, footprint: dict,
              rules=CONVERTER_RULES) -> dict:
    o = rules.log_offset_km2
    checked = pairs[pairs['identity_rel_err'].notna()]
    summary = {
        'spec_version': SPEC_VERSION, 'rules_version': CONVERTER_RULES_VERSION,
        'n_sits_districts': int(len(pairs)),
        'identity': {
            'checked': int(len(checked)),
            'failed': int((~checked['identity_ok'].astype(bool)).sum()),
            # Deleted or never-written H5: identity cannot be checked, the
            # district cannot enter the converter fit.
            'unchecked': int(len(pairs) - len(checked)),
            'max_rel_err': float(checked['identity_rel_err'].max()) if len(checked) else None,
            'duplicate_tiles': int(pairs.get('duplicate_tiles', pd.Series(dtype=float)).fillna(0).sum()),
            'threshold_mismatches': int((~pairs['threshold_match'].astype(bool)).sum()) if len(pairs) else 0,
            'tolerance': rules.identity_tolerance,
            'note': 'a failure is a bug (grid, rounding, footprint, duplicates), never a conversion target',
        },
        'decision': {k: v for k, v in decision.items() if k not in ('fit_keys', 'rules')},
        'track_a_footprint_pairs': footprint,
    }
    paired = pairs[pairs['identity_ok'].astype(bool) & (pairs['ndwi_c_km2'] >= rules.min_area_km2)]
    if len(paired) >= 2:
        target = decision.get('target_column', 'route_c_km2')
        x, y = paired['s1_c_km2'], paired[target]
        summary['paired_c'] = {
            'bland_altman_log': bland_altman_log(x, y, o),
            'ccc_log': lin_ccc(np.log(x + o), np.log(y + o)),
            'vs_ndwi_full_median_log_ratio': float(np.median(log_ratio(x, paired['ndwi_c_km2'], o))),
            'gate_retention_quantiles': (paired['gate_retention'].dropna()
                                         .quantile([.1, .25, .5, .75, .9]).to_dict()),
            'gate_retention_vs_builtup_spearman': (
                float(paired[['gate_retention', 'builtup_frac_c']].corr('spearman').iloc[0, 1])
                if paired['gate_retention'].notna().sum() > 2 else None),
            # Portability: does r_d drift with cloudiness (clear-pixel converter
            # applied to cloudy districts)?
            'log_ratio_by_cloud_tercile': (
                paired.assign(tercile=pd.qcut(paired['cloud_pct'], 3, labels=False, duplicates='drop'))
                .groupby('tercile')['log_ratio_c'].median().to_dict()
                if paired['cloud_pct'].nunique() >= 3 else None),
        }
    return _clean(summary)


def main() -> int:
    track_a = merge_results.load_track_a()
    archives = merge_results._score_archives(track_a)
    index = merge_results.load_sits_index()
    rows = []
    for key in sorted(archives):
        a = track_a[key]
        status, _ = merge_results.track_b_status(key, index.get(key), has_scores=True)
        if status != 'ok':
            continue
        with np.load(archives[key], allow_pickle=False) as archive:
            merge_results.validate_district_scores(archive, a)
            if len(archive['scores']) == 0:
                continue
            h5 = h5_summary(os.path.join(merge_results.PATCH_DIR, f'{cache_stem(key)}.h5'))
            rows.append(district_pair(a, archive, h5))
    pairs = pd.DataFrame(rows)
    if pairs.empty:
        pairs = pd.DataFrame(columns=['event_district_id', 'state', 'identity_ok', 'ndwi_c_km2',
                                      'identity_rel_err', 'threshold_match'])
    decision = converter_decision(pairs)
    footprint = track_a_footprint_pairs(track_a)
    summary = summarize(pairs, decision, footprint)

    os.makedirs(os.path.dirname(AGREEMENT_CSV), exist_ok=True)
    pairs.to_csv(AGREEMENT_CSV, index=False)
    with open(SUMMARY_JSON, 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2, allow_nan=False)
    converter = _clean({
        'decision': decision['decision'], 'reason': decision.get('reason'),
        'spec_version': SPEC_VERSION, 'rules_version': CONVERTER_RULES_VERSION,
        'target': CONVERTER_RULES.target, 'model': decision.get('model'),
        'cv': decision.get('cv'), 'fit_keys': decision['fit_keys'],
        'n_districts': decision['n_districts'], 'n_states': decision['n_states'],
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    })
    path = s1_converter.write(converter)
    print(f"Saved -> {AGREEMENT_CSV} ({len(pairs)} SITS districts), {SUMMARY_JSON}, {path}")
    print(f"Identity: {summary['identity']['failed']}/{summary['identity']['checked']} failed; "
          f"converter decision: {decision['decision']} ({decision.get('reason')})")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
