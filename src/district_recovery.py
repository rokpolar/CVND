"""Merge district recovery rows while retaining source provenance."""
import json
import pandas as pd
from functools import lru_cache
from pathlib import Path
from district_keys import make_event_district_id, normalize_name

INDEPENDENT_SOURCE_CLASSES = frozenset({
    'official_government', 'state_government', 'nrsc_isro',
    'humanitarian', 'humanitarian_network', 'humanitarian_aggregator',
    'national_red_cross', 'ifrc',
})


@lru_cache(maxsize=2048)
def district_search_terms(district):
    """Retain source spellings for queries after canonical identity merging."""
    path = Path(__file__).resolve().parents[1] / 'data/raw/district_recovery_aliases.csv'
    rows = pd.read_csv(path, keep_default_na=False).to_dict('records') if path.exists() else []
    values = {normalize_name(district)}
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row['action'] == 'alias_merge' and normalize_name(row['canonical_value']) in values:
                alias = normalize_name(row['source_value'])
                if alias not in values:
                    values.add(alias)
                    changed = True
    return sorted(values)


def apply_recovery(registry, evidence, aliases=()):
    parents = {}
    for event, group in registry.groupby('event_id'):
        for column in ('source_record_id', 'state', 'start_date', 'end_date'):
            if group[column].nunique() != 1:
                raise ValueError(f'Ambiguous parent {event}: {column}')
        parents[event] = group.iloc[0].to_dict()
    mapping = {normalize_name(x['source_value']): x for x in aliases
               if x['action'] in ('alias_merge', 'split_compound', 'drop_non_district')}

    def names(name):
        action = mapping.get(normalize_name(name))
        if not action:
            return [name]
        if action['action'] == 'drop_non_district':
            return []
        targets = [x.strip() for x in action['canonical_value'].split('|') if x.strip()]
        return [resolved for target in targets for resolved in
                ([target] if normalize_name(target) == normalize_name(name) else names(target))]

    rows = {}

    def add(row):
        key = make_event_district_id(row['event_id'], row['district'])
        row = {**row, 'event_district_id': key}
        if key not in rows:
            rows[key] = row
            return
        previous = rows[key]
        previous['district_resolution_evidence'] = json.dumps(list(dict.fromkeys(
            json.loads(previous.get('district_resolution_evidence', '[]')) +
            json.loads(row.get('district_resolution_evidence', '[]')))), ensure_ascii=False)
        previous['district_source'] = '|'.join(sorted(set(
            previous['district_source'].split('|') + row['district_source'].split('|'))))
        for field in ('district_resolution_source_class',
                      'district_resolution_evidence_type',
                      'district_resolution_circularity_risk',
                      'district_resolution_source_url'):
            values = [str(previous.get(field, '')).strip(), str(row.get(field, '')).strip()]
            previous[field] = '|'.join(sorted({value for value in values if value}))

    for row in registry.to_dict('records'):
        for name in names(row['district']):
            original = row['district']
            new = {**row, 'district': name}
            if name != original:
                new['district_resolution_evidence'] = json.dumps(
                    json.loads(row.get('district_resolution_evidence', '[]')) +
                    [f'recovery_alias:{original}->{name}'], ensure_ascii=False)
                new['aoi_match_status'] = 'pending'
            add(new)

    required = {'event_id', 'state', 'canonical_district', 'source_url', 'evidence_note'}
    missing = required - set(evidence.columns)
    if missing:
        raise ValueError(f'Recovery mapping missing columns: {sorted(missing)}')
    for number, record in enumerate(evidence.to_dict('records'), 2):
        event = record['event_id']
        if event not in parents:
            raise ValueError(f'Unknown recovery event {event}')
        parent = parents[event]
        for field in ('source_record_id', 'state', 'start_date', 'end_date'):
            value = record.get(field, '')
            if field == 'source_record_id' and value + '-IND' == parent[field]:
                continue
            if value and value != parent[field]:
                raise ValueError(f'Recovery identity mismatch row {number}: {event}/{field}')
        if record.get('year') and record['year'] != parent['start_date'][:4]:
            raise ValueError(f'Recovery year mismatch: {event}')
        if not record['source_url'] or not record['evidence_note']:
            raise ValueError(f'Missing recovery evidence: {event}')
        for name in names(record['canonical_district']):
            same_state = normalize_name(name) == normalize_name(parent['state'])
            if normalize_name(name) in ('', 'district_missing') or (
                    same_state and normalize_name(name) != 'puducherry'):
                raise ValueError(f'Invalid recovery district: {event}/{name}')
            provenance = {key: value for key, value in record.items() if value != ''}
            row = {**parent, 'district': name, 'district_source': 'external_recovery',
                   'aoi_level': 'district', 'aoi_match_status': 'pending',
                   'district_resolution_source_class': record.get('source_class', ''),
                   'district_resolution_evidence_type': record.get('evidence_type', ''),
                   'district_resolution_circularity_risk': record.get('circularity_risk', ''),
                   'district_resolution_source_url': record.get('source_url', ''),
                   'district_resolution_evidence': json.dumps([
                       json.dumps({'mapping_row': number, **provenance,
                                   'source_verification': 'supplied_not_independently_verified'},
                                  ensure_ascii=False, sort_keys=True)], ensure_ascii=False)}
            add(row)

    resolved = {r['event_id'] for r in rows.values()
                if r['district'] != 'district_missing'}
    rows = {key: row for key, row in rows.items()
            if row['event_id'] in resolved and row['district'] != 'district_missing'}
    result = (pd.DataFrame(rows.values()) if rows else registry.iloc[0:0].copy())
    result = result.drop(columns=['district_resolution_confidence'], errors='ignore')
    result = result.sort_values(['start_date', 'event_id', 'district']).reset_index(drop=True)
    if result.event_district_id.duplicated().any():
        raise ValueError('Duplicate event_district_id after recovery')
    return result


