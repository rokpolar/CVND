"""S1 -> SITS-NDWI converter artifact: schema, validation and application.

compare_tracks.py decides and fits the converter and writes it here;
merge_results.py reads it to put districts SITS cannot measure on the
SITS-NDWI scale (satellite_source S1_TO_SITS). Pure Python + numpy.

Models (areas in km², o = the rules' log offset):
  identity           y = s1
  deming_loglog      log(y + o) = a + b log(s1 + o)
  ols_loglog_strata  log(y + o) = c0 + c1 log(s1 + o) + c2 builtup_frac + c3 cropland_frac
"""
from __future__ import annotations

import json
import math
import os

from cvnd_layout import data_path
from flood_spec import (CONVERTER_DECISIONS, CONVERTING_DECISIONS, CONVERTER_RULES,
                        CONVERTER_RULES_VERSION, SPEC_VERSION)

CONVERTER_JSON = str(data_path('s1_to_sits_converter'))
MODEL_TYPES = ('identity', 'deming_loglog', 'ols_loglog_strata')


class ConverterUnavailable(ValueError):
    """No usable converter for the current spec and rules."""


def validate(converter: dict) -> dict:
    decision = converter.get('decision')
    if decision not in CONVERTER_DECISIONS:
        raise ConverterUnavailable(f'converter decision {decision!r} not in {CONVERTER_DECISIONS}')
    if converter.get('spec_version') != SPEC_VERSION:
        raise ConverterUnavailable(
            f"converter fitted under spec {converter.get('spec_version')}; expected {SPEC_VERSION}")
    if converter.get('rules_version') != CONVERTER_RULES_VERSION:
        raise ConverterUnavailable(
            f"converter decided under rules {converter.get('rules_version')}; "
            f"expected {CONVERTER_RULES_VERSION}")
    if decision in CONVERTING_DECISIONS:
        model = converter.get('model') or {}
        if model.get('type') not in MODEL_TYPES:
            raise ConverterUnavailable(f"converter model type {model.get('type')!r} unknown")
    return converter


def load(path: str | None = None) -> dict:
    """Validated converter, or ConverterUnavailable (missing / other spec / other rules)."""
    path = path or CONVERTER_JSON
    if not os.path.exists(path):
        raise ConverterUnavailable(f'{path} missing: run compare_tracks.py')
    with open(path, encoding='utf-8') as handle:
        return validate(json.load(handle))


def convert(model: dict, s1_km2: float, builtup_frac: float | None = None,
            cropland_frac: float | None = None) -> float | None:
    """S1 new water (km²) on the SITS-NDWI scale; None when an input is missing."""
    if s1_km2 is None or not math.isfinite(s1_km2):
        return None
    kind = model['type']
    if kind == 'identity':
        return float(s1_km2)
    offset = float(model.get('offset_km2', CONVERTER_RULES.log_offset_km2))
    x = math.log(s1_km2 + offset)
    if kind == 'deming_loglog':
        log_y = model['intercept'] + model['slope'] * x
    else:
        if builtup_frac is None or cropland_frac is None:
            return None
        coef = model['coef']
        log_y = (coef['const'] + coef['log_s1'] * x + coef['builtup_frac'] * builtup_frac
                 + coef['cropland_frac'] * cropland_frac)
    return max(0.0, math.exp(log_y) - offset)


def write(converter: dict, path: str | None = None) -> str:
    path = path or CONVERTER_JSON
    validate(converter)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(converter, handle, indent=2, allow_nan=False)
    return path
