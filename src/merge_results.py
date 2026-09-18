"""
merge_results.py — one district flood area on the SITS-NDWI scale.

This step is a pure function of tables. It reads measurements, it never makes
them: no Earth Engine, no model, no score archive, nothing written outside its
own --output. Re-routing the same measurements is therefore cheap and safe —
run it twice with two --routing values and compare the two files.

Inputs (all measured under flood_spec.SPEC; rows with another spec_version are
discarded, never reused):
  data/intermediate/event_districts.csv       (the registry: the row skeleton)
  data/cache/district/flood_extent.csv        (Track A: S1 + S2 NDWI, footprints)
  data/results/district_sits_measurements.csv (Track B: measured district values)
  data/cache/district/sits_patches_index.csv  (Track B patch status per district)
  data/intermediate/district_aoi.csv          (AOI identity for rows Track A lacks)
  data/results/s1_to_sits_converter.json      (compare_tracks.py decision)

Every registry row is written out. A stage that did not run is a status
(track_a_status / track_b_patch_status / sits_measure_status), never a missing
row: a district must not vanish from the output because one of its inputs is
absent. --recompute-from-npz re-derives the Track B values from the score
archives instead of reading the measurement table, for trying another gate
without re-running inference; it still writes nothing upstream.

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
  sits_then_track_a (default): SITS through the gate above for every district
      Track B measured with enough usable pixels; every other district is
      measured by s1_then_s2 instead of being left missing (route_reason
      track_a_sits_pending / _unavailable / _footprint_small). No converter.
  s1_then_s2: use Track A Sentinel-1 new water whenever it is
      observed, including zero. Only districts without an S1 observation use
      Track A Sentinel-2 NDWI; missing both remains missing.
  sits_primary: the SITS-first routing above.

Output: data/intermediate/district_flood_combined.csv (flood_spec.COMBINED_COLUMNS)
        or --output, to keep two routings side by side.
Run:    python src/merge_results.py [--routing sits_then_track_a|s1_then_s2|sits_primary]
                                    [--output PATH] [--recompute-from-npz]
        (numpy + pandas only; no model / GEE)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import sys
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import h5py

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1_converter  # noqa: E402
import sits_measure  # noqa: E402
from cvnd_layout import data_path  # noqa: E402
from district_keys import AOI_MATCHED, analysis_key, cache_stem, key_from_stem  # noqa: E402
from flood_spec import (COMBINED_COLUMNS, CONVERTING_DECISIONS,  # noqa: E402
                        DEFAULT_ROUTING, H5_LAYOUT_VERSION, ROUTING_MODES,
                        SATELLITE_SOURCES, SPEC, SPEC_VERSION, TEXT_DTYPES,
                        stale_spec_mask)
# The Track B aggregation has one implementation, in sits_measure: the merge and
# the measurement table must agree by construction, not by two copies staying in
# step. compare_tracks.py reaches for these names through this module.
from sits_measure import (_otsu, _youden,  # noqa: E402,F401
                          sits_candidates as _sits_candidates, sits_threshold)

SCORES_DIR = str(data_path("district_sits_scores"))
PATCH_DIR = str(data_path("district_sits_patches"))
TRACK_A_CSV = str(data_path("district_flood_extent"))
SITS_INDEX_CSV = str(data_path("district_sits_patches_index"))
MEASUREMENTS_CSV = str(data_path("district_sits_measurements"))
REGISTRY_CSV = str(data_path("event_districts"))
AOI_CSV = str(data_path("district_aoi"))
OUT_CSV = str(data_path("district_flood_combined"))
TILE_SELECTION_RULE = 'per_timestep_valid_fraction_v2'


def _text(archive, field):
    return str(np.asarray(archive[field]).item())


SCORE_VECTORS = ('ndwi_flood_km2', 'tile_area_km2', 'usable_px', 'usable_km2',
                 's1_flood_km2', 'block_id')


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_district_scores(archive, row, h5_path=None):
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
    if h5_path is not None:
        if not os.path.exists(h5_path):
            raise ValueError('SITS score archive has no current H5 input; rerun Track B')
        if _text(archive, 'patches_sha256') != _sha256_file(h5_path):
            raise ValueError('SITS score archive does not match the current H5 patches; rerun inference')
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


def s1_then_s2_route_area(c: Candidates) -> Route:
    """Prefer observed S1 (zero included), then use S2 NDWI as fallback."""
    if not c.aoi_matched:
        return Route(None, 'NONE', 'aoi_failed')
    s1 = _value(c.s1_km2)
    if s1 is not None:
        return Route(s1, 'S1', 's1_primary', 'aoi')
    ndwi = _value(c.ndwi_trackA_km2)
    if ndwi is not None and (c.s2_post_images or 0) > 0:
        return Route(ndwi, 'NDWI', 's2_fallback', 'aoi')
    return Route(None, 'NONE', 'no_s1_or_s2')


def sits_then_track_a_route_area(c: Candidates, spec=SPEC) -> Route:
    """SITS for every district Track B measured; Track A for the rest.

    Track B decides per district whether SITS is possible. A district it could
    not measure -- not run yet, no imagery / clear baseline / retained tile, or
    usable pixels below sits_usable_min_frac -- is measured by Track A (S1,
    then S2 NDWI) instead of being left missing. SITS rows go through
    route_area unchanged; route_reason on a Track A row says why SITS was not
    used, satellite_source says which Track A sensor measured it.
    """
    if not c.aoi_matched:
        return Route(None, 'NONE', 'aoi_failed')
    if c.sits_status == 'ok':
        frac = usable_fraction(c)
        if frac is None or frac >= spec.sits_usable_min_frac:
            return route_area(c, spec)
        why = 'track_a_sits_footprint_small'
    elif c.sits_status == 'unavailable':
        why = 'track_a_sits_unavailable'
    else:
        why = 'track_a_sits_pending'
    track_a = s1_then_s2_route_area(c)
    if track_a.satellite_source == 'NONE':
        return track_a
    return Route(track_a.combined_km2, track_a.satellite_source, why, track_a.optical_footprint)


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


def load_track_a(path=None, with_errors=False):
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
    error_keys = set(frame.loc[failed].apply(analysis_key, axis=1)) if failed.any() else set()
    if failed.any():
        print(f"Skipped {int(failed.sum())} Track-A ERROR rows; rerun Track A for them: "
              f"{sorted(error_keys)[:5]}")
        frame = frame.loc[~failed]
    rows = {}
    for _, r in frame.iterrows():
        key = analysis_key(r)
        if key in rows:
            raise ValueError(f'Track A contains duplicate analysis key {key}')
        rows[key] = r
    return (rows, error_keys) if with_errors else rows


def load_registry(path=None) -> dict:
    """The event-district registry: the row skeleton of the merged output.

    Every row here appears in the output, measured or not. Registry columns are
    identity only; AOI status in it is a pre-resolution placeholder and is never
    read as a match (build_flood_area_table.py drops it for the same reason).
    """
    path = path or REGISTRY_CSV
    if not os.path.exists(path):
        raise FileNotFoundError(
            f'{path} missing: run `src/build_emdat_events.py` first. The merge needs '
            f'the registry to know which districts exist, not only which were measured.')
    frame = pd.read_csv(path, dtype=TEXT_DTYPES)
    rows = {}
    for _, r in frame.iterrows():
        key = analysis_key(r)
        if key in rows:
            raise ValueError(f'Registry contains duplicate analysis key {key}')
        rows[key] = r
    return rows


def load_aoi(path=None) -> dict:
    """Resolved AOI identity per district, for rows Track A never reached."""
    path = path or AOI_CSV
    if not os.path.exists(path):
        return {}
    frame = pd.read_csv(path, dtype=TEXT_DTYPES)
    stale = stale_spec_mask(frame)
    if stale.any():
        print(f"Ignored {int(stale.sum())} AOI rows not resolved under {SPEC_VERSION}")
        frame = frame.loc[~stale]
    return {analysis_key(r): r for _, r in frame.iterrows()}


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


def load_sits_measurements(path=None) -> dict:
    """Track B measured values per district (sits_measure.MEASUREMENT_COLUMNS).

    This is the merge's only Track B measurement input. It exists so a re-merge
    needs neither the model nor the score archives: the expensive part has
    already been done and written down.
    """
    return sits_measure.load_measurements(path or MEASUREMENTS_CSV)


def _score_archives(track_a) -> dict:
    """Score archives that belong to a known district (--recompute-from-npz)."""
    archives = {key_from_stem(os.path.basename(f)[:-4]): f
                for f in glob.glob(os.path.join(SCORES_DIR, '*.npz'))}
    parents = {str(r.get('event_id')) for r in track_a.values()}
    result = {}
    for key, path in sorted(archives.items()):
        if key in track_a:
            h5_path = os.path.join(PATCH_DIR, f'{cache_stem(key)}.h5')
            if os.path.exists(h5_path):
                try:
                    with h5py.File(h5_path, 'r') as hdf:
                        attrs = hdf['meta'].attrs
                        bands = str(attrs.get('bands', '')).replace(' ', '')
                        rule = str(attrs.get('tile_selection_rule', ''))
                    if bands == 'B4,B3,B2' and rule != TILE_SELECTION_RULE:
                        print(f'WARN: ignoring {os.path.basename(path)}: stale Track-B tile pre-screen')
                        continue
                except (OSError, KeyError):
                    # The score archive's own H5 checksum/spec validation
                    # remains authoritative for legacy/test fixtures. Real
                    # production H5 files are readable and take the guard
                    # above; do not redefine unrelated archive validation.
                    pass
            result[key] = path
        elif key in parents:
            # A parent-event cache is not a district artifact. Never union it into
            # a district run where it could be mistaken for one district's score.
            print(f"WARN: ignoring parent-event score archive {os.path.basename(path)}")
        else:
            # Recorded, not fatal: a district whose Track A row is missing still
            # has a row in the output (track_a_status=not_run). Dying here would
            # throw away every other district's result over one stale archive.
            print(f"WARN: SITS scores {os.path.basename(path)} have no Track A row under "
                  f"{SPEC_VERSION}; not used for routing. Rerun Track A for {key}.")
    return result


def track_b_patch_status(key, index_entry=None) -> str:
    """What Track B's patch preparation did for this district.

    ok          patches prepared, or Track B concluded there is no imagery
    incomplete  a .blocks.json still sits beside the H5: the download can resume
    error       Track B raised for this district
    not_run     the Track B index has no entry for it
    """
    if os.path.exists(os.path.join(PATCH_DIR, f'{cache_stem(key)}.h5.blocks.json')):
        return 'incomplete'
    if index_entry is None:
        return 'not_run'
    status = str(index_entry.get('status', '')).strip()
    return 'ok' if status in ('OK', 'SKIPPED_NO_IMAGERY') else 'error'


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


def measurement_identity_error(measurement, reference) -> str | None:
    """Why a stored Track B row may not be used for this district, or None.

    The table-level analogue of validate_district_scores: a measurement must
    prove the district and geometry it claims. A mismatch is a provenance fault,
    not a missing stage, so the caller drops the measurement (and says so)
    instead of using it or killing the whole merge.
    """
    if reference is None:
        return None
    for field in ('event_district_id', 'event_id', 'source_record_id', 'state',
                  'district', 'start_date', 'geometry_id'):
        expected = reference.get(field)
        if expected is None or (isinstance(expected, float) and pd.isna(expected)):
            continue
        found = measurement.get(field)
        if str(found).strip() != str(expected).strip():
            return f'{field}: measured {found!r}, Track A has {expected!r}'
    return None


def _round(value, digits=4):
    value = _value(value)
    return None if value is None else round(value, digits)


def _share(part, whole):
    part, whole = _value(part), _value(whole)
    return None if part is None or not whole else part / whole


def _present(value) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except (TypeError, ValueError):
        return True


def _first(sources, name):
    for source in sources:
        if source is not None and _present(source.get(name)):
            return source.get(name)
    return None


def merge_row(identity, a=None, sits=None, index_entry=None, converter=None, spec=SPEC,
              routing=DEFAULT_ROUTING, aoi=None, track_a_status=None) -> dict:
    """Route one registry district. Pure: every input is an already-loaded row.

    identity  registry row (the skeleton; always present)
    a         Track A row, or None when Track A has no usable row
    sits      Track B area candidates: None = not measured, {} = measured with
              no usable pixel, else sits_measure.sits_candidates() output
    aoi       AOI table row, consulted only when Track A is absent
    """
    if routing not in ROUTING_MODES:
        raise ValueError(f'routing must be one of {ROUTING_MODES}')
    key = analysis_key(identity)
    # With a Track A row, its identity/AOI fields are used exactly as before, so
    # a stale Track A row still shows up downstream as an identity mismatch.
    # Without one, the resolved AOI table stands in; the registry's own
    # aoi_match_status is a placeholder and never counts as a match.
    sources = (a, identity) if a is not None else (aoi, identity)
    ta = a if a is not None else {}
    aoi_status = _first((a,) if a is not None else (aoi,), 'aoi_match_status')
    aoi_matched = str(aoi_status or '').strip().lower() in AOI_MATCHED
    sits_measured = sits is not None
    status, reason = track_b_status(key, index_entry, sits_measured)
    if sits_measured and aoi_matched and status == 'ok':
        if not sits:
            status, reason = 'unavailable', 'no_usable_pixels'
    else:
        sits = {}
    s1 = _value(ta.get('area_s1_km2'))
    eligible = _value(ta.get('eligible_km2'))
    builtup_frac, cropland_frac = _share(ta.get('builtup_km2'), eligible), _share(ta.get('cropland_km2'), eligible)
    decision = converter.get('decision') if converter else None
    converted = None
    if converter and decision in CONVERTING_DECISIONS and s1 is not None:
        converted = s1_converter.convert(converter['model'], s1, builtup_frac, cropland_frac)
    s2_post = _value(ta.get('s2_post_images'))
    candidates = Candidates(
        aoi_matched=aoi_matched,
        s1_km2=s1,
        ndwi_trackA_km2=_value(ta.get('area_s2_km2')),
        sits_full_km2=sits.get('sits_ndwi_full_km2'),
        sits_gated_km2=sits.get('sits_ndwi_gated_km2'),
        sits_method=sits.get('sits_method'),
        cloud_pct=_value(ta.get('cloud_pct')),
        s2_post_images=None if s2_post is None else int(s2_post),
        sits_status=status,
        sits_usable_km2=sits.get('sits_usable_km2'),
        sits_s1_usable_km2=sits.get('sits_s1_usable_km2'),
        eligible_km2=eligible,
        s1_converted_km2=converted,
        converter_decision=decision,
    )
    if routing == 'sits_primary':
        route = route_area(candidates, spec)
    elif routing == 'sits_then_track_a':
        route = sits_then_track_a_route_area(candidates, spec)
    else:
        route = s1_then_s2_route_area(candidates)
    legacy = legacy_route_area(candidates, spec)
    optical = bool(sits) or (candidates.ndwi_trackA_km2 is not None and (candidates.s2_post_images or 0) > 0)
    measured = aoi_matched
    if track_a_status is None:
        track_a_status = 'measured' if a is not None else 'not_run'
    return {
        **{c: _first(sources, c) for c in ('event_district_id', 'event_id', 'source_record_id',
                                           'start_date', 'state', 'district', 'aoi_level',
                                           'aoi_source')},
        'aoi_match_status': aoi_status,
        'geometry_id': _first(sources, 'geometry_id'),
        'combined_km2': _round(route.combined_km2),
        'satellite_source': route.satellite_source,
        'route_reason': route.route_reason,
        'routing_mode': routing,
        'optical_footprint': route.optical_footprint,
        'sits_status': status,
        'sits_reason': reason,
        'track_a_status': track_a_status,
        'track_b_patch_status': track_b_patch_status(key, index_entry),
        'sits_measure_status': 'measured' if sits_measured else 'not_run',
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
        'optical_observed_frac': _value(ta.get('optical_observed_frac')),
        'otsu_threshold_db': ta.get('otsu_threshold_db'),
        'otsu_fallback_used': ta.get('otsu_fallback_used'),
        's1_orbit': ta.get('s1_orbit'),
        's1_post_images': ta.get('s1_post_images'),
        's2_post_images': ta.get('s2_post_images'),
        'eligible_km2': eligible,
        'builtup_km2': _value(ta.get('builtup_km2')),
        'cropland_km2': _value(ta.get('cropland_km2')),
        'aoi_area_km2': _value(_first(sources, 'aoi_area_km2')),
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


def _h5_path(key):
    return os.path.join(PATCH_DIR, f'{cache_stem(key)}.h5')


def stale_tile_rule(bands, rule) -> bool:
    """An RGB-only H5 records TILE_SELECTION_RULE; one without the current rule
    was pre-screened under an older rule (the _score_archives guard)."""
    return (str(bands or '').replace(' ', '') == 'B4,B3,B2'
            and str(rule or '').strip() != TILE_SELECTION_RULE)


def measurement_staleness(row, key) -> str | None:
    """Why a stored measurement no longer describes the current Track B patches.

    The table-side counterpart of the archive checks: the row must come from a
    current tile pre-screen, and from the H5 now on disk when there is one. A
    removed H5 does not invalidate the row -- the table is the durable record.
    """
    if stale_tile_rule(row.get('bands'), row.get('tile_selection_rule')):
        return 'stale Track-B tile pre-screen'
    h5_path = _h5_path(key)
    if os.path.exists(h5_path) and str(row.get('patches_sha256')) != _sha256_file(h5_path):
        return 'measured on other patches than the current H5'
    return None


def _sits_from_table(measurements, track_a, registry=None) -> dict:
    """{key: candidates} from the measurement table; faulty rows are dropped."""
    registry = registry or {}
    result = {}
    for key, row in measurements.items():
        reference = track_a.get(key)
        problem = (measurement_identity_error(row, reference if reference is not None
                                              else registry.get(key))
                   or measurement_staleness(row, key))
        if problem:
            print(f"WARN: SITS measurement for {key} not used ({problem}); "
                  f"rerun run_sits_inference.py --events {key} --overwrite")
            continue
        result[key] = sits_measure.candidates_from_row(row)
    return result


def _sits_from_archives(track_a, spec=SPEC) -> dict:
    """{key: candidates} re-derived from the score archives (--recompute-from-npz)."""
    result = {}
    for key, path in _score_archives(track_a).items():
        with np.load(path, allow_pickle=False) as archive:
            # Scores must belong to the H5 currently on disk (stale after a
            # Track B re-download).
            validate_district_scores(archive, track_a[key], _h5_path(key))
            result[key] = _sits_candidates(archive, spec)
    return result


def main(routing=DEFAULT_ROUTING, output=None, recompute_from_npz=False):
    """Write one routed row per registry district to ``output``.

    Read-only on every input. The only file written is ``output`` (default
    OUT_CSV); Track A, the Track B measurement table, the index, the archives,
    the registry and the AOI table are never opened for writing.
    """
    if routing not in ROUTING_MODES:
        raise ValueError(f'routing must be one of {ROUTING_MODES}')
    output = str(output or OUT_CSV)
    print(f"Routing mode: {routing}")
    registry = load_registry()
    track_a, track_a_errors = load_track_a(with_errors=True)
    if recompute_from_npz:
        print(f"Track B values: recomputed from score archives in {SCORES_DIR}")
        sits_by_key = _sits_from_archives(track_a)
    else:
        print(f"Track B values: {MEASUREMENTS_CSV}")
        sits_by_key = _sits_from_table(load_sits_measurements(), track_a, registry)
    index = load_sits_index()
    aoi = load_aoi()
    # s1_then_s2 never converts, so it needs no converter artifact.
    converter = load_converter() if routing == 'sits_primary' else None

    for label, keys in (('Track A', set(track_a) | track_a_errors),
                        ('SITS measurement', set(sits_by_key))):
        outside = sorted(keys - set(registry))
        if outside:
            print(f"WARN: {len(outside)} {label} key(s) are not in the registry and have no "
                  f"output row; the registry changed since they were measured: {outside[:5]}")

    rows = []
    for key in sorted(registry):
        a = track_a.get(key)
        track_a_status = ('measured' if a is not None
                          else 'error' if key in track_a_errors else 'not_run')
        row = merge_row(registry[key], a, sits_by_key.get(key), index.get(key), converter,
                        routing=routing, aoi=aoi.get(key), track_a_status=track_a_status)
        assert row['satellite_source'] in SATELLITE_SOURCES
        rows.append(row)
        if row['satellite_source'] != 'NONE' or a is not None or key in sits_by_key:
            print(f"  {key}: A={track_a_status} B={row['track_b_patch_status']}/"
                  f"{row['sits_measure_status']} sits={row['sits_status']}/{row['sits_method']} "
                  f"s1={row['s1_flood_km2']} -> combined={row['combined_km2']} "
                  f"({row['satellite_source']}, {row['route_reason']}); "
                  f"legacy={row['legacy_combined_km2']} ({row['legacy_satellite_source']})")

    frame = pd.DataFrame(rows, columns=list(COMBINED_COLUMNS))
    # Rows without Track A leave blanks in these count columns; keep them integers
    # ("8", not "8.0") as they were when every row came from Track A.
    for column in ('s1_post_images', 's2_post_images'):
        frame[column] = pd.to_numeric(frame[column], errors='coerce').round().astype('Int64')
    os.makedirs(os.path.dirname(output) or '.', exist_ok=True)
    frame.to_csv(output, index=False)
    print(f"\nSaved -> {output}  ({len(rows)} registry rows, spec {SPEC_VERSION})")
    for column in ('track_a_status', 'track_b_patch_status', 'sits_measure_status',
                   'satellite_source', 'route_reason'):
        print(f"{column}: " + ", ".join(f"{k}={v}" for k, v in
                                        Counter(r[column] for r in rows).most_common()))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--routing', choices=ROUTING_MODES, default=DEFAULT_ROUTING)
    parser.add_argument('--output', default=None,
                        help=f'merged CSV to write (default: {OUT_CSV}); give each routing '
                             f'its own file to compare them')
    parser.add_argument('--recompute-from-npz', action='store_true',
                        help='re-derive Track B values from the score archives instead of '
                             'reading the measurement table (writes nothing upstream)')
    args = parser.parse_args()
    main(args.routing, args.output, args.recompute_from_npz)
