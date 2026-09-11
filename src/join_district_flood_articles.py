"""Strict event × district join, retaining missing observations and exclusion reasons."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cvnd_layout import data_path
from district_keys import AOI_MATCHED, SATELLITE_OBSERVED, normalize_name
from flood_spec import MEASURED_SOURCES

KEY = 'event_district_id'
IDENTITY = ['event_id', 'source_record_id', 'state', 'district', 'start_date']
FLOOD_COLUMNS = ['flood_area_km2', 'flood_ratio', 'aoi_area_km2', 'satellite_source', 'satellite_status', 'aoi_match_status']
OPTIONAL_FLOOD_COLUMNS = ['geometry_id', 'aoi_source', 'route_reason', 'spec_version',
                          'sits_status', 'converter_decision', 'eligible_km2',
                          'flood_ratio_eligible', 'legacy_flood_area_km2',
                          'legacy_satellite_source']


def require(frame, columns, label):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f'{label} missing columns: {sorted(missing)}')


def unique(frame, key, label):
    require(frame, [key], label)
    if frame[key].isna().any() or frame[key].astype(str).str.strip().eq('').any() or frame[key].duplicated().any():
        raise ValueError(f'{label}: {key} must be nonempty and unique')


def merge_observations(registry, observations, columns, label):
    unique(observations, KEY, label)
    require(observations, columns, label)
    unknown = set(observations[KEY]) - set(registry[KEY])
    if unknown:
        raise ValueError(f'{label} has keys outside current registry: {sorted(unknown)[:5]}')
    # Check identity even when IDs happen to coincide with a stale registry.
    checks = [col for col in IDENTITY if col in observations]
    audit = registry[[KEY] + checks].merge(observations[[KEY] + checks], on=KEY, validate='one_to_one', suffixes=('_registry', '_cache'))
    for col in checks:
        left, right = audit[col + '_registry'].fillna('').astype(str), audit[col + '_cache'].fillna('').astype(str)
        if not left.equals(right):
            raise ValueError(f'{label}: stale or inconsistent {col} for district keys')
    return registry.merge(observations[[KEY] + columns], on=KEY, how='left', validate='one_to_one')


def build_district_table(registry, flood, articles, covariates):
    require(registry, [KEY] + IDENTITY + ['aoi_level', 'district_resolution_confidence'], 'registry')
    unique(registry, KEY, 'registry')
    result = registry.copy()
    # Registry AOI status is a pre-resolution placeholder. Measured provenance is authoritative.
    result = result.drop(columns=['aoi_match_status'], errors='ignore')
    flood_columns = FLOOD_COLUMNS + [c for c in OPTIONAL_FLOOD_COLUMNS if c in flood]
    result = merge_observations(result, flood, flood_columns, 'district flood')
    article_columns = ['final_article_count', 'collection_status', 'count_source']
    article_columns += [c for c in ['query_collection_status', 'missing_text_count', 'candidate_article_count', 'heuristic_pass_count'] if c in articles]
    result = merge_observations(result, articles, article_columns, 'district article counts')
    result = result.rename(columns={'final_article_count': 'article_count', 'collection_status': 'article_collection_status'})
    require(covariates, ['state', 'district', 'urban_population_share', 'total_population', 'urban_population', 'rural_population', 'match_status', 'census_year', 'source'], 'Census covariates')
    cov = covariates.copy()
    for frame in (result, cov):
        frame['_state'] = frame['state'].map(normalize_name)
        frame['_district'] = frame['district'].map(normalize_name)
    keys = ['_state', '_district']
    ambiguous = cov.duplicated(keys, keep=False)
    ambiguous_keys = set(map(tuple, cov.loc[ambiguous, keys].values))
    cov = cov.loc[~ambiguous].rename(columns={'match_status': 'census_match_status', 'source': 'census_source'})
    cov_columns = ['urban_population_share', 'total_population', 'urban_population', 'rural_population', 'census_year', 'census_source', 'census_match_status']
    if 'census_district_code' in cov:
        cov_columns.append('census_district_code')
    result = result.merge(cov[keys + cov_columns], on=keys, how='left', validate='many_to_one')
    duplicate_match = result[keys].apply(tuple, axis=1).isin(ambiguous_keys)
    result.loc[duplicate_match, 'census_match_status'] = 'ambiguous'
    result['census_match_status'] = result['census_match_status'].fillna('missing')
    result['aoi_match_status'] = result['aoi_match_status'].fillna('not_observed')
    result['satellite_status'] = result['satellite_status'].fillna('not_observed')
    result['article_collection_status'] = result['article_collection_status'].fillna('not_executed')
    result['district_match_status'] = np.where(result['district'].fillna('').str.strip().isin(['', 'district_missing']), 'district_missing', result['district_resolution_confidence'])
    numeric = ['flood_area_km2', 'article_count', 'urban_population_share', 'total_population', 'urban_population', 'rural_population', 'aoi_area_km2', 'flood_ratio']
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors='coerce')
    # Values arriving with a failed status never become valid observations.
    collection_ok = result['article_collection_status'].eq('complete')
    source_invalid = result['flood_area_km2'].notna() & ~result['satellite_source'].isin(MEASURED_SOURCES)
    satellite_ok = result['satellite_status'].isin(SATELLITE_OBSERVED) & ~source_invalid
    result.loc[~collection_ok, 'article_count'] = np.nan
    result.loc[~satellite_ok, ['flood_area_km2', 'flood_ratio']] = np.nan
    reasons = [[] for _ in range(len(result))]

    def exclude(mask, reason):
        for i in np.flatnonzero(np.asarray(mask, dtype=bool)):
            reasons[i].append(reason)

    exclude(~result['district_match_status'].isin(['high', 'exact', 'resolved', 'matched']), 'district_unresolved')
    exclude(~result['aoi_level'].eq('district') | ~result['aoi_match_status'].isin(AOI_MATCHED), 'district_aoi_unmatched')
    exclude(source_invalid, 'satellite_source_invalid')
    exclude(~satellite_ok | ~np.isfinite(result['flood_area_km2']) | result['flood_area_km2'].lt(0), 'satellite_missing_or_invalid')
    exclude(~np.isfinite(result['aoi_area_km2']) | result['aoi_area_km2'].le(0) | result['flood_area_km2'].gt(result['aoi_area_km2']), 'aoi_area_invalid')
    exclude(~collection_ok, 'article_collection_incomplete')
    exclude(~np.isfinite(result['article_count']) | result['article_count'].lt(0) | result['article_count'].mod(1).ne(0), 'article_count_missing_or_invalid')
    census_ok = result['census_match_status'].isin(['matched', 'exact', 'crosswalk', 'matched_crosswalk'])
    exclude(~census_ok, 'census_unmatched')
    exclude(~result['urban_population_share'].between(0, 1) | ~np.isfinite(result['total_population']) | result['total_population'].le(0) | ~result['census_year'].eq(2011), 'census_invalid')
    population_ok = (np.isclose(result['urban_population_share'], result['urban_population'] / result['total_population'], equal_nan=False) & np.isclose(result['total_population'], result['urban_population'] + result['rural_population'], equal_nan=False) & result['urban_population'].ge(0) & result['rural_population'].ge(0))
    exclude(~population_ok, 'census_population_inconsistent')
    exclude(pd.to_datetime(result['start_date'], errors='coerce').isna(), 'onset_date_invalid')
    for identifier in ['geometry_id', 'census_district_code']:
        if identifier in result:
            known = result[identifier].notna() & result[identifier].astype(str).str.strip().ne('')
            duplicate_geography = result.loc[known].duplicated(['event_id', identifier], keep=False)
            bad = pd.Series(False, index=result.index)
            bad.loc[duplicate_geography.index] = duplicate_geography
            exclude(bad, 'ambiguous_duplicate_' + identifier)
    result['exclusion_reason'] = [';'.join(items) for items in reasons]
    result['analysis_eligible'] = result['exclusion_reason'].eq('')
    result = result.drop(columns=keys).sort_values(KEY).reset_index(drop=True)
    return result, result.loc[~result['analysis_eligible']].copy()


def qc_summary(table):
    n = len(table)
    def rate(mask):
        return {'success': int(mask.sum()), 'total': n, 'rate': float(mask.mean()) if n else None}
    summary = {
        'district_extraction': rate(table['district_match_status'].isin(['high', 'exact', 'resolved', 'matched'])),
        'district_aoi_match': rate(table['aoi_match_status'].isin(AOI_MATCHED)),
        'census_match': rate(table['census_match_status'].isin(['matched', 'exact', 'crosswalk', 'matched_crosswalk'])),
        'satellite_observation': rate(table['satellite_status'].isin(SATELLITE_OBSERVED) & table['flood_area_km2'].notna()),
        'gdelt_collection': rate(table.get('query_collection_status', table['article_collection_status']).eq('complete')),
        'article_observation': rate(table['article_collection_status'].eq('complete') & table['article_count'].notna()),
        'final_analyzable': rate(table['analysis_eligible']),
    }
    if 'satellite_source' in table:
        eligible = table['analysis_eligible'].astype(bool)
        summary['satellite_source_counts'] = {str(k): int(v) for k, v in table.loc[eligible, 'satellite_source'].value_counts().items()}
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name, key in [('events', 'event_districts'), ('flood', 'district_flood_area'), ('articles', 'district_article_counts_heuristic'), ('covariates', 'district_covariates'), ('output', 'district_flood_articles'), ('exclusions', 'district_analysis_exclusions'), ('qc', 'district_qc')]:
        parser.add_argument('--' + name, type=Path, default=data_path(key))
    parser.add_argument('--audit-missing', action='store_true', help='Build an exclusion audit with NA for absent satellite/article artifacts; never fabricate observations')
    args = parser.parse_args(argv)
    frames = []
    for name in ['events', 'flood', 'articles', 'covariates']:
        path = getattr(args, name)
        if not path.exists() and args.audit_missing and name in ['flood', 'articles']:
            columns = ([KEY] + FLOOD_COLUMNS + ['route_reason'] if name == 'flood' else [KEY, 'final_article_count', 'collection_status', 'count_source', 'query_collection_status'])
            frames.append(pd.DataFrame(columns=columns))
            print(f'AUDIT ONLY: {path} absent; all observations from this stage remain missing')
            continue
        if not path.exists():
            raise FileNotFoundError(f'Missing district {name}: {path}. Run the district producer; state caches are not compatible.')
        frames.append(pd.read_csv(path))
    table, excluded = build_district_table(*frames)
    for path, frame in [(args.output, table), (args.exclusions, excluded)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    qc = qc_summary(table)
    args.qc.parent.mkdir(parents=True, exist_ok=True)
    args.qc.write_text(json.dumps(qc, indent=2) + '\n')
    print(json.dumps(qc, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
