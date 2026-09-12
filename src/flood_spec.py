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
from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

from cvnd_config import PRIMARY_MEDIA_WINDOW_DAYS

POST_COMPOSITES = ('max_water', 'median')
PRE_REFERENCES = ('pre30d', 'same_season_3y')
WATER_INDICES = ('ndwi', 'mndwi')
GRID_CRSS = ('utm',)
# Storage layout of Track B HDF5 files, checked by run_sits_inference. Not part
# of the measurement hash: it changes when datasets are added, not definitions.
H5_LAYOUT_VERSION = 'h5-2'


@dataclass(frozen=True)
class MeasurementSpec:
    # Windows are half-open: post [onset, onset + post), pre [onset - pre, onset).
    post_window_days: int = PRIMARY_MEDIA_WINDOW_DAYS
    pre_window_days: int = 30
    pre_composite: str = 'median'
    # pre30d: the pre window above. same_season_3y (sensitivity variant, B2):
    # the post window's calendar days in each of the previous years, so
    # recurring seasonal water (paddies, monsoon wetlands) is not new water.
    pre_reference: str = 'pre30d'
    pre_reference_years: int = 3
    # max_water: per-pixel extreme (S1 VV min, NDWI max) = flood maximum extent.
    post_composite: str = 'max_water'
    reduce_scale_m: int = 10
    qa_scale_m: int = 100            # baseline month QA ratios only
    # Every reduction and download uses one pixel grid per district: the UTM
    # zone of the AOI centroid, pixels snapped to multiples of sits_pixel_m.
    grid_crs: str = 'utm'
    max_pixels: float = 1e10
    tile_scale: int = 4
    # A whole-AOI reduction that exceeds Earth Engine limits is summed over
    # grid-aligned sub-rectangles of this side (same pixels, same scale).
    reduce_split_m: int = 40960
    area_method: str = 'pixelArea'
    # ndwi = McFeeters (B3, B8); mndwi (sensitivity variant, B3) = (B3, B11).
    water_index: str = 'ndwi'
    ndwi_bands: tuple = ('B3', 'B8')
    mndwi_bands: tuple = ('B3', 'B11')
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
    # Fixed-range histogram: bucket edges do not depend on the region, so
    # histograms of sub-rectangles add up to the whole-AOI histogram.
    otsu_hist_min_db: float = -35.0
    otsu_hist_max_db: float = 5.0
    otsu_bucket_db: float = 0.5
    jrc_asset: str = 'JRC/GSW1_4/GlobalSurfaceWater'
    jrc_permanent_occurrence_gte: int = 50
    srtm_asset: str = 'USGS/SRTMGL1_003'
    slope_max_deg: float = 5.0
    lsib_asset: str = 'USDOS/LSIB_SIMPLE/2017'
    lsib_country: str = 'India'
    # ESA WorldCover (2021) strata for the paired comparison; static cover.
    worldcover_asset: str = 'ESA/WorldCover/v200'
    worldcover_builtup: int = 50
    worldcover_cropland: int = 40
    cloud_route_max_pct: float = 60.0   # legacy routing only
    sits_pixel_m: int = 10
    sits_patch_px: int = 64
    sits_keep_valid: float = 0.70
    sits_flood_min_frac: float = 0.05
    sits_min_pos: int = 20
    sits_j_min: float = 0.15
    sits_youden_steps: int = 60         # score quantiles 0.02..0.98 tried by the gate
    sits_score_otsu_bins: int = 64
    # Restore all retained tiles when gating kept less than this share of the
    # water AND S1 on the same usable pixels confirms the larger extent.
    sits_restore_gated_frac: float = 0.5
    # A SITS district whose usable pixels cover less than this share of the
    # eligible AOI is too cloudy to stand for the district -> S1_TO_SITS.
    sits_usable_min_frac: float = 0.4
    sits_n_pre: int = 4
    # Baseline t1..t4: same month ±1 over the previous years, then the event
    # year's earlier months; a month qualifies at this AOI clear fraction.
    sits_baseline_years: int = 3
    sits_baseline_min_clear: float = 0.5
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
        if self.pre_reference not in PRE_REFERENCES:
            raise ValueError(f'pre_reference must be one of {PRE_REFERENCES}')
        if self.water_index not in WATER_INDICES:
            raise ValueError(f'water_index must be one of {WATER_INDICES}')
        if self.grid_crs not in GRID_CRSS:
            raise ValueError(f'grid_crs must be one of {GRID_CRSS}')
        if self.area_method != 'pixelArea':
            raise ValueError("area_method must be 'pixelArea'")
        if self.post_window_days <= 0 or self.pre_window_days <= 0:
            raise ValueError('measurement windows must be positive')
        tile_m = self.sits_patch_px * self.sits_pixel_m
        if self.reduce_split_m % tile_m:
            raise ValueError(f'reduce_split_m must be a multiple of the {tile_m} m tile')

    @property
    def sits_patch_pixels(self) -> int:
        return self.sits_patch_px * self.sits_patch_px

    @property
    def water_bands(self) -> tuple:
        return self.ndwi_bands if self.water_index == 'ndwi' else self.mndwi_bands

    @property
    def otsu_buckets(self) -> int:
        return int(round((self.otsu_hist_max_db - self.otsu_hist_min_db) / self.otsu_bucket_db))


