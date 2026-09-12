import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from build_district_covariates import apply_census_recovery


class CensusRecoveryTests(unittest.TestCase):
    def run_recovery(self, **changes):
        record = dict(state='Assam', district='Majuli', census_year=2011,
                      method='official_retabulation', total_population=100,
                      urban_population=0, rural_population=100,
                      event_ids=['E1'], source_id='official', notes='Official 2011 table')
        record.update(changes)
        events = pd.DataFrame([dict(state='Assam', district='Majuli', event_id='E1', start_date='2020-01-01')])
        result = pd.DataFrame([dict(state='Assam', district='Majuli', match_status='unmatched')])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'recovery.json'
            path.write_text(json.dumps(dict(schema_version=1,
                sources={'official': {'url': 'https://example.gov.in/census'}}, records=[record])))
            return apply_census_recovery(result, events, pd.DataFrame(), path).iloc[0]

    def test_actual_zero_urban_preserved(self):
        row = self.run_recovery()
        self.assertEqual(row.urban_population_share, 0)
        self.assertEqual(row.total_population, 100)
        self.assertEqual(row.match_status, 'matched_crosswalk')
        self.assertIn('retabulated:', row.census_district_code)

    def test_inconsistent_total_rejected(self):
        with self.assertRaises(ValueError):
            self.run_recovery(total_population=101)

    def test_missing_population_rejected(self):
        with self.assertRaises(ValueError):
            self.run_recovery(urban_population=None)

    def test_wrong_year_rejected(self):
        with self.assertRaises(ValueError):
            self.run_recovery(census_year=2021)

    def test_unreviewed_event_stays_missing(self):
        self.assertEqual(self.run_recovery(event_ids=['E2']).match_status, 'unmatched')

    def test_post_reorganisation_event_cannot_use_old_boundary(self):
        self.assertEqual(self.run_recovery(valid_until='2016-10-11').match_status, 'unmatched')

    def test_future_boundary_cannot_apply_early(self):
        self.assertEqual(self.run_recovery(valid_from='2021-01-01').match_status, 'unmatched')

    def test_parent_proxy_rejected(self):
        with self.assertRaises(ValueError):
            self.run_recovery(method='parent_proxy')


if __name__ == '__main__':
    unittest.main()
