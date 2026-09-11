import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from analyze_coverage_disparity import analyze, fit_nb, coefficients, adjusted_predictions, conclusion_candidate, selection_bias, FORMULAS, RESULT_COLUMNS


def synthetic(n=1500):
    rng = np.random.default_rng(762)
    flood = rng.uniform(0, 5, n)
    urban = rng.uniform(0, 1, n)
    mu = np.exp(-.5 + .6 * flood + 1.1 * urban)
    alpha = .7
    y = rng.negative_binomial(1 / alpha, 1 / (1 + alpha * mu))
    return pd.DataFrame({'event_district_id': ['ED' + str(i) for i in range(n)], 'event_id': ['E' + str(i // 3) for i in range(n)], 'source_record_id': ['S' + str(i // 3) for i in range(n)], 'state': ['state' + str(i % 25) for i in range(n)], 'district': ['district' + str(i) for i in range(n)], 'start_date': ['2020-01-01' if i % 2 else '2021-01-01' for i in range(n)], 'article_count': y, 'flood_area_km2': np.expm1(flood), 'log_flood_area': flood, 'urban_population_share': urban, 'satellite_source': [('S1', 'NDWI', 'SITS_NDWI')[i % 3] for i in range(n)], 'analysis_eligible': True, 'exclusion_reason': ''})


class CoverageModelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = synthetic()
        cls.fit, _ = fit_nb(cls.data, FORMULAS['model_2'])

    def test_recovers_effects_and_estimated_overdispersion_with_zero_counts(self):
        self.assertTrue((self.data.article_count == 0).any())
        self.assertGreater(self.data.article_count.var(), self.data.article_count.mean())
        self.assertAlmostEqual(self.fit.params['log_flood_area'], .6, delta=.1)
        self.assertAlmostEqual(self.fit.params['urban_population_share'], 1.1, delta=.2)
        self.assertAlmostEqual(self.fit.params['alpha'], .7, delta=.15)

    def test_irr_and_adjusted_confidence_intervals(self):
        rows = coefficients(self.fit, 'model_2')
        urban = next(row for row in rows if row['term'] == 'urban_population_share')
        self.assertAlmostEqual(urban['irr_10pp'], np.exp(.1 * self.fit.params['urban_population_share']))
        pred = adjusted_predictions(self.fit, self.data)
        self.assertTrue((pred.ci_low < pred.predicted_article_count).all())
        self.assertTrue((pred.ci_high > pred.predicted_article_count).all())
        self.assertTrue((np.diff(pred.predicted_article_count) > 0).all())

    def test_constant_and_insufficient_inputs_are_not_fitted(self):
        with self.assertRaisesRegex(ValueError, 'insufficient sample'):
            fit_nb(self.data.head(4), FORMULAS['model_2'])
        with self.assertRaisesRegex(ValueError, 'outcome variation'):
            fit_nb(self.data.assign(article_count=0), FORMULAS['model_2'])
        with self.assertRaisesRegex(ValueError, 'rank-deficient'):
            fit_nb(self.data.assign(urban_population_share=.5), FORMULAS['model_2'])

    def test_conclusion_reports_negative_and_uncertain_urban_effect(self):
        rows = [{'model': 'model_1', 'term': 'log_flood_area', 'coefficient': .5, 'p_value': .001, 'se_type': 'ordinary'}, {'model': 'model_2', 'term': 'urban_population_share', 'coefficient': -.5, 'p_value': .001, 'se_type': 'ordinary'}]
        self.assertIn('negative', conclusion_candidate(pd.DataFrame(rows)))
        rows[1].update(coefficient=.2, p_value=.4)
        self.assertIn('insufficient evidence', conclusion_candidate(pd.DataFrame(rows)))

    def test_analysis_reports_clusters_and_no_forced_secondary_fit(self):
        summary, results, _, predictions, bias = analyze(self.data.head(250))
        self.assertEqual(summary['n_analyzable'], 250)
        self.assertIn('state_clustered', set(results.se_type))
        self.assertIn('insufficient sample', summary['model_status']['source_event_robustness'])
        self.assertIsNotNone(predictions)
        self.assertEqual(bias['rows'].sum(), 250)

    def test_source_sensitivity_models_reported(self):
        summary, results, _, _, _ = analyze(self.data.head(250))
        statuses = summary['model_status']
        self.assertEqual(statuses['model_2_source_fe'], 'estimated (sensitivity)')
        self.assertIn('C(satellite_source)[T.S1]', set(results.term))
        for source in ['S1', 'NDWI', 'SITS_NDWI']:
            self.assertEqual(statuses[f'model_2_by_source_{source}'], 'estimated (sensitivity)')
        self.assertEqual(summary['satellite_source_counts'], {'S1': 84, 'NDWI': 83, 'SITS_NDWI': 83})
        self.assertTrue(any('not a correction' in note for note in summary['warnings']))
        small, _, _, _, _ = analyze(self.data.head(40))
        self.assertIn('insufficient sample', small['model_status']['model_2_by_source_S1'])
        single, _, _, _, _ = analyze(self.data.head(250).assign(satellite_source='S1'))
        self.assertIn('fewer than two', single['model_status']['model_2_source_fe'])
        with self.assertRaisesRegex(ValueError, 'satellite_source'):
            analyze(self.data.head(30).assign(satellite_source='S1(cloud)'))

    def test_no_data_is_reported_without_numeric_conclusion(self):
        table = self.data.head(5).assign(analysis_eligible=False, exclusion_reason='satellite_missing')
        summary, results, sample, predictions, bias = analyze(table)
        self.assertEqual(summary['n_analyzable'], 0)
        self.assertEqual(summary['spearman']['rho'], None)
        self.assertIsNone(predictions)
        self.assertEqual(list(results.columns), RESULT_COLUMNS)
        self.assertIn('No empirical conclusion', summary['conclusion_candidate'])

    def test_terciles_are_based_on_unique_districts(self):
        data = self.data.head(30)
        _, before = selection_bias(data)
        _, after = selection_bias(pd.concat([data, data.head(3)]))
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
