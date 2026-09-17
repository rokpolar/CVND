"""Offline district input/cache audit. Never invokes Earth Engine or BigQuery."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import h5py
import pandas as pd
from cvnd_layout import data_path
from flood_spec import CONVERTER_RULES_VERSION, SPEC_VERSION, stale_spec_mask

# Satellite artifacts measured under flood_spec.SPEC; another spec_version is stale.
SPEC_ARTIFACTS = {'district_aoi', 'district_flood_extent', 'district_flood_combined', 'district_flood_area'}
# JSON artifacts carrying spec_version (and rules_version for the converter).
JSON_ARTIFACTS = {
    's1_to_sits_converter': ('decision', 'spec_version', 'rules_version'),
    'track_agreement_summary': ('spec_version', 'rules_version', 'identity', 'decision'),
}


def _inspect_json(key, fields):
    path = data_path(key)
    if not path.exists():
        return {'artifact': key, 'path': str(path), 'status': 'missing', 'details': ''}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        missing = [f for f in fields if f not in payload]
        if missing:
            raise ValueError(f'missing fields {missing}')
        if payload['spec_version'] != SPEC_VERSION:
            return {'artifact': key, 'path': str(path), 'status': 'stale_spec',
                    'details': f"{payload['spec_version']} != {SPEC_VERSION}"}
        if payload.get('rules_version') != CONVERTER_RULES_VERSION:
            return {'artifact': key, 'path': str(path), 'status': 'stale_spec',
                    'details': f"rules {payload.get('rules_version')} != {CONVERTER_RULES_VERSION}"}
        details = f"decision {payload['decision']}" if 'decision' in payload and isinstance(payload['decision'], str) else ''
        return {'artifact': key, 'path': str(path), 'status': 'present', 'details': details}
    except (ValueError, OSError) as exc:
        return {'artifact': key, 'path': str(path), 'status': 'invalid', 'details': str(exc)}


def inspect_artifacts():
    required = {
        'emdat_base': None,
        'census_district_input': None,
        'event_districts': ['event_district_id', 'event_id', 'source_record_id', 'state', 'district', 'start_date'],
        'district_covariates': ['state', 'district', 'urban_population_share', 'census_year'],
        'district_aoi': ['event_district_id', 'aoi_level', 'aoi_match_status', 'aoi_area_km2'],
        'district_flood_extent': ['event_district_id', 'aoi_level', 'aoi_match_status', 'eligible_km2',
                                  'optical_observed_km2', 's1_on_optical_km2'],
        'district_flood_combined': ['event_district_id', 'combined_km2', 'satellite_source', 'route_reason',
                                    'sits_status', 'legacy_combined_km2'],
        'district_flood_area': ['event_district_id', 'flood_area_km2', 'satellite_status', 'satellite_source', 'spec_version'],
        'track_agreement': ['event_district_id', 'identity_ok', 'identity_rel_err', 's1_c_km2', 'ndwi_c_km2'],
        'district_article_counts_heuristic': ['event_district_id', 'final_article_count', 'collection_status'],
    }
    rows = []
    registry_path = data_path('event_districts')
    registry = pd.read_csv(registry_path, dtype=str, keep_default_na=False) if registry_path.exists() else None
    for key, columns in required.items():
        path = data_path(key)
        status = 'present' if path.exists() else 'missing'
        details = ''
        if path.exists() and columns:
            try:
                frame = pd.read_csv(path)
                if key in SPEC_ARTIFACTS:
                    stale = stale_spec_mask(frame)
                    if stale.any():
                        versions = frame['spec_version'] if 'spec_version' in frame else pd.Series('missing', index=frame.index)
                        found = sorted({str(v) for v in versions[stale]})
                        rows.append({'artifact': key, 'path': str(path), 'status': 'stale_spec',
                                     'details': f'{int(stale.sum())}/{len(frame)} rows not under {SPEC_VERSION}: {found[:3]}'})
                        continue
                missing = set(columns) - set(frame.columns)
                if missing:
                    raise ValueError(f'missing columns {sorted(missing)}')
                if 'event_district_id' in columns and (frame.event_district_id.isna().any() or frame.event_district_id.duplicated().any()):
                    raise ValueError('empty or duplicate district key')
                if registry is not None and key != 'event_districts' and 'event_district_id' in frame:
                    if not set(frame.event_district_id) <= set(registry.event_district_id):
                        raise ValueError('stale registry: unknown district IDs')
                    common = [c for c in ('event_id', 'source_record_id', 'state', 'district', 'start_date') if c in frame]
                    audit = frame[['event_district_id'] + common].fillna('').astype(str).merge(
                        registry[['event_district_id'] + common], on='event_district_id', suffixes=('_cache', '_registry'))
                    if any(not audit[c+'_cache'].equals(audit[c+'_registry']) for c in common):
                        raise ValueError('stale registry: changed identity')
                if 'aoi_level' in frame and not frame.aoi_level.eq('district').all():
                    raise ValueError('contains a non-district AOI: cache is not district-only')
                details = f'{len(frame)} rows'
            except (ValueError, OSError) as exc:
                status, details = 'invalid', str(exc)
        rows.append({'artifact': key, 'path': str(path), 'status': status, 'details': details})
    rows.extend(_inspect_json(key, fields) for key, fields in JSON_ARTIFACTS.items())
    rows.extend(_inspect_track_b(registry))
    rows.extend(_inspect_article_qa(registry))
    return rows


def _inspect_track_b(registry):
    path = data_path('district_sits_patches_index')
    if registry is None or not path.exists():
        return [{'artifact': 'track_b_completion', 'path': str(path), 'status': 'missing',
                 'details': 'registry or Track-B index missing'}]
    try:
        index = pd.read_csv(path, dtype=str, keep_default_na=False)
        current = set(registry.event_district_id)
        indexed = set(index.event_district_id)
        unknown = indexed - current
        complete = index.status.isin(['OK', 'SKIPPED_NO_IMAGERY'])
        errors = int((~complete).sum())
        absent = len(current - indexed)
        unsafe = []
        patch_dir = data_path('district_sits_patches')
        for h5_path in patch_dir.glob('*.h5'):
            if Path(str(h5_path) + '.blocks.json').exists():
                continue
            with h5py.File(h5_path, 'r') as hdf:
                attrs = hdf['meta'].attrs
                bands = str(attrs.get('bands', '')).replace(' ', '')
                rule = str(attrs.get('tile_selection_rule', ''))
                if bands == 'B4,B3,B2' and rule != 'per_timestep_valid_fraction_v2':
                    unsafe.append(h5_path.name)
        status = 'present' if not unknown and not errors and not absent and not unsafe else 'invalid'
        details = (f'complete={int(complete.sum())}/{len(current)}, errors={errors}, absent={absent}, '
                   f'unsafe_prescreen={len(unsafe)}, unknown={len(unknown)}')
        return [{'artifact': 'track_b_completion', 'path': str(path), 'status': status,
                 'details': details}]
    except (OSError, ValueError, KeyError) as exc:
        return [{'artifact': 'track_b_completion', 'path': str(path), 'status': 'invalid',
                 'details': str(exc)}]


def _inspect_article_qa(registry):
    from types import SimpleNamespace
    from article_qa import article_pipeline_state
    from cvnd_config import PRIMARY_NEWS_WINDOW_DAYS, SENSITIVITY_NEWS_WINDOW_DAYS

    work = data_path('event_districts').parent / 'article_qa'
    reuse_state = 'none'
    if registry is not None:
        args = SimpleNamespace(registry=data_path('event_districts'),
                               source=data_path('gdelt_articles'), work=work)
        reuse_state = article_pipeline_state(args)
    rows = []
    for days, label in ((PRIMARY_NEWS_WINDOW_DAYS, 'primary'),
                        (SENSITIVITY_NEWS_WINDOW_DAYS, 'sensitivity')):
        path = work / f'counts_{days}d.csv'
        artifact = f'article_qa_{label}_{days}d'
        if registry is None or not path.exists():
            rows.append({'artifact': artifact, 'path': str(path), 'status': 'missing',
                         'details': f'pipeline_state={reuse_state}'})
            continue
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            required = {'event_district_id', 'final_article_count', 'collection_status',
                        'article_count_is_lower_bound', 'window_days'}
            if not required <= set(frame):
                raise ValueError(f'missing columns {sorted(required - set(frame))}')
            current, found = set(registry.event_district_id), set(frame.event_district_id)
            if frame.event_district_id.duplicated().any() or current != found:
                raise ValueError(f'registry mismatch extra={len(found-current)} missing={len(current-found)}')
            if set(frame.window_days) != {str(days)}:
                raise ValueError('wrong window_days')
            statuses = frame.collection_status.str.strip().str.lower()
            if not statuses.isin({'complete', 'partial', 'incomplete'}).all():
                raise ValueError('invalid collection_status')
            observed = statuses.isin({'complete', 'partial'})
            counts = pd.to_numeric(frame.final_article_count, errors='coerce')
            if counts[observed].isna().any():
                raise ValueError('observed row missing final_article_count')
            lower = frame.article_count_is_lower_bound.str.lower().isin({'true', '1'})
            if not lower[statuses.eq('partial')].all():
                raise ValueError('partial row is not marked as a lower bound')
            status = 'present' if reuse_state == 'llm_complete' else 'invalid'
            details = (f'rows={len(frame)}, complete={int(statuses.eq("complete").sum())}, '
                       f'partial={int(statuses.eq("partial").sum())}, '
                       f'incomplete={int(statuses.eq("incomplete").sum())}, '
                       f'pipeline_state={reuse_state}')
            rows.append({'artifact': artifact, 'path': str(path), 'status': status,
                         'details': details})
        except (OSError, ValueError, KeyError) as exc:
            rows.append({'artifact': artifact, 'path': str(path), 'status': 'invalid',
                         'details': str(exc)})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict', action='store_true', help='Exit nonzero if any required input/cache is unavailable or stale')
    args = parser.parse_args(argv)
    rows = inspect_artifacts()
    print(json.dumps({'spatial_unit': 'event × district', 'spec_version': SPEC_VERSION,
                      'converter_rules_version': CONVERTER_RULES_VERSION, 'artifacts': rows}, indent=2))
    return int(args.strict and any(r['status'] != 'present' for r in rows))


if __name__ == '__main__':
    sys.exit(main())
