import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from join_district_flood_articles import build_district_table, qc_summary


class DistrictJoinTests(unittest.TestCase):
    def setUp(self):
        self.registry = pd.DataFrame([dict(event_district_id=f'E1::{d}', event_id='E1', source_record_id='F1', state='Assam', district=d, start_date='2020-01-01', aoi_level='district', district_resolution_confidence='high') for d in ['A', 'B', 'C']])
        self.flood = self.registry.copy().assign(flood_area_km2=[5, np.nan, 0], flood_ratio=[.05, np.nan, 0], aoi_area_km2=100, satellite_source='S1', satellite_status=['observed', 'failed', 'observed'], aoi_match_status='matched')
        self.articles = self.registry.copy().assign(final_article_count=[0, 0, 0], collection_status=['complete', 'complete', 'failed'], count_source='heuristic')
        self.cov = pd.DataFrame([dict(state='Assam', district=d, total_population=100, urban_population=20, rural_population=80, urban_population_share=.2, census_year=2011, source='official', match_status='matched') for d in ['A', 'B', 'C']])

    def test_zero_is_observed_missing_is_not_zero_and_all_rows_retained(self):
        table, exclusions = build_district_table(self.registry, self.flood, self.articles, self.cov)
        self.assertEqual(len(table), 3)
        self.assertEqual(len(exclusions), 2)
        self.assertEqual(table.loc[0, 'article_count'], 0)
        self.assertTrue(table.loc[0, 'analysis_eligible'])
        self.assertTrue(pd.isna(table.loc[1, 'flood_area_km2']))
        self.assertTrue(pd.isna(table.loc[2, 'article_count']))
        self.assertIn('article_collection_incomplete', table.loc[2, 'exclusion_reason'])
        self.assertEqual(qc_summary(table)['final_analyzable']['success'], 1)

    def test_duplicate_keys_fail_instead_of_multiplying_observations(self):
        with self.assertRaisesRegex(ValueError, 'unique'):
            build_district_table(self.registry, pd.concat([self.flood, self.flood.head(1)]), self.articles, self.cov)

    def test_ambiguous_census_is_excluded_and_not_arbitrarily_selected(self):
        table, _ = build_district_table(self.registry, self.flood, self.articles, pd.concat([self.cov, self.cov.head(1)]))
        self.assertEqual(table.loc[0, 'census_match_status'], 'ambiguous')
        self.assertTrue(pd.isna(table.loc[0, 'urban_population_share']))

    def test_state_aoi_and_stale_cache_rejected(self):
        with self.assertRaisesRegex(ValueError, 'stale'):
            build_district_table(self.registry, self.flood.assign(state='Another state'), self.articles, self.cov)
        table, _ = build_district_table(self.registry.assign(aoi_level='state'), self.flood, self.articles, self.cov)
        self.assertFalse(table.analysis_eligible.any())

    def test_missing_article_row_is_not_successful_zero(self):
        table, _ = build_district_table(self.registry, self.flood, self.articles.iloc[1:], self.cov)
        self.assertTrue(pd.isna(table.loc[0, 'article_count']))
        self.assertEqual(table.loc[0, 'article_collection_status'], 'not_executed')

    def test_invalid_flood_area_and_census_denominator_excluded(self):
        table, _ = build_district_table(self.registry, self.flood.assign(flood_area_km2=1000), self.articles, self.cov.assign(total_population=0))
        self.assertFalse(table.analysis_eligible.any())
        self.assertIn('aoi_area_invalid', table.loc[0, 'exclusion_reason'])
        self.assertIn('census_invalid', table.loc[0, 'exclusion_reason'])


if __name__ == '__main__':
    unittest.main()
