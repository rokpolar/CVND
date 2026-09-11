"""Prespecified NB2 analysis of district news visibility and observed flood extent.

NB2 estimates dispersion by maximum likelihood; no composite scores or cutoffs
enter the primary models. Inference is associational, not causal.
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr
import statsmodels.formula.api as smf
from patsy import build_design_matrices

from cvnd_layout import data_path, output_path
from flood_spec import (CONVERTER_RULES, MEASURED_SOURCES, SATELLITE_SOURCES, SITS_SOURCES,
                        SPEC_VARIANTS)

FORMULAS = {
    'model_1': 'article_count ~ log_flood_area',
    'model_2': 'article_count ~ log_flood_area + urban_population_share',
    'model_3': 'article_count ~ log_flood_area + urban_population_share + C(year)',
}
# Sensitivity only: never enters conclusion_candidate.
SENSITIVITY_FORMULAS = {
    'model_2_source_fe': FORMULAS['model_2'] + ' + C(satellite_source)',
}
SOURCE_NOTE = ('Flood area is Sentinel-1 new water over the eligible AOI for every district under the interim routing '
               '(satellite_source S1), or, under sits_primary routing, SITS-NDWI on the retained clear tiles with Sentinel-1 '
               'converted to the SITS-NDWI scale (S1_TO_SITS) where SITS cannot measure the district; the satellite-source '
               'fixed effect, by-source and SITS-only subsamples are sensitivity analyses, not a correction.')
# Exclusions that belong to the satellite stage: a routing definition with its
# own area can make these rows analyzable.
SATELLITE_EXCLUSIONS = {'satellite_missing_or_invalid', 'satellite_source_invalid', 'aoi_area_invalid'}
ROUTING_NOTE = ('(a) legacy: pre-refactor routing (S1 whenever SITS was not run, a 60% cloud cut); (b) primary: the '
                'current routing (interim S1 for every district, or SITS primary with S1_TO_SITS); (c) the primary sample '
                'restricted to SITS sources (empty under the interim routing); (d) a Track A spec variant '
                'applied as the relative change of the routed sensor (NDWI for SITS rows, S1 for S1_TO_SITS rows): '
                'area_b x (variant + o) / (primary + o), a first-order approximation because Track B is not rerun '
                'under variants. Robust when |coef_a - coef_b| < half the width of the 95% CI of (b).')
# Fixed numerical eligibility rules, never tuned using coefficient direction.
MIN_OBSERVATIONS = 20
MIN_CLUSTERS = 20
MIN_SOURCE_EVENTS = 10
RESULT_COLUMNS = ['model', 'term', 'se_type', 'coefficient', 'standard_error', 'p_value', 'ci_low', 'ci_high', 'irr', 'irr_ci_low', 'irr_ci_high', 'irr_10pp', 'irr_10pp_ci_low', 'irr_10pp_ci_high', 'n', 'alpha']


def prepare_analysis(table):
    required = {'event_district_id', 'event_id', 'source_record_id', 'state', 'district', 'start_date', 'article_count', 'flood_area_km2', 'urban_population_share', 'satellite_source', 'analysis_eligible', 'exclusion_reason'}
    if required - set(table.columns):
        raise ValueError(f'Analysis input missing columns: {sorted(required - set(table.columns))}; run district join first')
    if table['event_district_id'].isna().any() or table['event_district_id'].duplicated().any():
        raise ValueError('Analysis input requires unique nonempty event_district_id')
    data = table.copy()
    eligible = data['analysis_eligible'].astype(str).str.lower().isin(['true', '1'])
    source = data['satellite_source']
    if not (source.isna() | source.isin(SATELLITE_SOURCES)).all():
        raise ValueError(f'satellite_source outside {SATELLITE_SOURCES}; rebuild the flood-area table')
    if (eligible & ~source.isin(MEASURED_SOURCES)).any():
        raise ValueError('Eligible rows require a measured satellite_source')
    for col in ['article_count', 'flood_area_km2', 'urban_population_share']:
        data[col] = pd.to_numeric(data[col], errors='coerce')
    valid = (np.isfinite(data[['article_count', 'flood_area_km2', 'urban_population_share']]).all(axis=1) & data['article_count'].ge(0) & data['article_count'].mod(1).eq(0) & data['flood_area_km2'].ge(0) & data['urban_population_share'].between(0, 1))
    dates = pd.to_datetime(data['start_date'], errors='coerce')
    valid &= dates.notna()
    if (eligible & ~valid).any():
        raise ValueError('Rows marked eligible contain invalid analysis values; rebuild district join')
    if (eligible & data['exclusion_reason'].fillna('').ne('')).any():
        raise ValueError('Eligible rows contain exclusion reasons')
    sample = data.loc[eligible].copy()
    sample['log_flood_area'] = np.log1p(sample['flood_area_km2'])
    sample['year'] = dates.loc[eligible].dt.year.astype(str)
    return data, sample


def fit_nb(data, formula):
    if len(data) < MIN_OBSERVATIONS:
        raise ValueError(f'insufficient sample: N={len(data)} < {MIN_OBSERVATIONS}')
    if data['article_count'].nunique() < 2:
        raise ValueError('insufficient outcome variation')
    model = smf.negativebinomial(formula, data=data, loglike_method='nb2', missing='raise')
    x = model.exog
    if np.linalg.matrix_rank(x) < x.shape[1]:
        raise ValueError('rank-deficient design: predictors cannot be identified')
    if len(data) < max(MIN_OBSERVATIONS, 5 * (x.shape[1] + 1)):
        raise ValueError('insufficient sample for number of model parameters')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        result = model.fit(method='bfgs', maxiter=500, disp=False)
    if not result.mle_retvals.get('converged', False):
        raise ValueError('NB2 maximum likelihood did not converge')
    if not np.isfinite(result.params).all() or not np.isfinite(result.bse).all() or (result.bse <= 0).any():
        raise ValueError('NB2 covariance or coefficient estimates are not reliable')
    if result.params['alpha'] <= 0:
        raise ValueError('NB2 dispersion estimate is not positive')
    return result, list(dict.fromkeys(str(w.message) for w in caught))


FIT_ERRORS = (ValueError, np.linalg.LinAlgError, FloatingPointError)


def estimate(name, formula, data, rows, notes, inference):
    """Fit one NB2 model and append ordinary rows, plus state-clustered rows when
    the fixed cluster gate is met. Raises FIT_ERRORS when the model is not estimable."""
    result, caught = fit_nb(data, formula)
    rows.extend(coefficients(result, name))
    notes.extend(f'{name}: {message}' for message in caught)
    groups = data['state']
    n_clusters = groups.nunique()
    if n_clusters >= MIN_CLUSTERS and len(data) > 2 * n_clusters:
        try:
            from statsmodels.stats.sandwich_covariance import cov_cluster
            covariance = cov_cluster(result, pd.factorize(groups)[0], use_correction=True)
            if not np.isfinite(covariance).all() or (np.diag(covariance) <= 0).any():
                raise ValueError('nonpositive/nonfinite clustered variance')
            rows.extend(coefficients(result, name, covariance, 'state_clustered', n_clusters - 1))
            inference[name] = (covariance, n_clusters - 1)
        except (ValueError, np.linalg.LinAlgError) as exc:
            notes.append(f'{name}: state-clustered SE unavailable: {exc}; ordinary SE used')
    else:
        notes.append(f'{name}: {n_clusters} state clusters / N={len(data)}; require >= {MIN_CLUSTERS} clusters and N > 2G; ordinary SE used and independence assumption is a limitation')
    return result


def source_sensitivity(sample, rows, notes, inference, statuses):
    """Satellite-source fixed effect and by-source Model 2 subsamples (sensitivity only)."""
    for name, formula in SENSITIVITY_FORMULAS.items():
        if sample['satellite_source'].nunique() < 2:
            statuses[name] = 'insufficient source variation: fewer than two satellite sources'
            continue
        try:
            estimate(name, formula, sample, rows, notes, inference)
            statuses[name] = 'estimated (sensitivity)'
        except FIT_ERRORS as exc:
            statuses[name] = str(exc)
    parameters = len(FORMULAS['model_2'].split(' ~ ')[1].split(' + ')) + 1
    minimum = max(MIN_OBSERVATIONS, 5 * (parameters + 1))
    subsets = [(f'model_2_by_source_{source}', sample[sample['satellite_source'] == source])
               for source in MEASURED_SOURCES]
    subsets.append(('model_2_sits_only', sample[sample['satellite_source'].isin(SITS_SOURCES)]))
    for name, subset in subsets:
        if subset.empty:
            continue
        if len(subset) < minimum:
            statuses[name] = f'insufficient sample: N={len(subset)} < {minimum}'
            continue
        try:
            estimate(name, FORMULAS['model_2'], subset, rows, notes, inference)
            statuses[name] = 'estimated (sensitivity)'
        except FIT_ERRORS as exc:
            statuses[name] = str(exc)


def definition_sample(full, area):
    """Rows eligible on every stage but the satellite one, with ``area`` as the
    flood area: the same registry, articles and Census rows for every routing."""
    reasons = full['exclusion_reason'].fillna('').astype(str).str.split(';')
    base = reasons.map(lambda items: {i for i in items if i} <= SATELLITE_EXCLUSIONS)
    data = full.copy()
    data['flood_area_km2'] = pd.to_numeric(area, errors='coerce')
    for col in ['article_count', 'urban_population_share', 'aoi_area_km2']:
        data[col] = pd.to_numeric(data[col], errors='coerce')
    dates = pd.to_datetime(data['start_date'], errors='coerce')
    ok = (base & np.isfinite(data[['article_count', 'flood_area_km2', 'urban_population_share']]).all(axis=1)
          & data['article_count'].ge(0) & data['article_count'].mod(1).eq(0)
          & data['flood_area_km2'].ge(0) & data['urban_population_share'].between(0, 1)
          & dates.notna() & data['flood_area_km2'].le(data['aoi_area_km2']))
    sample = data.loc[ok].copy()
    sample['log_flood_area'] = np.log1p(sample['flood_area_km2'])
    sample['year'] = dates.loc[ok].dt.year.astype(str)
    return sample


def variant_areas(sample, primary_track_a, variant_track_a, offset=CONVERTER_RULES.log_offset_km2):
    """Primary areas scaled by the variant's relative change of the routed sensor."""
    key = 'event_district_id'
    cols = ['area_s1_km2', 'area_s2_km2']
    joined = (sample[[key, 'flood_area_km2', 'satellite_source']]
              .merge(primary_track_a[[key] + cols], on=key, how='left')
              .merge(variant_track_a[[key] + cols], on=key, how='left', suffixes=('', '_variant')))
    sensor = np.where(joined['satellite_source'].isin(SITS_SOURCES), 'area_s2_km2', 'area_s1_km2')
    primary = np.where(sensor == 'area_s2_km2', joined['area_s2_km2'], joined['area_s1_km2']).astype(float)
    variant = np.where(sensor == 'area_s2_km2', joined['area_s2_km2_variant'],
                       joined['area_s1_km2_variant']).astype(float)
    return pd.Series(joined['flood_area_km2'].to_numpy() * (variant + offset) / (primary + offset),
                     index=sample.index)


