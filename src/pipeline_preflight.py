"""Offline district input/cache audit. Never invokes Earth Engine or BigQuery."""
from __future__ import annotations
import argparse
import json
import sys

import pandas as pd
from cvnd_layout import data_path
from flood_spec import SPEC_VERSION, stale_spec_mask

# Satellite artifacts measured under flood_spec.SPEC; another spec_version is stale.
SPEC_ARTIFACTS = {'district_aoi', 'district_flood_extent', 'district_flood_combined', 'district_flood_area'}


def inspect_artifacts():
    required = {
        'emdat_base': None,
        'census_district_input': None,
        'event_districts': ['event_district_id', 'event_id', 'source_record_id', 'state', 'district', 'start_date'],
        'district_covariates': ['state', 'district', 'urban_population_share', 'census_year'],
        'district_aoi': ['event_district_id', 'aoi_level', 'aoi_match_status', 'aoi_area_km2'],
        'district_flood_extent': ['event_district_id', 'aoi_level', 'aoi_match_status'],
        'district_flood_combined': ['event_district_id', 'combined_km2', 'satellite_source', 'route_reason'],
        'district_flood_area': ['event_district_id', 'flood_area_km2', 'satellite_status', 'satellite_source', 'spec_version'],
        'district_article_counts_heuristic': ['event_district_id', 'final_article_count', 'collection_status'],
    }
    rows = []
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
                if 'aoi_level' in frame and not frame.aoi_level.eq('district').all():
                    raise ValueError('contains a state AOI: cache is not district-only')
                details = f'{len(frame)} rows'
            except (ValueError, OSError) as exc:
                status, details = 'invalid', str(exc)
        rows.append({'artifact': key, 'path': str(path), 'status': status, 'details': details})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict', action='store_true', help='Exit nonzero if any required input/cache is unavailable or stale')
    args = parser.parse_args(argv)
    rows = inspect_artifacts()
    print(json.dumps({'spatial_unit': 'event × district', 'spec_version': SPEC_VERSION, 'artifacts': rows}, indent=2))
    return int(args.strict and any(r['status'] != 'present' for r in rows))


if __name__ == '__main__':
    sys.exit(main())
