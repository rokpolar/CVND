import sys
import unittest
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from district_recovery import apply_recovery, independent_recovery_evidence


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.base = pd.DataFrame([dict(event_id='E001', source_record_id='2020-0001-IND',
            state='Assam', start_date='2020-01-01', end_date='2020-01-02',
            district='district_missing', event_district_id='E001::district_missing',
            district_resolution_confidence='unresolved', district_resolution_evidence='[]',
            district_source='state_only', aoi_level='district', aoi_match_status='unresolved')])
        self.record = dict(event_id='E001', source_record_id='2020-0001', state='Assam',
            start_date='', end_date='', year='2020', canonical_district='Dhemaji',
            source_url='https://example.org/report', evidence_note='supplied evidence')

    def test_restore_deduplicate_and_remove_confidence(self):
        result = apply_recovery(self.base, pd.DataFrame([self.record, self.record]))
        self.assertEqual(result.district.tolist(), ['Dhemaji'])
        self.assertNotIn('district_resolution_confidence', result)

    def test_reject_wrong_event_date(self):
        with self.assertRaises(ValueError):
            apply_recovery(self.base, pd.DataFrame([{**self.record, 'start_date': '2021-01-01'}]))

    def test_drop_event_without_recovery(self):
        empty = pd.DataFrame(columns=self.record)
        result = apply_recovery(self.base, empty)
        self.assertTrue(result.empty)

    def test_news_informed_recovery_is_not_primary(self):
        evidence = pd.DataFrame([
            {**self.record, 'circularity_risk': 'none',
             'source_class': 'official_government'},
            {**self.record, 'canonical_district': 'Jorhat',
             'circularity_risk': 'news_used_for_geography_only',
             'source_class': 'official_quoted_media'},
            {**self.record, 'canonical_district': 'Kamrup',
             'circularity_risk': 'none',
             'source_class': 'secondary_quotes_government'},
        ])
        primary = apply_recovery(self.base, independent_recovery_evidence(evidence))
        sensitivity = apply_recovery(self.base, evidence)
        self.assertEqual(primary.district.tolist(), ['Dhemaji'])
        self.assertEqual(sensitivity.district.tolist(), ['Dhemaji', 'Jorhat', 'Kamrup'])
        self.assertNotIn('district_resolution_confidence', sensitivity)
        self.assertEqual(primary.iloc[0].district_resolution_circularity_risk, 'none')