def _model_2_terms(data):
    rows, notes, inference = [], [], {}
    result = estimate('model_2', FORMULAS['model_2'], data, rows, notes, inference)
    frame = pd.DataFrame(rows)
    se = 'state_clustered' if (frame.se_type == 'state_clustered').any() else 'ordinary'
    frame = frame[frame.se_type == se].set_index('term')
    urban, flood = frame.loc['urban_population_share'], frame.loc['log_flood_area']
    return {'status': 'estimated', 'n': int(result.nobs), 'se_type': se,
            'urban_coefficient': float(urban.coefficient), 'urban_ci': [float(urban.ci_low), float(urban.ci_high)],
            'urban_p': float(urban.p_value), 'log_area_coefficient': float(flood.coefficient),
            'log_area_ci': [float(flood.ci_low), float(flood.ci_high)]}


def routing_comparison(full, sample, variants=None):
    """Model 2 under the legacy routing, the new routing, SITS only and spec variants."""
    definitions = {'b_primary': sample,
                   'c_sits_only': sample[sample['satellite_source'].isin(SITS_SOURCES)]}
    if 'legacy_flood_area_km2' in full:
        definitions['a_legacy'] = definition_sample(full, full['legacy_flood_area_km2'])
    for name, (primary, variant) in (variants or {}).items():
        scaled = sample.copy()
        scaled['flood_area_km2'] = variant_areas(sample, primary, variant)
        scaled = scaled[np.isfinite(scaled['flood_area_km2']) & scaled['flood_area_km2'].ge(0)]
        scaled['log_flood_area'] = np.log1p(scaled['flood_area_km2'])
        definitions[f'd_{name}'] = scaled
    if 'a_legacy' in definitions:
        common = set(definitions['a_legacy']['event_district_id']) & set(sample['event_district_id'])
        definitions['a_legacy_common'] = definitions['a_legacy'][definitions['a_legacy']['event_district_id'].isin(common)]
        definitions['b_primary_common'] = sample[sample['event_district_id'].isin(common)]
    out = {'note': ROUTING_NOTE, 'variants_available': sorted((variants or {}).keys()),
           'variants_defined': sorted(SPEC_VARIANTS), 'definitions': {}}
    for name, data in definitions.items():
        try:
            out['definitions'][name] = _model_2_terms(data)
        except FIT_ERRORS as exc:
            out['definitions'][name] = {'status': str(exc), 'n': int(len(data))}
    a, b = out['definitions'].get('a_legacy', {}), out['definitions'].get('b_primary', {})
    if a.get('status') == 'estimated' and b.get('status') == 'estimated':
        diff = abs(a['urban_coefficient'] - b['urban_coefficient'])
        half_width = (b['urban_ci'][1] - b['urban_ci'][0]) / 2
        out['verdict'] = {
            'urban_coefficient_difference': diff, 'primary_ci_half_width': half_width,
            'result': ('legacy result is robust to the routing change' if diff < half_width
                       else 'sensor mixing biased the legacy urbanization coefficient'),
        }
    else:
        out['verdict'] = {'result': 'not assessable: legacy or primary Model 2 not estimated'}
    return out


