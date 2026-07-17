import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import seaborn as sns
import geopandas as gpd
import requests
import json
import os
import warnings
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

# ── State name normalization: GeoJSON names → your events.csv names ───────────
STATE_NAME_MAP = {
    'Andaman & Nicobar Island': 'Andaman and Nicobar Islands',
    'Arunachal Pradesh':        'Arunachal Pradesh',
    'Assam':                    'Assam',
    'Bihar':                    'Bihar',
    'Chandigarh':               'Chandigarh',
    'Chhattisgarh':             'Chhattisgarh',
    'Dadra & Nagar Haveli':     'Dadra and Nagar Haveli',
    'Daman & Diu':              'Daman and Diu',
    'Delhi':                    'Delhi',
    'Goa':                      'Goa',
    'Gujarat':                  'Gujarat',
    'Haryana':                  'Haryana',
    'Himachal Pradesh':         'Himachal Pradesh',
    'Jammu & Kashmir':          'Jammu and Kashmir',
    'Jharkhand':                'Jharkhand',
    'Karnataka':                'Karnataka',
    'Kerala':                   'Kerala',
    'Lakshadweep':              'Lakshadweep',
    'Madhya Pradesh':           'Madhya Pradesh',
    'Maharashtra':              'Maharashtra',
    'Manipur':                  'Manipur',
    'Meghalaya':                'Meghalaya',
    'Mizoram':                  'Mizoram',
    'Nagaland':                 'Nagaland',
    'Odisha':                   'Odisha',
    'Puducherry':               'Puducherry',
    'Punjab':                   'Punjab',
    'Rajasthan':                'Rajasthan',
    'Sikkim':                   'Sikkim',
    'Tamil Nadu':               'Tamil Nadu',
    'Telangana':                'Telangana',
    'Tripura':                  'Tripura',
    'Uttar Pradesh':            'Uttar Pradesh',
    'Uttarakhand':              'Uttarakhand',
    'West Bengal':              'West Bengal',
}

def load_india_geojson():
    """Download India state boundaries GeoJSON at runtime."""
    url = ('https://raw.githubusercontent.com/geohacker/'
           'india/master/state/india_telengana.geojson')
    print("  Downloading India state boundaries...")
    try:
        resp = requests.get(url, timeout=30)
        gdf  = gpd.GeoDataFrame.from_features(
            resp.json()['features'], crs='EPSG:4326'
        )
        # Normalize state name column
        name_col = None
        for col in ['NAME_1', 'ST_NM', 'name', 'NAME', 'state']:
            if col in gdf.columns:
                name_col = col
                break
        if name_col is None:
            print(f"  WARN: Could not find name column. Columns: {list(gdf.columns)}")
            return None, None
        gdf = gdf.rename(columns={name_col: 'state'})
        gdf['state'] = gdf['state'].map(STATE_NAME_MAP).fillna(gdf['state'])
        print(f"  OK  GeoJSON loaded: {len(gdf)} states/UTs")
        return gdf, name_col
    except Exception as e:
        print(f"  WARN: Could not load GeoJSON: {e}")
        return None, None


