"""
compute_mss.py — Media Salience Score (MSS)

Primary input: data/gdelt_bq.json (BigQuery export).
Does NOT read news.py / raw_gdelt.csv — that path is optional/legacy
(see src/archive/news.py).

Primary MSS uses AHP weights; Entropy/Equal retained for sensitivity.
"""

from __future__ import annotations

import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cvnd_paths import (  # noqa: E402
    EVENTS,
    GDELT_BQ,
    MSS_RANK_STABILITY as MSS_RANK_STABILITY_PATH,
    MSS_RESULTS,
    MSS_WEIGHT_META as MSS_WEIGHT_META_PATH,
    MSS_WEIGHT_PROVENANCE as MSS_WEIGHT_PROVENANCE_PATH,
)

MSS_FEATURES = ["S_vol", "S_sov", "S_TTFR", "S_CD"]
AHP_LABELS = MSS_FEATURES

# Pairwise judgments (Saaty 1–9): see module doc in Step 5 below.
AHP_MATRIX = np.array([
    [1,   1,   3,   3],
    [1,   1,   3,   3],
    [1/3, 1/3, 1,   1],
    [1/3, 1/3, 1,   1],
])


def compute_ahp_weights(matrix: np.ndarray, labels: list[str]) -> dict:
    """Derive AHP weights via column-normalization + row means; print CR."""
    n = matrix.shape[0]
    col_sums = matrix.sum(axis=0)
    norm = matrix / col_sums
    weights = norm.mean(axis=1)

    weighted_sum = matrix @ weights
    lambda_max = (weighted_sum / weights).mean()
    ci = (lambda_max - n) / (n - 1)

    ri_table = {
        1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12,
        6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
    }
    ri = ri_table.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0

    print("\n  AHP Pairwise Comparison Matrix:")
    header = f"  {'':>8}" + "".join(f"{label:>8}" for label in labels)
    print(header)
    for i, label in enumerate(labels):
        row = f"  {label:>8}" + "".join(
            f"{matrix[i, j]:>8.3f}" for j in range(n)
        )
        print(row)

    print("\n  Derived weights (principal eigenvector):")
    result: dict = {}
    for label, weight in zip(labels, weights):
        print(f"    {label:>8}: {weight:.4f}")
        result[label] = round(float(weight), 4)

    print(f"\n  λ_max = {lambda_max:.4f}")
    print(f"  CI    = {ci:.4f}")
    print(f"  RI    = {ri:.4f}  (Saaty 1980, n={n})")
    print(f"  CR    = {cr:.4f}  ", end="")
    if cr < 0.10:
        print("✓ CR < 0.10 — judgments are consistent (AHP valid)")
    else:
        print("✗ CR ≥ 0.10 — judgments are inconsistent, revise matrix")

    result["CR"] = round(cr, 4)
    result["lambda_max"] = round(float(lambda_max), 4)
    return result


