"""
cp_10_di.py  —  LEGACY Discrepancy Index (DI)

*** LEGACY cohort-relative score — not the primary under-reporting measure. ***
Primary analysis: src/compute_expected_coverage.py (sparse NegBin + log_ratio).

Legacy formula (HER dropped to avoid PSS/HER double-counting):
    EIS = PSS_n                         [ALPHA = 1.0]
    DI  = MSS_n - EIS

Interpretation (if used):
    DI > 0  →  over-reported relative to this legacy benchmark
    DI < 0  →  under-reported relative to this legacy benchmark

Hygiene (#17):
    - Respects data/events_quarantine.csv
    - Does NOT impute missing MSS as 0
"""

import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from scipy import stats
import statsmodels.api as sm
import os
import warnings
warnings.filterwarnings('ignore')

# Legacy only: drop HER double-count with PSS (ALPHA=1.0 → EIS = PSS_n)
ALPHA = 1.0

print("=" * 60)
print("CP-10: LEGACY DISCREPANCY INDEX (DI)")
print("=" * 60)
print("NOTE: Legacy cohort-relative score. Prefer expected_coverage / log_ratio.")
print(f"\nFormula : EIS = {ALPHA}·PSS_n + {1-ALPHA}·HER_n  (HER weight=0)")
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

n_q = df['event_id'].isin(quarantine_ids).sum()
if n_q:
    print(f"Excluding {n_q} quarantined events: "
          f"{sorted(df.loc[df['event_id'].isin(quarantine_ids), 'event_id'].tolist())}")
    df = df[~df['event_id'].isin(quarantine_ids)].copy()

no_mss = df['MSS'].isna().sum()
if no_mss:
    print(f"{no_mss} events have no MSS → dropped (not imputed as 0)")

before = len(df)
df = df.dropna(subset=['PSS', 'MSS', 'exposure_rate'])
dropped = before - len(df)
if dropped:
    print(f"{dropped} events dropped: missing PSS, MSS, or exposure_rate")

print(f"\nEvents entering LEGACY DI computation: {len(df)}")

# ── Step 1: Normalize (legacy MinMax — sensitivity only) ──────────────────────
print("\n[Step 1] LEGACY MinMax normalize PSS, MSS, HER to [0, 1]")

scaler = MinMaxScaler()
df['PSS_n'] = scaler.fit_transform(df[['PSS']]).round(6)
df['MSS_n'] = scaler.fit_transform(df[['MSS']]).round(6)
df['HER_n'] = scaler.fit_transform(df[['exposure_rate']]).round(6)

print(f"  PSS_n : {df['PSS_n'].min():.4f} – {df['PSS_n'].max():.4f}")
print(f"  MSS_n : {df['MSS_n'].min():.4f} – {df['MSS_n'].max():.4f}")
print(f"  HER_n : {df['HER_n'].min():.4f} – {df['HER_n'].max():.4f} (not used in EIS)")

# ── Step 2: Expected Impact Score (PSS only) ──────────────────────────────────
print(f"\n[Step 2] EIS = PSS_n  (ALPHA={ALPHA}; HER excluded to avoid double-count)")

df['EIS'] = (ALPHA * df['PSS_n'] + (1 - ALPHA) * df['HER_n']).round(6)

print(f"  EIS range  : {df['EIS'].min():.4f} – {df['EIS'].max():.4f}")
print(f"  EIS mean   : {df['EIS'].mean():.4f}")
print(f"  EIS median : {df['EIS'].median():.4f}")

# ── Step 3: Discrepancy Index ─────────────────────────────────────────────────
print("\n[Step 3] DI = MSS_n - EIS  (legacy)")

df['DI'] = (df['MSS_n'] - df['EIS']).round(6)

print(f"  DI range   : {df['DI'].min():.4f} – {df['DI'].max():.4f}")
print(f"  DI mean    : {df['DI'].mean():.4f}")
print(f"  DI median  : {df['DI'].median():.4f}")
print(f"  DI std     : {df['DI'].std():.4f}")

over  = (df['DI'] > 0).sum()
under = (df['DI'] < 0).sum()
fair  = (df['DI'] == 0).sum()
print(f"\n  Over-reported  (DI > 0): {over}  events")
print(f"  Fairly reported (DI = 0): {fair}  events")
print(f"  Under-reported (DI < 0): {under}  events")