def coefficients(result, name, covariance=None, se_type='ordinary', dof=None):
    names = list(result.params.index)
    cov = np.asarray(result.cov_params() if covariance is None else covariance)
    standard_errors = np.sqrt(np.diag(cov))
    # Cluster inference uses t(G-1); ordinary MLE uses normal asymptotics.
    if dof is None:
        distribution = norm
    else:
        from scipy.stats import t
        distribution = t(df=dof)
    critical = distribution.ppf(0.975)
    rows = []
    for i, term in enumerate(names):
        if term == 'alpha':
            continue
        beta, se = float(result.params[term]), float(standard_errors[i])
        lo, hi = beta - critical * se, beta + critical * se
        row = dict(model=name, term=term, se_type=se_type, coefficient=beta, standard_error=se, p_value=float(2 * distribution.sf(abs(beta / se))), ci_low=lo, ci_high=hi, irr=float(np.exp(beta)), irr_ci_low=float(np.exp(lo)), irr_ci_high=float(np.exp(hi)), n=int(result.nobs), alpha=float(result.params['alpha']), irr_10pp=np.nan, irr_10pp_ci_low=np.nan, irr_10pp_ci_high=np.nan)
        if term == 'urban_population_share':
            row.update(irr_10pp=float(np.exp(.1 * beta)), irr_10pp_ci_low=float(np.exp(.1 * lo)), irr_10pp_ci_high=float(np.exp(.1 * hi)))
        rows.append(row)
    return rows


