import os
import re
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

os.makedirs('outputs', exist_ok=True)
plt.rcParams.update({
    'font.family':   'DejaVu Sans',
    'font.size':     11,
    'axes.titlesize': 13,
    'axes.titleweight': 'bold',
    'figure.dpi':    150,
})

COLORS = {'High': '#2ecc71', 'Middle': '#f39c12', 'Low': '#e74c3c'}
INCOME_ORDER = ['High', 'Middle', 'Low']
EXPECTED_COVERAGE_PATH = 'data/expected_coverage.csv'


def _save_plot_csv(csv_path: str, df: pd.DataFrame) -> None:
    df.to_csv(csv_path, index=False)
    print(f"  SAVED: {csv_path}")


def plot_observed_vs_expected():
    if not os.path.exists(EXPECTED_COVERAGE_PATH):
        print("  SKIP Plot 5: waiting for expected_coverage.csv")
        return

    df = pd.read_csv(EXPECTED_COVERAGE_PATH)
    plot_df = df[
        ['event_id', 'state', 'income_group', 'observed', 'expected', 'log_ratio']
    ].copy()
    plot_df['income_group'] = pd.Categorical(
        plot_df['income_group'], categories=INCOME_ORDER, ordered=True
    )
    plot_df = plot_df.sort_values(['income_group', 'event_id'])
    _save_plot_csv('outputs/plot5_observed_vs_expected.csv', plot_df)

    fig, ax = plt.subplots(figsize=(8, 8))
    for income in INCOME_ORDER:
        grp = df[df['income_group'] == income]
        if grp.empty:
            continue
        ax.scatter(grp['expected'], grp['observed'],
                   label=f'{income} income',
                   color=COLORS.get(income, 'gray'),
                   s=70, alpha=0.85, edgecolors='white', linewidth=0.5, zorder=3)

    lim = max(df['expected'].max(), df['observed'].max()) * 1.05
    ax.plot([0, lim], [0, lim], 'k--', alpha=0.35, linewidth=1.2, label='y = expected')
    ax.set_xlabel('Expected MSS (μ̂)', labelpad=8)
    ax.set_ylabel('Observed MSS (y)', labelpad=8)
    ax.set_title('Calibration: Observed vs Expected MSS\n'
                 'AHP-weighted media severity vs Gaussian severity model')
    ax.legend(framealpha=0.9)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    plt.tight_layout()
    out = 'outputs/plot5_observed_vs_expected.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {out}")


def plot_log_ratio_histogram():
    if not os.path.exists(EXPECTED_COVERAGE_PATH):
        print("  SKIP Plot 6: waiting for expected_coverage.csv")
        return

    df = pd.read_csv(EXPECTED_COVERAGE_PATH)
    bins = 25
    counts, edges = np.histogram(df['log_ratio'], bins=bins)
    hist_df = pd.DataFrame({
        'bin_start': edges[:-1],
        'bin_end': edges[1:],
        'count': counts,
    })
    _save_plot_csv('outputs/plot6_log_ratio_histogram.csv', hist_df)

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.hist(df['log_ratio'], bins=bins, color='#5c6bc0', edgecolor='white', alpha=0.9)
    ax.axvline(0, color='black', linestyle='--', linewidth=1.0, alpha=0.6)
    ax.set_xlabel('log_ratio = ln((y+1e-4)/(μ̂+1e-4))', labelpad=8)
    ax.set_ylabel('Number of events', labelpad=8)
    ax.set_title('Residual Distribution (log ratio)\n'
                 'Continuous metric; under_flag = log_ratio<0; '
                 'severity_tier low = bottom tertile')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    out = 'outputs/plot6_log_ratio_histogram.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {out}")


def plot_log_ratio_ranking():
    if not os.path.exists(EXPECTED_COVERAGE_PATH):
        print("  SKIP Plot 7: waiting for expected_coverage.csv")
        return

    df = pd.read_csv(EXPECTED_COVERAGE_PATH).sort_values('log_ratio')
    # Show extremes only for readability
    show = pd.concat([df.head(20), df.tail(20)]).drop_duplicates('event_id')
    rank_cols = [
        'event_id', 'state', 'income_group', 'observed', 'expected',
        'log_ratio', 'under_flag', 'severity_tier', 'rank_undercovered',
    ]
    rank_df = show[[c for c in rank_cols if c in show.columns]].copy()
    rank_df['bar_label'] = rank_df['state'] + ' (' + rank_df['event_id'] + ')'
    rank_df['bar_color'] = np.where(rank_df['log_ratio'] < 0, 'under', 'over')
    rank_df = rank_df.sort_values('log_ratio')
    _save_plot_csv('outputs/plot7_log_ratio_ranking.csv', rank_df)

    labels = rank_df['bar_label']
    colors = ['#e74c3c' if v < 0 else '#2ecc71' for v in rank_df['log_ratio']]

    fig, ax = plt.subplots(figsize=(11, 9))
    ax.barh(labels, rank_df['log_ratio'], color=colors, zorder=3)
    ax.axvline(0, color='black', linestyle='--', linewidth=0.9, alpha=0.5)
    ax.set_xlabel('log_ratio', labelpad=8)
    ax.set_title('Coverage Imbalance Ranking (extremes)\n'
                 'Continuous log_ratio; under = log_ratio<0; '
                 'red tail ≈ severity_tier low (tertile)\n'
                 'Not ground-truth media bias — GDELT vs sparse severity model')
    ax.grid(axis='x', alpha=0.3, zorder=0)
    plt.tight_layout()
    out = 'outputs/plot7_log_ratio_ranking.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {out}")


