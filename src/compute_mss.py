import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from sklearn.decomposition import PCA
import os
import json
import warnings
warnings.filterwarnings('ignore')

MSS_WEIGHT_META_PATH = "data/mss_weight_sensitivity.json"
MSS_FEATURES = ['S_vol', 'S_sov', 'S_TTFR', 'S_CD']
W_FIXED = np.array([0.3, 0.3, 0.2, 0.2])


def entropy_weights(X: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Shannon entropy weight method (EWM) for positive indicators in [0, 1]."""
    X = np.asarray(X, dtype=float)
    n, _m = X.shape
    if n < 2:
        return np.ones(_m) / _m

    col_sum = X.sum(axis=0)
    zero_cols = col_sum <= eps
    P = np.zeros_like(X)
    for j in range(X.shape[1]):
        if zero_cols[j]:
            P[:, j] = 1.0 / n
        else:
            P[:, j] = X[:, j] / col_sum[j]

    P = np.clip(P, eps, None)
    k = 1.0 / np.log(n)
    entropy = -k * np.sum(P * np.log(P), axis=0)
    diversity = 1.0 - entropy
    if diversity.sum() <= eps:
        return np.ones(_m) / _m
    diversity[zero_cols] = 0.0
    if diversity.sum() <= eps:
        return np.ones(_m) / _m
    return diversity / diversity.sum()


def pca_loadings_weights(X: np.ndarray) -> tuple[np.ndarray, float]:
    """First-component absolute loadings, normalized to sum to 1."""
    pca = PCA(n_components=1, random_state=42)
    pca.fit(X)
    loadings = np.abs(pca.components_[0])
    weights = loadings / loadings.sum()
    return weights, float(pca.explained_variance_ratio_[0])


def weighted_mss(frame: pd.DataFrame, weights: np.ndarray) -> pd.Series:
    return (frame[MSS_FEATURES].values @ weights).round(4)


def rank_shift(base: pd.Series, alt: pd.Series) -> tuple[float, float]:
    rb = base.rank(ascending=False, method='average')
    ra = alt.rank(ascending=False, method='average')
    diff = (rb - ra).abs()
    return float(diff.max()), float(diff.mean())

print("=" * 60)
print("CP-09: COMPUTE MEDIA SALIENCE SCORE (MSS)")
print("=" * 60)

# ── Step 1: Load and merge all 3 BigQuery JSON parts ─────────────────────────
print("\n[Step 1] Loading BigQuery JSON files...")

parts = []
for fname in ['data/gdelt_bq_part1.json',
              'data/gdelt_bq_part2.json',
              'data/gdelt_bq_part3.json',
              'data/gdelt_bq_part4.json',
              'data/gdelt_bq_part5.json',
              'data/gdelt_bq_part6.json']:
    if os.path.exists(fname):
        with open(fname, 'r') as f:
            data = json.load(f)
        df_part = pd.DataFrame(data)
        print(f"  {fname}: {len(df_part)} rows")
        parts.append(df_part)
    else:
        print(f"  MISSING: {fname}")

raw = pd.concat(parts, ignore_index=True)
raw['article_count']   = raw['article_count'].astype(int)
raw['coverage_days']   = raw['coverage_days'].astype(int)
raw['first_article_date'] = pd.to_datetime(raw['first_article_date'])
raw['last_article_date']  = pd.to_datetime(raw['last_article_date'])

print(f"\nTotal rows after merge: {len(raw)}")
print(f"Events covered: {raw['event_id'].nunique()}")
print(f"Languages found: {sorted(raw['source_lang'].dropna().unique())}")

# ── Step 2: Aggregate per event (sum across languages) ────────────────────────
print("\n[Step 2] Aggregating per event...")

# Total articles per event (all languages combined)
event_agg = raw.groupby(['event_id', 'state']).agg(
    total_articles   = ('article_count',    'sum'),
    first_date       = ('first_article_date','min'),
    last_date        = ('last_article_date', 'max'),
    coverage_days    = ('coverage_days',     'max'),  # max across langs (days already per-day)
).reset_index()

# Indic language classification
INDIC_LANGS = {'hin','mal','tam','tel','kan','ben','mar','guj','pan','urd',
               'ori','asm','pun','sat','kok','dog','mai','mni'}

raw['is_indic'] = raw['source_lang'].isin(INDIC_LANGS)
raw['is_en']    = raw['source_lang'] == 'en'

indic_agg = raw[raw['is_indic']].groupby('event_id')['article_count'].sum().reset_index()
indic_agg.columns = ['event_id', 'indic_articles']

en_agg = raw[raw['is_en']].groupby('event_id')['article_count'].sum().reset_index()
en_agg.columns = ['event_id', 'en_articles']

# Per-language counts for key Indic languages
lang_pivot = raw[raw['is_indic']].pivot_table(
    index='event_id', columns='source_lang',
    values='article_count', aggfunc='sum', fill_value=0
).reset_index()

df = event_agg.merge(indic_agg, on='event_id', how='left')
df = df.merge(en_agg,    on='event_id', how='left')
df['indic_articles'] = df['indic_articles'].fillna(0).astype(int)
df['en_articles']    = df['en_articles'].fillna(0).astype(int)
df['indic_share']    = (df['indic_articles'] / df['total_articles'].replace(0, np.nan)).fillna(0)

# ── Step 3: Load events for onset dates ──────────────────────────────────────
print("\n[Step 3] Loading event onset dates...")
events = pd.read_csv('data/events.csv')[['event_id', 'state', 'start_date', 'income_group']]
events['onset_date'] = pd.to_datetime(events['start_date'])
df = df.merge(events[['event_id','onset_date','income_group']], on='event_id', how='left')

# ── Step 4: Compute MSS components per your formula ──────────────────────────
print("\n[Step 4] Computing MSS components...")

# N_total_news = total articles across ALL events (denominator for S_sov)
N_total = df['total_articles'].sum()
print(f"  N_total_news (all events): {N_total:,}")

# S_vol: min-max normalized volume
# Check skewness — if >2, use log scaling
skew = df['total_articles'].skew()
print(f"  Article count skewness: {skew:.2f}")

if abs(skew) > 2:
    print("  Skewness > 2 → using log scaling for S_vol (as per formula note)")
    df['vol_scaled'] = np.log1p(df['total_articles'])
else:
    print("  Skewness <= 2 → using linear scaling for S_vol")
    df['vol_scaled'] = df['total_articles'].astype(float)

scaler = MinMaxScaler()
df['S_vol'] = scaler.fit_transform(df[['vol_scaled']]).round(4)

# S_sov: share of voice = Vol_e / N_total_news
df['S_sov'] = (df['total_articles'] / N_total).round(6)
# Normalize S_sov to [0,1] as well for comparability
df['S_sov'] = scaler.fit_transform(df[['S_sov']]).round(4)

# S_TTFR: exponential decay on time-to-first-report
# S_TTFR = exp(-γ × (t_first - t_onset))
# γ = 0.3 (default); sensitivity checked at 0.1 and 0.5
GAMMA = 0.3

df['t_first_days'] = (df['first_date'] - df['onset_date']).dt.days.clip(lower=0)

# For events with no coverage (first_date is NaT), assign max decay
df['t_first_days'] = df['t_first_days'].fillna(14)

df['S_TTFR_g03'] = np.exp(-GAMMA       * df['t_first_days']).round(4)
df['S_TTFR_g01'] = np.exp(-0.1         * df['t_first_days']).round(4)
df['S_TTFR_g05'] = np.exp(-0.5         * df['t_first_days']).round(4)
df['S_TTFR']     = df['S_TTFR_g03']  # primary

# S_CD: coverage days normalized
# CD_e = count of days where Vol_e,d >= δ (δ=1)
# coverage_days_threshold_1 already computed in BigQuery
# Use coverage_days as CD_e (all days with ≥1 article)
df['S_CD'] = scaler.fit_transform(df[['coverage_days']]).round(4)

# ── Step 5: Compute MSS (fixed weights primary) + EWM/PCA sensitivity ────────
# MSS = w_vol·S_vol + w_sov·S_sov + w_TTFR·S_TTFR + w_CD·S_CD
# Primary: w_vol=0.3, w_sov=0.3, w_TTFR=0.2, w_CD=0.2

W_VOL, W_SOV, W_TTFR, W_CD = W_FIXED
df['MSS'] = weighted_mss(df, W_FIXED)

print("\n[Step 5] Weight sensitivity — fixed vs Entropy (EWM) vs PCA loadings...")
X = df[MSS_FEATURES].values
w_ewm = entropy_weights(X)
w_pca, pca_ev = pca_loadings_weights(X)

df['MSS_ewm'] = weighted_mss(df, w_ewm)
df['MSS_pca'] = weighted_mss(df, w_pca)

print("  Fixed weights : "
      f"S_vol={W_VOL:.4f}, S_sov={W_SOV:.4f}, S_TTFR={W_TTFR:.4f}, S_CD={W_CD:.4f}")
print("  EWM weights   : "
      f"S_vol={w_ewm[0]:.4f}, S_sov={w_ewm[1]:.4f}, S_TTFR={w_ewm[2]:.4f}, S_CD={w_ewm[3]:.4f}")
print("  PCA weights   : "
      f"S_vol={w_pca[0]:.4f}, S_sov={w_pca[1]:.4f}, S_TTFR={w_pca[2]:.4f}, S_CD={w_pca[3]:.4f} "
      f"(PC1 EV={pca_ev:.4f})")

for label, col in [('EWM', 'MSS_ewm'), ('PCA', 'MSS_pca')]:
    corr = df['MSS'].corr(df[col])
    max_s, mean_s = rank_shift(df['MSS'], df[col])
    print(f"  vs {label:3s}: Pearson r={corr:.4f}, max rank shift={max_s:.0f}, mean rank shift={mean_s:.2f}")

weight_meta = {
    "primary": "fixed",
    "features": MSS_FEATURES,
    "weights": {
        "fixed": W_FIXED.tolist(),
        "ewm": w_ewm.tolist(),
        "pca": w_pca.tolist(),
    },
    "pca_explained_variance": pca_ev,
    "sensitivity_vs_fixed": {
        "ewm": {
            "pearson_r": float(df['MSS'].corr(df['MSS_ewm'])),
            "max_rank_shift": float(rank_shift(df['MSS'], df['MSS_ewm'])[0]),
            "mean_rank_shift": float(rank_shift(df['MSS'], df['MSS_ewm'])[1]),
        },
        "pca": {
            "pearson_r": float(df['MSS'].corr(df['MSS_pca'])),
            "max_rank_shift": float(rank_shift(df['MSS'], df['MSS_pca'])[0]),
            "mean_rank_shift": float(rank_shift(df['MSS'], df['MSS_pca'])[1]),
        },
    },
    "n_events": int(len(df)),
}
os.makedirs("data", exist_ok=True)
with open(MSS_WEIGHT_META_PATH, "w", encoding="utf-8") as f:
    json.dump(weight_meta, f, indent=2)
print(f"  SAVED: {MSS_WEIGHT_META_PATH}")

# ── Step 6: Sensitivity analysis on γ ────────────────────────────────────────
print("\n[Step 6] Sensitivity analysis on γ (TTFR decay constant)...")
for g_label, g_col in [('γ=0.1', 'S_TTFR_g01'),
                        ('γ=0.3', 'S_TTFR_g03'),
                        ('γ=0.5', 'S_TTFR_g05')]:
    mss_g = (W_VOL*df['S_vol'] + W_SOV*df['S_sov'] +
             W_TTFR*df[g_col]  + W_CD*df['S_CD'])
    rank_g = mss_g.rank(ascending=False).astype(int)
    rank_primary = df['MSS'].rank(ascending=False).astype(int)
    max_shift = (rank_g - rank_primary).abs().max()
    print(f"  {g_label}: max rank shift vs primary = {max_shift}")

# ── Step 7: Summary ──────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("MSS RESULTS SUMMARY")
print("=" * 60)

result = df[['event_id', 'state', 'income_group',
             'total_articles', 'indic_articles', 'en_articles',
             'indic_share', 'coverage_days', 't_first_days',
             'S_vol', 'S_sov', 'S_TTFR', 'S_CD', 'MSS', 'MSS_ewm', 'MSS_pca']].copy()

print(result.sort_values('MSS', ascending=False).to_string(index=False))

print(f"\nMSS range : {result['MSS'].min():.4f} – {result['MSS'].max():.4f}")
print(f"MSS mean  : {result['MSS'].mean():.4f}")
print(f"MSS median: {result['MSS'].median():.4f}")
print(f"Zero MSS  : {(result['MSS'] == 0).sum()} events")

print("\nMean MSS by income group:")
print(result.groupby('income_group')['MSS'].mean().round(4).to_string())

print("\nMean total_articles by income group:")
print(result.groupby('income_group')['total_articles'].mean().round(0).to_string())

print("\nMean indic_share by income group:")
print(result.groupby('income_group')['indic_share'].mean().round(4).to_string())

print("\nTop 10 by MSS:")
print(result.nlargest(10,'MSS')[['event_id','state','total_articles',
                                   'MSS','indic_share']].to_string(index=False))

print("\nBottom 10 by MSS:")
print(result.nsmallest(10,'MSS')[['event_id','state','total_articles',
                                    'MSS','indic_share']].to_string(index=False))

# ── Step 8: Save ──────────────────────────────────────────────────────────────
os.makedirs('data', exist_ok=True)
result.to_csv('data/mss_results.csv', index=False)
print(f"\nSAVED: data/mss_results.csv")
print("\nCP-09 COMPLETE — ready for CP-10")