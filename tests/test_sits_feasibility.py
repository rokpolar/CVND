import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sits_feasibility as feas  # noqa: E402


def probe_rows(spec):
    """spec: list of (year, state, sr_status, l1c_status, new_water_km2)."""
    rows = []
    for i, (year, state, sr, l1c, water) in enumerate(spec):
        row = {'event_district_id': f'E{i}::d', 'state': state, 'year': year, 'aoi_status': 'matched',
               'grid_blocks': 4}
        for source, status in (('sr', sr), ('l1c', l1c)):
            row.update({f'{source}_status': status,
                        f'{source}_reason': 'ok' if status == 'ok' else 'no_post_imagery',
                        f'{source}_kept_tiles': 100 if status == 'ok' else None,
                        f'{source}_usable_frac': 0.5 if status == 'ok' else None,
                        f'{source}_new_water_c_km2': water if status == 'ok' else None})
        rows.append(row)
    rows.append({'event_district_id': 'X::district_missing', 'aoi_status': 'unresolved', 'year': 2020,
                 'state': 'S0'})
    return pd.DataFrame(rows)


class FeasibilityTests(unittest.TestCase):
    def test_classify_in_pipeline_order(self):
        self.assertEqual(feas.classify(3, 0, None, None), ('unavailable', 'no_post_imagery'))
        self.assertEqual(feas.classify(0, 2, None, None), ('unavailable', 'no_pre_imagery'))
        self.assertEqual(feas.classify(3, 2, None, None), ('unavailable', 'no_clear_baseline'))
        self.assertEqual(feas.classify(3, 2, [1], None), ('error', 'tile_probe_failed'))
        self.assertEqual(feas.classify(3, 2, [1], 0.2), ('unavailable', 'no_retained_tiles'))
        self.assertEqual(feas.classify(3, 2, [1], 12), ('ok', 'ok'))

    def test_baseline_candidates_need_a_composite(self):
        stats = {'clear_201906': 0.8, 'water_201906': 0.1, 'clear_201905': 0.9}
        counts = {'n_201906': 3, 'n_201905': 0}
        a, b = feas.baseline_candidates(stats, counts, [(2019, 6), (2019, 5)], [])
        self.assertEqual(a, [('2019-06', None, 0.8, 0.1)])

    def test_grid_cost(self):
        cost = feas.grid_cost(85.0, 26.0, 85.2, 26.1)
        self.assertEqual(cost['grid_tiles'], 32 * 18)
        self.assertEqual(cost['grid_blocks'], 2 * 2)

    def test_proceed_when_unavailability_is_low(self):
        frame = probe_rows([(2020, f'S{i % 6}', 'ok', 'ok', 5.0) for i in range(35)]
                           + [(2020, 'S0', 'unavailable', 'unavailable', None)] * 5)
        summary = feas.summarize(frame)
        self.assertEqual(summary['aoi_matched'], 40)
        self.assertEqual(summary['gate']['verdict'], 'proceed')
        self.assertEqual(summary['gate']['converter_sample'], 'expected_sufficient')
        self.assertEqual(summary['sources']['sr']['by_year']['2020']['unavailable'], 5)

    def test_year_caused_unavailability_suggests_l1c(self):
        frame = probe_rows([(2016, 'S1', 'unavailable', 'ok', 2.0)] * 20
                           + [(2015, 'S2', 'unavailable', 'unavailable', None)] * 10
                           + [(2021, f'S{i % 5}', 'ok', 'ok', 3.0) for i in range(20)])
        gate = feas.summarize(frame)['gate']
        self.assertEqual(gate['verdict'], 'consider_l1c')
        self.assertEqual(gate['basis_source'], 'l1c')
        self.assertAlmostEqual(gate['l1c_unavailable_rate'], 0.2)
        self.assertFalse(gate['l1c_still_above_max'])

    def test_non_year_unavailability_needs_a_decision(self):
        frame = probe_rows([(2021, 'S1', 'unavailable', 'unavailable', None)] * 20
                           + [(2021, 'S2', 'ok', 'ok', 0.5)] * 20)
        gate = feas.summarize(frame)['gate']
        self.assertEqual(gate['verdict'], 'unavailable_not_year')
        self.assertEqual(gate['converter_sample'], 'expected_insufficient')   # no new water >= 1 km²


if __name__ == '__main__':
    unittest.main()
