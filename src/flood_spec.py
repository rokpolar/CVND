"""One measurement specification for every satellite flood-area number.

Every flood area written by Track A (S1 / S2 NDWI), Track B (SITS tiles) and the
merge is produced under the single ``SPEC`` below: the same post/pre windows,
composites, eligibility mask, reduction scale and pixel-area method. Its hash,
``SPEC_VERSION``, is stored on every cached row, H5 file and score archive, so
changing any field invalidates all satellite caches by design.

This module is pure Python (no Earth Engine import) so offline steps, the
preflight audit and tests can share the contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from cvnd_config import PRIMARY_MEDIA_WINDOW_DAYS

POST_COMPOSITES = ('max_water', 'median')


@dataclass(frozen=True)
class MeasurementSpec:
    # Windows are half-open: post [onset, onset + post), pre [onset - pre, onset).
    post_window_days: int = PRIMARY_MEDIA_WINDOW_DAYS
    pre_window_days: int = 30
    pre_composite: str = 'median'
    # max_water: per-pixel extreme (S1 VV min, NDWI max) = flood maximum extent.
    post_composite: str = 'max_water'
    reduce_scale_m: int = 10
    qa_scale_m: int = 100            # ratios only (cloud fraction, baseline QA)
    max_pixels: float = 1e10
    tile_scale: int = 4
    area_method: str = 'pixelArea'
    ndwi_bands: tuple = ('B3', 'B8')
    ndwi_water_gt: float = 0.0
    s2_collection: str = 'COPERNICUS/S2_SR_HARMONIZED'
    s2_cloudy_pixel_pct_max: float = 80
    s2_scl_exclude: tuple = (3, 8, 9, 10, 11)
    s1_collection: str = 'COPERNICUS/S1_GRD'
    s1_orbits: tuple = ('ASCENDING', 'DESCENDING')
    s1_speckle_radius_px: int = 1
    otsu_lo_db: float = -20.0
    otsu_hi_db: float = -13.0
    otsu_fallback_db: float = -16.0
    otsu_bins: int = 255
    otsu_bucket_db: float = 0.5
    jrc_asset: str = 'JRC/GSW1_4/GlobalSurfaceWater'
    jrc_permanent_occurrence_gte: int = 50
    srtm_asset: str = 'USGS/SRTMGL1_003'
    slope_max_deg: float = 5.0
    lsib_asset: str = 'USDOS/LSIB_SIMPLE/2017'
    lsib_country: str = 'India'
    cloud_route_max_pct: float = 60.0
    sits_pixel_m: int = 10
    sits_patch_px: int = 64
    sits_keep_valid: float = 0.70
    sits_flood_min_frac: float = 0.05
    sits_min_pos: int = 20
    sits_j_min: float = 0.15
    sits_n_pre: int = 4
    aoi_max_error_m: float = 1000
    gaul_level2: str = 'FAO/GAUL/2015/level2'

    def __post_init__(self):
        # SITS tiles are counted on a fixed 10 m grid. Only at the same reduce
        # scale are a pixelArea sum and a tile pixel count the same sum; a
        # coarser Track A scale would make SITS-NDWI incomparable.
        if self.reduce_scale_m != self.sits_pixel_m:
            raise ValueError(
                f'reduce_scale_m={self.reduce_scale_m} differs from the SITS grid '
                f'({self.sits_pixel_m} m); SITS-NDWI areas would not be comparable'
            )
        if self.post_composite not in POST_COMPOSITES:
            raise ValueError(f'post_composite must be one of {POST_COMPOSITES}')
        if self.pre_composite != 'median':
            raise ValueError("pre_composite must be 'median'")
        if self.area_method != 'pixelArea':
            raise ValueError("area_method must be 'pixelArea'")
        if self.post_window_days <= 0 or self.pre_window_days <= 0:
            raise ValueError('measurement windows must be positive')

    @property
    def sits_patch_pixels(self) -> int:
        return self.sits_patch_px * self.sits_patch_px


def spec_version(spec: MeasurementSpec) -> str:
    payload = json.dumps(asdict(spec), sort_keys=True)
    return 'fs1-' + hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]


SPEC = MeasurementSpec()
SPEC_VERSION = spec_version(SPEC)

# Closed vocabularies. SITS_NDWI is NDWI measured on the retained clear SITS
# tiles only; NDWI is Track A NDWI over the whole district AOI.
SATELLITE_SOURCES = ('S1', 'NDWI', 'SITS_NDWI', 'SITS_NDWI_RESTORED', 'NONE')
MEASURED_SOURCES = SATELLITE_SOURCES[:-1]
ROUTE_REASONS = (
    'sits_gate_passed', 'sits_restored_by_s1', 'sits_gate_failed',
    'cloud_routed_to_s1', 'no_optical_s1', 'no_s1_ndwi', 'no_measurement',
    'aoi_failed',
)
OPTICAL_FOOTPRINTS = ('aoi', 'sits_tiles')

# Column contracts shared by the Earth Engine producers and offline consumers.
IDENTITY_COLUMNS = (
    'event_district_id', 'event_id', 'source_record_id', 'start_date', 'state',
    'district',
)
AOI_COLUMNS = ('aoi_level', 'aoi_source', 'aoi_match_status', 'geometry_id', 'aoi_area_km2')
# Read these as text from CSV: a numeric geometry_id with NaNs would otherwise
# come back as "17598.0" and stop matching H5/NPZ provenance.
TEXT_DTYPES = {column: str for column in IDENTITY_COLUMNS + ('geometry_id', 'spec_version')}
TRACK_A_COLUMNS = (
    'area_s1_km2', 'area_s2_km2', 'ndwi_pre_water_km2', 'ndwi_during_water_km2',
    's1_pre_images', 's1_post_images', 's2_pre_images', 's2_post_images',
    'cloud_pct', 'otsu_threshold_db', 'otsu_fallback_used', 'otsu_separability',
    's1_orbit', 'baseline_status', 'spec_version',
)
COMBINED_COLUMNS = IDENTITY_COLUMNS + AOI_COLUMNS[:-1] + (
    'combined_km2', 'satellite_source', 'route_reason', 'optical_footprint',
    's1_flood_km2', 'ndwi_flood_km2', 'sits_ndwi_full_km2', 'sits_ndwi_gated_km2',
    'sits_detect_km2', 'sits_footprint_km2', 'sits_threshold', 'sits_method',
    'optical_available', 'cloud_pct', 'otsu_threshold_db', 'otsu_fallback_used',
    's1_orbit', 's1_post_images', 's2_post_images', 'aoi_area_km2', 'spec_version',
)
FLOOD_AREA_COLUMNS = IDENTITY_COLUMNS + (
    'flood_area_km2', 'flood_ratio', 'aoi_area_km2', 'satellite_source',
    'satellite_status', 'district_match_status', 'geometry_id', 'aoi_match_status',
    'analysis_observation_status', 'route_reason', 'cloud_pct',
    'otsu_fallback_used', 's1_orbit', 'spec_version',
)


def otsu_from_histogram(counts, centers) -> tuple[float | None, float]:
    """Return (Otsu threshold, separability) for a histogram.

    The threshold is the upper bucket centre of the lower class; separability is
    between-class variance over total variance. A degenerate histogram (empty or
    a single occupied bucket) has no threshold.
    """
    counts = np.asarray(counts, dtype=float)
    centers = np.asarray(centers, dtype=float)
    total = counts.sum()
    if counts.size == 0 or total <= 0:
        return None, 0.0
    mean = (counts * centers).sum() / total
    total_var = (counts * (centers - mean) ** 2).sum() / total
    if total_var <= 0:
        return None, 0.0
    w0 = np.cumsum(counts) / total
    w1 = 1.0 - w0
    sum0 = np.cumsum(counts * centers) / total
    with np.errstate(divide='ignore', invalid='ignore'):
        mu0 = sum0 / w0
        mu1 = (mean - sum0) / w1
        between = w0 * w1 * (mu0 - mu1) ** 2
    between = np.where((w0 > 0) & (w1 > 1e-12), between, 0.0)
    best = int(np.argmax(between))
    if between[best] <= 0:
        return None, 0.0
    return float(centers[best]), float(between[best] / total_var)


def stale_spec_mask(frame):
    """True for rows whose spec_version is missing or differs from SPEC_VERSION."""
    if 'spec_version' not in frame.columns:
        return pd.Series(True, index=frame.index)
    return frame['spec_version'].astype('string').str.strip().ne(SPEC_VERSION).fillna(True)


def require_spec(frame, label: str) -> None:
    if 'spec_version' not in frame.columns:
        raise ValueError(
            f'{label} has no spec_version; regenerate it under {SPEC_VERSION}'
        )
    stale = stale_spec_mask(frame)
    if stale.any():
        found = sorted({str(v) for v in frame.loc[stale, 'spec_version']})[:3]
        raise ValueError(
            f'{label}: {int(stale.sum())} rows measured under another spec '
            f'{found}; expected {SPEC_VERSION}. Regenerate satellite caches.'
        )
