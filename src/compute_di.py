import pandas as pd
import numpy as np
import statsmodels.api as sm
from scipy import stats
import os
import warnings
warnings.filterwarnings('ignore')

print("=" * 60)
print("CP-10: DISCREPANCY INDEX (DI)")
print("=" * 60)

# ── Load PSS and MSS ──────────────────────────────────────────────────────────
pss = pd.read_csv('data/pss_results.csv')
mss = pd.read_csv('data/mss_results.csv')
events = pd.read_csv('data/events.csv')[['event_id','state','income_group','start_date']]
covars = pd.read_csv('data/state_covariates.csv')

print(f"\nPSS events: {len(pss)}")
print(f"MSS events: {len(mss)}")

# ── Merge PSS and MSS ─────────────────────────────────────────────────────────
df = pss[['event_id','state','PSS','income_group']].merge(
    mss[['event_id','MSS','total_articles','indic_share',
         'coverage_days','t_first_days']], on='event_id', how='inner')

print(f"Events with both PSS and MSS: {len(df)}")

# Handle events in PSS but not MSS — assign MSS=0 (zero coverage)
pss_only = pss[~pss['event_id'].isin(mss['event_id'])]
if len(pss_only) > 0:
    print(f"Events with PSS but no MSS (zero coverage): {len(pss_only)}")
    zero_mss = pss_only[['event_id','state','PSS','income_group']].copy()
    zero_mss['MSS'] = 0.0
    zero_mss['total_articles'] = 0
    zero_mss['indic_share'] = 0.0
    zero_mss['coverage_days'] = 0
    zero_mss['t_first_days'] = 14
    df = pd.concat([df, zero_mss], ignore_index=True)

print(f"Total events for DI computation: {len(df)}")

# ── Step 1: OLS regression MSS ~ PSS ─────────────────────────────────────────
print("\n[Step 1] OLS regression: MSS ~ PSS")
print("-" * 40)

X = sm.add_constant(df['PSS'])
model = sm.OLS(df['MSS'], X).fit()

print(model.summary())

# Key stats
r2       = model.rsquared
coef_pss = model.params['PSS']
p_pss    = model.pvalues['PSS']

print(f"\nR²: {r2:.4f}")
print(f"PSS coefficient: {coef_pss:.4f} (p={p_pss:.4f})")

if p_pss < 0.05:
    print("  PSS is a significant predictor of MSS")
    print("  → Regression residuals are a valid bias measure")
else:
    print("  WARN: PSS not significant predictor of MSS")
    print("  → DI residuals capture noise as well as bias")
    print("  → Note this as a limitation in paper")

# ── Step 2: Compute DI as regression residual ─────────────────────────────────
print("\n[Step 2] Computing DI = MSS residual from OLS")
df['MSS_predicted'] = model.predict(X)
df['DI'] = model.resid  # positive = undercovered, negative = overcovered

# Standardize DI for comparability
df['DI_std'] = (df['DI'] - df['DI'].mean()) / df['DI'].std()

print(f"\nDI range  : {df['DI'].min():.4f} – {df['DI'].max():.4f}")
print(f"DI mean   : {df['DI'].mean():.4f}  (should be ~0 by OLS property)")
print(f"DI std    : {df['DI'].std():.4f}")
print(f"DI median : {df['DI'].median():.4f}")

# ── Step 3: DI by income group ────────────────────────────────────────────────
print("\n[Step 3] DI by income group")
print("-" * 40)

di_income = df.groupby('income_group')['DI'].agg(['mean','std','count','median'])
print(di_income.round(4))

# Statistical test: Low vs High DI difference
low_di  = df[df['income_group'] == 'Low']['DI']
high_di = df[df['income_group'] == 'High']['DI']
mid_di  = df[df['income_group'] == 'Middle']['DI']

t_stat, p_val = stats.ttest_ind(low_di, high_di)
print(f"\nT-test Low vs High DI:")
print(f"  t={t_stat:.4f}, p={p_val:.4f}")
if p_val < 0.05:
    print("  SIGNIFICANT: Low-income events are systematically under/overcovered vs High-income")
else:
    print("  Not significant at p<0.05 — note as limitation (small N per group)")

# Mann-Whitney U (non-parametric, more robust for small N)
u_stat, p_mw = stats.mannwhitneyu(low_di, high_di, alternative='two-sided')
print(f"\nMann-Whitney U test Low vs High DI:")
print(f"  U={u_stat:.1f}, p={p_mw:.4f}")

# ── Step 4: DI per event table ────────────────────────────────────────────────
print("\n[Step 4] Full DI table")
print("-" * 40)

result = df[['event_id','state','income_group',
             'PSS','MSS','MSS_predicted','DI','DI_std',
             'total_articles','indic_share','coverage_days']].copy()

result = result.sort_values('DI', ascending=False)

print("\nMost UNDERCOVERED (DI > 0, positive residual):")
print(result.head(15)[['event_id','state','income_group',
                         'PSS','MSS','DI']].to_string(index=False))

print("\nMost OVERCOVERED (DI < 0, negative residual):")
print(result.tail(15)[['event_id','state','income_group',
                        'PSS','MSS','DI']].to_string(index=False))

# ── Step 5: State-level aggregation ──────────────────────────────────────────
print("\n[Step 5] State-level mean DI")
print("-" * 40)

state_di = (df.groupby(['state','income_group'])
              .agg(mean_DI=('DI','mean'),
                   std_DI=('DI','std'),
                   n_events=('DI','count'),
                   mean_PSS=('PSS','mean'),
                   mean_MSS=('MSS','mean'))
              .reset_index()
              .sort_values('mean_DI', ascending=False))

print(state_di.round(4).to_string(index=False))

print("\nMean DI by income group (state-level):")
print(state_di.groupby('income_group')['mean_DI'].mean().round(4))

# ── Step 6: Calibration check on known events ────────────────────────────────
print("\n[Step 6] Calibration check on known events")
print("-" * 40)
known = {
    'E01': ('Kerala 2018 — historically catastrophic, high coverage expected', 'overcovered'),
    'E10': ('Odisha 2022 Balasore — real disaster, low coverage expected',     'undercovered'),
    'E12': ('Delhi 2023 — metro event, high coverage expected',                'overcovered'),
    'E02': ('Bihar 2019 — severe but peripheral, underreported',               'undercovered'),
}
for eid, (desc, expected) in known.items():
    row = df[df['event_id']==eid]
    if row.empty:
        print(f"  {eid}: NOT IN DATA")
        continue
    di_val = row['DI'].values[0]
    actual = 'overcovered' if di_val < 0 else 'undercovered'
    match  = '✓' if actual == expected else '✗'
    print(f"  {match} {eid} {desc}")
    print(f"      DI={di_val:.4f} → {actual} (expected: {expected})")

# ── Save ──────────────────────────────────────────────────────────────────────
os.makedirs('data', exist_ok=True)
result.to_csv('data/di_results.csv', index=False)
state_di.to_csv('data/state_di.csv', index=False)

print(f"\nSAVED: data/di_results.csv")
print(f"SAVED: data/state_di.csv")
print("\nCP-10 COMPLETE — ready for CP-11 and visualize.py")