# ══════════════════════════════════════════════════════════
# PLOT 1 — PSS vs MSS scatter (runs after CP-09)
# ══════════════════════════════════════════════════════════
def plot_pss_mss_scatter():
    pss_path = 'data/pss_results.csv'
    mss_path = 'data/mss_results.csv'

    if not os.path.exists(pss_path) or not os.path.exists(mss_path):
        print("  SKIP Plot 1: waiting for pss_results.csv and mss_results.csv (ready after CP-09)")
        return

    pss_df = pd.read_csv(pss_path)
    mss_df = pd.read_csv(mss_path)

    # pss_results already includes income_group; do not re-merge events
    # (duplicate column → income_group_x/_y and KeyError).
    df = pss_df.merge(mss_df[['event_id', 'MSS']], on='event_id')
    if 'income_group' not in df.columns:
        events = pd.read_csv('data/events.csv')[['event_id', 'income_group']]
        df = df.merge(events, on='event_id')

    fig, ax = plt.subplots(figsize=(10, 7))

    for income in INCOME_ORDER:
        grp = df[df['income_group'] == income]
        ax.scatter(grp['PSS'], grp['MSS'],
                   label=f'{income} income',
                   color=COLORS.get(income, 'gray'),
                   s=140, zorder=3,
                   edgecolors='white', linewidth=0.8)
        for _, row in grp.iterrows():
            ax.annotate(row['state'],
                        (row['PSS'], row['MSS']),
                        textcoords='offset points',
                        xytext=(7, 4), fontsize=8.5,
                        color='#333333')

    # Perfect-coverage diagonal
    lim = max(df['PSS'].max(), df['MSS'].max()) * 1.1
    ax.plot([0, lim], [0, lim], 'k--', alpha=0.25,
            linewidth=1.2, label='Perfect coverage line')

    # Regression line
    from numpy.polynomial.polynomial import polyfit
    if len(df) > 2:
        c = np.polyfit(df['PSS'], df['MSS'], 1)
        x_line = np.linspace(0, df['PSS'].max(), 100)
        ax.plot(x_line, np.polyval(c, x_line),
                color='steelblue', alpha=0.5,
                linewidth=1.5, linestyle='-.', label='OLS fit')

    ax.set_xlabel('Physical Severity Score (PSS)', labelpad=8)
    ax.set_ylabel('Media Salience Score (MSS)', labelpad=8)
    ax.set_title('Actual Flood Damage vs Media Coverage\n'
                 'Points above diagonal = overcovered; below = undercovered')
    ax.legend(framealpha=0.9)
    ax.set_xlim(left=-0.02)
    ax.set_ylim(bottom=-0.02)
    plt.tight_layout()
    path = 'outputs/plot1_pss_vs_mss_scatter.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {path}")


# ══════════════════════════════════════════════════════════
# PLOT 2 — DI by income group (runs after CP-10)
# ══════════════════════════════════════════════════════════
def plot_di_by_income():
    di_path = 'data/di_results.csv'
    if not os.path.exists(di_path):
        print("  SKIP Plot 2: waiting for di_results.csv (ready after CP-10)")
        return

    df  = pd.read_csv(di_path)
    cov = pd.read_csv('data/state_covariates.csv')[['state','gsdp_per_capita']]
    df  = df.merge(cov, on='state', how='left')

    # Mean DI per income group
    di_avg = (df.groupby('income_group')['DI']
                .agg(['mean', 'sem'])
                .reindex(INCOME_ORDER)
                .reset_index())

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(di_avg['income_group'], di_avg['mean'],
                  color=[COLORS[g] for g in di_avg['income_group']],
                  width=0.5, zorder=3,
                  yerr=di_avg['sem'], capsize=5,
                  error_kw={'elinewidth': 1.5, 'ecolor': '#555'})

    ax.axhline(0, color='black', linewidth=0.9,
               linestyle='--', alpha=0.5)

    for bar, val in zip(bars, di_avg['mean']):
        offset = 0.008 if val >= 0 else -0.018
        ax.text(bar.get_x() + bar.get_width() / 2,
                val + offset, f'{val:.3f}',
                ha='center', fontsize=10, fontweight='bold')

    ax.set_xlabel('Income Group', labelpad=8)
    ax.set_ylabel('Mean Discrepancy Index (DI)', labelpad=8)
    ax.set_title('Media Coverage Bias by Economic Group\n'
                 'Positive DI = undercovered relative to physical damage')
    ax.grid(axis='y', alpha=0.3, zorder=0)
    plt.tight_layout()
    path = 'outputs/plot2_di_by_income_group.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {path}")


