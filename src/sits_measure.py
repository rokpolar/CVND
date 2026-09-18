"""Track B (SITS) district measurements: the aggregation and its own table.

The score archives under ``data/cache/district/sits_scores/*.npz`` hold per-tile
detail (one score and one area per 64x64 tile). This module turns one archive
into the district-level numbers the merge routes on, and stores them as one CSV
row per district in ``data/results/district_sits_measurements.csv``.

That table is the point: a Track B measurement costs hours of download and
inference, and it used to exist only inside the NPZ binaries, recomputed by
merge_results on every run. With the table, the merge reads measured values and
never needs the model, Earth Engine or the archives; deleting the archives costs
the per-tile detail, not the measurement.

Writes are row-wise upserts keyed by ``district_keys.analysis_key``: re-inferring
one district replaces that district's row and leaves every other row untouched
(the ``satellite.write_sits_index`` pattern, made incremental).

Producer: ``run_sits_inference.py`` (writes one row per scored district).
Consumers: ``merge_results.py`` (reads only), ``compare_tracks.py`` (reads the
archives directly, because it needs the per-tile detail).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cvnd_layout import data_path  # noqa: E402
from district_keys import analysis_key  # noqa: E402
from flood_spec import (H5_LAYOUT_VERSION, SPEC, SPEC_VERSION,  # noqa: E402
                        TEXT_DTYPES, otsu_from_histogram, stale_spec_mask)

MEASUREMENT_CSV = str(data_path("district_sits_measurements"))

IDENTITY_COLUMNS = ('event_district_id', 'event_id', 'source_record_id', 'state',
                    'district', 'start_date', 'geometry_id')
# Every number _sits_candidates() derives from one archive, so the merge can be
# reproduced from this table alone.
VALUE_COLUMNS = ('sits_ndwi_full_km2', 'sits_ndwi_gated_km2', 'sits_detect_km2',
                 'sits_footprint_km2', 'sits_usable_km2', 'sits_s1_usable_km2',
                 'sits_threshold')
PROVENANCE_COLUMNS = ('spec_version', 'layout_version', 'model_id',
                      'checkpoint_sha256', 'patches_sha256', 'upstream_commit',
                      # From the H5 meta: lets the merge reject a stale tile
                      # pre-screen (satellite.TILE_SELECTION_RULE) without the H5.
                      'bands', 'tile_selection_rule')
MEASUREMENT_COLUMNS = (IDENTITY_COLUMNS + VALUE_COLUMNS
                       + ('sits_method', 'n_tiles') + PROVENANCE_COLUMNS)
# Hashes and version strings must never be parsed as numbers.
MEASUREMENT_DTYPES = {**TEXT_DTYPES,
                      **{column: str for column in PROVENANCE_COLUMNS + ('sits_method',)}}


# ── aggregation ───────────────────────────────────────────────────────────────

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


def sits_candidates(archive, spec=SPEC) -> dict:
    """Area candidates from one validated score archive; empty dict = no usable tiles.

    ``archive`` is an ``np.load`` NPZ or any mapping of the same arrays, so
    run_sits_inference can measure the payload it is about to save without
    reading it back.
    """
    scores = np.asarray(archive['scores'])
    if len(scores) == 0 or float(np.asarray(archive['usable_px']).sum()) == 0:
        return {}
    thr, method = sits_threshold(scores, np.asarray(archive['ndwi_flood']), spec)
    flagged = scores > thr
    flood_km2 = np.asarray(archive['ndwi_flood_km2'])
    tile_km2 = np.asarray(archive['tile_area_km2'])
    return {
        'sits_threshold': thr, 'sits_method': method,
        'sits_ndwi_full_km2': float(flood_km2.sum()),
        'sits_ndwi_gated_km2': float(flood_km2[flagged].sum()),
        # Flagged-tile extent is NOT a water area; kept for reference only.
        'sits_detect_km2': float(tile_km2[flagged].sum()),
        'sits_footprint_km2': float(tile_km2.sum()),
        'sits_usable_km2': float(np.asarray(archive['usable_km2']).sum()),
        'sits_s1_usable_km2': float(np.asarray(archive['s1_flood_km2']).sum()),
    }


# ── one measured district as a table row ──────────────────────────────────────

def archive_text(archive, field: str, default: str = '') -> str:
    """Read a 0-d string field from an NPZ archive or a plain payload mapping."""
    try:
        value = archive[field]
    except (KeyError, IndexError):
        return default
    if value is None:
        return default
    array = np.asarray(value)
    return str(array.item()) if array.shape == () else str(value)


def measurement_row(archive, spec=SPEC, provenance=None) -> dict:
    """One CSV row for a scored district: identity, measurement and provenance.

    A district whose tiles carry no usable pixel is still a measurement: the row
    is written with an empty ``sits_method`` and no values, which the merge reads
    back as 'unavailable / no_usable_pixels' exactly as it read an empty archive.
    ``provenance`` supplies fields the archive does not carry (the H5 ``bands``
    and ``tile_selection_rule``).
    """
    values = sits_candidates(archive, spec)
    row = {column: archive_text(archive, column) for column in IDENTITY_COLUMNS}
    row.update({column: values.get(column) for column in VALUE_COLUMNS})
    row['sits_method'] = values.get('sits_method', '')
    row['n_tiles'] = int(len(np.asarray(archive['scores'])))
    row.update({column: archive_text(archive, column) for column in PROVENANCE_COLUMNS})
    if not row['checkpoint_sha256']:
        row['checkpoint_sha256'] = archive_text(archive, 'weights_sha256')
    row.update({k: v for k, v in (provenance or {}).items() if k in PROVENANCE_COLUMNS and v})
    return {column: row.get(column) for column in MEASUREMENT_COLUMNS}


def _float(value):
    if value is None:
        return None
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None


def candidates_from_row(row) -> dict:
    """The merge's area candidates from one stored row; empty dict = not measurable.

    Must agree with ``sits_candidates`` on the same district: this is what makes
    a re-merge from the table identical to a re-merge from the archives.
    """
    method = str(row.get('sits_method') or '').strip()
    if not method or method.lower() in ('nan', 'none'):
        return {}
    values = {column: _float(row.get(column)) for column in VALUE_COLUMNS}
    if values['sits_ndwi_full_km2'] is None or values['sits_usable_km2'] is None:
        return {}
    return {**values, 'sits_method': method}


# ── table IO ──────────────────────────────────────────────────────────────────

def _read_table(path) -> pd.DataFrame:
    # round_trip: the default parser can return 1.8314999999999997 for a stored
    # 1.8315, and routing compares these values against thresholds.
    frame = pd.read_csv(path, dtype=MEASUREMENT_DTYPES, float_precision='round_trip')
    return frame.reindex(columns=list(MEASUREMENT_COLUMNS))


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [c for c in ('event_district_id', 'event_id') if c in frame.columns]
    if columns and len(frame):
        frame = frame.sort_values(columns, na_position='last')
    return frame.reset_index(drop=True)


def upsert_measurements(rows, path=None) -> pd.DataFrame:
    """Replace the rows of the given districts; keep every other row verbatim.

    One district may be re-inferred at any time (a fixed download, a rerun after
    a crash) without putting the other districts' hours of measurement at risk.
    """
    path = Path(path or MEASUREMENT_CSV)
    incoming = pd.DataFrame(list(rows), columns=list(MEASUREMENT_COLUMNS))
    if path.exists():
        existing = _read_table(path)
        if len(existing) and len(incoming):
            replaced = set(incoming.apply(analysis_key, axis=1))
            existing = existing.loc[~existing.apply(analysis_key, axis=1).isin(replaced)]
        frame = pd.concat([existing, incoming], ignore_index=True)
    else:
        frame = incoming
    # A blank anywhere would otherwise turn the whole column into floats ("12.0").
    frame['n_tiles'] = pd.to_numeric(frame['n_tiles'], errors='coerce').round().astype('Int64')
    frame = _sorted(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)
    return frame


def load_measurements(path=None, expected_layout: str = H5_LAYOUT_VERSION) -> dict:
    """Measured districts under the current spec and H5 layout, by analysis key."""
    path = str(path or MEASUREMENT_CSV)
    if not os.path.exists(path):
        return {}
    frame = _read_table(path)
    stale = stale_spec_mask(frame)
    if stale.any():
        print(f"Ignored {int(stale.sum())} SITS measurement rows not under {SPEC_VERSION}; "
              f"rerun run_sits_inference.py for them")
        frame = frame.loc[~stale]
    layout = frame['layout_version'].astype('string').str.strip().ne(expected_layout).fillna(True)
    if layout.any():
        print(f"Ignored {int(layout.sum())} SITS measurement rows not on H5 layout "
              f"{expected_layout}")
        frame = frame.loc[~layout]
    rows = {}
    for _, row in frame.iterrows():
        key = analysis_key(row)
        if key in rows:
            raise ValueError(f'{path} contains duplicate analysis key {key}')
        rows[key] = row
    return rows
