"""Report same-event overlap across mixed reference vintages; never sum blindly."""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from shapely.geometry import shape
from shapely.validation import make_valid
from pyproj import Geod

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import satellite as sat
from boundary_recovery import load_boundaries, load_supplemental

def main():
    records=json.loads((ROOT/'data/cache/district/satellite_checkpoint_a.json').read_text())
    gb,features,_=load_boundaries(); osm,osm_features=load_supplemental()
    base=ROOT/'data/raw/geoboundaries_2021'
    gaul_path=base/'existing_gaul_geometries.json'
    if not gaul_path.exists():
        sat.ensure_gee()
        ids=sorted({int(r['geometry_id']) for r in records.values() if str(r.get('geometry_id','')).isdigit() and str(r.get('aoi_source','')).startswith('FAO/')})
        collection=sat.ee.FeatureCollection(sat.SPEC.gaul_level2).filter(sat.ee.Filter.inList('ADM2_CODE',ids))
        gaul_path.write_text(json.dumps(collection.getInfo()))
    gaul={str(f['properties']['ADM2_CODE']):make_valid(shape(f['geometry'])) for f in json.loads(gaul_path.read_text())['features']}
    grouped=defaultdict(list)
    for identity,r in records.items():
        pair=(r['state'],r['district'])
        if pair in osm:
            geom=shape(osm_features[pair]['geojson']); source='OSM_reference'
        elif pair in gb:
            geom=shape(features[gb[pair]['shape_id']]['geometry']); source='GB2021_reference'
        elif str(r.get('geometry_id')) in gaul:
            geom=gaul[str(r['geometry_id'])]; source='GAUL_reference'
        else: continue
        grouped[r['event_id']].append((identity,r,geom,source))
    audit=[]; geod=Geod(ellps='WGS84')
    for event,rows in grouped.items():
        for i,(left,lr,lg,ls) in enumerate(rows):
            for right,rr,rg,rs in rows[i+1:]:
                if lr['state']!=rr['state'] or not lg.intersects(rg): continue
                shared=lg.intersection(rg)
                fraction=shared.area/min(lg.area,rg.area)
                if fraction<=.01: continue
                km2=abs(geod.geometry_area_perimeter(shared)[0])/1e6
                audit.append(dict(event_id=event,left_id=left,right_id=right,left_source=ls,right_source=rs,
                                  overlap_fraction_of_smaller=round(fraction,6),overlap_km2=round(km2,3),
                                  warning='Do not sum district flood areas; reference geometries overlap. Recompute on common boundaries or union pixel masks.'))
    out=ROOT/'data/intermediate/event_aoi_overlap_audit.csv'
    fields=['event_id','left_id','right_id','left_source','right_source','overlap_fraction_of_smaller','overlap_km2','warning']
    with out.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(audit)
    print(json.dumps({'overlapping_pairs':len(audit),'affected_events':len(set(r['event_id'] for r in audit)),
                      'mixed_source_pairs':sum(r['left_source']!=r['right_source'] for r in audit),'report':str(out)}),flush=True)

if __name__=='__main__': main()