def independent_recovery_evidence(evidence):
    """Return geography evidence that was not selected from news coverage."""
    keep = pd.Series(True, index=evidence.index)
    if 'circularity_risk' in evidence:
        risk = evidence['circularity_risk'].fillna('').astype(str).str.strip().str.lower()
        keep &= risk.isin(('', 'none'))
    if 'source_class' in evidence:
        source_class = evidence['source_class'].fillna('').astype(str).str.strip().str.lower()
        keep &= source_class.eq('') | source_class.isin(INDEPENDENT_SOURCE_CLASSES)
    return evidence.loc[keep].copy()


def recover_from_files(registry, path, *, include_circularity_risk=False):
    if not path.exists():
        return registry.drop(columns=['district_resolution_confidence'], errors='ignore')
    evidence = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not include_circularity_risk:
        evidence = independent_recovery_evidence(evidence)
    aliases_path = path.with_name('district_recovery_aliases.csv')
    aliases = (pd.read_csv(aliases_path, dtype=str, keep_default_na=False).to_dict('records')
               if aliases_path.exists() else [])
    return apply_recovery(registry, evidence, aliases)


def apply_registry_exclusions(registry, path):
    """Apply an explicit, audited event-district exclusion list.

    The list is intentionally separate from recovery evidence: recovery records
    remain available for audit, while the production cohort can reproduce a
    reviewed exclusion exactly. Every configured key must exist so stale or
    misspelled exclusions fail loudly instead of silently changing the cohort.
    """
    if not path.exists():
        return registry.copy(), registry.iloc[0:0].copy()
    exclusions = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {'event_district_id', 'exclusion_reason'}
    missing = required - set(exclusions)
    if missing:
        raise ValueError(f'District exclusion list missing columns: {sorted(missing)}')
    if exclusions.event_district_id.eq('').any() or exclusions.event_district_id.duplicated().any():
        raise ValueError('District exclusion keys must be non-empty and unique')
    if exclusions.exclusion_reason.str.strip().eq('').any():
        raise ValueError('District exclusion reason must be non-empty')
    configured = set(exclusions.event_district_id)
    available = set(registry.event_district_id)
    unknown = sorted(configured - available)
    if unknown:
        raise ValueError(f'District exclusion keys not produced by derivation: {unknown}')
    removed = registry[registry.event_district_id.isin(configured)].copy()
    removed = removed.merge(exclusions, on='event_district_id', how='left', validate='one_to_one')
    retained = registry[~registry.event_district_id.isin(configured)].copy().reset_index(drop=True)
    return retained, removed.reset_index(drop=True)
