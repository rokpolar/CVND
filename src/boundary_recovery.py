"""Pinned, explicit district reference-boundary overrides shared by Tracks A/B.

These are 2021 reference geometries, not assertions of historical boundaries.
No network downloads or fuzzy matching occur during resolution.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'data/raw/geoboundaries_2021'
OSM_BASE = BASE.parent / 'osm_boundary_review'


@lru_cache(maxsize=1)
def load_supplemental():
    path = OSM_BASE / 'recovery_manifest.json'
    if not path.exists():
        return {}, {}
    manifest = json.loads(path.read_text())
    decisions, features = {}, {}
    for row in manifest['decisions']:
        identity = (row['state'], row['district'])
        if identity in decisions or row['decision'] != 'accepted_reference_boundary':
            raise ValueError('Ambiguous or unapproved supplemental boundary')
        if Path(row['file']).name != row['file']:
            raise ValueError('Invalid supplemental filename')
        raw = (OSM_BASE / row['file']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('Supplemental boundary SHA256 mismatch')
        found = [r for r in json.loads(raw) if r.get('osm_type') == 'relation' and r['osm_id'] == row['relation_id']]
        if len(found) != 1:
            raise ValueError('Missing supplemental district relation')
        feature = found[0]
        tags = feature.get('extratags', {})
        if (tags.get('admin_level') != '5' or tags.get('ref:LGD:district') != row['lgd_code']
                or feature['address'].get('state') != row['state']):
            raise ValueError('Supplemental district identity mismatch')
        decisions[identity], features[identity] = row, feature
    return decisions, features


@lru_cache(maxsize=1)
def load_boundaries():
    path = BASE / 'recovery_manifest.json'
    if not path.exists():
        return {}, {}, {}
    manifest = json.loads(path.read_text())
    raw = (BASE / 'ADM2.geojson').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['source_sha256']:
        raise ValueError('Pinned recovery boundary SHA256 mismatch')
    features = {f['properties']['shapeID']: f for f in json.loads(raw)['features']}
    decisions = {}
    for row in manifest['decisions']:
        identity = (row['state'], row['district'])
        if identity in decisions or row['shape_id'] not in features:
            raise ValueError('Ambiguous or missing recovery boundary')
        if row['decision'] != 'accepted_reference_boundary':
            raise ValueError('Unapproved boundary in recovery manifest')
        decisions[identity] = row
    return decisions, features, manifest


def expected_reference_identity(row):
    identity = (row.get('state'), row.get('district'))
    supplemental, _ = load_supplemental()
    if identity in supplemental:
        r = supplemental[identity]
        return ('OpenStreetMap/snapshot/' + r['snapshot_date'] + '@' + r['sha256'],
                'OSM:relation/' + str(r['relation_id']))
    decisions, _, manifest = load_boundaries()
    if identity in decisions:
        return ('geoBoundaries/gbOpen/IND/ADM2/2021@' + manifest['source_sha256'],
                decisions[identity]['shape_id'])
    return None


def cache_reference_matches(entry, row):
    expected = expected_reference_identity(row)
    source = str(entry.get('aoi_source', ''))
    if expected is None:
        return not source.startswith(('geoBoundaries/', 'OpenStreetMap/'))
    return (source, str(entry.get('geometry_id', ''))) == expected


def resolve_reference_aoi(row, ee, spec):
    supplemental, osm_features = load_supplemental()
    identity = (row.get('state'), row.get('district'))
    osm = supplemental.get(identity)
    if osm is not None:
        geometry = ee.Geometry(osm_features[identity]['geojson'], proj='EPSG:4326', geodesic=False)
        return {
            'geometry': geometry, 'aoi_level': 'district', 'aoi_match_status': 'matched',
            'aoi_source': 'OpenStreetMap/snapshot/' + osm['snapshot_date'] + '@' + osm['sha256'],
            'geometry_id': 'OSM:relation/' + str(osm['relation_id']),
            'aoi_area_km2': float(geometry.area(maxError=spec.aoi_max_error_m).getInfo()) / 1e6,
            'aoi_boundary_year': None, 'aoi_match_method': 'reviewed_osm_district_lgd',
            'aoi_reference_name': osm_features[identity]['name'],
            'aoi_historical_boundary_verified': False,
            'aoi_match_evidence': osm['evidence'], 'aoi_boundary_note': osm['note'],
            'aoi_lgd_code': osm['lgd_code'],
        }
    decisions, features, manifest = load_boundaries()
    decision = decisions.get((row.get('state'), row.get('district')))
    if decision is None:
        return None
    feature = features[decision['shape_id']]
    geometry = ee.Geometry(feature['geometry'], proj='EPSG:4326', geodesic=False)
    return {
        'geometry': geometry, 'aoi_level': 'district', 'aoi_match_status': 'matched',
        'aoi_source': 'geoBoundaries/gbOpen/IND/ADM2/2021@' + manifest['source_sha256'],
        'geometry_id': decision['shape_id'],
        'aoi_area_km2': float(geometry.area(maxError=spec.aoi_max_error_m).getInfo()) / 1e6,
        'aoi_boundary_year': 2021, 'aoi_match_method': decision['method'],
        'aoi_reference_name': decision['reference_name'],
        'aoi_historical_boundary_verified': False,
        'aoi_match_evidence': decision['evidence'],
        'aoi_boundary_note': decision['note'],
    }