def plot_log_ratio_by_income():
    if not os.path.exists(EXPECTED_COVERAGE_PATH):
        print("  SKIP Plot 8: waiting for expected_coverage.csv")
        return

    df = pd.read_csv(EXPECTED_COVERAGE_PATH)
    avg = (df.groupby('income_group')['log_ratio']
             .agg(['mean', 'sem', 'count'])
             .reindex(INCOME_ORDER)
             .reset_index())
    avg.columns = ['income_group', 'mean_log_ratio', 'sem', 'n_events']
    _save_plot_csv('outputs/plot8_log_ratio_by_income.csv', avg)

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(avg['income_group'], avg['mean_log_ratio'],
                  color=[COLORS[g] for g in avg['income_group']],
                  width=0.5, zorder=3,
                  yerr=avg['sem'], capsize=5,
                  error_kw={'elinewidth': 1.5, 'ecolor': '#555'})
    ax.axhline(0, color='black', linewidth=0.9, linestyle='--', alpha=0.5)
    for bar, val in zip(bars, avg['mean_log_ratio']):
        offset = 0.02 if val >= 0 else -0.04
        ax.text(bar.get_x() + bar.get_width() / 2, val + offset,
                f'{val:.3f}', ha='center', fontsize=10, fontweight='bold')
    ax.set_xlabel('Income Group', labelpad=8)
    ax.set_ylabel('Mean log_ratio', labelpad=8)
    ax.set_title('log_ratio by Income Group\n'
                 'Continuous log_ratio; under_flag = log_ratio<0; '
                 'severity_tier low = bottom tertile\n'
                 'Cluster-robust SE by state in compute_expected_coverage.py; '
                 'CI covering 0 → no detectable gradient')
    ax.grid(axis='y', alpha=0.3, zorder=0)
    plt.tight_layout()
    out = 'outputs/plot8_log_ratio_by_income.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {out}")


