"""
merge_results.py — one district flood area on the SITS-NDWI scale.

Inputs (all measured under flood_spec.SPEC; rows or archives with another
spec_version are discarded, never reused):
  data/cache/district/flood_extent.csv        (Track A: S1 + S2 NDWI, footprints)
  data/cache/district/sits_patches_index.csv  (Track B status per district)
  data/cache/district/sits_scores/{cache_stem(event_district_id)}.npz
                                              (Track B: SITS score + per-tile areas)
  data/results/s1_to_sits_converter.json      (compare_tracks.py decision)

SITS (Track B) is the primary measurement. It must run for every district and
its status decides the route (route_area):
  pending      Track B not run, incomplete (.blocks.json left) or not inferred
               -> NA (sits_pending). Never a silent S1 fallback: which sensor
               measures a district must not depend on how far the computation got.
  ok           SITS-NDWI on the retained tiles through the quality gate below.
               If the usable pixels cover less than sits_usable_min_frac of the
               eligible AOI, the tiles cannot stand for the district -> S1_TO_SITS.
  unavailable  a data condition (no pre/post imagery, no clear baseline, no
               retained tile) -> S1_TO_SITS.
S1_TO_SITS is Track A S1 new water converted to the SITS-NDWI scale with the
converter compare_tracks.py decided. Decision excluded/insufficient -> NA
(..._excluded); converter missing or fitted under another spec -> NA
(converter_missing). Raw S1 never enters combined_km2.

SITS gate: SITS is patch-level (a flagged tile is flagged whole even if only a
sliver is water), so flagged-tile extent is a DETECTION extent, not an area.
Youden's J of SITS scores against NDWI-flood tiles decides the fusion:
  ndwi-calib (J >= sits_j_min): NDWI new water inside flagged tiles, restored
      to all retained tiles when gating kept less than sits_restore_gated_frac
      of the water AND S1 on the same usable pixels confirms the larger extent
  low-conf / otsu: the gate is unreliable -> NDWI on all retained tiles
The pre-refactor routing is kept as legacy_route_area and written to the
legacy_* columns for the before/after comparison.

Routing mode (--routing, flood_spec.ROUTING_MODES):
  s1_interim (default until Track B covers every district and the converter
      is decided): every district is measured by Track A Sentinel-1 new water
      over the eligible AOI alone (satellite_source S1, route_reason
      interim_s1_only). One sensor for all districts, so no sensor mixing;
      SITS columns are still filled where Track B exists, for reference only.
  sits_primary: the SITS-first routing above.

Output: data/intermediate/district_flood_combined.csv (flood_spec.COMBINED_COLUMNS)
Run:    python src/merge_results.py [--routing s1_interim|sits_primary]
        (numpy + pandas only; no model / GEE)
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1_converter  # noqa: E402
from cvnd_layout import data_path  # noqa: E402
from district_keys import AOI_MATCHED, analysis_key, cache_stem, key_from_stem  # noqa: E402
from flood_spec import (COMBINED_COLUMNS, CONVERTING_DECISIONS,  # noqa: E402
                        DEFAULT_ROUTING, H5_LAYOUT_VERSION, ROUTING_MODES,
                        SATELLITE_SOURCES, SPEC, SPEC_VERSION, TEXT_DTYPES,
                        otsu_from_histogram, stale_spec_mask)

SCORES_DIR = str(data_path("district_sits_scores"))
PATCH_DIR = str(data_path("district_sits_patches"))
TRACK_A_CSV = str(data_path("district_flood_extent"))
SITS_INDEX_CSV = str(data_path("district_sits_patches_index"))
OUT_CSV = str(data_path("district_flood_combined"))


def _otsu(x, spec=SPEC):
    """Otsu threshold on scores in [0,1]."""
    hist, edges = np.histogram(x, bins=spec.sits_score_otsu_bins, range=(0.0, 1.0))
    threshold, _ = otsu_from_histogram(hist, (edges[:-1] + edges[1:]) / 2)
    return 0.5 if threshold is None else threshold


def _youden(scores, labels, spec=SPEC):
    """Threshold that maximises TPR - FPR against NDWI-flood labels; returns (t, J).
    This is a *balanced* boundary (not 'capture 85% of positives'), so it does not
    over-flag the way a low percentile does. J also measures how separable the two are."""
    P = int(labels.sum())
    N = int((~labels).sum())
    if P == 0 or N == 0:
        return None, 0.0
    ts = np.quantile(scores, np.linspace(0.02, 0.98, spec.sits_youden_steps))
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
        t, j = _youden(scores, flood, spec)
        if t is not None and j >= spec.sits_j_min:   # good separation -> trust SITS
            return t, 'ndwi-calib'
        return _otsu(scores, spec), 'low-conf'      # NDWI floods don't separate -> SITS unreliable
    return _otsu(scores, spec), 'otsu'              # too few NDWI positives -> plain Otsu


def _text(archive, field):
    return str(np.asarray(archive[field]).item())


SCORE_VECTORS = ('ndwi_flood_km2', 'tile_area_km2', 'usable_px', 'usable_km2',
                 's1_flood_km2', 'block_id')


def validate_district_scores(archive, row):
    """External scores must prove the same district/geometry, model, spec and layout."""
    for field in ['event_district_id', 'event_id', 'source_record_id', 'state', 'district', 'start_date', 'geometry_id']:
        if field not in archive or _text(archive, field) != str(row.get(field)):
            raise ValueError(f'SITS cache missing or stale district provenance: {field}; regenerate district scores')
    for field in ['model_id', 'weights_sha256', 'patches_sha256']:
        if field not in archive or not _text(archive, field).strip():
            raise ValueError(f'SITS score archive requires {field} provenance from external inference')
    if 'spec_version' not in archive or _text(archive, 'spec_version') != SPEC_VERSION:
        raise ValueError(f'SITS score archive was measured under another spec; expected {SPEC_VERSION}')
    if 'layout_version' not in archive or _text(archive, 'layout_version') != H5_LAYOUT_VERSION:
        raise ValueError(f'SITS score archive has another H5 layout; expected {H5_LAYOUT_VERSION}; '
                         f'rerun run_sits_inference.py')
    scores, water = archive['scores'], archive['ndwi_flood']
    if scores.ndim != 1 or water.shape != scores.shape or not np.isfinite(scores).all() or not np.isfinite(water).all():
        raise ValueError('SITS scores and NDWI pixel counts must be equal-length finite vectors')
    if (scores < 0).any() or (scores > 1).any() or (water < 0).any() or (water > SPEC.sits_patch_pixels).any():
        raise ValueError('Invalid SITS score range or NDWI patch pixel count')
    for field in SCORE_VECTORS:
        if field not in archive:
            raise ValueError(f'SITS score archive missing {field}; rerun run_sits_inference.py')
        values = archive[field]
        if values.shape != scores.shape or not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f'SITS {field} must be a finite nonnegative vector matching scores')


@dataclass(frozen=True)
class Candidates:
    """Comparable new-water areas for one district (km²; None = not measured)."""
    aoi_matched: bool
    s1_km2: float | None = None            # Track A S1 over the eligible AOI
    ndwi_trackA_km2: float | None = None   # Track A NDWI over the observed AOI (legacy only)
    sits_full_km2: float | None = None
    sits_gated_km2: float | None = None
    sits_method: str | None = None         # None: no usable SITS tiles
    cloud_pct: float | None = None         # legacy routing only
    s2_post_images: int | None = None
    sits_status: str = 'pending'
    sits_usable_km2: float | None = None
    sits_s1_usable_km2: float | None = None   # S1 new water on the SITS usable pixels
    eligible_km2: float | None = None
    s1_converted_km2: float | None = None     # s1_km2 on the SITS-NDWI scale
    converter_decision: str | None = None     # None: converter missing / other spec


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


def _to_sits_scale(c: Candidates, reason: str, excluded_reason: str) -> Route:
    if c.converter_decision is None:
        return Route(None, 'NONE', 'converter_missing')
    if c.converter_decision not in CONVERTING_DECISIONS:
        return Route(None, 'NONE', excluded_reason)
    converted = _value(c.s1_converted_km2)
    if _value(c.s1_km2) is None or converted is None:
        return Route(None, 'NONE', 'no_s1')
    return Route(converted, 'S1_TO_SITS', reason, 'aoi')


def usable_fraction(c: Candidates) -> float | None:
    usable, eligible = _value(c.sits_usable_km2), _value(c.eligible_km2)
    if usable is None or not eligible:
        return None
    return usable / eligible


def route_area(c: Candidates, spec=SPEC) -> Route:
    """Pick one area on the SITS-NDWI scale. Pure; the routing table lives here."""
    if not c.aoi_matched:
        return Route(None, 'NONE', 'aoi_failed')
    if c.sits_status == 'pending':
        return Route(None, 'NONE', 'sits_pending')
    if c.sits_status == 'unavailable':
        return _to_sits_scale(c, 'sits_unavailable_converted', 'sits_unavailable_excluded')

    frac = usable_fraction(c)
    if frac is not None and frac < spec.sits_usable_min_frac:
        return _to_sits_scale(c, 'sits_footprint_small', 'sits_footprint_small_excluded')
    full, gated = _value(c.sits_full_km2), _value(c.sits_gated_km2)
    if c.sits_method == 'ndwi-calib':
        # SITS can also MISS flood tiles: if gating cut the water by more than
        # the restore share AND S1 on the same pixels confirms the larger
        # extent, restore all retained tiles.
        s1 = _value(c.sits_s1_usable_km2)
        if full and gated < spec.sits_restore_gated_frac * full and s1 is not None and s1 >= full:
            return Route(full, 'SITS_NDWI_RESTORED', 'sits_restored_by_s1', 'sits_tiles')
        return Route(gated, 'SITS_NDWI', 'sits_gate_passed', 'sits_tiles')
    return Route(full, 'SITS_NDWI', 'sits_gate_failed', 'sits_tiles')


def interim_route_area(c: Candidates) -> Route:
    """s1_interim: Track A S1 new water for every district, whatever Track B did."""
    if not c.aoi_matched:
        return Route(None, 'NONE', 'aoi_failed')
    s1 = _value(c.s1_km2)
    if s1 is None:
        return Route(None, 'NONE', 'no_s1')
    return Route(s1, 'S1', 'interim_s1_only', 'aoi')


def legacy_route_area(c: Candidates, spec=SPEC) -> Route:
    """The pre-refactor routing, verbatim (flood_spec.LEGACY_* vocabulary)."""
    if not c.aoi_matched:
        return Route(None, 'NONE', 'aoi_failed')
    s1, ndwi = _value(c.s1_km2), _value(c.ndwi_trackA_km2)
    cloud = _value(c.cloud_pct)
    too_cloudy = cloud is None or cloud >= spec.cloud_route_max_pct

    if c.sits_method is not None:
        full, gated = _value(c.sits_full_km2), _value(c.sits_gated_km2)
        if too_cloudy:
            if s1 is not None:
                return Route(s1, 'S1', 'cloud_routed_to_s1')
            return Route(None, 'NONE', 'no_measurement')
        if c.sits_method == 'ndwi-calib':
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


def load_sits_index(path=None) -> dict:
    """Track B index entries under the current spec, by analysis key."""
    path = path or SITS_INDEX_CSV
    if not os.path.exists(path):
        return {}
    frame = pd.read_csv(path, dtype=TEXT_DTYPES)
    stale = stale_spec_mask(frame)
    if stale.any():
        print(f"Ignored {int(stale.sum())} Track-B index rows not under {SPEC_VERSION}")
    return {analysis_key(r): r for _, r in frame.loc[~stale].iterrows()}


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


def track_b_status(key, index_entry=None, has_scores=False) -> tuple[str, str]:
    """(sits_status, reason) before the score archive is read."""
    h5_path = os.path.join(PATCH_DIR, f'{cache_stem(key)}.h5')
    if os.path.exists(h5_path + '.blocks.json'):
        return 'pending', 'track_b_incomplete'
    if has_scores:
        return 'ok', 'ok'
    if index_entry is None:
        return 'pending', 'track_b_not_run'
    status = str(index_entry.get('status', ''))
    reason = index_entry.get('reason')
    reason = None if reason is None or pd.isna(reason) else str(reason)
    if status == 'SKIPPED_NO_IMAGERY':
        return 'unavailable', reason or 'no_imagery'
    if status == 'OK':
        kept = _value(index_entry.get('kept_tiles'))
        if kept == 0:
            return 'unavailable', 'no_retained_tiles'
        return 'pending', 'inference_missing'
    return 'pending', 'track_b_error'


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
        'sits_usable_km2': float(archive['usable_km2'].sum()),
        'sits_s1_usable_km2': float(archive['s1_flood_km2'].sum()),
    }


def _round(value, digits=4):
    value = _value(value)
    return None if value is None else round(value, digits)


def _share(part, whole):
    part, whole = _value(part), _value(whole)
    return None if part is None or not whole else part / whole


def merge_row(a, archive=None, index_entry=None, converter=None, spec=SPEC,
              routing=DEFAULT_ROUTING) -> dict:
    if routing not in ROUTING_MODES:
        raise ValueError(f'routing must be one of {ROUTING_MODES}')
    key = analysis_key(a)
    aoi_matched = str(a.get('aoi_match_status', '')).strip().lower() in AOI_MATCHED
    status, reason = track_b_status(key, index_entry, archive is not None)
    sits = {}
    if archive is not None and aoi_matched and status == 'ok':
        validate_district_scores(archive, a)
        sits = _sits_candidates(archive, spec)
        if not sits:
            status, reason = 'unavailable', 'no_usable_pixels'
    s1 = _value(a.get('area_s1_km2'))
    eligible = _value(a.get('eligible_km2'))
    builtup_frac, cropland_frac = _share(a.get('builtup_km2'), eligible), _share(a.get('cropland_km2'), eligible)
    decision = converter.get('decision') if converter else None
    converted = None
    if converter and decision in CONVERTING_DECISIONS and s1 is not None:
        converted = s1_converter.convert(converter['model'], s1, builtup_frac, cropland_frac)
    s2_post = _value(a.get('s2_post_images'))
    candidates = Candidates(
        aoi_matched=aoi_matched,
        s1_km2=s1,
        ndwi_trackA_km2=_value(a.get('area_s2_km2')),
        sits_full_km2=sits.get('sits_ndwi_full_km2'),
        sits_gated_km2=sits.get('sits_ndwi_gated_km2'),
        sits_method=sits.get('sits_method'),
        cloud_pct=_value(a.get('cloud_pct')),
        s2_post_images=None if s2_post is None else int(s2_post),
        sits_status=status,
        sits_usable_km2=sits.get('sits_usable_km2'),
        sits_s1_usable_km2=sits.get('sits_s1_usable_km2'),
        eligible_km2=eligible,
        s1_converted_km2=converted,
        converter_decision=decision,
    )
    route = (route_area(candidates, spec) if routing == 'sits_primary'
             else interim_route_area(candidates))
    legacy = legacy_route_area(candidates, spec)
    optical = bool(sits) or (candidates.ndwi_trackA_km2 is not None and (candidates.s2_post_images or 0) > 0)
    measured = aoi_matched
    return {
        **{c: a.get(c) for c in ('event_district_id', 'event_id', 'source_record_id',
                                 'start_date', 'state', 'district', 'aoi_level',
                                 'aoi_source', 'aoi_match_status', 'geometry_id')},
        'combined_km2': _round(route.combined_km2),
        'satellite_source': route.satellite_source,
        'route_reason': route.route_reason,
        'routing_mode': routing,
        'optical_footprint': route.optical_footprint,
        'sits_status': status,
        'sits_reason': reason,
        'converter_decision': decision,
        's1_flood_km2': _round(s1) if measured else None,
        'ndwi_flood_km2': _round(candidates.ndwi_trackA_km2) if measured else None,
        'sits_ndwi_full_km2': _round(sits.get('sits_ndwi_full_km2')),
        'sits_ndwi_gated_km2': _round(sits.get('sits_ndwi_gated_km2')),
        'sits_detect_km2': _round(sits.get('sits_detect_km2')),
        'sits_footprint_km2': _round(sits.get('sits_footprint_km2')),
        'sits_usable_km2': _round(sits.get('sits_usable_km2')),
        'sits_usable_frac': _round(usable_fraction(candidates)),
        'sits_s1_usable_km2': _round(sits.get('sits_s1_usable_km2')),
        'sits_threshold': _round(sits.get('sits_threshold'), 3),
        'sits_method': sits.get('sits_method', 'no-sits'),
        'optical_available': optical and measured,
        'cloud_pct': candidates.cloud_pct,
        'optical_observed_frac': _value(a.get('optical_observed_frac')),
        'otsu_threshold_db': a.get('otsu_threshold_db'),
        'otsu_fallback_used': a.get('otsu_fallback_used'),
        's1_orbit': a.get('s1_orbit'),
        's1_post_images': a.get('s1_post_images'),
        's2_post_images': a.get('s2_post_images'),
        'eligible_km2': eligible,
        'builtup_km2': _value(a.get('builtup_km2')),
        'cropland_km2': _value(a.get('cropland_km2')),
        'aoi_area_km2': _value(a.get('aoi_area_km2')),
        'legacy_combined_km2': _round(legacy.combined_km2),
        'legacy_satellite_source': legacy.satellite_source,
        'legacy_route_reason': legacy.route_reason,
        'spec_version': SPEC_VERSION,
    }


def load_converter():
    try:
        converter = s1_converter.load()
    except s1_converter.ConverterUnavailable as exc:
        print(f"S1 -> SITS converter unavailable ({exc}); S1_TO_SITS rows stay NA "
              f"(converter_missing)")
        return None
    print(f"S1 -> SITS converter: decision {converter['decision']}")
    return converter


def main(routing=DEFAULT_ROUTING):
    if routing not in ROUTING_MODES:
        raise ValueError(f'routing must be one of {ROUTING_MODES}')
    print(f"Routing mode: {routing}")
    track_a = load_track_a()
    archives = _score_archives(track_a)
    index = load_sits_index()
    # The interim routing never converts, so it needs no converter artifact.
    converter = load_converter() if routing == 'sits_primary' else None
    rows = []
    for key in sorted(track_a):
        a = track_a[key]
        archive = np.load(archives[key], allow_pickle=False) if key in archives else None
        try:
            row = merge_row(a, archive, index.get(key), converter, routing=routing)
        finally:
            if archive is not None:
                archive.close()
        assert row['satellite_source'] in SATELLITE_SOURCES
        rows.append(row)
        c = row['combined_km2']
        print(f"  {key}: sits={row['sits_status']}/{row['sits_method']} "
              f"s1={row['s1_flood_km2']} -> combined={c} "
              f"({row['satellite_source']}, {row['route_reason']}); "
              f"legacy={row['legacy_combined_km2']} ({row['legacy_satellite_source']})")

    os.makedirs(os.path.dirname(OUT_CSV) or '.', exist_ok=True)
    pd.DataFrame(rows, columns=list(COMBINED_COLUMNS)).to_csv(OUT_CSV, index=False)
    print(f"\nSaved -> {OUT_CSV}  ({len(rows)} district rows, spec {SPEC_VERSION})")
    print("route_reason: " + ", ".join(f"{k}={v}" for k, v in
                                       Counter(r['route_reason'] for r in rows).most_common()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--routing', choices=ROUTING_MODES, default=DEFAULT_ROUTING)
    main(parser.parse_args().routing)