def adjusted_predictions(result, data, covariance=None, dof=None):
    grid = pd.DataFrame({'urban_population_share': np.linspace(data['urban_population_share'].min(), data['urban_population_share'].max(), 101), 'log_flood_area': np.log1p(data['flood_area_km2'].median())})
    x = np.asarray(build_design_matrices([result.model.data.design_info], grid)[0])
    names = result.model.exog_names[:x.shape[1]]
    beta = result.params.loc[names].to_numpy()
    cov = np.asarray(result.cov_params() if covariance is None else covariance)[:x.shape[1], :x.shape[1]]
    eta = x @ beta
    variance = np.einsum('ij,jk,ik->i', x, cov, x)
    if not np.isfinite(variance).all() or (variance < -1e-9).any():
        raise ValueError('Invalid adjusted-mean covariance')
    se = np.sqrt(np.maximum(variance, 0))
    if dof is None:
        critical = norm.ppf(.975)
    else:
        from scipy.stats import t
        critical = t.ppf(.975, dof)
    grid['predicted_article_count'] = np.exp(eta)
    grid['ci_low'] = np.exp(eta - critical * se)
    grid['ci_high'] = np.exp(eta + critical * se)
    grid['flood_area_km2_fixed'] = data['flood_area_km2'].median()
    return grid


