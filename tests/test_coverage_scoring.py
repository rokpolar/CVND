"""Synthetic fixtures validate mechanics only; never used as research artifacts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.stats import nbinom

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import score_coverage as scoring
from analyze_coverage_disparity import fit_nb

ROOT = Path(__file__).resolve().parents[1]


def synthetic(n=750):
    rng = np.random.default_rng(72381)
    flood = rng.uniform(0, 4, n)
    pop = rng.normal(0, .7, n)
    year = rng.integers(2017, 2024, n)
    mu = np.exp(.6 + .5 * flood + .4 * pop + .09 * (year - 2020))
    alpha = .65
    y = rng.negative_binomial(1 / alpha, 1 / (1 + alpha * mu))
    return pd.DataFrame({'event_district_id': [f'ED{i:06d}' for i in range(n)],
                         'event_id': [f'E{i // 2}' for i in range(n)],
                         'source_record_id': [f'S{i // 5:05d}' for i in range(n)],
                         'state': [f'State{i % 3}' for i in range(n)],
                         'district': [f'District{i}' for i in range(n)],
                         'start_date': [f'{yr}-03-01' for yr in year],
                         'article_count': y, 'flood_area_km2': np.expm1(flood),
                         'total_population': 1e6 * np.exp(pop), 'urban_population_share': .4,
                         'analysis_eligible': True, 'exclusion_reason': ''})


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = synthetic()
        cls.scores, cls.diag, cls.summary = scoring.score_coverage(cls.table, sensitivity_no_population=True)

    def test_coefficient_and_dispersion_recovery(self):
        _, sample = scoring.prepare_scoring(synthetic(5000))
        fit, _ = fit_nb(sample, scoring.FORMULA)
        for key, target, tolerance in [('Intercept', .6, .1), ('log_flood_area', .5, .05),
                                       ('log_population', .4, .07), ('year_c', .09, .03), ('alpha', .65, .07)]:
            self.assertAlmostEqual(fit.params[key], target, delta=tolerance)

    def test_group_separation_exactly_once(self):
        self.assertEqual(self.summary['status'], 'available')
        self.assertEqual(self.summary['oof_test_assignment_counts'], {1: len(self.table)})
        self.assertTrue(self.scores.groupby('source_record_id').fold_id.nunique().eq(1).all())
        for fold in self.summary['folds']:
            self.assertFalse(set(fold['train_source_ids']) & set(fold['test_source_ids']))
            self.assertEqual(fold['n_train'] + fold['n_test'], len(self.table))
            self.assertGreater(fold['models']['nb2']['alpha'], 0)
        self.assertEqual(len(self.diag[self.diag.model == 'nb2']), len(self.table))

    def test_shuffle_reproducible_by_key(self):
        shuffled, _, _ = scoring.score_coverage(self.table.sample(frac=1, random_state=4))
        columns = ['event_district_id', 'fold_id'] + scoring.NUMERIC_SCORES + ['coverage_class', 'extrapolation_flag']
        expected = self.scores[columns].sort_values('event_district_id').reset_index(drop=True)
        actual = shuffled[columns].sort_values('event_district_id').reset_index(drop=True)
        pd.testing.assert_frame_equal(expected, actual)

    def test_held_out_outcomes_do_not_change_own_predictions(self):
        changed = self.table.copy()
        held_out = self.scores.fold_id.eq(0)
        changed.loc[held_out, 'article_count'] += 100
        scored, _, _ = scoring.score_coverage(changed)
        for col in ['expected_article_count_oof', 'alpha_oof']:
            np.testing.assert_array_equal(scored.loc[held_out, col], self.scores.loc[held_out, col])

    def test_nb_parameterization_and_tail_boundaries(self):
        mu, alpha = np.array([.02, 4., 8.]), .6
        dist = scoring.nb_distribution(mu, alpha)
        np.testing.assert_allclose(dist.mean(), mu)
        np.testing.assert_allclose(dist.var(), mu + alpha * mu ** 2)
        y = [0, 0, 100]
        scores = scoring.score_predictions(y, mu, alpha)
        np.testing.assert_allclose(scores.p_upper, nbinom.sf(np.array(y) - 1, 1 / alpha, 1 / (1 + alpha * mu)))
        self.assertEqual(scores.p_upper.iloc[0], 1)
        self.assertEqual(scores.coverage_class.iloc[0], 'within_expected_range')
        self.assertEqual(scores.coverage_class.iloc[2], 'relative_over_candidate')
        under = scoring.score_predictions([0], [100], .1)
        self.assertEqual(under.coverage_class.iloc[0], 'relative_under_candidate')
        self.assertGreater(scores.p_upper.iloc[2], dist.sf(y)[2])
        np.testing.assert_allclose(scores.pearson_residual, (y - mu) / np.sqrt(mu + alpha * mu**2))
        np.testing.assert_allclose(scores.predictive_low_90, dist.ppf(.05))
        np.testing.assert_allclose(scores.predictive_high_90, dist.ppf(.95))

    def test_invalid_prediction_parameters(self):
        for mu, alpha in [(0, .5), (-1, .5), (np.inf, .5), (1, 0), (1, np.nan), (1e200, .5)]:
            with self.subTest(mu=mu, alpha=alpha), self.assertRaises(ValueError):
                scoring.score_predictions([0], [mu], alpha)

    def test_missing_is_not_zero_and_all_rows_preserved(self):
        table = self.table.copy()
        table.loc[0, ['article_count', 'flood_area_km2']] = np.nan
        table.loc[0, 'analysis_eligible'] = False
        table.loc[0, 'exclusion_reason'] = 'satellite_missing;article_incomplete'
        table.loc[1, 'article_count'] = 0
        scored, _, _ = scoring.score_coverage(table)
        pd.testing.assert_frame_equal(scored[table.columns], table)
        self.assertEqual(scored.loc[0, 'coverage_class'], 'not_scored')
        self.assertTrue(scored.loc[0, scoring.NUMERIC_SCORES].isna().all())
        self.assertEqual(scored.loc[1, 'scoring_status'], 'scored')
        self.assertEqual(scored.loc[1, 'coverage_ratio'], 0)

    def test_input_contract_errors(self):
        invalid = [('event_district_id', ''), ('source_record_id', '  '),
                   ('total_population', 0), ('total_population', np.inf),
                   ('article_count', -1), ('article_count', .5), ('article_count', np.nan),
                   ('flood_area_km2', np.inf), ('flood_area_km2', -1),
                   ('start_date', 'bad'), ('urban_population_share', 2),
                   ('exclusion_reason', 'failed'), ('analysis_eligible', 'maybe')]
        for col, value in invalid:
            frame = self.table.copy()
            frame[col] = frame[col].astype(object)
            frame.loc[0, col] = value
            with self.subTest(col=col, value=value), self.assertRaises(ValueError):
                scoring.prepare_scoring(frame)
        duplicate = self.table.copy()
        duplicate.loc[0, 'event_district_id'] = duplicate.loc[1, 'event_district_id']
        with self.assertRaises(ValueError):
            scoring.prepare_scoring(duplicate)
        with self.assertRaisesRegex(ValueError, 'quality contract'):
            scoring.prepare_scoring(self.table.assign(article_collection_status='incomplete'))
        with self.assertRaisesRegex(ValueError, 'aoi_area'):
            scoring.prepare_scoring(self.table.assign(aoi_area_km2=0))
        with self.assertRaisesRegex(ValueError, 'Census'):
            scoring.prepare_scoring(self.table.assign(census_year=2020))

    def test_insufficient_and_empty_never_fit(self):
        cases = [self.table.head(49), self.table.assign(source_record_id='only_one'),
                 self.table.assign(analysis_eligible=False, exclusion_reason='not_observed', article_count=np.nan, flood_area_km2=np.nan), self.table.head(0)]
        with patch.object(scoring, 'fit_model', side_effect=AssertionError('must not fit')):
            for table in cases:
                scored, diag, summary = scoring.score_coverage(table)
                self.assertEqual(summary['status'], 'insufficient_data')
                self.assertEqual(len(scored), len(table))
                self.assertTrue(diag.empty)
                self.assertTrue(scored[scoring.NUMERIC_SCORES].isna().all().all())
                self.assertTrue(scored.coverage_class.eq('not_scored').all())
                json.dumps(scoring.json_ready(summary), allow_nan=False)

    def test_train_gates_and_collinearity(self):
        for table, settings in [(self.table, scoring.Settings(min_train_rows=1000)),
                                (self.table, scoring.Settings(min_train_sources=1000)),
                                (self.table.assign(total_population=1e6), scoring.Settings())]:
            scores, _, summary = scoring.score_coverage(table, settings)
            self.assertEqual(summary['status'], 'unavailable')
            self.assertTrue(scores.expected_article_count_oof.isna().all())
        self.assertIn('rank-deficient', summary['folds'][0]['models']['nb2']['reason'])

    def test_single_year_omitted_globally_multiyear_fold_must_fail(self):
        _, _, summary = scoring.score_coverage(self.table.assign(start_date='2020-03-01'))
        self.assertNotIn('year_c', summary['formulas']['nb2'])
        table = self.table.assign(start_date='2020-03-01')
        table.loc[self.scores.fold_id.eq(0), 'start_date'] = '2021-03-01'
        scores, _, summary = scoring.score_coverage(table)
        self.assertIn('year_c', summary['formulas']['nb2'])
        self.assertTrue(scores.loc[scores.fold_id.eq(0), 'coverage_class'].eq('not_scored').all())
        self.assertEqual(summary['status'], 'partially_available')
        self.assertIn('rank-deficient', summary['folds'][0]['models']['nb2']['reason'])

    def test_partial_failure_and_common_success_comparison(self):
        original = scoring.fit_model
        calls = {'nb2': 0}

        def fail_one(train, formula, family):
            if family == 'nb2':
                calls['nb2'] += 1
                if calls['nb2'] == 1:
                    raise ValueError('injected convergence failure')
            return original(train, formula, family)

        with patch.object(scoring, 'fit_model', side_effect=fail_one):
            scores, diag, summary = scoring.score_coverage(self.table)
        self.assertEqual(summary['status'], 'partially_available')
        self.assertTrue(scores.loc[scores.fold_id.eq(0), scoring.NUMERIC_SCORES].isna().all().all())
        common = summary['poisson_comparison_common_success']
        self.assertEqual(common['nb2']['n_rows'], summary['n_scored'])
        self.assertEqual(common['poisson']['n_rows'], summary['n_scored'])
        self.assertGreater(len(diag[diag.model == 'poisson']), common['n_rows'])

    def test_all_fit_failures_do_not_use_fallback(self):
        with patch.object(scoring, 'fit_model', side_effect=ValueError('injected failure')):
            scores, diag, summary = scoring.score_coverage(self.table)
        self.assertEqual(summary['status'], 'unavailable')
        self.assertTrue(scores[scoring.NUMERIC_SCORES].isna().all().all())
        self.assertTrue(diag.empty)

    def test_unreliable_fit_rejected(self):
        from types import SimpleNamespace
        fake = SimpleNamespace(mle_retvals={'converged': False})
        with patch.object(scoring, 'fit_nb', return_value=(fake, [])), self.assertRaisesRegex(ValueError, 'converge'):
            scoring.fit_model(self.table, scoring.FORMULA, 'nb2')
        fake.mle_retvals['converged'] = True
        fake.params = pd.Series({'alpha': .5})
        fake.cov_params = lambda: np.array([[np.inf]])
        with patch.object(scoring, 'fit_nb', return_value=(fake, [])), self.assertRaisesRegex(ValueError, 'covariance'):
            scoring.fit_model(self.table, scoring.FORMULA, 'nb2')

    def test_nonfinite_predictions_fail_without_scores(self):
        from types import SimpleNamespace
        fake = SimpleNamespace(params=pd.Series({'alpha': .5}),
                               predict=lambda data: np.full(len(data), np.inf))
        with patch.object(scoring, 'fit_model', return_value=(fake, [])):
            scores, diag, summary = scoring.score_coverage(self.table)
        self.assertEqual(summary['status'], 'unavailable')
        self.assertTrue(scores[scoring.NUMERIC_SCORES].isna().all().all())
        self.assertTrue(diag.empty)
        self.assertIn('finite and positive', summary['folds'][0]['models']['nb2']['reason'])

    def test_extrapolation_uses_only_training_ranges(self):
        _, sample = scoring.prepare_scoring(self.table)
        for entry in self.summary['folds']:
            train = sample[sample.source_record_id.isin(entry['train_source_ids'])]
            test = sample[sample.source_record_id.isin(entry['test_source_ids'])]
            cols = ['log_flood_area', 'log_population', 'year_c']
            expected = (test[cols].lt(train[cols].min()) | test[cols].gt(train[cols].max())).any(axis=1)
            pd.testing.assert_series_equal(self.scores.loc[test.index, 'extrapolation_flag'].astype(bool), expected, check_names=False)

    def test_settings_and_model_parameter_gates(self):
        for kwargs in [{'tail_threshold': 0}, {'tail_threshold': .5}, {'min_rows': 0},
                       {'min_sources': 1.5}, {'n_splits': 4}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                scoring.Settings(**kwargs)
        _, _, summary = scoring.score_coverage(self.table, scoring.Settings(rows_per_parameter=130))
        self.assertEqual(summary['status'], 'unavailable')
        status = summary['folds'][0]['models']['nb2']
        self.assertEqual(status['parameter_count'], 5)
        self.assertEqual(status['required_train_rows'], 650)
        self.assertEqual(summary['folds'][0]['models']['poisson']['status'], 'available')

    def test_metrics_source_macro_is_not_row_weighted(self):
        frame = self.diag[self.diag.model == 'nb2'].head(7).copy()
        frame['source_record_id'] = ['A'] * 6 + ['B']
        frame['absolute_error'] = [0] * 6 + [14]
        result = scoring.metrics(frame)
        self.assertEqual(result['row_weighted']['mae'], 2)
        self.assertEqual(result['source_macro']['mae'], 7)
        self.assertEqual(sum(row['n'] for row in scoring.calibration(frame)), 7)

    def test_diagnostics_match_direct_likelihood(self):
        frame = self.diag[self.diag.model == 'nb2']
        expected = -nbinom.logpmf(frame.observed, 1 / frame.alpha, 1 / (1 + frame.alpha * frame.expected))
        np.testing.assert_allclose(frame.negative_log_probability, expected)
        self.assertEqual(self.summary['poisson_comparison_common_success']['n_rows'], len(self.table))
        self.assertEqual(sum(row['n'] for row in self.summary['calibration']['nb2']), len(self.table))

    def test_sensitivity_keeps_main_scores(self):
        scores, _, _ = scoring.score_coverage(self.table)
        pd.testing.assert_frame_equal(scores, self.scores[scores.columns])
        sensitivity = self.summary['sensitivity_no_population']
        self.assertEqual(sensitivity['n_common_rows'], len(self.table))
        self.assertTrue(-1 <= sensitivity['rank_correlation'] <= 1)
        self.assertEqual(sum(row['n'] for row in sensitivity['label_transitions']), len(self.table))

    def test_cli_null_outputs_and_stale_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, results, outputs = root / 'input.csv', root / 'results', root / 'outputs'
            table = self.table.head(7).assign(analysis_eligible=False, exclusion_reason='not_observed', article_count=np.nan, flood_area_km2=np.nan)
            table.to_csv(source, index=False)
            command = [sys.executable, str(ROOT / 'src/score_coverage.py'), '--input', str(source), '--results-dir', str(results), '--output-dir', str(outputs), '--sensitivity-no-population']
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (outputs / 'coverage_scoring_summary.json').read_text()
            self.assertNotIn('NaN', text)
            self.assertNotIn('Infinity', text)
            summary = json.loads(text)
            self.assertEqual(summary['status'], 'insufficient_data')
            self.assertIsNone(summary['diagnostics_available']['nb2']['row_weighted']['mae'])
            self.assertEqual(len(summary['input_sha256']), 64)
            read = pd.read_csv(results / 'coverage_scores.csv')
            self.assertEqual(len(read), len(table))
            self.assertTrue(read[scoring.NUMERIC_SCORES].isna().all().all())
            self.assertEqual(len(list(outputs.glob('*.png'))), 2)
            self.assertTrue((outputs / 'coverage_scoring_report.md').exists())
            pd.DataFrame({'bad': [1]}).to_csv(source, index=False)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads((outputs / 'coverage_scoring_summary.json').read_text())['status'], 'error')
            self.assertFalse(list(outputs.glob('*.png')))
            self.assertFalse((results / 'coverage_scores.csv').exists())

    def test_populated_figures_and_output_schemas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = dict(self.summary, input_sha256='synthetic-test-only', git_sha=None, library_versions={})
            scoring.write_outputs(self.scores, self.diag, summary, root, root)
            for name in ['coverage_scores.csv', 'coverage_oof_diagnostics.csv', 'coverage_scoring_actual_vs_expected.png', 'coverage_scoring_calibration.png']:
                self.assertGreater((root / name).stat().st_size, 100)

    def test_offline_runner_and_skip_analysis(self):
        import os
        env = dict(os.environ, PYTHON=sys.executable)
        result = subprocess.run(['bash', 'scripts/run_pipeline.sh', '--dry-run'], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('src/score_coverage.py', result.stdout)
        env['SKIP_ANALYSIS'] = '1'
        result = subprocess.run(['bash', 'scripts/run_pipeline.sh', '--dry-run'], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('src/score_coverage.py', result.stdout)
        self.assertNotIn('src/analyze_coverage_disparity.py', result.stdout)


if __name__ == '__main__':
    unittest.main()
