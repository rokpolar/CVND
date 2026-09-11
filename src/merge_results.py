"""
merge_results.py — route comparable S1 / NDWI / SITS-NDWI candidates to one
district flood area.

Inputs (all measured under flood_spec.SPEC; rows or archives with another
spec_version are discarded, never reused):
  data/cache/district/flood_extent.csv  (Track A: S1 + S2 NDWI new water, cloud QA)
  data/cache/district/sits_scores/{cache_stem(event_district_id)}.npz
                                        (Track B: SITS score + per-tile NDWI km²)

Every candidate uses the same definition, new water = water(post) AND NOT
water(pre) AND eligible, so routing chooses a sensor/footprint, not a formula:
  1. SITS is patch-level (a flagged tile is flagged whole even if only a sliver
     is water), so flagged-tile extent is a DETECTION extent, not an area. SITS
     locates; pixel-level NDWI quantifies. A quality gate (Youden's J of
     SITS-vs-NDWI agreement, not external validation) decides the fusion:
        (a) ndwi-calib (J >= sits_j_min): NDWI inside SITS-flagged tiles
            (restored to all retained tiles when gating cut the water by more
            than half AND S1 independently confirms the larger extent)
        (b) otsu/low-conf: SITS unreliable -> Track A NDWI over the whole AOI,
            or NDWI over all retained tiles when Track A has no NDWI
  2. Cloud routing: cloud_pct >= cloud_route_max_pct (or unknown) -> S1.
     No SITS patches -> S1, else Track A NDWI when the AOI was mostly seen.

Output: data/intermediate/district_flood_combined.csv (flood_spec.COMBINED_COLUMNS)
Run:    python src/merge_results.py     (numpy + pandas only; no model / GEE)
"""
from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cvnd_layout import data_path  # noqa: E402
from district_keys import AOI_MATCHED, analysis_key, key_from_stem  # noqa: E402
from flood_spec import (COMBINED_COLUMNS, SATELLITE_SOURCES, SPEC,  # noqa: E402
                        SPEC_VERSION, TEXT_DTYPES, otsu_from_histogram,
                        stale_spec_mask)

SCORES_DIR = str(data_path("district_sits_scores"))
TRACK_A_CSV = str(data_path("district_flood_extent"))
OUT_CSV = str(data_path("district_flood_combined"))


def _otsu(x):
    """Otsu threshold on scores in [0,1]."""
    hist, edges = np.histogram(x, bins=64, range=(0.0, 1.0))
    threshold, _ = otsu_from_histogram(hist, (edges[:-1] + edges[1:]) / 2)
    return 0.5 if threshold is None else threshold


def _youden(scores, labels):
    """Threshold that maximises TPR - FPR against NDWI-flood labels; returns (t, J).
    This is a *balanced* boundary (not 'capture 85% of positives'), so it does not
    over-flag the way a low percentile does. J also measures how separable the two are."""
    P = int(labels.sum())
    N = int((~labels).sum())
    if P == 0 or N == 0:
        return None, 0.0
    ts = np.quantile(scores, np.linspace(0.02, 0.98, 60))
    best_t, best_j = float(np.median(scores)), -1.0
    for t in ts:
        pred = scores > t
        tpr = (pred & labels).sum() / P
        fpr = (pred & ~labels).sum() / N
        j = tpr - fpr
        if j > best_j:
            best_j, best_t = j, float(t)
    return best_t, best_j


def sits_threshold(scores, ndwi_flood, spec=SPEC):
    """Return (threshold, method): NDWI-calibrated (Youden's J) -> Otsu -> low-confidence."""
    flood = ndwi_flood >= spec.sits_flood_min_frac * spec.sits_patch_pixels
    if int(flood.sum()) >= spec.sits_min_pos and int((~flood).sum()) >= spec.sits_min_pos:
        t, j = _youden(scores, flood)
        if t is not None and j >= spec.sits_j_min:   # good separation -> trust SITS
            return t, 'ndwi-calib'
        return _otsu(scores), 'low-conf'            # NDWI floods don't separate -> SITS unreliable
    return _otsu(scores), 'otsu'                    # too few NDWI positives -> plain Otsu