def selection_bias(table):
    """Define terciles using unique districts, avoiding event-frequency weighting."""
    districts = table[['state', 'district', 'urban_population_share']].drop_duplicates()
    if districts.duplicated(['state', 'district']).any():
        raise ValueError('Urbanization differs across observations of the same district')
    known = districts['urban_population_share'].dropna()
    edges = known.quantile([1/3, 2/3]).to_numpy() if len(known) else []
    if len(edges) != 2 or edges[0] == edges[1] or known.nunique() < 3:
        qc = table.copy()
        qc['urbanization_group'] = np.where(qc['urban_population_share'].notna(), 'known_unstratified', 'unknown')
        qc['_excluded'] = ~qc['analysis_eligible'].astype(str).str.lower().isin(['true', '1'])
        report = qc.groupby('urbanization_group').agg(rows=('event_district_id', 'size'), excluded=('_excluded', 'sum')).reset_index()
        report['exclusion_rate'] = report['excluded'] / report['rows']
        return report, 'insufficient distinct urbanization values for terciles; unknown Census matches remain a separate group'
    classified = table.copy()
    classified['urbanization_group'] = pd.cut(classified['urban_population_share'], [-np.inf, *edges, np.inf], labels=['low', 'medium', 'high']).astype(object).fillna('unknown')
    classified['_excluded'] = ~classified['analysis_eligible'].astype(str).str.lower().isin(['true', '1'])
    report = classified.groupby('urbanization_group', observed=True).agg(rows=('event_district_id', 'size'), excluded=('_excluded', 'sum')).reset_index()
    report['exclusion_rate'] = report['excluded'] / report['rows']
    return report, f'district-based urbanization tercile cutpoints: {edges.tolist()}; unknown Census matches cannot be assigned an urbanization level'


def conclusion_candidate(results):
    def effect(model, term):
        rows = results[(results.model == model) & (results.term == term)] if len(results) else results
        if rows.empty:
            return None
        cluster = rows[rows.se_type == 'state_clustered']
        return (cluster if not cluster.empty else rows[rows.se_type == 'ordinary']).iloc[0]
    flood = effect('model_1', 'log_flood_area')
    urban = effect('model_2', 'urban_population_share')
    if flood is None or urban is None:
        return 'Insufficient valid data or stable model fits to assess H1 and H2. No empirical conclusion is available.'
    h1 = flood.coefficient > 0 and flood.p_value < .05
    h2 = urban.coefficient > 0 and urban.p_value < .05
    if urban.coefficient < 0:
        evidence = 'statistically supported' if urban.p_value < .05 else 'uncertain'
        return f'The estimated urbanization association is negative ({evidence}): at similar observed flood extent, higher urbanization is associated with fewer expected articles. H2 is not supported. H1 is ' + ('supported.' if h1 else 'not supported.')
    if h1 and h2:
        return 'Larger observed flood extent is associated with more articles. At similar observed flood extent, higher urbanization is additionally associated with greater news visibility, consistent with an urban-rural coverage disparity.'
    if h1:
        return 'Flood extent is positively associated with article counts, but there is insufficient evidence of a consistent urbanization-related coverage disparity at similar observed flood extent.'
    if h2:
        return 'H1 is not supported. Higher urbanization is associated with greater expected coverage at similar observed flood extent; this supports H2 alone.'
    return 'The analysis provides insufficient evidence for H1 or H2; the hypothesized positive associations are not established.'


