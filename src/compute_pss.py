import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import os
import warnings
warnings.filterwarnings('ignore')

# ── Load data ─────────────────────────────────────────────────────────────────
df = pd.read_csv('data/severity_raw.csv')
df['affected_area_km2'] = df['adjusted_flood_area_km2']
df = df.dropna(subset=['affected_area_km2', 'population_exposed'])

print("=" * 55)
print("CP-07: COMPUTE PHYSICAL SEVERITY SCORE (PSS)")
print("=" * 55)
print(f"\nEvents loaded: {len(df)}")
print("Normalization: MinMax(log1p(x)) for area and population")

# ── log1p then MinMax to [0, 1] ───────────────────────────────────────────────
# Raw MinMax compresses most events near 0 after district-scale floods;
# log1p reduces right-skew before scaling.
scaler = MinMaxScaler()
df['area_log'] = np.log1p(df['affected_area_km2'].astype(float))
df['pop_log'] = np.log1p(df['population_exposed'].astype(float))
df['area_norm'] = scaler.fit_transform(df[['area_log']]).round(4)
df['pop_norm'] = scaler.fit_transform(df[['pop_log']]).round(4)

print("\nNormalized values (after log1p + MinMax):")
print(df[['event_id', 'state', 'affected_area_km2', 'area_log', 'area_norm',
          'population_exposed', 'pop_log', 'pop_norm']].to_string(index=False))

# ── PSS with primary weights ─────────────────────────────────────────────────
W_AREA = 0.5
W_POP  = 0.5

df['PSS'] = ((W_AREA * df['area_norm']) + (W_POP * df['pop_norm'])).round(4)

# ── Sensitivity analysis on weights ──────────────────────────────────────────
# Tests whether the PSS ranking is stable across different weight choices.
# This is what makes the 0.6/0.4 split defensible in the paper.
weight_configs = {
    'equal_0.5_0.5':   (0.5, 0.5),
    'primary_0.6_0.4': (0.6, 0.4),   # our chosen weights
    'area_heavy_0.7_0.3': (0.7, 0.3),
    'pop_heavy_0.4_0.6':  (0.4, 0.6),
}

print("\n" + "=" * 55)
print("SENSITIVITY ANALYSIS — PSS rank across weight configs")
print("=" * 55)

rank_df = df[['event_id', 'state']].copy()
for label, (wa, wp) in weight_configs.items():
    pss_vals = (wa * df['area_norm'] + wp * df['pop_norm'])
    rank_df[label] = pss_vals.rank(ascending=False).astype(int)

print(rank_df.to_string(index=False))

# Check rank stability: max rank difference across configs per event
rank_cols = list(weight_configs.keys())
rank_df['max_rank_shift'] = rank_df[rank_cols].max(axis=1) - rank_df[rank_cols].min(axis=1)
max_shift = rank_df['max_rank_shift'].max()
unstable  = rank_df[rank_df['max_rank_shift'] > 2]

print(f"\nMax rank shift across all weight configs: {max_shift}")
if unstable.empty:
    print("  OK  Rankings are stable (shift <= 2) — weight choice is defensible")
else:
    print(f"  WARN  {len(unstable)} events shift rank by >2 positions:")
    print(unstable[['event_id', 'state', 'max_rank_shift']].to_string(index=False))
    print("  Note this in paper as a limitation of PSS weight sensitivity")

# ── Final PSS table ───────────────────────────────────────────────────────────
print("\n" + "=" * 55)
print(f"FINAL PSS  (weights: area={W_AREA}, population={W_POP})")
print("=" * 55)

pss_df = df[['event_id', 'state', 'affected_area_km2',
             'population_exposed', 'area_norm', 'pop_norm', 'PSS']].copy()
pss_sorted = pss_df.sort_values('PSS', ascending=False)
print(pss_sorted.to_string(index=False))

print(f"\nPSS range : {pss_df['PSS'].min()} – {pss_df['PSS'].max()}")
print(f"PSS mean  : {pss_df['PSS'].mean():.4f}")
print(f"PSS median: {pss_df['PSS'].median():.4f}")

# ── Income group breakdown ────────────────────────────────────────────────────
events = pd.read_csv('data/events.csv')[['event_id', 'income_group']]
pss_df = pss_df.merge(events, on='event_id')
print("\nMean PSS by income group:")
print(pss_df.groupby('income_group')['PSS'].mean().round(4).to_string())
print("\nThis is a preview — if Low-income PSS >= High-income PSS,")
print("any MSS gap found later is strong evidence of reporting bias.")

# ── Save ──────────────────────────────────────────────────────────────────────
os.makedirs('data', exist_ok=True)
pss_df.to_csv('data/pss_results.csv', index=False)
print(f"\nSAVED: data/pss_results.csv")
print("\nCP-07 COMPLETE — ready for CP-08")