def _text(archive, field):
    return str(np.asarray(archive[field]).item())


def validate_district_scores(archive, row):
    """External scores must prove the same district/geometry, model and spec."""
    for field in ['event_district_id', 'event_id', 'source_record_id', 'state', 'district', 'start_date', 'geometry_id']:
        if field not in archive or _text(archive, field) != str(row.get(field)):
            raise ValueError(f'SITS cache missing or stale district provenance: {field}; regenerate district scores')
    for field in ['model_id', 'weights_sha256', 'patches_sha256']:
        if field not in archive or not _text(archive, field).strip():
            raise ValueError(f'SITS score archive requires {field} provenance from external inference')
    if 'spec_version' not in archive or _text(archive, 'spec_version') != SPEC_VERSION:
        raise ValueError(f'SITS score archive was measured under another spec; expected {SPEC_VERSION}')
    scores, water = archive['scores'], archive['ndwi_flood']
    if scores.ndim != 1 or water.shape != scores.shape or not np.isfinite(scores).all() or not np.isfinite(water).all():
        raise ValueError('SITS scores and NDWI pixel counts must be equal-length finite vectors')
    if (scores < 0).any() or (scores > 1).any() or (water < 0).any() or (water > SPEC.sits_patch_pixels).any():
        raise ValueError('Invalid SITS score range or NDWI patch pixel count')
    for field in ['ndwi_flood_km2', 'tile_area_km2', 'usable_px']:
        if field not in archive:
            raise ValueError(f'SITS score archive missing {field}; rerun run_sits_inference.py')
        values = archive[field]
        if values.shape != scores.shape or not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f'SITS {field} must be a finite nonnegative vector matching scores')


@dataclass(frozen=True)
class Candidates:
    """Comparable new-water areas for one district (km²; None = not measured)."""
    aoi_matched: bool
    s1_km2: float | None = None
    ndwi_trackA_km2: float | None = None
    sits_full_km2: float | None = None
    sits_gated_km2: float | None = None
    sits_method: str | None = None      # None: no usable SITS tiles
    cloud_pct: float | None = None
    s2_post_images: int | None = None


@dataclass(frozen=True)
class Route:
    combined_km2: float | None
    satellite_source: str
    route_reason: str
    optical_footprint: str | None = None


def _value(x):
    if x is None:
        return None
    try:
        return None if pd.isna(x) else float(x)
    except (TypeError, ValueError):
        return None


def route_area(c: Candidates, spec=SPEC) -> Route:
    """Pick one area from comparable candidates. Pure; the routing table lives here."""
    if not c.aoi_matched:
        return Route(None, 'NONE', 'aoi_failed')
    s1, ndwi = _value(c.s1_km2), _value(c.ndwi_trackA_km2)
    cloud = _value(c.cloud_pct)
    too_cloudy = cloud is None or cloud >= spec.cloud_route_max_pct

    if c.sits_method is not None:
        full, gated = _value(c.sits_full_km2), _value(c.sits_gated_km2)
        if too_cloudy:
            # Retained tiles cover only the clear part of the AOI; with most of
            # the district unseen the optical number misses the ground -> radar.
            if s1 is not None:
                return Route(s1, 'S1', 'cloud_routed_to_s1')
            return Route(None, 'NONE', 'no_measurement')
        if c.sits_method == 'ndwi-calib':
            # SITS can also MISS flood tiles: if gating cut the water by more than
            # half AND radar confirms the larger extent, restore all retained tiles.
            if full and gated < 0.5 * full and s1 is not None and s1 >= full:
                return Route(full, 'SITS_NDWI_RESTORED', 'sits_restored_by_s1', 'sits_tiles')
            return Route(gated, 'SITS_NDWI', 'sits_gate_passed', 'sits_tiles')
        if ndwi is not None:
            return Route(ndwi, 'NDWI', 'sits_gate_failed', 'aoi')
        return Route(full, 'SITS_NDWI', 'sits_gate_failed', 'sits_tiles')

    if s1 is not None:
        return Route(s1, 'S1', 'no_optical_s1')
    if ndwi is not None and not too_cloudy:
        return Route(ndwi, 'NDWI', 'no_s1_ndwi', 'aoi')
    return Route(None, 'NONE', 'no_measurement')