def spec_version(spec: MeasurementSpec) -> str:
    payload = json.dumps(asdict(spec), sort_keys=True)
    return 'fs1-' + hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]


SPEC = MeasurementSpec()
SPEC_VERSION = spec_version(SPEC)


@dataclass(frozen=True)
class ConverterRules:
    """Pre-registered S1 -> SITS-NDWI converter decision rules.

    Fixed before any paired data is examined; not part of SPEC (they decide
    how measurements are combined, not how they are made) and hashed on their
    own into every converter artifact.
    """
    min_districts: int = 30          # paired districts with A_ndwi(C) >= min_area_km2
    min_states: int = 5
    min_area_km2: float = 1.0
    equivalence_ratio: float = 1.2   # TOST bounds on the median log ratio: ±log(1.2)
    heterogeneity_p: float = 0.10    # joint Wald test on r_d covariates
    iou_min: float = 0.5
    cv_tolerance_ratio: float = 1.25  # stratified converter: median |log error| <= log(1.25)
    deming_slope_ci_max_width: float = 0.5   # "narrow" Deming slope CI for a linear converter
    identity_tolerance: float = 0.01  # |A_ndwi - A_blocks| / max(A_ndwi, 1 km²)
    alpha: float = 0.05
    log_offset_km2: float = 0.1      # r_d = log((A_s1 + o) / (A_target + o))
    # The SITS-NDWI scale S1 is converted to: sits_route = the value the SITS
    # path reports on C (gated / restored / full); ndwi_full = all NDWI new
    # water on C. Both are reported; this one decides.
    target: str = 'sits_route'
    wald_cluster_min_states: int = 20   # CR1 by state from here, HC1 below
    bootstrap_reps: int = 2000
    seed: int = 20260911


CONVERTER_RULES = ConverterRules()
CONVERTER_RULES_VERSION = 'cr1-' + hashlib.sha256(
    json.dumps(asdict(CONVERTER_RULES), sort_keys=True).encode('utf-8')).hexdigest()[:12]

# Sensitivity variants of the measurement (Track A only; never the primary).
SPEC_VARIANTS = {
    # B2: seasonal water is not new water
    'pre_same_season_3y': {'pre_reference': 'same_season_3y'},
    'jrc_seasonal_10': {'jrc_permanent_occurrence_gte': 10},
    # B3: optical built-up false positives
    'mndwi': {'water_index': 'mndwi'},
}


def variant_spec(name: str) -> MeasurementSpec:
    if name not in SPEC_VARIANTS:
        raise KeyError(f'unknown spec variant {name!r}; known: {sorted(SPEC_VARIANTS)}')
    return replace(SPEC, **SPEC_VARIANTS[name])


