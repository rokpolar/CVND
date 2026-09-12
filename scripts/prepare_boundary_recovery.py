"""Download pinned geoBoundaries reference layers and inspect district matches."""
import json
import hashlib
from pathlib import Path
import requests
from shapely.geometry import shape
from shapely.validation import make_valid
from shapely.strtree import STRtree
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/raw/geoboundaries_2021'
OUT.mkdir(exist_ok=True)

def key(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', str(s)) if not unicodedata.combining(c))
    return re.sub(r'[\W_]+', '', s.casefold())

def main():
    layers = {}
    for level in ('ADM1', 'ADM2'):
        api = f'https://www.geoboundaries.org/api/current/gbOpen/IND/{level}/'
        mp = OUT / f'{level}_metadata.json'
        if not mp.exists():
            r = requests.get(api, timeout=90); r.raise_for_status()
            mp.write_text(json.dumps(r.json(), indent=2))
        meta = json.loads(mp.read_text())
        fp = OUT / f'{level}.geojson'
        if not fp.exists():
            r = requests.get(meta['gjDownloadURL'], timeout=180); r.raise_for_status()
            fp.write_bytes(r.content)
        layers[level] = json.loads(fp.read_text())['features']
        print(level, len(layers[level]), layers[level][0]['properties'], hashlib.sha256(fp.read_bytes()).hexdigest(), flush=True)
    states = [make_valid(shape(f['geometry'])) for f in layers['ADM1']]
    tree = STRtree(states)
    rows = []
    for f in layers['ADM2']:
        geom = make_valid(shape(f['geometry']))
        choices = [(float(geom.intersection(states[int(i)]).area / geom.area), int(i))
                   for i in tree.query(geom)]
        fraction, index = max(choices)
        rows.append(dict(state=layers['ADM1'][index]['properties']['shapeName'],
                         district=f['properties']['shapeName'], shape_id=f['properties']['shapeID'],
                         state_overlap=fraction, valid=shape(f['geometry']).is_valid))
    (OUT / 'district_catalog.json').write_text(json.dumps(rows, indent=2))
    checkpoint = json.loads((ROOT / 'data/cache/district/satellite_checkpoint_a.json').read_text())
    failed = sorted(set((r['state'],r['district']) for r in checkpoint.values() if r['baseline_status'].startswith('ERROR')))
    exact, missing = [], []
    for state, district in failed:
        matches = [r for r in rows if key(r['state']) == key(state) and key(r['district']) == key(district) and r['state_overlap'] >= .95]
        (exact if len(matches)==1 else missing).append((state,district))
    print('EXACT',len(exact),'MISSING',len(missing), flush=True)
    for state in sorted(set(s for s,d in missing)):
        print(state, 'MISSING:', ', '.join(d for s,d in missing if s==state), flush=True)
        print('AVAILABLE:', ', '.join(r['district'] for r in rows if key(r['state'])==key(state)), flush=True)

if __name__ == '__main__': main()