def load_track_a(path=None) -> dict:
    path = path or TRACK_A_CSV
    if not os.path.exists(path):
        raise FileNotFoundError(f'{path} missing: run `src/satellite.py --track A` first')
    frame = pd.read_csv(path, dtype=TEXT_DTYPES)
    stale = stale_spec_mask(frame)
    if stale.any():
        print(f"Discarded {int(stale.sum())} Track-A rows not measured under {SPEC_VERSION}; "
              f"rerun Track A for them")
        frame = frame.loc[~stale]
    # A failed computation is not a measurement of "nothing": leave the district
    # out so the area table records it as missing until Track A is rerun.
    failed = frame.get('baseline_status', pd.Series('', index=frame.index)).astype(str).str.startswith('ERROR')
    if failed.any():
        print(f"Skipped {int(failed.sum())} Track-A ERROR rows; rerun Track A for them: "
              f"{frame.loc[failed].apply(analysis_key, axis=1).tolist()[:5]}")
        frame = frame.loc[~failed]
    rows = {}
    for _, r in frame.iterrows():
        key = analysis_key(r)
        if key in rows:
            raise ValueError(f'Track A contains duplicate analysis key {key}')
        rows[key] = r
    return rows


def _score_archives(track_a) -> dict:
    archives = {key_from_stem(os.path.basename(f)[:-4]): f
                for f in glob.glob(os.path.join(SCORES_DIR, '*.npz'))}
    parents = {str(r.get('event_id')) for r in track_a.values()}
    result = {}
    for key, path in archives.items():
        if key in track_a:
            result[key] = path
        elif key in parents:
            # A parent-event cache is not a district artifact. Never union it into
            # a district run where it could be mistaken for one district's score.
            print(f"WARN: ignoring parent-event score archive {os.path.basename(path)}")
        else:
            raise ValueError(f'SITS scores {os.path.basename(path)} have no Track A row '
                             f'under {SPEC_VERSION}; rerun Track A for {key}')
    return result


def _sits_candidates(archive, spec=SPEC) -> dict:
    """Area candidates from one validated score archive; empty dict = no usable tiles."""
    scores = archive['scores']
    if len(scores) == 0 or float(archive['usable_px'].sum()) == 0:
        return {}
    thr, method = sits_threshold(scores, archive['ndwi_flood'], spec)
    flagged = scores > thr
    flood_km2, tile_km2 = archive['ndwi_flood_km2'], archive['tile_area_km2']
    return {
        'sits_threshold': thr, 'sits_method': method,
        'sits_ndwi_full_km2': float(flood_km2.sum()),
        'sits_ndwi_gated_km2': float(flood_km2[flagged].sum()),
        # Flagged-tile extent is NOT a water area; kept for reference only.
        'sits_detect_km2': float(tile_km2[flagged].sum()),
        'sits_footprint_km2': float(tile_km2.sum()),
    }


def _round(value, digits=4):
    value = _value(value)
    return None if value is None else round(value, digits)


