import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import boundary_recovery as br


class BoundaryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patch=patch.object(br,'BASE',self.root); self.patch.start()
        br.load_boundaries.cache_clear()
        self.osm_patch=patch.object(br,'OSM_BASE',self.root/'osm'); self.osm_patch.start()
        br.load_supplemental.cache_clear()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.patch.stop)
        self.addCleanup(br.load_boundaries.cache_clear)
        self.addCleanup(self.osm_patch.stop)
        self.addCleanup(br.load_supplemental.cache_clear)

    def fixture(self):
        raw=json.dumps({'features':[{'properties':{'shapeID':'1'},'geometry':{'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,0]]]}}]}).encode()
        (self.root/'ADM2.geojson').write_bytes(raw)
        row={'state':'A','district':'B','shape_id':'1','decision':'accepted_reference_boundary',
             'method':'reviewed_alias','reference_name':'Bee','evidence':'https://example.org','note':'Reference only'}
        manifest={'source_sha256':hashlib.sha256(raw).hexdigest(),'decisions':[row]}
        (self.root/'recovery_manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_missing_manifest_leaves_existing_resolver_alone(self):
        self.assertIsNone(br.resolve_reference_aoi({'state':'A','district':'B'},None,None))

    def test_other_state_and_typo_not_matched(self):
        self.fixture()
        for row in ({'state':'Other','district':'B'},{'state':'A','district':'B-typo'}):
            self.assertIsNone(br.resolve_reference_aoi(row,None,None))

    def test_corrupt_geometry_rejected(self):
        self.fixture(); (self.root/'ADM2.geojson').write_text('{}')
        with self.assertRaisesRegex(ValueError,'SHA256'): br.load_boundaries()

    def test_duplicate_decision_rejected(self):
        m=self.fixture(); m['decisions']*=2
        (self.root/'recovery_manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'Ambiguous'): br.load_boundaries()

    def test_unapproved_decision_rejected(self):
        m=self.fixture(); m['decisions'][0]['decision']='unresolved'
        (self.root/'recovery_manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'Unapproved'): br.load_boundaries()

    def test_provenance_and_historical_limitation(self):
        self.fixture()
        ee=SimpleNamespace(Geometry=lambda *a,**k:SimpleNamespace(area=lambda **k:SimpleNamespace(getInfo=lambda:2e6)))
        out=br.resolve_reference_aoi({'state':'A','district':'B'},ee,SimpleNamespace(aoi_max_error_m=10))
        self.assertEqual(out['geometry_id'],'1')
        self.assertEqual(out['aoi_area_km2'],2)
        self.assertEqual(out['aoi_boundary_year'],2021)
        self.assertFalse(out['aoi_historical_boundary_verified'])
        self.assertIn('2021@',out['aoi_source'])

    def test_cache_rejects_old_geometry_and_wrong_source(self):
        self.fixture()
        row={'state':'A','district':'B'}
        source,gid=br.expected_reference_identity(row)
        self.assertTrue(br.cache_reference_matches({'aoi_source':source,'geometry_id':gid},row))
        self.assertFalse(br.cache_reference_matches({'aoi_source':'FAO/GAUL/2015/level2','geometry_id':gid},row))
        self.assertFalse(br.cache_reference_matches({'aoi_source':source,'geometry_id':'wrong'},row))

    def test_cache_rejects_removed_reference_approval(self):
        self.fixture()
        self.assertFalse(br.cache_reference_matches({'aoi_source':'OpenStreetMap/snapshot/old'}, {'state':'Other','district':'B'}))

    def osm_fixture(self, level='5'):
        folder=self.root/'osm'; folder.mkdir()
        raw=json.dumps([{'osm_type':'relation','osm_id':42,'name':'B',
                         'extratags':{'admin_level':level,'ref:LGD:district':'123'},
                         'address':{'state':'A'},'geojson':{'type':'Polygon','coordinates':[]}}]).encode()
        (folder/'B.json').write_bytes(raw)
        row={'state':'A','district':'B','decision':'accepted_reference_boundary','relation_id':42,
             'file':'B.json','sha256':hashlib.sha256(raw).hexdigest(),'lgd_code':'123',
             'snapshot_date':'2026-09-12','evidence':'https://example.org','note':'Reference only'}
        (folder/'recovery_manifest.json').write_text(json.dumps({'decisions':[row]}))

    def test_osm_rejects_subdistrict(self):
        self.osm_fixture(level='6')
        with self.assertRaisesRegex(ValueError,'identity mismatch'): br.load_supplemental()

    def test_osm_checksum_is_pinned(self):
        self.osm_fixture(); (self.root/'osm/B.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'SHA256'): br.load_supplemental()

    def test_osm_provenance_does_not_claim_historical_year(self):
        self.osm_fixture()
        ee=SimpleNamespace(Geometry=lambda *a,**k:SimpleNamespace(area=lambda **k:SimpleNamespace(getInfo=lambda:3e6)))
        out=br.resolve_reference_aoi({'state':'A','district':'B'},ee,SimpleNamespace(aoi_max_error_m=10))
        self.assertIsNone(out['aoi_boundary_year'])
        self.assertEqual(out['geometry_id'],'OSM:relation/42')
        self.assertFalse(out['aoi_historical_boundary_verified'])
        self.assertTrue(br.cache_reference_matches(out,{'state':'A','district':'B'}))

if __name__=='__main__': unittest.main()