def analyze(table):
    full, sample = prepare_analysis(table)
    notes = ['Associational analysis: flood extent does not control all disaster impacts, outlet availability, population size, or media access.', 'Census 2011 and GAUL 2015 may not represent event-year district boundaries or urbanization.', 'GDELT-indexed district-explicit coverage is not all disaster reporting; location extraction and language coverage can affect selection.', 'District rows within a source flood and repeated districts may be dependent; state clustering is only a partial correction.']
    if 'date_precision' in full:
        imputed = full['date_precision'].fillna('').str.contains('start:month').sum()
        if imputed:
            notes.append(f'{imputed} registry onset dates are month-imputed; their 14-day news windows have timing uncertainty.')
    rows, fits, inference, statuses = [], {}, {}, {}
    for name, formula in FORMULAS.items():
        if name == 'model_3' and sample['year'].nunique() < 2:
            statuses[name] = 'insufficient sample: fewer than two years'
            continue
        try:
            fits[name] = estimate(name, formula, sample, rows, notes, inference)
            statuses[name] = 'estimated'
        except FIT_ERRORS as exc:
            statuses[name] = str(exc)
    source_sensitivity(sample, rows, notes, inference, statuses)
    notes.append(SOURCE_NOTE)
    counts = sample.groupby('source_record_id')['district'].size()
    multi = sample[sample['source_record_id'].isin(counts[counts >= 2].index)]
    n_source = multi['source_record_id'].nunique()
    if n_source >= MIN_SOURCE_EVENTS and len(multi) >= 5 * (n_source + 3):
        try:
            formula = FORMULAS['model_2'] + ' + C(source_record_id)'
            fit, caught = fit_nb(multi, formula)
            rows.extend(coefficients(fit, 'source_event_robustness'))
            statuses['source_event_robustness'] = f'estimated secondary unconditional source fixed-effects NB2; {n_source} source events'
            notes.extend(caught)
            notes.append('Source fixed-effects NB2 is secondary and susceptible to incidental-parameter bias; ordinary SE are reported.')
        except FIT_ERRORS as exc:
            statuses['source_event_robustness'] = str(exc)
    else:
        statuses['source_event_robustness'] = f'insufficient sample: {n_source} multi-district source events, {len(multi)} rows; require >= {MIN_SOURCE_EVENTS} groups and >= 5*(groups+3) rows'
    statuses['exposed_population_robustness'] = 'not implemented: no verified flood-mask × gridded-population input contract; area × average density is never used'
    corr = {'rho': None, 'p_value': None}
    if len(sample) >= 3 and sample['flood_area_km2'].nunique() > 1 and sample['article_count'].nunique() > 1:
        rho, p = spearmanr(sample['flood_area_km2'], sample['article_count'])
        corr = {'rho': float(rho), 'p_value': float(p)}
    distribution_columns = ['flood_area_km2', 'article_count', 'urban_population_share']
    summary = {'n_total': len(full), 'n_analyzable': len(sample), 'n_excluded': len(full) - len(sample), 'districts': len(sample[['state', 'district']].drop_duplicates()), 'parent_events': int(sample.event_id.nunique()), 'source_flood_events': int(sample.source_record_id.nunique()), 'satellite_source_counts': {str(k): int(v) for k, v in sample['satellite_source'].value_counts().items()}, 'sensitivity_formulas': SENSITIVITY_FORMULAS, 'spearman': corr, 'distributions': sample[distribution_columns].describe().to_dict(), 'missing_counts': {c: int(full[c].isna().sum()) for c in distribution_columns}, 'exclusion_counts': full['exclusion_reason'].fillna('').str.split(';').explode().loc[lambda s: s.ne('')].value_counts().to_dict(), 'model_status': statuses, 'formulas': FORMULAS, 'article_count_variance': float(sample.article_count.var()) if len(sample) > 1 else None, 'article_count_mean': float(sample.article_count.mean()) if len(sample) else None}
    results = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    bias, selection_note = selection_bias(full)
    notes.append(selection_note)
    qc_columns = {'district_match_status', 'aoi_match_status', 'census_match_status', 'satellite_status', 'article_collection_status'}
    if qc_columns.issubset(full.columns):
        from join_district_flood_articles import qc_summary
        qc_frame = full.copy()
        qc_frame['analysis_eligible'] = qc_frame['analysis_eligible'].astype(str).str.lower().isin(['true', '1'])
        summary['stage_qc'] = qc_summary(qc_frame)
    else:
        summary['stage_qc'] = {'status': 'QC columns not available in supplied analysis input'}
    summary['available_input_distributions'] = full[distribution_columns].describe().to_dict()
    summary['estimated_dispersion'] = {name: float(fit.params['alpha']) for name, fit in fits.items()}
    summary['warnings'] = notes
    summary['conclusion_candidate'] = conclusion_candidate(results)
    predictions = None
    if 'model_2' in fits:
        cov, dof = inference.get('model_2', (None, None))
        predictions = adjusted_predictions(fits['model_2'], sample, cov, dof)
    return summary, results, sample, predictions, bias