def merge_row(a, archive=None, spec=SPEC) -> dict:
    aoi_matched = str(a.get('aoi_match_status', '')).strip().lower() in AOI_MATCHED
    sits = {}
    if archive is not None and aoi_matched:
        validate_district_scores(archive, a)
        sits = _sits_candidates(archive, spec)
    s2_post = _value(a.get('s2_post_images'))
    candidates = Candidates(
        aoi_matched=aoi_matched,
        s1_km2=_value(a.get('area_s1_km2')),
        ndwi_trackA_km2=_value(a.get('area_s2_km2')),
        sits_full_km2=sits.get('sits_ndwi_full_km2'),
        sits_gated_km2=sits.get('sits_ndwi_gated_km2'),
        sits_method=sits.get('sits_method'),
        cloud_pct=_value(a.get('cloud_pct')),
        s2_post_images=None if s2_post is None else int(s2_post),
    )
    route = route_area(candidates, spec)
    ndwi, full = candidates.ndwi_trackA_km2, sits.get('sits_ndwi_full_km2')
    if ndwi is not None and full is not None and full > ndwi * 1.1 + 0.5:
        # Retained clear tiles are a subset of the AOI: exceeding the AOI-wide
        # measurement signals a definition mismatch, not more water.
        print(f"  WARN {analysis_key(a)}: SITS NDWI {full:.2f} km² on retained tiles > "
              f"Track A NDWI {ndwi:.2f} km² over the AOI")
    optical = bool(sits) or (ndwi is not None and (candidates.s2_post_images or 0) > 0)
    measured = aoi_matched
    return {
        **{c: a.get(c) for c in ('event_district_id', 'event_id', 'source_record_id',
                                 'start_date', 'state', 'district', 'aoi_level',
                                 'aoi_source', 'aoi_match_status', 'geometry_id')},
        'combined_km2': _round(route.combined_km2),
        'satellite_source': route.satellite_source,
        'route_reason': route.route_reason,
        'optical_footprint': route.optical_footprint,
        's1_flood_km2': _round(candidates.s1_km2) if measured else None,
        'ndwi_flood_km2': _round(ndwi) if measured else None,
        'sits_ndwi_full_km2': _round(full),
        'sits_ndwi_gated_km2': _round(sits.get('sits_ndwi_gated_km2')),
        'sits_detect_km2': _round(sits.get('sits_detect_km2')),
        'sits_footprint_km2': _round(sits.get('sits_footprint_km2')),
        'sits_threshold': _round(sits.get('sits_threshold'), 3),
        'sits_method': sits.get('sits_method', 'no-sits'),
        'optical_available': optical and measured,
        'cloud_pct': candidates.cloud_pct,
        'otsu_threshold_db': a.get('otsu_threshold_db'),
        'otsu_fallback_used': a.get('otsu_fallback_used'),
        's1_orbit': a.get('s1_orbit'),
        's1_post_images': a.get('s1_post_images'),
        's2_post_images': a.get('s2_post_images'),
        'aoi_area_km2': _value(a.get('aoi_area_km2')),
        'spec_version': SPEC_VERSION,
    }


def main():
    track_a = load_track_a()
    archives = _score_archives(track_a)
    rows = []
    for key in sorted(track_a):
        a = track_a[key]
        archive = np.load(archives[key], allow_pickle=False) if key in archives else None
        try:
            row = merge_row(a, archive)
        finally:
            if archive is not None:
                archive.close()
        assert row['satellite_source'] in SATELLITE_SOURCES
        rows.append(row)
        c = row['combined_km2']
        print(f"  {key}: {row['sits_method']:10s} ndwi={row['ndwi_flood_km2']} "
              f"s1={row['s1_flood_km2']} -> combined={c} "
              f"({row['satellite_source']}, {row['route_reason']})")

    os.makedirs(os.path.dirname(OUT_CSV) or '.', exist_ok=True)
    pd.DataFrame(rows, columns=list(COMBINED_COLUMNS)).to_csv(OUT_CSV, index=False)
    print(f"\nSaved -> {OUT_CSV}  ({len(rows)} district rows, spec {SPEC_VERSION})")


if __name__ == '__main__':
    main()
