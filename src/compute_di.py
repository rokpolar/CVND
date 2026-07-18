"""
cp_10_di.py  —  Discrepancy Index (DI)

Formula:
    EIS = α·PSS_n + (1-α)·HER_n        [default α = 0.6]
    DI  = MSS_n - EIS                   [range: -1 to +1]

Interpretation:
    DI > 0  →  over-reported  (more coverage than severity warrants)
    DI = 0  →  fairly reported
    DI < 0  →  under-reported (less coverage than severity warrants)

Inputs:
    data/pss_results.csv          — event_id, state, PSS, income_group
    data/mss_results.csv          — event_id, MSS
    data/severity_raw.csv         — event_id, exposure_rate

Output:
    data/di_results.csv
    data/state_di.csv
"""

import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from scipy import stats
import statsmodels.api as sm
import os
import warnings
warnings.filterwarnings('ignore')

# ── tuneable ──────────────────────────────────────────────────────────────────
ALPHA = 0.6   # weight on PSS in EIS; (1-ALPHA) goes to HER

print("=" * 60)
print("CP-10: DISCREPANCY INDEX (DI)")
print("=" * 60)
print(f"\nFormula : EIS = {ALPHA}·PSS_n + {1-ALPHA}·HER_n")
print(f"          DI  = MSS_n - EIS")

# ── Load ──────────────────────────────────────────────────────────────────────
pss    = pd.read_csv('data/pss_results.csv')
mss    = pd.read_csv('data/mss_results.csv')
sev    = pd.read_csv('data/severity_raw.csv')[['event_id', 'exposure_rate']]
events = pd.read_csv('data/events.csv')[['event_id', 'income_group']]

print(f"\nPSS events : {len(pss)}")
print(f"MSS events : {len(mss)}")
print(f"Severity rows: {len(sev)}")

# ── Quarantine list (duplicates / malformed / incomplete) ─────────────────────
QUARANTINE_PATH = 'data/events_quarantine.csv'
quarantine_ids = set()
if os.path.exists(QUARANTINE_PATH):
    qdf = pd.read_csv(QUARANTINE_PATH)
    quarantine_ids = set(qdf.loc[qdf['status'] == 'quarantine', 'event_id'].astype(str))
    print(f"\nQuarantine list: {len(quarantine_ids)} events from {QUARANTINE_PATH}")
else:
    print(f"\nWARNING: {QUARANTINE_PATH} not found — no events quarantined")

# ── Merge ─────────────────────────────────────────────────────────────────────
df = (pss[['event_id', 'state', 'PSS']]
      .merge(events, on='event_id', how='left')
      .merge(mss[['event_id', 'MSS']], on='event_id', how='left')
      .merge(sev, on='event_id', how='left'))

# Drop quarantined events before scoring
n_q = df['event_id'].isin(quarantine_ids).sum()
if n_q:
    print(f"Excluding {n_q} quarantined events: "
          f"{sorted(df.loc[df['event_id'].isin(quarantine_ids), 'event_id'].tolist())}")
    df = df[~df['event_id'].isin(quarantine_ids)].copy()

# Missing MSS stays missing — do not impute zero coverage
no_mss = df['MSS'].isna().sum()
if no_mss:
    print(f"{no_mss} events have no MSS → dropped (not imputed as 0)")

# Drop rows where PSS, MSS, or exposure_rate is missing (can't compute DI)
before = len(df)
df = df.dropna(subset=['PSS', 'MSS', 'exposure_rate'])
dropped = before - len(df)
if dropped:
    print(f"{dropped} events dropped: missing PSS, MSS, or exposure_rate")

print(f"\nEvents entering DI computation: {len(df)}")

# ── Step 1: Normalize PSS, MSS, HER to [0, 1] ────────────────────────────────
print("\n[Step 1] Normalizing PSS, MSS, HER to [0, 1]")