def write_figures(sample, predictions, figure1, figure2):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
    for path in [figure1, figure2]:
        path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.8, 4.2), constrained_layout=True)
    ax.scatter(np.log1p(sample.flood_area_km2), np.log1p(sample.article_count), color='#276779', alpha=.6, s=20, linewidth=0)
    ax.set(xlabel='log(1 + observed flood area in km²)', ylabel='log(1 + article count)')
    if sample.empty:
        ax.text(.5, .5, 'No analyzable observations', transform=ax.transAxes, ha='center')
    fig.savefig(figure1, dpi=300)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(5.8, 4.2), constrained_layout=True)
    if predictions is not None:
        ax.plot(predictions.urban_population_share, predictions.predicted_article_count, color='#276779')
        ax.fill_between(predictions.urban_population_share, predictions.ci_low, predictions.ci_high, color='#276779', alpha=.2, label='95% CI for expected count')
        ax.set_title(f'Observed flood area fixed at median: {predictions.flood_area_km2_fixed.iloc[0]:.2f} km²', fontsize=10)
        ax.legend(frameon=False, fontsize=9)
    else:
        ax.text(.5, .5, 'Model 2 unavailable\nNo adjusted effect estimated', transform=ax.transAxes, ha='center')
    ax.set(xlabel='District urban population share (2011)', ylabel='Expected article count in 14 days')
    fig.savefig(figure2, dpi=300)
    plt.close(fig)


def write_report(summary, results, bias, path):
    lines = ['# Coverage disparity results', '', f"N = {summary['n_analyzable']} district-event observations; {summary['districts']} districts; {summary['parent_events']} parent events; {summary['source_flood_events']} source floods.", f"Excluded: {summary['n_excluded']} of {summary['n_total']} registry rows.", f"Spearman rho = {summary['spearman']['rho']}; p = {summary['spearman']['p_value']}.", '', 'Primary model: log E[article_count] = intercept + beta_flood log(1 + flood_area_km2) + beta_urban urban_population_share. NB2 variance = mu + alpha * mu²; alpha is estimated.', '', 'M1/M2/M3 use the same complete-case sample. Fixed decision rule: positive coefficient and two-sided p < 0.05; prefer state-clustered inference when the prespecified cluster rule is met. No cutoff on urbanization enters the model.', '', '| Model / SE | Term | Coefficient (SE) | 95% CI | p | IRR [95% CI] | 10pp IRR [95% CI] |', '| --- | --- | --- | --- | --- | --- | --- |']
    for r in results.itertuples():
        irr10 = f'{r.irr_10pp:.3f} [{r.irr_10pp_ci_low:.3f}, {r.irr_10pp_ci_high:.3f}]' if pd.notna(r.irr_10pp) else '—'
        lines.append(f'| {r.model} / {r.se_type} | {r.term} | {r.coefficient:.4f} ({r.standard_error:.4f}) | [{r.ci_low:.4f}, {r.ci_high:.4f}] | {r.p_value:.4g} | {r.irr:.3f} [{r.irr_ci_low:.3f}, {r.irr_ci_high:.3f}] | {irr10} |')
    lines += ['', 'Flood IRR is per one-unit increase in log(1 + km²); the urbanization IRR is per 0→1 change, with 10 percentage points reported separately.', '', '## Model availability', '']
    lines += [f'- {name}: {status}' for name, status in summary['model_status'].items()]
    lines += ['', '## Descriptive distributions and missingness', '', '```json', json.dumps({k: summary[k] for k in ['distributions', 'available_input_distributions', 'missing_counts', 'exclusion_counts', 'stage_qc', 'estimated_dispersion', 'article_count_variance', 'article_count_mean']}, indent=2), '```', '', '## Selection check', '', '```', bias.to_string(index=False), '```', '', '## Conclusion candidate', '', summary['conclusion_candidate'], '', 'These results describe associations at similar observed flood extent; they do not establish intent or causation.', '', '## Data-quality warnings', '']
    lines += [f'- {note}' for note in summary['warnings']]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')