# ══════════════════════════════════════════════════════════
# PLOT 3 — DI per event horizontal bar (runs after CP-10)
# ══════════════════════════════════════════════════════════
def plot_di_per_event():
    di_path = 'data/di_results.csv'
    if not os.path.exists(di_path):
        print("  SKIP Plot 3: waiting for di_results.csv (ready after CP-10)")
        return

    df     = pd.read_csv(di_path).sort_values('DI')
    labels = df['state'] + ' (' + df['event_id'] + ')'
    bar_colors = ['#e74c3c' if v > 0 else '#2ecc71' for v in df['DI']]

    fig, ax = plt.subplots(figsize=(12, 7))
    bars = ax.barh(labels, df['DI'], color=bar_colors, zorder=3)
    ax.axvline(0, color='black', linewidth=0.9,
               linestyle='--', alpha=0.5)

    # Annotate DI values
    for bar, val in zip(bars, df['DI']):
        offset = 0.003 if val >= 0 else -0.003
        ax.text(val + offset,
                bar.get_y() + bar.get_height() / 2,
                f'{val:.3f}',
                va='center', fontsize=8.5)

    ax.set_xlabel('Discrepancy Index (DI)', labelpad=8)
    ax.set_title('Discrepancy Index per Flood Event\n'
                 'Red = undercovered  |  Green = overcovered')

    red_patch   = mpatches.Patch(color='#e74c3c', label='Undercovered (DI > 0)')
    green_patch = mpatches.Patch(color='#2ecc71', label='Overcovered (DI < 0)')
    ax.legend(handles=[red_patch, green_patch], loc='lower right')
    ax.grid(axis='x', alpha=0.3, zorder=0)
    plt.tight_layout()
    path = 'outputs/plot3_di_per_event.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {path}")


# ══════════════════════════════════════════════════════════
# PLOT 4 — Spatial DI map (runs after CP-10)
# ══════════════════════════════════════════════════════════
def plot_spatial_di_map():
    di_path = 'data/di_results.csv'
    if not os.path.exists(di_path):
        print("  SKIP Plot 4: waiting for di_results.csv (ready after CP-10)")
        return

    gdf, _ = load_india_geojson()
    if gdf is None:
        print("  SKIP Plot 4: GeoJSON unavailable")
        return

    di_df = pd.read_csv(di_path)[['state', 'DI']]

    # For states with multiple events, take mean DI
    di_agg = di_df.groupby('state')['DI'].mean().reset_index()

    gdf = gdf.merge(di_agg, on='state', how='left')

    fig, ax = plt.subplots(1, 1, figsize=(10, 12))

    # States with no events: light gray
    gdf_no_data = gdf[gdf['DI'].isna()]
    gdf_no_data.plot(ax=ax, color='#e0e0e0', edgecolor='white', linewidth=0.5)

    # States with DI: diverging colormap centered at 0
    gdf_data = gdf[gdf['DI'].notna()]
    if not gdf_data.empty:
        vmax = max(abs(gdf_data['DI'].min()), abs(gdf_data['DI'].max()))
        gdf_data.plot(
            ax=ax, column='DI',
            cmap='RdYlGn_r',   # red = undercovered, green = overcovered
            vmin=-vmax, vmax=vmax,
            edgecolor='white', linewidth=0.5,
            legend=True,
            legend_kwds={
                'label':       'Discrepancy Index (DI)',
                'orientation': 'horizontal',
                'shrink':      0.6,
                'pad':         0.02
            }
        )

        # Annotate state names on the map
        for _, row in gdf_data.iterrows():
            try:
                centroid = row.geometry.centroid
                ax.annotate(row['state'],
                            xy=(centroid.x, centroid.y),
                            fontsize=7, ha='center',
                            color='#222222',
                            fontweight='bold')
            except:
                pass

    ax.set_title('Spatial Distribution of Discrepancy Index\n'
                 'Red = undercovered  |  Green = overcovered\n'
                 'Gray = no event in dataset',
                 pad=12)
    ax.set_axis_off()
    plt.tight_layout()
    path = 'outputs/plot4_spatial_di_map.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  SAVED: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 55)
    print("VISUALIZE — CVND PIPELINE FIGURES")
    print("=" * 55)

    available = [f for f in [
        'data/pss_results.csv', 'data/mss_results.csv',
        'data/di_results.csv',  'data/raw_gdelt.csv'
    ] if os.path.exists(f)]

    print(f"CSVs found: {available}\n")

    print("Plot 1: PSS vs MSS scatter")
    plot_pss_mss_scatter()

    print("\nPlot 2: DI by income group")
    plot_di_by_income()

    print("\nPlot 3: DI per event")
    plot_di_per_event()

    print("\nPlot 4: Spatial DI map")
    plot_spatial_di_map()

    saved = [f for f in os.listdir('outputs') if f.endswith('.png')]
    print(f"\n{'=' * 55}")
    print(f"Done. {len(saved)} figure(s) saved in outputs/")
    for f in sorted(saved):
        print(f"  outputs/{f}") 