# Closed vocabularies. SITS is the primary measurement: SITS_NDWI is NDWI new
# water on the retained clear SITS tiles; S1_TO_SITS is Sentinel-1 new water
# over the eligible AOI converted to the SITS-NDWI scale for districts SITS
# cannot measure. A district whose Track B has not finished is missing, never
# silently measured by another sensor.
#
# Routing modes. sits_primary is the design above; it needs Track B for every
# district and the converter. s1_interim measures every district with Track A
# Sentinel-1 new water alone (one sensor, no SITS, no conversion) until those
# exist; its source label is 'S1'.
ROUTING_MODES = ('s1_interim', 'sits_primary')
DEFAULT_ROUTING = 's1_interim'
SATELLITE_SOURCES = ('SITS_NDWI', 'SITS_NDWI_RESTORED', 'S1_TO_SITS', 'S1', 'NONE')
MEASURED_SOURCES = SATELLITE_SOURCES[:-1]
SITS_SOURCES = ('SITS_NDWI', 'SITS_NDWI_RESTORED')
ROUTE_REASONS = (
    'sits_gate_passed', 'sits_restored_by_s1', 'sits_gate_failed',
    'sits_footprint_small', 'sits_footprint_small_excluded',
    'sits_unavailable_converted', 'sits_unavailable_excluded',
    'sits_pending', 'converter_missing', 'interim_s1_only', 'no_s1', 'aoi_failed',
)
SITS_STATUSES = ('ok', 'unavailable', 'pending')
CONVERTER_DECISIONS = ('identity', 'linear', 'stratified', 'excluded', 'insufficient')
CONVERTING_DECISIONS = ('identity', 'linear', 'stratified')
OPTICAL_FOOTPRINTS = ('aoi', 'sits_tiles')
# The pre-refactor routing, kept verbatim for the before/after comparison.
LEGACY_SATELLITE_SOURCES = ('S1', 'NDWI', 'SITS_NDWI', 'SITS_NDWI_RESTORED', 'NONE')
LEGACY_ROUTE_REASONS = (
    'sits_gate_passed', 'sits_restored_by_s1', 'sits_gate_failed',
    'cloud_routed_to_s1', 'no_optical_s1', 'no_s1_ndwi', 'no_measurement',
    'aoi_failed',
)

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
    's1_orbit',
    # Footprints on the measurement grid. optical_observed = eligible and seen
    # by S2 in both the pre and the post composite: the only pixels where
    # area_s2_km2 can be nonzero, so S1 restricted to it is S1's paired value.
    'grid_crs', 'grid_aoi_km2', 'eligible_km2', 'optical_observed_km2',
    'optical_observed_frac', 's1_on_optical_km2', 's1_ndwi_both_km2',
    'builtup_km2', 'cropland_km2', 's1_builtup_km2', 'ndwi_builtup_km2',
    'first_post_date_s1', 'first_post_date_s2',
    'error_kind', 'baseline_status', 'spec_version',
)
COMBINED_COLUMNS = IDENTITY_COLUMNS + AOI_COLUMNS[:-1] + (
    'combined_km2', 'satellite_source', 'route_reason', 'routing_mode', 'optical_footprint',
    'sits_status', 'sits_reason', 'converter_decision',
    's1_flood_km2', 'ndwi_flood_km2', 'sits_ndwi_full_km2', 'sits_ndwi_gated_km2',
    'sits_detect_km2', 'sits_footprint_km2', 'sits_usable_km2', 'sits_usable_frac',
    'sits_s1_usable_km2', 'sits_threshold', 'sits_method',
    'optical_available', 'cloud_pct', 'optical_observed_frac', 'otsu_threshold_db',
    'otsu_fallback_used', 's1_orbit', 's1_post_images', 's2_post_images',
    'eligible_km2', 'builtup_km2', 'cropland_km2', 'aoi_area_km2',
    'legacy_combined_km2', 'legacy_satellite_source', 'legacy_route_reason',
    'spec_version',
)
FLOOD_AREA_COLUMNS = IDENTITY_COLUMNS + (
    'flood_area_km2', 'flood_ratio', 'aoi_area_km2', 'satellite_source',
    'satellite_status', 'district_match_status', 'geometry_id', 'aoi_match_status',
    'analysis_observation_status', 'route_reason', 'cloud_pct',
    'otsu_fallback_used', 's1_orbit',
    # flood_ratio keeps the AOI denominator; this one excludes permanent
    # water, steep slopes and area outside India, where nothing is measured.
    'eligible_km2', 'flood_ratio_eligible', 'sits_status', 'converter_decision',
    'legacy_flood_area_km2', 'legacy_satellite_source', 'spec_version',
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


def ndwi_new_water(pre, post, nodata, scale, spec=SPEC):
    """Per-pixel NDWI new water on downloaded ×scale layers: observed pre and
    post, water after, not water before (eligibility is applied by callers)."""
    cut = spec.ndwi_water_gt * scale
    observed = (pre != nodata) & (post != nodata)
    return observed & (post > cut) & (pre <= cut), observed


def s1_new_water(pre, post, nodata, scale, threshold_db):
    """Per-pixel S1 new water on downloaded dB ×scale layers: observed pre and
    post, dark after, not dark before. A pixel missing either composite is not
    new water, as in Track A where the masked comparison is unmasked to 0."""
    if threshold_db is None or not np.isfinite(threshold_db):
        return np.zeros(np.shape(pre), dtype=bool)
    observed = (pre != nodata) & (post != nodata)
    post_dark = post.astype(np.float64) / scale < threshold_db
    pre_dark = pre.astype(np.float64) / scale < threshold_db
    return observed & post_dark & ~pre_dark


def stale_spec_mask(frame, expected: str = SPEC_VERSION):
    """True for rows whose spec_version is missing or differs from ``expected``."""
    if 'spec_version' not in frame.columns:
        return pd.Series(True, index=frame.index)
    return frame['spec_version'].astype('string').str.strip().ne(expected).fillna(True)


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