scaler = MinMaxScaler()
df['PSS_n'] = scaler.fit_transform(df[['PSS']]).round(6)
df['MSS_n'] = scaler.fit_transform(df[['MSS']]).round(6)
df['HER_n'] = scaler.fit_transform(df[['exposure_rate']]).round(6)

print(f"  PSS_n : {df['PSS_n'].min():.4f} – {df['PSS_n'].max():.4f}")
print(f"  MSS_n : {df['MSS_n'].min():.4f} – {df['MSS_n'].max():.4f}")
print(f"  HER_n : {df['HER_n'].min():.4f} – {df['HER_n'].max():.4f}")

# ── Step 2: Expected Impact Score ─────────────────────────────────────────────
print(f"\n[Step 2] EIS = {ALPHA}·PSS_n + {1-ALPHA}·HER_n")

df['EIS'] = (ALPHA * df['PSS_n'] + (1 - ALPHA) * df['HER_n']).round(6)

print(f"  EIS range  : {df['EIS'].min():.4f} – {df['EIS'].max():.4f}")
print(f"  EIS mean   : {df['EIS'].mean():.4f}")
print(f"  EIS median : {df['EIS'].median():.4f}")

# ── Step 3: Discrepancy Index ─────────────────────────────────────────────────
print("\n[Step 3] DI = MSS_n - EIS")

df['DI'] = (df['MSS_n'] - df['EIS']).round(6)

print(f"  DI range   : {df['DI'].min():.4f} – {df['DI'].max():.4f}  (theoretical: -1 to +1)")
print(f"  DI mean    : {df['DI'].mean():.4f}")
print(f"  DI median  : {df['DI'].median():.4f}")
print(f"  DI std     : {df['DI'].std():.4f}")

over  = (df['DI'] > 0).sum()
under = (df['DI'] < 0).sum()
fair  = (df['DI'] == 0).sum()
print(f"\n  Over-reported  (DI > 0): {over}  events")
print(f"  Fairly reported (DI = 0): {fair}  events")
print(f"  Under-reported (DI < 0): {under}  events")

# ── Step 4: Sensitivity analysis on α ────────────────────────────────────────
print("\n[Step 4] Sensitivity analysis — DI rank stability across α values")
print("-" * 55)

alphas = {'α=0.5': 0.5, 'α=0.6 (base)': 0.6, 'α=0.7': 0.7, 'α=0.8': 0.8}
rank_df = df[['event_id', 'state']].copy()

for label, a in alphas.items():
    eis_alt = a * df['PSS_n'] + (1 - a) * df['HER_n']
    di_alt  = df['MSS_n'] - eis_alt
    rank_df[label] = di_alt.rank(ascending=True).astype(int)  # rank 1 = most undercovered

rank_cols = list(alphas.keys())
rank_df['max_rank_shift'] = rank_df[rank_cols].max(axis=1) - rank_df[rank_cols].min(axis=1)
max_shift = rank_df['max_rank_shift'].max()
unstable  = rank_df[rank_df['max_rank_shift'] > 5]

print(f"  Max rank shift across α values: {max_shift}")
if unstable.empty:
    print("  ✓ Rankings stable (shift ≤ 5) — α = 0.6 is defensible")
else:
    print(f"  ⚠ {len(unstable)} events shift rank by > 5 positions across α:")
    print(unstable[['event_id', 'state', 'max_rank_shift']].to_string(index=False))
    print("  Note this as a sensitivity limitation in the paper.")

# ── Step 5: DI by income group ────────────────────────────────────────────────
print("\n[Step 5] DI by income group")
print("-" * 55)

di_income = (df.groupby('income_group')['DI']
               .agg(mean='mean', median='median', std='std', n='count')
               .round(4))
print(di_income)

# T-test and Mann-Whitney: Low vs High
low_di  = df[df['income_group'] == 'Low']['DI']
high_di = df[df['income_group'] == 'High']['DI']