# ── Step 4: α sensitivity (kept for paper appendix; HER unused when α=1) ───────
print("\n[Step 4] Sensitivity — legacy DI ranks if HER were reintroduced")
print("-" * 55)

alphas = {'α=0.5': 0.5, 'α=1.0 (base)': 1.0, 'α=0.7': 0.7, 'α=0.8': 0.8}
rank_df = df[['event_id', 'state']].copy()

for label, a in alphas.items():
    eis_alt = a * df['PSS_n'] + (1 - a) * df['HER_n']
    di_alt  = df['MSS_n'] - eis_alt
    rank_df[label] = di_alt.rank(ascending=True).astype(int)

rank_cols = list(alphas.keys())
rank_df['max_rank_shift'] = rank_df[rank_cols].max(axis=1) - rank_df[rank_cols].min(axis=1)
max_shift = rank_df['max_rank_shift'].max()
unstable  = rank_df[rank_df['max_rank_shift'] > 5]

print(f"  Max rank shift across α values: {max_shift}")
if unstable.empty:
    print("  ✓ Rankings stable (shift ≤ 5)")
else:
    print(f"  ⚠ {len(unstable)} events shift rank by > 5 positions across α")
    print("  Legacy DI is unstable — use expected_coverage log_ratio instead.")

# ── Step 5: DI by income (cluster-robust OLS) ─────────────────────────────────
print("\n[Step 5] Legacy DI by income group (cluster-robust SE by state)")
print("-" * 55)

di_income = (df.groupby('income_group')['DI']
               .agg(mean='mean', median='median', std='std', n='count')
               .round(4))
print(di_income)

dummies = pd.get_dummies(df['income_group'], drop_first=True)
X = sm.add_constant(dummies.astype(float))
ols = sm.OLS(df['DI'], X).fit(cov_type='cluster', cov_kwds={'groups': df['state']})
print(ols.summary2())

any_sig = False
for name in ols.params.index:
    if name == 'const':
        continue
    lo, hi = ols.conf_int().loc[name]
    covers = lo <= 0 <= hi
    print(f"  {name}: coef={ols.params[name]:.4f}, CI[{lo:.4f},{hi:.4f}], "
          f"covers_0={covers}")
    if not covers:
        any_sig = True
if not any_sig:
    print("  → No detectable income gradient on legacy DI (CIs cover 0).")

# ── Step 6: Calibration (E12 quarantined — use E42) ───────────────────────────
print("\n[Step 6] Calibration check on known events (legacy DI)")
print("-" * 55)

known = {
    'E01': ('Kerala 2018 — catastrophic, high coverage expected',   'over'),
    'E42': ('Delhi 2023 season — metro event, high coverage expected', 'over'),
    'E02': ('Bihar 2019 — severe but peripheral',                   'under'),
    'E10': ('Odisha 2022 — real disaster, low coverage expected',   'under'),
}
for eid, (desc, expected) in known.items():
    row = df[df['event_id'] == eid]
    if row.empty:
        print(f"  ? {eid}: not in data (quarantined or missing)")
        continue
    di_val = row['DI'].values[0]
    actual = 'over' if di_val > 0 else 'under'
    mark   = '✓' if actual == expected else '✗'
    print(f"  {mark} {eid} {desc}")
    print(f"      DI={di_val:.4f}  PSS_n={row['PSS_n'].values[0]:.4f}"
          f"  MSS_n={row['MSS_n'].values[0]:.4f}")

# ── Step 7: Tables ────────────────────────────────────────────────────────────
print("\n[Step 7] Legacy DI table (most under-reported first)")
print("-" * 55)

result = df[['event_id', 'state', 'income_group',
             'PSS_n', 'HER_n', 'EIS', 'MSS_n', 'DI']].copy()
result = result.sort_values('DI')

print("\nMost UNDER-REPORTED (DI most negative):")
print(result.head(15).to_string(index=False))

print("\nMost OVER-REPORTED (DI most positive):")
print(result.tail(15).to_string(index=False))

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

os.makedirs('data', exist_ok=True)
result.to_csv('data/di_results.csv', index=False)
state_di.to_csv('data/state_di.csv', index=False)

print(f"\nSAVED: data/di_results.csv  ({len(result)} events)  [LEGACY]")
print(f"SAVED: data/state_di.csv   ({len(state_di)} states)  [LEGACY]")
print("\nLEGACY CP-10 COMPLETE — primary metric is expected_coverage.log_ratio")