def load_variants():
    """{variant: (primary Track A, variant Track A)} for variants that were run."""
    from flood_spec import TEXT_DTYPES, spec_version, stale_spec_mask, variant_spec
    primary_path = data_path('district_flood_extent')
    if not primary_path.exists():
        return {}
    primary = pd.read_csv(primary_path, dtype=TEXT_DTYPES)
    primary = primary.loc[~stale_spec_mask(primary)]
    found = {}
    for name in SPEC_VARIANTS:
        path = data_path('district_flood_extent_variants') / f'flood_extent.{name}.csv'
        if path.exists():
            frame = pd.read_csv(path, dtype=TEXT_DTYPES)
            found[name] = (primary, frame.loc[~stale_spec_mask(frame, spec_version(variant_spec(name)))])
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=data_path('district_flood_articles'))
    parser.add_argument('--output-dir', type=Path, help='Override report/figure directory')
    parser.add_argument('--results-dir', type=Path, help='Override model and QC table directory')
    args = parser.parse_args(argv)
    if not args.input.exists():
        raise FileNotFoundError(f'Missing {args.input}; run district join. No synthetic research results are generated.')
    table = pd.read_csv(args.input)
    summary, results, sample, predictions, bias = analyze(table)
    full, _ = prepare_analysis(table)
    comparison = routing_comparison(full, sample, load_variants())
    def out(key):
        path = output_path(key)
        return args.output_dir / path.name if args.output_dir else path
    def data(key):
        path = data_path(key)
        return args.results_dir / path.name if args.results_dir else path
    for key, frame in [('coverage_model_results', results), ('district_selection_bias', bias)]:
        path = data(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    comparison_path = data('routing_comparison')
    comparison_path.write_text(json.dumps(json.loads(pd.Series(comparison).to_json()), indent=2) + '\n')
    print(f"Routing comparison: {comparison['verdict']['result']} -> {comparison_path}")
    pred_path = data('coverage_predictions')
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    if predictions is not None:
        predictions.to_csv(pred_path, index=False)
    else:
        pd.DataFrame(columns=['urban_population_share', 'predicted_article_count', 'ci_low', 'ci_high', 'flood_area_km2_fixed']).to_csv(pred_path, index=False)
    out('coverage_summary').parent.mkdir(parents=True, exist_ok=True)
    # Convert pandas NaN to JSON null for portable, strict JSON outputs.
    clean_summary = json.loads(pd.Series(summary).to_json())
    out('coverage_summary').write_text(json.dumps(clean_summary, indent=2, allow_nan=False) + '\n')
    write_figures(sample, predictions, out('flood_area_vs_articles'), out('urbanization_adjusted_coverage'))
    write_report(clean_summary, results, bias, out('paper_results'))
    print(f"Analyzable N={len(sample)}; report: {out('paper_results')}")
    print(summary['conclusion_candidate'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
