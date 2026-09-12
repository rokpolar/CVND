"""Accept only reviewed district relations from the cached one-time lookup."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from pyproj import Geod
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/raw/osm_boundary_review'
# Explicit OSM district relation and LGD identifiers; not town/subdistrict hits.
REVIEWED=[
 ('Assam','Bajali',16704179,'739',422.95,'https://bajali.assam.gov.in/about-us/about-district'),
 ('Assam','Tamulpur',16702229,'756',None,'https://www.kharithi.bodoland.gov.in/tamulpur'),
 ('Meghalaya','Eastern West Khasi Hills',14723470,'740',1145,'https://easternwestkhasihills.meghalaya.gov.in/'),
 ('Sikkim','Gyalshing',1790817,'228',872,'https://rmdd.sikkim.gov.in/storage/notification/notificationdoc-3IkbsZRQgLX9S6qmWGPHYR7pDjBujD1iCaeVgcf3.pdf'),
 ('Telangana','Bhadradri Kothagudem',7698599,'690',7483,'https://kothagudem.telangana.gov.in/demography/'),
]

def main():
    accepted=[]
    for state,district,relation,lgd,official_area,evidence in REVIEWED:
        file=district.replace(' ','_')+'.json'
        raw=(BASE/file).read_bytes()
        choices=[r for r in json.loads(raw) if r.get('osm_type')=='relation' and r['osm_id']==relation]
        assert len(choices)==1
        r=choices[0]; tags=r['extratags']; geom=shape(r['geojson'])
        assert tags['admin_level']=='5' and tags['ref:LGD:district']==lgd
        assert r['address']['state']==state and r['address']['country_code']=='in'
        assert r['type']=='administrative' and geom.is_valid and geom.geom_type in ('Polygon','MultiPolygon')
        area=abs(Geod(ellps='WGS84').geometry_area_perimeter(geom)[0])/1e6
        if official_area: assert abs(area/official_area-1) < .10
        accepted.append(dict(state=state,district=district,relation_id=relation,lgd_code=lgd,
                             file=file,sha256=hashlib.sha256(raw).hexdigest(),official_area_km2=official_area,
                             geometry_area_km2=area,evidence=evidence,
                             source=f'https://www.openstreetmap.org/relation/{relation}',
                             decision='accepted_reference_boundary',snapshot_date=datetime.now(timezone.utc).date().isoformat(),
                             note='OSM district relation with LGD code; present-day reference only, not event-year boundary equivalence. '+
                             ('Published district area within 10%.' if official_area else 'No authoritative area comparison available; lower confidence.')))
    manifest={'license':'ODbL 1.0','attribution':'© OpenStreetMap contributors',
              'license_url':'https://www.openstreetmap.org/copyright','decisions':accepted,
              'rejected':{'Shamator':'OSM polygon 193 km2 versus official 469 km2; rejected incomplete extent.',
                          'Chumoukedima':'Conflicting published area and OSM polygon; not verified.',
                          'Itanagar Capital Region':'No district polygon returned.'}}
    (BASE/'recovery_manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest,indent=2))

if __name__=='__main__': main()
