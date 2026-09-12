"""Audit GAUL names and recover unique spacing/punctuation matches only.

Run from the repository: python scripts/recover_aoi_matching.py [--run].
Other aliases are review candidates, never automatic boundary equivalences.
"""
import argparse
import csv
import difflib
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def key(value):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', str(value)).casefold())


def unique_spacing_match(district, candidates):
    found = [r for r in candidates if key(r[1]) == key(district)]
    return found[0] if len(found) == 1 else None


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    import ee
    import pandas as pd
    import satellite as sat
    ee.Initialize(project='cvnd-507907')
    ee.data.setDeadline(180000)
    cache = ROOT / 'data/cache/district'
    out = ROOT / 'data/intermediate'
    collection = ee.FeatureCollection(sat.SPEC.gaul_level2)
    names = collection.filter(ee.Filter.eq('ADM0_NAME', 'India')).reduceColumns(
        ee.Reducer.toList(3), ['ADM1_NAME', 'ADM2_NAME', 'ADM2_CODE']).getInfo()['list']
    (out / 'gaul_name_catalog.json').write_text(json.dumps(names, indent=2))
    checkpoint = cache / 'satellite_checkpoint_a.json'
    records = json.loads(checkpoint.read_text())
    registry = pd.read_csv(ROOT / 'data/intermediate/event_districts.csv')
    registry_by_key = {sat.analysis_key(r): r for _, r in registry.iterrows()}
    failed = [r for r in records.values() if str(r.get('baseline_status', '')).startswith('ERROR')]
    counts = Counter((r['state'], r['district']) for r in failed)
    with (ROOT / 'data/raw/district_name_crosswalk.csv').open() as f:
        census = list(csv.DictReader(f))
    audit, accepted = [], {}
    for (state, district), count in sorted(counts.items()):
        candidates = [r for r in names if r[0] == sat.GAUL_STATE_ALIASES.get(state, state)]
        match = unique_spacing_match(district, candidates)
        aliases = [r['census_district'] for r in census
                   if r['registry_state'] == state and r['registry_district'] == district]
        suggestions = [r[1] for r in candidates if any(key(r[1]) == key(a) for a in aliases)]
        if not suggestions:
            suggestions = difflib.get_close_matches(district, [r[1] for r in candidates], n=3, cutoff=0.45)
        status = 'unique_spacing_match' if match else 'boundary_review_required'
        if state in sat.GAUL_UNAVAILABLE_STATES:
            status = 'alternative_boundary_required'
        if match:
            accepted[(state, district)] = match
        audit.append(dict(state=state, district=district, event_rows=count, status=status,
                          gaul_name=match[1] if match else '', gaul_code=match[2] if match else '',
                          candidates=' | '.join(suggestions),
                          source=sat.SPEC.gaul_level2,
                          note='Same normalized spelling; retains GAUL reference geography, not proof of event-year boundaries'
                          if match else 'Candidate only; verify administrative history before using geometry'))
    pd.DataFrame(audit).to_csv(out / 'aoi_matching_audit.csv', index=False)
    pd.DataFrame([r for r in audit if r['status'] == 'unique_spacing_match']).to_csv(
        ROOT / 'data/raw/gaul_spacing_crosswalk.csv', index=False)
    summary = {'failed_rows_before': len(failed), 'unique_failed_districts': len(counts),
               'spacing_recoverable_rows': sum(r['event_rows'] for r in audit if r['status'] == 'unique_spacing_match'),
               'spacing_recoverable_districts': len(accepted)}
    print(json.dumps(summary), flush=True)
    if not args.run:
        return
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = cache / ('before_aoi_recovery_' + stamp)
    backup.mkdir()
    for path in (checkpoint, cache / 'flood_extent.csv', out / 'district_aoi.csv'):
        shutil.copy2(path, backup / path.name)
    original_resolver = sat.resolve_aoi

    def resolver(row, spec=sat.SPEC):
        match = accepted.get((row.get('state'), row.get('district')))
        if match is None:
            return original_resolver(row, spec)
        replacement = row.copy()
        replacement['district'] = match[1]
        result = original_resolver(replacement, spec)
        if result['geometry_id'] != str(match[2]):
            raise ValueError('Verified GAUL code changed')
        return result

    sat.resolve_aoi = resolver
    targets = [registry_by_key[r['event_district_id']] for r in failed
               if (r['state'], r['district']) in accepted]
    aoi = pd.read_csv(out / 'district_aoi.csv').set_index('event_district_id', drop=False)
    for col in (*sat.AOI_COLUMNS, 'aoi_error'):
        if col in aoi and col != 'aoi_area_km2':
            aoi[col] = aoi[col].astype(object)

    def persist():
        temp = checkpoint.with_suffix('.recovery.tmp')
        sat.save_checkpoint(records, str(temp))
        temp.replace(checkpoint)
        csv_path = cache / 'flood_extent.csv'
        temp_csv = csv_path.with_suffix('.recovery.tmp')
        pd.DataFrame(records.values()).sort_values('event_district_id').to_csv(temp_csv, index=False)
        temp_csv.replace(csv_path)
        temp_aoi = out / 'district_aoi.recovery.tmp'
        aoi.to_csv(temp_aoi, index=False)
        temp_aoi.replace(out / 'district_aoi.csv')

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(sat.detect_flood_baseline, row): sat.analysis_key(row) for row in targets}
        for i, future in enumerate(as_completed(futures), 1):
            identity = futures[future]
            result = future.result()
            if not sat._cache_identity_matches(result, registry_by_key[identity]):
                raise ValueError('Recovered row identity/spec mismatch')
            records[identity] = result
            if result.get('aoi_match_status') == 'matched':
                for col in sat.AOI_COLUMNS:
                    aoi.loc[identity, col] = result.get(col)
                if 'aoi_error' in aoi:
                    aoi.loc[identity, 'aoi_error'] = ''
            persist()
            print(f'RECOVERED {i}/{len(targets)} {identity} {result["baseline_status"]}', flush=True)
    summary['final_status_counts'] = dict(Counter(r['baseline_status'].split(':')[0] for r in records.values()))
    summary['backup'] = str(backup)
    (out / 'aoi_recovery_summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
