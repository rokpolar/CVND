import sys
import unittest
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from reuse_state_articles import candidates


class ReuseTests(unittest.TestCase):
    def test_window_identity_and_state(self):
        window = dict(source_record_id='2017-001-IND', state='Gujarat',
                      query_start=date(2017, 6, 1), query_end_exclusive=date(2017, 6, 15))
        row = dict(source_record_id='2017-001-IND', state='Gujarat', published_at='2017-06-01')
        self.assertEqual(candidates(row, [window]), [window])
        self.assertEqual(candidates({**row, 'published_at': '2017-06-14T23:59:59Z'}, [window]), [window])
        for change in ({'published_at': '2017-06-15'}, {'published_at': None},
                       {'published_at': 'invalid'}, {'state': 'Punjab'},
                       {'source_record_id': 'other'}):
            self.assertEqual(candidates({**row, **change}, [window]), [])


if __name__ == '__main__':
    unittest.main()
