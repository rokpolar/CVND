"""Read-only integrity checks for the latest AOI recovery."""
import json
from collections import Counter
from pathlib import Path
import pandas as pd

root = Path(__file__).resolve().parents[1]
summary = json.loads((root / 'data/intermediate/aoi_recovery_summary.json').read_text())
before = json.loads((Path(summary['backup']) / 'satellite_checkpoint_a.json').read_text())
after = json.loads((root / 'data/cache/district/satellite_checkpoint_a.json').read_text())
assert set(before) == set(after)
changed = [k for k in before if before[k] != after[k]]
assert len(changed) == 34
assert all(before[k]['baseline_status'].startswith('ERROR') for k in changed)
assert all(after[k]['baseline_status'] in ('OK', 'NO_IMAGERY') for k in changed)
aoi = pd.read_csv(root / 'data/intermediate/district_aoi.csv', dtype={'geometry_id': 'string'}).set_index('event_district_id')
flood = pd.read_csv(root / 'data/cache/district/flood_extent.csv').set_index('event_district_id')
assert len(flood) == len(after) == 1630
assert flood.index.is_unique and aoi.index.is_unique
assert set(flood.index) == set(after)
for k in changed:
    assert aoi.loc[k, 'aoi_match_status'] == 'matched'
    assert int(float(aoi.loc[k, 'geometry_id'])) == int(after[k]['geometry_id'])
    assert flood.loc[k, 'baseline_status'] == after[k]['baseline_status']
print(json.dumps({'records': len(after), 'changed': len(changed),
                  'unchanged': len(after)-len(changed),
                  'status_counts': dict(Counter(r['baseline_status'].split(':')[0] for r in after.values())),
                  'identity_and_aoi_checks': 'passed'}, indent=2))
