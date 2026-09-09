"""Source-group OOF NB2 scoring of observed district coverage (not causal labels)."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import subprocess
import warnings

import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson, spearmanr
from sklearn.model_selection import GroupKFold
import statsmodels.formula.api as smf

from analyze_coverage_disparity import MIN_OBSERVATIONS, fit_nb, prepare_analysis
from cvnd_layout import ROOT, data_path, output_path

FORMULA = 'article_count ~ log_flood_area + log_population + year_c'
NUMERIC_SCORES = ['expected_article_count_oof', 'alpha_oof', 'coverage_difference',
                  'coverage_ratio', 'pearson_residual', 'p_lower', 'p_upper',
                  'predictive_low_90', 'predictive_high_90']
DIAGNOSTIC_COLUMNS = ['model', 'fold_id', 'event_district_id', 'source_record_id',
                      'observed', 'expected', 'alpha', 'absolute_error',
                      'negative_log_probability', 'predictive_low_90',
                      'predictive_high_90', 'interval_covered', 'interval_width',
                      'observed_zero', 'predicted_zero_probability']
LIMITATIONS = [
    'Observed GDELT coverage under accessible-body and heuristic definitions, not socially deserved coverage, causal discrimination, or intentional neglect.',
    'Central 90% discrete prediction intervals are plug-in approximations; beta/alpha estimation uncertainty is not included. They are not confidence intervals for the mean.',
    'Candidate labels are exploratory alerts, not confirmed or multiplicity-adjusted discoveries. No quota or equal tail proportions are imposed.',
    'Census 2011 total district population is not affected or exposed population. Boundaries, observation selection, source dependence and satellite/news window differences remain limitations.',
    'Operational sample gates do not guarantee power. Marginal count variance exceeding its mean does not establish conditional overdispersion.',
]


@dataclass(frozen=True)
class Settings:
    min_rows: int = 50
    min_sources: int = 10
    min_train_rows: int = 30
    min_train_sources: int = 5
    rows_per_parameter: int = 5
    tail_threshold: float = .05
    n_splits: int = 5

    def __post_init__(self):
        for key in ['min_rows', 'min_sources', 'min_train_rows', 'min_train_sources', 'rows_per_parameter']:
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{key} must be a positive integer')
        if self.n_splits != 5:
            raise ValueError('The prespecified split is GroupKFold(n_splits=5)')
        if not 0 < self.tail_threshold < .5:
            raise ValueError('tail_threshold must be between 0 and 0.5')


def prepare_scoring(table):
    """Keep original values for export; validate eligible observations without repair."""
    if 'total_population' not in table:
        raise ValueError('Scoring input missing total_population')
    for key in ['event_district_id', 'source_record_id', 'analysis_eligible']:
        if key not in table:
            raise ValueError(f'Scoring input missing {key}')
    full = table.copy().reset_index(drop=True)
    ids = full.event_district_id.astype('string')
    if ids.isna().any() or ids.str.strip().eq('').any() or ids.duplicated().any():
        raise ValueError('Scoring requires unique nonempty event_district_id')
    if ids.ne(ids.str.strip()).any():
        raise ValueError('event_district_id contains surrounding whitespace')
    flags = full.analysis_eligible.astype(str).str.lower()
    if not flags.isin(['true', 'false', '1', '0']).all():
        raise ValueError('analysis_eligible must be explicitly True/False or 1/0')
    _, sample = prepare_analysis(full)
    pop = pd.to_numeric(sample.total_population, errors='coerce')
    if (~np.isfinite(pop) | pop.le(0)).any():
        raise ValueError('Eligible rows require finite total_population > 0')
    sources = sample.source_record_id.astype('string')
    if sources.isna().any() or sources.str.strip().eq('').any() or sources.ne(sources.str.strip()).any():
        raise ValueError('Eligible rows require nonempty source_record_id without surrounding whitespace')
    # Honor the join quality contract whenever its audit columns are supplied.
    checks = {'district_match_status': ['high', 'exact', 'resolved', 'matched'],
              'aoi_level': ['district'], 'aoi_match_status': ['matched', 'exact'],
              'satellite_status': ['observed', 'ok', 'OK'],
              'article_collection_status': ['complete'],
              'census_match_status': ['matched', 'exact', 'crosswalk', 'matched_crosswalk']}
    for column, allowed in checks.items():
        if column in sample and not sample[column].isin(allowed).all():
            raise ValueError(f'Eligible rows contradict join quality contract: {column}')
    if 'aoi_area_km2' in sample:
        area = pd.to_numeric(sample.aoi_area_km2, errors='coerce')
        if (~np.isfinite(area) | area.le(0) | sample.flood_area_km2.gt(area)).any():
            raise ValueError('Eligible rows contradict aoi_area_km2 contract')
    if 'census_year' in sample and not pd.to_numeric(sample.census_year, errors='coerce').eq(2011).all():
        raise ValueError('Eligible rows require Census 2011')
    if {'urban_population', 'rural_population'} & set(sample.columns):
        if not {'urban_population', 'rural_population'} <= set(sample.columns):
            raise ValueError('Incomplete Census population audit columns')
        urban = pd.to_numeric(sample.urban_population, errors='coerce')
        rural = pd.to_numeric(sample.rural_population, errors='coerce')
        valid = (np.isfinite(urban) & np.isfinite(rural) & urban.ge(0) & rural.ge(0)
                 & np.isclose(pop, urban + rural)
                 & np.isclose(sample.urban_population_share, urban / pop))
        if not valid.all():
            raise ValueError('Eligible rows have inconsistent Census population')
    for identifier in ['geometry_id', 'census_district_code']:
        if identifier in full:
            known = full[identifier].notna() & full[identifier].astype(str).str.strip().ne('')
            duplicates = full.loc[known].duplicated(['event_id', identifier], keep=False)
            if duplicates.reindex(sample.index, fill_value=False).any():
                raise ValueError(f'Eligible rows have ambiguous duplicate {identifier}')
    sample['source_record_id'] = sources.astype(str)
    sample['event_district_id'] = sample.event_district_id.astype(str)
    sample['log_population'] = np.log(pop / 1_000_000)
    sample['year_c'] = pd.to_datetime(sample.start_date).dt.year - 2020
    return full, sample.sort_values(['source_record_id', 'event_district_id'])


def nb_distribution(mu, alpha):
    mu = np.asarray(mu, dtype=float)
    if not np.isfinite(mu).all() or (mu <= 0).any() or not np.isfinite(alpha) or alpha <= 0:
        raise ValueError('NB2 requires finite positive mu and alpha')
    with np.errstate(over='ignore', invalid='ignore'):
        variance = mu + alpha * mu ** 2
    if not np.isfinite(variance).all():
        raise ValueError('NB2 predictive variance outside numeric range')
    n = 1.0 / alpha
    p = 1.0 / (1.0 + alpha * mu)
    if not np.isfinite(n) or n <= 0 or (p <= 0).any() or (p >= 1).any():
        raise ValueError('NB2 distribution parameters outside numeric range')
    return nbinom(n, p)


def score_predictions(y, mu, alpha, threshold=.05):
    y, mu = np.asarray(y, dtype=float), np.asarray(mu, dtype=float)
    dist = nb_distribution(mu, alpha)
    if not np.isfinite(y).all() or (y < 0).any() or (y % 1 != 0).any():
        raise ValueError('Counts must be finite nonnegative integers')
    lower, upper = dist.cdf(y), dist.sf(y - 1)
    result = pd.DataFrame({
        'expected_article_count_oof': mu, 'alpha_oof': alpha,
        'coverage_difference': y - mu, 'coverage_ratio': y / mu,
        'pearson_residual': (y - mu) / np.sqrt(mu + alpha * mu ** 2),
        'p_lower': lower, 'p_upper': upper,
        'predictive_low_90': dist.ppf(.05), 'predictive_high_90': dist.ppf(.95),
        'coverage_class': np.select([(lower <= threshold) & (y < mu),
                                     (upper <= threshold) & (y > mu)],
                                    ['relative_under_candidate', 'relative_over_candidate'],
                                    default='within_expected_range')})
    if not np.isfinite(result[NUMERIC_SCORES].to_numpy()).all():
        raise ValueError('Nonfinite score or prediction interval')
    return result


def fit_model(train, formula, family):
    if family != 'poisson':
        fit, notes = fit_nb(train, formula)
    else:
        model = smf.poisson(formula, data=train, missing='raise')
        if np.linalg.matrix_rank(model.exog) < model.exog.shape[1]:
            raise ValueError('rank-deficient Poisson design')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            fit = model.fit(method='bfgs', maxiter=500, disp=False)
        notes = list(dict.fromkeys(str(w.message) for w in caught))
    if not fit.mle_retvals.get('converged', False):
        raise ValueError('Maximum likelihood did not converge')
    if not np.isfinite(fit.params).all() or not np.isfinite(np.asarray(fit.cov_params())).all():
        raise ValueError('Nonfinite coefficients or covariance')
    return fit, notes


def diagnostic_rows(test, mu, alpha, family, fold):
    dist = poisson(mu) if family == 'poisson' else nb_distribution(mu, alpha)
    y = test.article_count.to_numpy()
    low, high = dist.ppf(.05), dist.ppf(.95)
    frame = pd.DataFrame({'model': family, 'fold_id': fold,
                          'event_district_id': test.event_district_id.to_numpy(),
                          'source_record_id': test.source_record_id.to_numpy(),
                          'observed': y, 'expected': mu, 'alpha': np.nan if alpha is None else alpha,
                          'absolute_error': np.abs(y - mu),
                          'negative_log_probability': -dist.logpmf(y),
                          'predictive_low_90': low, 'predictive_high_90': high,
                          'interval_covered': ((y >= low) & (y <= high)).astype(float),
                          'interval_width': high - low, 'observed_zero': (y == 0).astype(float),
                          'predicted_zero_probability': dist.pmf(0)})
    if not np.isfinite(frame.drop(columns=['model', 'event_district_id', 'source_record_id', 'alpha'])).all().all():
        raise ValueError('Nonfinite predictive diagnostics')
    return frame


def metrics(frame):
    columns = {'absolute_error': 'mae', 'negative_log_probability': 'mean_negative_log_predictive_probability',
               'interval_covered': 'coverage_90', 'interval_width': 'mean_interval_width_90',
               'observed_zero': 'observed_zero_rate', 'predicted_zero_probability': 'mean_predicted_zero_probability'}
    return {'n_rows': len(frame), 'n_sources': int(frame.source_record_id.nunique()),
            'row_weighted': frame[list(columns)].mean().rename(columns).to_dict(),
            'source_macro': frame.groupby('source_record_id')[list(columns)].mean().mean().rename(columns).to_dict()}


def calibration(frame):
    if frame.empty:
        return []
    frame = frame.copy()
    # Quantile edges depend only on OOF expected counts; equal values stay together.
    if frame.expected.nunique() == 1:
        frame['bin'] = 0
    else:
        frame['bin'] = pd.qcut(frame.expected, q=min(10, len(frame)), duplicates='drop', labels=False)
    grouped = frame.groupby('bin', observed=True)
    return grouped.agg(n=('observed', 'size'), expected_min=('expected', 'min'),
                       expected_max=('expected', 'max'), observed_mean=('observed', 'mean'),
                       expected_mean=('expected', 'mean')).reset_index().to_dict('records')


def score_coverage(table, settings=None, sensitivity_no_population=False):
    settings = settings or Settings()
    full, sample = prepare_scoring(table)
    single_year = sample.year_c.nunique() == 1
    formula = FORMULA.replace(' + year_c', '') if single_year else FORMULA
    formulas = {'nb2': formula, 'poisson': formula}
    if sensitivity_no_population:
        formulas['nb2_no_population'] = formula.replace(' + log_population', '')
    scores = full.copy()
    for col in NUMERIC_SCORES:
        scores[col] = np.nan
    scores['fold_id'] = pd.Series(pd.NA, index=scores.index, dtype='Int64')
    scores['extrapolation_flag'] = pd.Series(pd.NA, index=scores.index, dtype='boolean')
    scores['scoring_status'] = 'not_scored'
    scores['scoring_reason'] = 'excluded_by_input_contract'
    scores['coverage_class'] = 'not_scored'
    n_sources = int(sample.source_record_id.nunique())
    summary = {'settings': asdict(settings), 'formulas': formulas,
               'transforms': {'log_flood_area': 'log1p(flood_area_km2)', 'log_population': 'log(total_population / 1000000)', 'year_c': 'start_date.year - 2020'},
               'year_term_omitted': single_year,
               'existing_nb_fit_guards': {'min_rows': MIN_OBSERVATIONS, 'rows_per_parameter': 5, 'require_outcome_variation': True},
               'variance': 'mu + alpha * mu^2; alpha estimated by maximum likelihood',
               'n_total': len(full), 'n_eligible': len(sample), 'n_sources': n_sources,
               'n_input_sources': int(full.source_record_id.nunique()),
               'n_excluded': len(full) - len(sample), 'folds': [], 'limitations': LIMITATIONS,
               'exclusion_counts': full.exclusion_reason.fillna('').str.split(';').explode().loc[lambda x: x.ne('')].value_counts().to_dict(),
               'missing_counts': full[['article_count', 'flood_area_km2', 'total_population']].isna().sum().to_dict(),
               'extrapolation_definition': 'Any main-model predictor outside the training marginal min/max; this is not a joint-support test.',
               'interval': 'Central 90% plug-in count prediction interval: ppf(0.05), ppf(0.95)',
               'tail_rule': 'cdf(y) <= threshold and y < mu; sf(y-1) <= threshold and y > mu',
               'oof_test_assignment_counts': {}}
    diagnostics, alternate = [], []
    enough = len(sample) >= settings.min_rows and n_sources >= max(settings.min_sources, settings.n_splits)
    scores.loc[sample.index, 'scoring_reason'] = 'insufficient_data' if not enough else 'fold_fit_failed'
    if enough:
        assigned = pd.Series(0, index=sample.index)
        for fold, (train_pos, test_pos) in enumerate(GroupKFold(n_splits=5).split(sample, groups=sample.source_record_id)):
            train, test = sample.iloc[train_pos], sample.iloc[test_pos]
            train_sources, test_sources = set(train.source_record_id), set(test.source_record_id)
            if train_sources & test_sources:
                raise AssertionError('Source leakage in OOF split')
            assigned.loc[test.index] += 1
            scores.loc[test.index, 'fold_id'] = fold
            entry = {'fold_id': fold, 'n_train': len(train), 'n_test': len(test),
                     'n_train_sources': len(train_sources), 'n_test_sources': len(test_sources),
                     'train_source_ids': sorted(train_sources), 'test_source_ids': sorted(test_sources), 'models': {}}
            for family, current_formula in formulas.items():
                predictors = current_formula.split(' ~ ')[1].split(' + ')
                parameter_count = 1 + len(predictors) + (family != 'poisson')
                minimum = max(settings.min_train_rows, settings.rows_per_parameter * parameter_count)
                if family != 'poisson':
                    minimum = max(minimum, MIN_OBSERVATIONS, 5 * parameter_count)
                status = {'status': 'failed', 'converged': False, 'alpha': None, 'parameter_count': parameter_count,
                          'required_train_rows': minimum}
                try:
                    if len(train) < minimum or len(train_sources) < settings.min_train_sources:
                        raise ValueError('insufficient training rows or sources')
                    fit, notes = fit_model(train, current_formula, family)
                    mu = np.asarray(fit.predict(test), dtype=float)
                    if not np.isfinite(mu).all() or (mu <= 0).any():
                        raise ValueError('OOF means must be finite and positive')
                    alpha = float(fit.params['alpha']) if family != 'poisson' else None
                    status.update(converged=True, alpha=alpha, warnings=notes, coefficients=fit.params.to_dict())
                    diag = diagnostic_rows(test, mu, alpha, family, fold)
                    if family != 'poisson':
                        scored = score_predictions(test.article_count, mu, alpha, settings.tail_threshold)
                        scored.index = test.index
                        if family == 'nb2':
                            scores.loc[test.index, scored.columns] = scored
                            scores.loc[test.index, 'scoring_status'] = 'scored'
                            scores.loc[test.index, 'scoring_reason'] = 'oof_prediction_available'
                            scores.loc[test.index, 'extrapolation_flag'] = (test[predictors].lt(train[predictors].min()) | test[predictors].gt(train[predictors].max())).any(axis=1)
                        else:
                            scored['event_district_id'] = test.event_district_id
                            alternate.append(scored)
                    diagnostics.append(diag)
                    status.update(status='available', converged=True, alpha=alpha, warnings=notes,
                                  coefficients=fit.params.to_dict())
                except (ValueError, RuntimeError, np.linalg.LinAlgError, FloatingPointError, OverflowError, ZeroDivisionError) as exc:
                    status['reason'] = str(exc)
                    if family == 'nb2':
                        scores.loc[test.index, 'scoring_reason'] = 'fold_fit_failed: ' + str(exc)
                entry['models'][family] = status
            summary['folds'].append(entry)
        if not assigned.eq(1).all():
            raise AssertionError('Each eligible row must be held out exactly once')
        summary['oof_test_assignment_counts'] = assigned.value_counts().to_dict()
    diag = pd.concat(diagnostics, ignore_index=True) if diagnostics else pd.DataFrame(columns=DIAGNOSTIC_COLUMNS)
    n_scored = int(scores.scoring_status.eq('scored').sum())
    summary.update(n_scored=n_scored, status=('insufficient_data' if not enough else 'available' if n_scored == len(sample) else 'partially_available' if n_scored else 'unavailable'),
                   scoring_reason_counts=scores.scoring_reason.value_counts().to_dict(),
                   coverage_class_counts=scores.coverage_class.value_counts().to_dict())
    summary['diagnostics_available'] = {family: metrics(diag[diag.model == family]) for family in formulas}
    primary = diag[diag.model == 'nb2']
    comparison = diag[diag.model == 'poisson']
    common = set(primary.event_district_id) & set(comparison.event_district_id)
    summary['poisson_comparison_common_success'] = {
        'scope': 'Only test rows with both NB2 and Poisson predictions; source_macro averages within source, then equally across sources.',
        'n_rows': len(common), 'fraction_of_eligible': len(common) / len(sample) if len(sample) else None,
        **{family: metrics(diag[(diag.model == family) & diag.event_district_id.isin(common)]) for family in ['nb2', 'poisson']}}
    summary['calibration'] = {family: calibration(diag[diag.model == family]) for family in formulas}
    if sensitivity_no_population:
        alt = pd.concat(alternate) if alternate else pd.DataFrame(columns=['event_district_id'] + NUMERIC_SCORES + ['coverage_class'])
        for col in NUMERIC_SCORES + ['coverage_class']:
            scores['no_population_' + col] = scores.event_district_id.map(alt.set_index('event_district_id')[col])
        scores['no_population_coverage_class'] = scores.no_population_coverage_class.fillna('not_scored')
        paired = scores[scores.scoring_status.eq('scored') & scores.no_population_expected_article_count_oof.notna()]
        main_res, alt_res = paired.pearson_residual, paired.no_population_pearson_residual
        rho = spearmanr(main_res, alt_res).statistic if len(paired) > 1 and main_res.nunique() > 1 and alt_res.nunique() > 1 else None
        summary['sensitivity_no_population'] = {
            'n_common_rows': len(paired), 'n_common_sources': int(paired.source_record_id.nunique()),
            'rank_measure': 'Spearman correlation of signed OOF Pearson residuals', 'rank_correlation': rho,
            'sign_change_rate': (np.sign(main_res) != np.sign(alt_res)).mean() if len(paired) else None,
            'candidate_label_change_rate': (paired.coverage_class != paired.no_population_coverage_class).mean() if len(paired) else None,
            'label_transitions': paired.groupby(['coverage_class', 'no_population_coverage_class']).size().rename('n').reset_index().to_dict('records')}
    return scores, diag, summary


def json_ready(value):
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or value is pd.NA or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return value


def write_outputs(scores, diagnostics, summary, results_dir, output_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    scores.to_csv(results_dir / 'coverage_scores.csv', index=False)
    diagnostics.to_csv(results_dir / 'coverage_oof_diagnostics.csv', index=False)
    summary = json_ready(summary)
    (output_dir / 'coverage_scoring_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    for name in ['coverage_scoring_actual_vs_expected', 'coverage_scoring_calibration']:
        fig, ax = plt.subplots(figsize=(6, 4.5), constrained_layout=True)
        if summary['n_scored']:
            if name.endswith('actual_vs_expected'):
                valid = scores[scores.scoring_status == 'scored']
                x, y = valid.expected_article_count_oof, pd.to_numeric(valid.article_count)
                ax.scatter(x, y, s=14, alpha=.5)
            else:
                cal = pd.DataFrame(summary['calibration']['nb2'])
                x, y = cal.expected_mean, cal.observed_mean
                ax.plot(x, y, 'o-')
            limit = max(float(max(x)), float(max(y)), 1)
            ax.plot([0, limit], [0, limit], '--', color='gray', label='Observed = expected')
            ax.legend()
        else:
            ax.text(.5, .5, 'No valid OOF predictions\nNo empirical conclusion', ha='center', transform=ax.transAxes)
        ax.set(xlabel='OOF expected article count', ylabel='Observed article count' if name.endswith('actual_vs_expected') else 'Mean observed article count', title='NB2 observed coverage')
        fig.savefig(output_dir / (name + '.png'), dpi=200)
        plt.close(fig)
    report = ['# Relative coverage scoring', '',
              f"Status: {summary['status']}. Input rows: {summary['n_total']}; eligible: {summary['n_eligible']}; source events: {summary['n_sources']}; scored: {summary['n_scored']}.",
              '', f"Formula: `{summary['formulas']['nb2']}`. Estimated NB2 alpha; source-group five-fold OOF only.",
              '', 'No empirical conclusion is available.' if not summary['n_scored'] else 'Labels identify exploratory relative coverage candidates under the fitted observed-count distribution.',
              '', '## Settings and provenance', '', '```json', json.dumps({k: summary[k] for k in ['settings', 'transforms', 'input_sha256', 'git_sha', 'library_versions']}, indent=2), '```',
              '', '## OOF diagnostics', '', 'NB2/Poisson comparison uses common successful test rows only. Available-model diagnostics have separate coverage.',
              '', '```json', json.dumps({k: summary[k] for k in ['diagnostics_available', 'poisson_comparison_common_success', 'calibration', 'folds', 'scoring_reason_counts']}, indent=2), '```']
    if 'sensitivity_no_population' in summary:
        report += ['', '## Population sensitivity', '', '```json', json.dumps(summary['sensitivity_no_population'], indent=2), '```']
    report += ['', '## Interpretation limits', ''] + ['- ' + note for note in LIMITATIONS]
    (output_dir / 'coverage_scoring_report.md').write_text('\n'.join(report) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=data_path('district_flood_articles'))
    parser.add_argument('--results-dir', type=Path, default=data_path('coverage_scores').parent)
    parser.add_argument('--output-dir', type=Path, default=output_path('coverage_scoring_summary').parent)
    parser.add_argument('--sensitivity-no-population', action='store_true')
    for name in ['min_rows', 'min_sources', 'min_train_rows', 'min_train_sources', 'rows_per_parameter']:
        parser.add_argument('--' + name.replace('_', '-'), type=int, default=getattr(Settings(), name))
    parser.add_argument('--tail-threshold', type=float, default=.05)
    args = parser.parse_args(argv)
    # Invalidate only this scorer's artifacts before reading/fitting: a failed new
    # input must not leave an old successful scoring report or figure in place.
    artifacts = [(args.results_dir, 'coverage_scores.csv'), (args.results_dir, 'coverage_oof_diagnostics.csv')]
    artifacts += [(args.output_dir, 'coverage_scoring_' + suffix) for suffix in ['summary.json', 'report.md', 'actual_vs_expected.png', 'calibration.png']]
    if args.input.resolve() in {(directory / name).resolve() for directory, name in artifacts}:
        parser.error('Input cannot be a scorer output path')
    for directory, name in artifacts:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).unlink(missing_ok=True)
    try:
        settings = Settings(**{name: getattr(args, name) for name in asdict(Settings()) if name != 'n_splits'})
        payload = args.input.read_bytes()
        table = pd.read_csv(io.BytesIO(payload), dtype={'event_district_id': str, 'source_record_id': str, 'event_id': str})
        scores, diagnostics, summary = score_coverage(table, settings, args.sensitivity_no_population)
        try:
            sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            sha = None
        summary.update(input_path=str(args.input.resolve()), input_sha256=hashlib.sha256(payload).hexdigest(), git_sha=sha,
                       library_versions={name: importlib.metadata.version(name) for name in ['numpy', 'pandas', 'scipy', 'statsmodels', 'scikit-learn', 'matplotlib']})
        write_outputs(scores, diagnostics, summary, args.results_dir, args.output_dir)
    except Exception as exc:
        for directory, name in artifacts:
            (directory / name).unlink(missing_ok=True)
        (args.output_dir / 'coverage_scoring_summary.json').write_text(json.dumps({'status': 'error', 'reason': str(exc)}, allow_nan=False) + '\n')
        raise
    print(f"Coverage scoring: {summary['status']}; {summary['n_scored']}/{summary['n_eligible']} eligible rows scored ({summary['n_total']} input rows)")


if __name__ == '__main__':
    main()