def entropy_weights(X: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Shannon entropy weights for positive indicators in [0, 1]."""
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


def print_entropy_weights(
    labels: list[str], weights: np.ndarray, X: np.ndarray
) -> None:
    """Print entropy weights with per-criterion entropy for transparency."""
    P = np.clip(X / X.sum(axis=0), 1e-12, None)
    k = 1.0 / np.log(len(X))
    entropy = -k * (P * np.log(P)).sum(axis=0)
    print("\n  Entropy weights (data-driven):")
    for label, weight, ent in zip(labels, weights, entropy):
        print(f"    {label:>8}: w={weight:.4f}  entropy={ent:.4f}")


def weighted_mss(frame: pd.DataFrame, weights: np.ndarray) -> pd.Series:
    values = (frame[MSS_FEATURES].values @ weights).round(4)
    return pd.Series(values, index=frame.index)


def rank_shift(base: pd.Series, alt: pd.Series) -> tuple[float, float]:
    rb = base.rank(ascending=False, method="average")
    ra = alt.rank(ascending=False, method="average")
    diff = (rb - ra).abs()
    return float(diff.max()), float(diff.mean())


def weights_vector(ahp: dict) -> np.ndarray:
    return np.array([ahp[label] for label in MSS_FEATURES], dtype=float)


def main() -> None:
    print("=" * 60)
    print("COMPUTE MEDIA SALIENCE SCORE (MSS)")
    print("=" * 60)

    # ── Step 1: Load BigQuery JSON ───────────────────────────────────────────────
    print("\n[Step 1] Loading BigQuery JSON...")

    gdelt_path = str(GDELT_BQ)
    if not os.path.exists(gdelt_path):
        raise FileNotFoundError(f"Missing GDELT export: {gdelt_path}")

    with open(gdelt_path, "r") as f:
        data = json.load(f)
    raw = pd.DataFrame(data)
    print(f"  {gdelt_path}: {len(raw)} rows")
    raw["article_count"] = raw["article_count"].astype(int)
    raw["coverage_days"] = raw["coverage_days"].astype(int)
    raw["first_article_date"] = pd.to_datetime(raw["first_article_date"])
    raw["last_article_date"] = pd.to_datetime(raw["last_article_date"])

    print(f"\nTotal rows: {len(raw)}")
    print(f"Events covered: {raw['event_id'].nunique()}")
    print(f"Languages found: {sorted(raw['source_lang'].dropna().unique())}")

    # ── Step 2: Aggregate per event ───────────────────────────────────────────────
    print("\n[Step 2] Aggregating per event...")

    event_agg = raw.groupby(["event_id", "state"]).agg(
        total_articles=("article_count", "sum"),
        first_date=("first_article_date", "min"),
        last_date=("last_article_date", "max"),
        coverage_days=("coverage_days", "max"),
    ).reset_index()

    INDIC_LANGS = {
        "hin", "mal", "tam", "tel", "kan", "ben", "mar", "guj", "pan", "urd",
        "ori", "asm", "pun", "sat", "kok", "dog", "mai", "mni",
    }
    raw["is_indic"] = raw["source_lang"].isin(INDIC_LANGS)
    raw["is_en"] = raw["source_lang"] == "en"

    indic_agg = (
        raw[raw["is_indic"]]
        .groupby("event_id")["article_count"]
        .sum()
        .reset_index()
        .rename(columns={"article_count": "indic_articles"})
    )
    en_agg = (
        raw[raw["is_en"]]
        .groupby("event_id")["article_count"]
        .sum()
        .reset_index()
        .rename(columns={"article_count": "en_articles"})
    )

    df = event_agg.merge(indic_agg, on="event_id", how="left")
    df = df.merge(en_agg, on="event_id", how="left")
    df["indic_articles"] = df["indic_articles"].fillna(0).astype(int)
    df["en_articles"] = df["en_articles"].fillna(0).astype(int)
    df["indic_share"] = (
        df["indic_articles"] / df["total_articles"].replace(0, np.nan)
    ).fillna(0)

    # ── Step 3: Event onset dates ─────────────────────────────────────────────────
    print("\n[Step 3] Loading event onset dates...")
    events = pd.read_csv(EVENTS)[
        ["event_id", "state", "start_date", "income_group"]
    ]
    events["onset_date"] = pd.to_datetime(events["start_date"])
    df = df.merge(
        events[["event_id", "onset_date", "income_group"]], on="event_id", how="left"
    )

    # ── Step 4: Compute normalized components ─────────────────────────────────────
    print("\n[Step 4] Computing MSS components...")

    N_total = df["total_articles"].sum()
    print(f"  N_total_news (all events): {N_total:,}")

    skew = df["total_articles"].skew()
    print(f"  Article count skewness: {skew:.2f}")
    if abs(skew) > 2:
        print("  Skewness > 2 → using log scaling for S_vol")
        df["vol_scaled"] = np.log1p(df["total_articles"])
    else:
        print("  Skewness <= 2 → using linear scaling for S_vol")
        df["vol_scaled"] = df["total_articles"].astype(float)

    scaler = MinMaxScaler()
    df["S_vol"] = scaler.fit_transform(df[["vol_scaled"]]).round(4)
    df["S_sov"] = scaler.fit_transform(
        (df["total_articles"] / N_total).values.reshape(-1, 1)
    ).round(4)

    GAMMA = 0.3
    df["t_first_days"] = (
        (df["first_date"] - df["onset_date"]).dt.days.clip(lower=0).fillna(14)
    )
    df["S_TTFR_g01"] = np.exp(-0.1 * df["t_first_days"]).round(4)
    df["S_TTFR_g03"] = np.exp(-GAMMA * df["t_first_days"]).round(4)
    df["S_TTFR_g05"] = np.exp(-0.5 * df["t_first_days"]).round(4)
    df["S_TTFR"] = df["S_TTFR_g03"]

    df["S_CD"] = scaler.fit_transform(df[["coverage_days"]]).round(4)

    # ── Step 5: AHP weights (primary) ─────────────────────────────────────────────
    print("\n[Step 5] Deriving weights via AHP (Saaty 1980)")
    print("-" * 55)
    ahp = compute_ahp_weights(AHP_MATRIX, AHP_LABELS)
    w_ahp = weights_vector(ahp)
    W_VOL, W_SOV, W_TTFR, W_CD = w_ahp
    print(
        f"\n  AHP weights: vol={W_VOL:.4f}, sov={W_SOV:.4f}, "
        f"TTFR={W_TTFR:.4f}, CD={W_CD:.4f}  (sum={w_ahp.sum():.4f})"
    )

    # ── Step 6: Entropy weights (robustness) ──────────────────────────────────────
    print("\n[Step 6] Entropy weighting — robustness check")
    print("-" * 55)
    components_df = df[MSS_FEATURES].copy()
    w_entropy = entropy_weights(components_df.values)
    print_entropy_weights(AHP_LABELS, w_entropy, components_df.values)
    print(
        f"\n  Entropy weights: vol={w_entropy[0]:.4f}, sov={w_entropy[1]:.4f}, "
        f"TTFR={w_entropy[2]:.4f}, CD={w_entropy[3]:.4f}  (sum={w_entropy.sum():.4f})"
    )

    # ── Step 7: MSS under AHP (primary) and entropy (robustness) ──────────────────
    print("\n[Step 7] Computing MSS (AHP primary) and MSS_entropy (robustness)")
    print("-" * 55)

    df["MSS"] = weighted_mss(df, w_ahp)
    df["MSS_entropy"] = weighted_mss(df, w_entropy)

    # ── Step 8: Rank stability across weight sets + γ sensitivity ─────────────────
    print("\n[Step 8] Rank stability across all weight sets + γ sensitivity")
    print("-" * 55)

    rank_configs = {
        "AHP (primary)": df["MSS"],
        "Entropy": df["MSS_entropy"],
        "Equal (0.25×4)": weighted_mss(df, np.full(4, 0.25)),
        "Vol-heavy": weighted_mss(df, np.array([0.4, 0.4, 0.1, 0.1])),
        "Time-heavy": weighted_mss(df, np.array([0.2, 0.2, 0.3, 0.3])),
        "AHP γ=0.1": (
            W_VOL * df["S_vol"]
            + W_SOV * df["S_sov"]
            + W_TTFR * df["S_TTFR_g01"]
            + W_CD * df["S_CD"]
        ).round(4),
        "AHP γ=0.5": (
            W_VOL * df["S_vol"]
            + W_SOV * df["S_sov"]
            + W_TTFR * df["S_TTFR_g05"]
            + W_CD * df["S_CD"]
        ).round(4),
    }

    rank_df = df[["event_id", "state"]].copy()
    for label, mss_vals in rank_configs.items():
        rank_df[label] = mss_vals.rank(ascending=False).astype(int)

    rank_cols = list(rank_configs.keys())
    rank_df["max_rank_shift"] = (
        rank_df[rank_cols].max(axis=1) - rank_df[rank_cols].min(axis=1)
    )
    max_shift = int(rank_df["max_rank_shift"].max())
    unstable = rank_df[rank_df["max_rank_shift"] > 5]

    print(f"  Max rank shift across all configs: {max_shift}")
    if unstable.empty:
        print("  ✓ Rankings stable (shift ≤ 5 positions) across all weight sets and γ values")
        print("    → AHP weights are defensible; results robust to weight choice")
    else:
        print(f"  ⚠ {len(unstable)} events shift rank by > 5 positions:")
        print(unstable[["event_id", "state", "max_rank_shift"]].to_string(index=False))
        print("    → Note instability as a limitation in the paper")

    print("\n  Weight comparison table (for methods section):")
    print(
        f"  {'Criterion':<10} {'AHP':>8} {'Entropy':>10} {'Equal':>8} "
        f"{'Vol-heavy':>10} {'Time-heavy':>11}"
    )
    for i, criterion in enumerate(AHP_LABELS):
        equal = 0.25
        vol_heavy = 0.4 if criterion in ("S_vol", "S_sov") else 0.1
        time_heavy = 0.2 if criterion in ("S_vol", "S_sov") else 0.3
        print(
            f"  {criterion:<10} {w_ahp[i]:>8.4f} {w_entropy[i]:>10.4f} "
            f"{equal:>8.4f} {vol_heavy:>10.4f} {time_heavy:>11.4f}"
        )

    entropy_corr = float(df["MSS"].corr(df["MSS_entropy"]))
    entropy_max_shift, entropy_mean_shift = rank_shift(df["MSS"], df["MSS_entropy"])
    print(
        f"\n  AHP vs Entropy: Pearson r={entropy_corr:.4f}, "
        f"max rank shift={entropy_max_shift:.0f}, "
        f"mean rank shift={entropy_mean_shift:.2f}"
    )

    for g_label, g_col in [
        ("γ=0.1", "S_TTFR_g01"),
        ("γ=0.3", "S_TTFR_g03"),
        ("γ=0.5", "S_TTFR_g05"),
    ]:
        mss_g = (
            W_VOL * df["S_vol"]
            + W_SOV * df["S_sov"]
            + W_TTFR * df[g_col]
            + W_CD * df["S_CD"]
        )
        max_s, _ = rank_shift(df["MSS"], mss_g)
        print(f"  {g_label}: max rank shift vs AHP primary = {max_s:.0f}")

    weight_meta = {
        "primary": "ahp",
        "features": MSS_FEATURES,
        "weights": {
            "ahp": w_ahp.tolist(),
            "entropy": w_entropy.tolist(),
            "equal": [0.25, 0.25, 0.25, 0.25],
            "vol_heavy": [0.4, 0.4, 0.1, 0.1],
            "time_heavy": [0.2, 0.2, 0.3, 0.3],
        },
        "ahp_cr": ahp["CR"],
        "ahp_lambda_max": ahp["lambda_max"],
        "sensitivity_vs_primary": {
            "entropy": {
                "pearson_r": entropy_corr,
                "max_rank_shift": entropy_max_shift,
                "mean_rank_shift": entropy_mean_shift,
            },
        },
        "rank_stability": {
            "max_rank_shift_all_configs": max_shift,
            "n_unstable_events": int(len(unstable)),
        },
        "n_events": int(len(df)),
    }
    MSS_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with open(MSS_WEIGHT_META_PATH, "w", encoding="utf-8") as f:
        json.dump(weight_meta, f, indent=2)
    print(f"\n  SAVED: {MSS_WEIGHT_META_PATH}")

    # ── Step 9: Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("MSS RESULTS SUMMARY  (primary = AHP weights)")
    print("=" * 60)

    result = df[
        [
            "event_id",
            "state",
            "income_group",
            "total_articles",
            "indic_articles",
            "en_articles",
            "indic_share",
            "coverage_days",
            "t_first_days",
            "S_vol",
            "S_sov",
            "S_TTFR",
            "S_CD",
            "MSS",
            "MSS_entropy",
        ]
    ].copy()

    print(result.sort_values("MSS", ascending=False).to_string(index=False))

    print(f"\nMSS (AHP) range  : {result['MSS'].min():.4f} – {result['MSS'].max():.4f}")
    print(f"MSS (AHP) mean   : {result['MSS'].mean():.4f}")
    print(f"MSS (AHP) median : {result['MSS'].median():.4f}")
    print(f"Zero MSS         : {(result['MSS'] == 0).sum()} events")
    print(
        f"\nCorrelation MSS_AHP vs MSS_entropy: "
        f"{result['MSS'].corr(result['MSS_entropy']):.4f}"
    )
    print("(High correlation = entropy weighting confirms AHP rankings)")

    print("\nMean MSS by income group:")
    print(result.groupby("income_group")["MSS"].mean().round(4).to_string())

    print("\nMean total_articles by income group:")
    print(result.groupby("income_group")["total_articles"].mean().round(0).to_string())

    print("\nMean indic_share by income group:")
    print(result.groupby("income_group")["indic_share"].mean().round(4).to_string())

    print("\nTop 10 by MSS:")
    print(
        result.nlargest(10, "MSS")[
            ["event_id", "state", "total_articles", "MSS", "MSS_entropy", "indic_share"]
        ].to_string(index=False)
    )
    print("\nBottom 10 by MSS:")
    print(
        result.nsmallest(10, "MSS")[
            ["event_id", "state", "total_articles", "MSS", "MSS_entropy", "indic_share"]
        ].to_string(index=False)
    )

    # ── Step 10: Save ─────────────────────────────────────────────────────────────
    weight_record = pd.DataFrame([
        {
            "method": "AHP",
            "S_vol": w_ahp[0],
            "S_sov": w_ahp[1],
            "S_TTFR": w_ahp[2],
            "S_CD": w_ahp[3],
            "CR": ahp["CR"],
        },
        {
            "method": "Entropy",
            "S_vol": w_entropy[0],
            "S_sov": w_entropy[1],
            "S_TTFR": w_entropy[2],
            "S_CD": w_entropy[3],
            "CR": None,
        },
        {
            "method": "Equal",
            "S_vol": 0.25,
            "S_sov": 0.25,
            "S_TTFR": 0.25,
            "S_CD": 0.25,
            "CR": None,
        },
    ])
    weight_record.to_csv(MSS_WEIGHT_PROVENANCE_PATH, index=False)
    rank_df.to_csv(MSS_RANK_STABILITY_PATH, index=False)
    result.to_csv(MSS_RESULTS, index=False)

    print(f"\nSAVED: {MSS_RESULTS}")
    print(f"SAVED: {MSS_WEIGHT_PROVENANCE_PATH}  (cite this in paper appendix)")
    print(f"SAVED: {MSS_RANK_STABILITY_PATH}")
    print("\nMSS COMPLETE — next: compute_expected_coverage.py")


if __name__ == "__main__":
    main()