if len(low_di) > 1 and len(high_di) > 1:
    t_stat, p_t = stats.ttest_ind(low_di, high_di)
    u_stat, p_u = stats.mannwhitneyu(low_di, high_di, alternative='two-sided')
    print(f"\n  T-test (Low vs High):          t={t_stat:.4f}, p={p_t:.4f}")
    print(f"  Mann-Whitney U (Low vs High):  U={u_stat:.1f}, p={p_u:.4f}")

    sig = p_u < 0.05
    direction = "lower" if low_di.mean() < high_di.mean() else "higher"
    if sig:
        print(f"\n  ✓ SIGNIFICANT (p<0.05): Low-income events have {direction} DI")
        print("    → Evidence of systematic reporting bias by income group")
    else:
        print(f"\n  ✗ Not significant (p≥0.05) — note as limitation (small N per group)")
else:
    print("\n  Insufficient data for Low vs High comparison")

# ── Step 6: OLS regression DI ~ income (for the covariate file) ──────────────
# This is a preview only — full regression vs state covariates is in a
# separate script. Here we just confirm DI varies meaningfully with income.
print("\n[Step 6] OLS preview: DI ~ income group dummies")
print("-" * 55)

dummies = pd.get_dummies(df['income_group'], drop_first=True)
X = sm.add_constant(dummies.astype(float))
ols = sm.OLS(df['DI'], X).fit()
print(ols.summary2())

# ── Step 7: Calibration check ────────────────────────────────────────────────
print("\n[Step 7] Calibration check on known events")
print("-" * 55)

known = {
    'E01': ('Kerala 2018 — catastrophic, high coverage expected',   'over'),
    'E12': ('Delhi 2023 — metro event, high coverage expected',     'over'),
    'E02': ('Bihar 2019 — severe but peripheral',                   'under'),
    'E10': ('Odisha 2022 — real disaster, low coverage expected',   'under'),
}
for eid, (desc, expected) in known.items():
    row = df[df['event_id'] == eid]
    if row.empty:
        print(f"  ? {eid}: not in data")
        continue
    di_val = row['DI'].values[0]
    actual = 'over' if di_val > 0 else 'under'
    mark   = '✓' if actual == expected else '✗'
    print(f"  {mark} {eid} {desc}")
    print(f"      DI={di_val:.4f}  PSS_n={row['PSS_n'].values[0]:.4f}"
          f"  HER_n={row['HER_n'].values[0]:.4f}  MSS_n={row['MSS_n'].values[0]:.4f}")

# ── Step 8: Full sorted table ─────────────────────────────────────────────────
print("\n[Step 8] Full DI table (most under-reported first)")
print("-" * 55)

result = df[['event_id', 'state', 'income_group',
             'PSS_n', 'HER_n', 'EIS', 'MSS_n', 'DI']].copy()
result = result.sort_values('DI')

print("\nMost UNDER-REPORTED (DI most negative):")
print(result.head(15).to_string(index=False))

print("\nMost OVER-REPORTED (DI most positive):")
print(result.tail(15).to_string(index=False))

# ── State-level aggregation ───────────────────────────────────────────────────
state_di = (df.groupby(['state', 'income_group'])
              .agg(mean_DI    =('DI', 'mean'),
                   median_DI  =('DI', 'median'),
                   std_DI     =('DI', 'std'),
                   n_events   =('DI', 'count'),
                   mean_PSS_n =('PSS_n', 'mean'),
                   mean_HER_n =('HER_n', 'mean'),
                   mean_MSS_n =('MSS_n', 'mean'),
                   mean_EIS   =('EIS', 'mean'))
              .reset_index()
              .sort_values('mean_DI'))

print("\n[State-level DI]")
print(state_di.round(4).to_string(index=False))

# ── Save ──────────────────────────────────────────────────────────────────────
os.makedirs('data', exist_ok=True)
result.to_csv('data/di_results.csv', index=False)
state_di.to_csv('data/state_di.csv', index=False)

print(f"\nSAVED: data/di_results.csv  ({len(result)} events)")
print(f"SAVED: data/state_di.csv   ({len(state_di)} states)")
print("\nCP-10 COMPLETE — ready for covariate regression script")