def plot_coverage_map():
    """Plot 9: Choropleth map of mean log_ratio by state on India map."""
    if not os.path.exists(EXPECTED_COVERAGE_PATH):
        print("  SKIP Plot 9: waiting for expected_coverage.csv")
        return

    import geopandas as gpd
    from matplotlib.colors import TwoSlopeNorm

    df = pd.read_csv(EXPECTED_COVERAGE_PATH)
    state_agg = (
        df.groupby('state')['log_ratio']
        .agg(mean_log_ratio='mean', n_events='count')
        .reset_index()
    )

    shapefile_url = (
        'https://naciscdn.org/naturalearth/10m/cultural/'
        'ne_10m_admin_1_states_provinces.zip'
    )
    cache_path = 'data/ne_india_states.gpkg'
    if os.path.exists(cache_path):
        gdf = gpd.read_file(cache_path)
    else:
        world = gpd.read_file(shapefile_url)
        gdf = world[world['admin'] == 'India'][['name', 'geometry']].copy()
        os.makedirs('data', exist_ok=True)
        gdf.to_file(cache_path, driver='GPKG')

    gdf = gdf.merge(state_agg, left_on='name', right_on='state', how='left')

    from matplotlib.colors import LinearSegmentedColormap

    vmax = max(abs(state_agg['mean_log_ratio'].min()),
               abs(state_agg['mean_log_ratio'].max()), 0.01)
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)

    dramatic_cmap = LinearSegmentedColormap.from_list('dramatic', [
        (0.0,  '#7a3300'),
        (0.15, '#b34700'),
        (0.35, '#e06600'),
        (0.5,  '#f5f5dc'),
        (0.65, '#1b8a1b'),
        (0.85, '#0a5f0a'),
        (1.0,  '#003300'),
    ])

    fig, ax = plt.subplots(figsize=(10, 12))
    fig.set_facecolor('#ffffff')
    ax.set_facecolor('#ffffff')

    gdf.plot(
        column='mean_log_ratio',
        cmap=dramatic_cmap,
        norm=norm,
        linewidth=0.8,
        edgecolor='#e0e0e0',
        ax=ax,
        legend=False,
        missing_kwds={'color': '#f0f0f0', 'edgecolor': '#aaa',
                      'hatch': '////', 'label': 'No data'},
    )

    sm = plt.cm.ScalarMappable(cmap=dramatic_cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.025, pad=0.02, shrink=0.7)
    cbar.set_label('Mean log_ratio\n(red = under-covered, green = over-covered)',
                   fontsize=10, color='black')
    cbar.ax.yaxis.set_tick_params(color='black')
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color='black')

    matched = gdf.dropna(subset=['mean_log_ratio'])
    for _, row in matched.iterrows():
        centroid = row.geometry.centroid
        ax.annotate(
            f"{row['name']}\n{row['mean_log_ratio']:+.3f} (n={int(row['n_events'])})",
            xy=(centroid.x, centroid.y),
            fontsize=5.5, ha='center', va='center',
            fontweight='bold', color='#111',
            bbox=dict(boxstyle='round,pad=0.15', fc='white', alpha=0.85, lw=0),
        )

    ax.set_title('Coverage Imbalance by State\n'
                 'Mean log_ratio: red = under-covered, green = over-covered',
                 fontsize=14, fontweight='bold', color='black')
    ax.set_axis_off()
    plt.tight_layout()

    map_csv = state_agg.sort_values('mean_log_ratio')
    _save_plot_csv('outputs/plot9_coverage_map.csv', map_csv)

    out = 'outputs/plot9_coverage_map.png'
    plt.savefig(out, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {out}")


def refresh_pipeline_result_figures(md_path='outputs/pipeline_result.md'):
    """Insert / replace the Figures section after plots are written."""
    plot_links = []
    for fname, label in [
        ('plot5_observed_vs_expected.png', 'Observed vs expected calibration'),
        ('plot6_log_ratio_histogram.png', 'log_ratio residual histogram'),
        ('plot7_log_ratio_ranking.png', 'Coverage imbalance ranking (extremes)'),
        ('plot8_log_ratio_by_income.png', 'log_ratio by income group'),
        ('plot9_coverage_map.png', 'Coverage imbalance choropleth map'),
    ]:
        if os.path.exists(os.path.join('outputs', fname)):
            plot_links.append(f'- [{label}]({fname})')

    if not plot_links:
        return

    section = '## Figures\n\n' + '\n'.join(plot_links) + '\n'
    if not os.path.exists(md_path):
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('# CVND Pipeline Results\n\n' + section)
        print(f'  SAVED: {md_path}')
        return

    with open(md_path, 'r', encoding='utf-8') as f:
        text = f.read()

    if re.search(r'^## Figures\b', text, flags=re.M):
        text = re.sub(
            r'^## Figures\b.*?(?=^## |\Z)',
            section + '\n',
            text,
            count=1,
            flags=re.M | re.S,
        )
    else:
        text = text.rstrip() + '\n\n' + section

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'  SAVED: {md_path} (figures section refreshed)')


if __name__ == '__main__':
    print("=" * 55)
    print("VISUALIZE — CVND PIPELINE FIGURES")
    print("=" * 55)

    available = [f for f in [
        'data/mss_results.csv',
        'data/expected_coverage.csv',
        'data/raw_gdelt.csv',
    ] if os.path.exists(f)]

    print(f"CSVs found: {available}\n")

    print("Plot 5: Observed vs expected")
    plot_observed_vs_expected()

    print("\nPlot 6: log_ratio histogram")
    plot_log_ratio_histogram()

    print("\nPlot 7: log_ratio ranking")
    plot_log_ratio_ranking()

    print("\nPlot 8: log_ratio by income")
    plot_log_ratio_by_income()

    print("\nPlot 9: Coverage map")
    plot_coverage_map()

    print("\nRefreshing markdown report figure links")
    refresh_pipeline_result_figures()

    saved_png = sorted(f for f in os.listdir('outputs') if f.endswith('.png'))
    saved_csv = sorted(f for f in os.listdir('outputs') if f.startswith('plot') and f.endswith('.csv'))
    print(f"\n{'=' * 55}")
    print(f"Done. {len(saved_png)} figure(s), {len(saved_csv)} plot CSV(s) in outputs/")
    for f in saved_png:
        print(f"  outputs/{f}")
    for f in saved_csv:
        print(f"  outputs/{f}")
    if os.path.exists('outputs/pipeline_result.md'):
        print("  outputs/pipeline_result.md")
