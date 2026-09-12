"""End-to-end offline contracts; all observations here are test fixtures."""
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import district_articles as da
from build_district_covariates import parse_census_table, project_to_events
from build_flood_area_table import build_flood_area_table
from flood_spec import SPEC_VERSION
from join_district_flood_articles import build_district_table


class ObservationContractTests(unittest.TestCase):
    def setUp(self):
        self.registry = pd.DataFrame([dict(event_district_id='E1::' + district.lower(), event_id='E1', source_record_id='S1', state='Odisha', district=district, start_date='2020-01-01', end_date='2020-01-03', aoi_level='district', aoi_match_status='pending', district_resolution_confidence='high') for district in ['Puri', 'Cuttack']])

    def article(self, district='Puri', **changes):
        row = dict(event_district_id='E1::' + district.lower(), event_id='E1', source_record_id='S1', state='Odisha', district=district, url='https://news.example/one', published_at='2020-01-02T00:00:00Z', district_evidence='gkg_location', locations_lower=f'3#{district}, Odisha, India#IN#', body_text='Flood waters reached homes.', document_status='ok')
        return {**row, **changes}

    def counts(self, rows, status='complete', registry=None):
        registry = self.registry if registry is None else registry
        with tempfile.TemporaryDirectory() as tmp:
            payload, manifest = Path(tmp)/'articles.gz', Path(tmp)/'manifest.json'
            with gzip.open(payload, 'wt') as handle:
                for row in rows:
                    handle.write(json.dumps(row) + '\n')
            da.write_collection_manifest(manifest, registry, status=status, article_payload_sha256=da.file_fingerprint(payload))
            return da.build_district_counts(registry, rows, manifest_path=manifest, article_payload_path=payload)

    def test_state_only_and_homonymous_other_state_never_count(self):
        for location in ['2#Odisha, India#IN#', '3#Puri, Bihar, India#IN#', '3#Puri, Bihar, India#IN#;2#Odisha, India#IN#']:
            result = self.counts([self.article(locations_lower=location)])
            self.assertTrue(result.final_article_count.eq(0).all())

    def test_same_article_counts_only_explicitly_mentioned_districts(self):
        rows = [self.article(d) for d in ['Puri', 'Cuttack']]
        self.assertTrue(self.counts(rows).final_article_count.eq(1).all())
        rows[1]['locations_lower'] = rows[0]['locations_lower']
        counts = self.counts(rows).set_index('district')
        self.assertEqual(counts.loc['Puri', 'final_article_count'], 1)
        self.assertEqual(counts.loc['Cuttack', 'final_article_count'], 0)

    def test_window_includes_onset_excludes_day_fourteen(self):
        for date, expected in [('2020-01-01',1),('2020-01-14T23:59:59Z',1),('2020-01-15',0),('2019-12-31',0)]:
            self.assertEqual(self.counts([self.article(published_at=date)]).final_article_count.sum(), expected)

    def test_missing_manifest_or_incomplete_text_never_becomes_zero(self):
        missing = da.build_district_counts(self.registry, [])
        self.assertTrue(missing.final_article_count.isna().all())
        for document in ['http_error', 'extract_weak', 'pending']:
            counts = self.counts([self.article(document_status=document)]).set_index('district')
            self.assertTrue(pd.isna(counts.loc['Puri', 'final_article_count']))
            self.assertEqual(counts.loc['Puri', 'query_collection_status'], 'complete')
        failed = self.counts([], status='failed')
        self.assertTrue(failed.final_article_count.isna().all())
        self.assertTrue(self.counts([]).final_article_count.eq(0).all())

    def test_title_fallback_requires_literal_district_and_state(self):
        base = self.article(district_evidence='title', locations_lower='2#Odisha, India#IN#')
        self.assertTrue(da.has_district_evidence({**base,'title':'Flood in Puri, Odisha'}))
        self.assertFalse(da.has_district_evidence({**base,'title':'Odisha flood'}))
        query = da.build_query(da.prepare_event_windows(self.registry), title_fallback=False)
        self.assertNotIn('g.title_lower,\n        CONCAT', query)
        query = da.build_query(da.prepare_event_windows(self.registry), title_fallback=True)
        self.assertIn('UNNEST(e.district_patterns)', query)
        self.assertEqual(da._literal_regex('A (B).'), r'A \(B\)\.')

    def test_stale_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp)/'manifest.json'
            da.write_collection_manifest(manifest, self.registry, status='complete', article_payload_sha256=da.article_payload_fingerprint([]))
            with self.assertRaisesRegex(ValueError,'registry'):
                da.build_district_counts(self.registry.assign(start_date='2021-01-01'),[],manifest_path=manifest)

    def test_census_zero_ambiguous_and_wrong_year(self):
        values = pd.DataFrame([dict(state='Odisha',district='Puri',total_population=100,urban_population=20,rural_population=80)])
        with self.assertRaisesRegex(ValueError, 'non-positive'):
            parse_census_table(values.assign(total_population=0,urban_population=0,rural_population=0))
        with self.assertRaisesRegex(ValueError, '2011'):
            parse_census_table(values.assign(census_year=2020))
        for invalid in [float('inf'),10.5]:
            with self.assertRaises(ValueError):
                parse_census_table(values.assign(urban_population=invalid))
        cov = parse_census_table(values)
        projected = project_to_events(pd.concat([cov,cov]),self.registry)
        self.assertEqual(projected.loc[0,'match_status'],'ambiguous')
        self.assertTrue(pd.isna(projected.loc[0,'urban_population_share']))
        projected = project_to_events(cov,pd.concat([self.registry,self.registry]))
        self.assertEqual(len(projected),2)

    def test_full_join_keeps_real_zero_and_excludes_missing(self):
        combined = self.registry.copy().assign(combined_km2=[0,None],aoi_area_km2=100,aoi_match_status='matched',satellite_source=['S1_TO_SITS','NONE'],spec_version=SPEC_VERSION)
        aoi = self.registry.copy().assign(aoi_match_status='matched',aoi_area_km2=100,spec_version=SPEC_VERSION)
        flood = build_flood_area_table(combined,self.registry,aoi)
        articles = self.counts([])
        cov = parse_census_table(pd.DataFrame([dict(state='Odisha',district=d,total_population=100,urban_population=20,rural_population=80) for d in ['Puri','Cuttack']]))
        table, excluded = build_district_table(self.registry,flood,articles,cov)
        self.assertEqual(len(table),2)
        self.assertEqual(len(excluded),1)
        self.assertEqual(table.loc[table.analysis_eligible,'article_count'].item(),0)
        self.assertEqual(table.loc[table.analysis_eligible,'flood_area_km2'].item(),0)


if __name__ == '__main__':
    unittest.main()
