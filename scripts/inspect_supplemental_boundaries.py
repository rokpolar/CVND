"""One-time cached lookup of eight missing district boundaries, not an app API.

Nominatim policy: single machine/thread, <=1 request/s, identifiable User-Agent,
cache every response; OSM contributors attribution and ODbL apply.
https://operations.osmfoundation.org/policies/nominatim/
"""
import json
import time
from pathlib import Path
import requests
from shapely.geometry import shape
from pyproj import Geod

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/raw/osm_boundary_review'; OUT.mkdir(exist_ok=True)
TARGETS=[('Arunachal Pradesh','Itanagar Capital Region'),('Assam','Bajali'),('Assam','Tamulpur'),
         ('Meghalaya','Eastern West Khasi Hills'),('Nagaland','Chumoukedima'),('Nagaland','Shamator'),
         ('Sikkim','Gyalshing'),('Telangana','Bhadradri Kothagudem')]

def main():
    session=requests.Session()
    session.headers['User-Agent']='CVND-BoundaryReview/1.0 (one-time district boundary research; Python requests)'
    for state,district in TARGETS:
        path=OUT/(district.replace(' ','_')+'.json')
        if not path.exists():
            response=session.get('https://nominatim.openstreetmap.org/search',params={
                'q':f'{district}, {state}, India','format':'jsonv2','countrycodes':'in',
                'polygon_geojson':1,'addressdetails':1,'extratags':1,'namedetails':1,'limit':3},timeout=90)
            response.raise_for_status(); path.write_text(response.text); time.sleep(1.1)
        rows=json.loads(path.read_text())
        for r in rows:
            geom=shape(r['geojson'])
            area=abs(Geod(ellps='WGS84').geometry_area_perimeter(geom)[0])/1e6 if geom.geom_type in ('Polygon','MultiPolygon') else 0
            print(district,json.dumps({k:r.get(k) for k in ('osm_type','osm_id','type','addresstype','name','address','extratags')},ensure_ascii=False),geom.geom_type,'area',round(area,1),flush=True)
        if not rows: print(district,'NO RESULT',flush=True)

if __name__=='__main__': main()
