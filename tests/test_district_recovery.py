import sys
import unittest
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from district_recovery import apply_recovery


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
