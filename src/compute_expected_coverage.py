"""
compute_expected_coverage.py  —  Sparse Negative-Binomial expected coverage

Primary model (no GDELT volume offset):
    n_articles ~ NegBin(
        log1p(physical_severity),   # pop_exposed OR flood_area via AIC
        log1p(total_deaths),
        C(onset_year),
        monsoon_flag
    )

Discrepancy (continuous):
    log_ratio = ln( (y + 0.5) / (mu_hat + 0.5) )

Notes:
- Respects data/events_quarantine.csv (#17).
- Does not impute missing article counts as zero.
- Interim outcome: mss_results.total_articles (fixed 0–14 window not yet
  re-extracted; treated as GDELT-monitored volume proxy).
- Legacy Min-Max DI is not used here.
"""

from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.genmod.generalized_linear_model import GLMResultsWrapper

warnings.filterwarnings("ignore", category=RuntimeWarning)

QUARANTINE_PATH = "data/events_quarantine.csv"
EMDAT_PATH = "data/emdat_raw.xlsx"
MEDIA_WINDOW_DAYS = 14
MONSOON_MONTHS = {6, 7, 8, 9}


def load_quarantine_ids(path: str = QUARANTINE_PATH) -> set[str]:
    if not os.path.exists(path):
        print(f"WARNING: {path} not found — no events quarantined")
        return set()
    qdf = pd.read_csv(path)
    ids = set(qdf.loc[qdf["status"] == "quarantine", "event_id"].astype(str))
    print(f"Quarantine list: {len(ids)} events from {path}")
    return ids


def attach_deaths_from_emdat(events: pd.DataFrame) -> pd.Series:
    """Best-effort match of EM-DAT Total Deaths onto location-events."""
    deaths = pd.Series(np.nan, index=events.index, dtype=float)
    if not os.path.exists(EMDAT_PATH):
        print(f"WARNING: {EMDAT_PATH} missing — total_deaths unavailable")
        return deaths

    raw = pd.read_excel(EMDAT_PATH)
    raw = raw[raw["Disaster Type"].astype(str).str.lower() == "flood"].copy()
    raw = raw[(raw["Start Year"] >= 2015) & (raw["Start Year"] <= 2026)].copy()

    def _make_date(y, m, d, default_day=1):
        if pd.isna(y) or pd.isna(m):
            return pd.NaT
        day = int(d) if not pd.isna(d) else default_day
        try:
            return pd.Timestamp(int(y), int(m), day)
        except ValueError:
            return pd.NaT

    raw["start_dt"] = [
        _make_date(r["Start Year"], r["Start Month"], r["Start Day"])
        for _, r in raw.iterrows()
    ]
    raw = raw.dropna(subset=["start_dt"])
    loc = raw["Location"].fillna("").astype(str).str.lower()
    admin = raw.get("Admin Units", pd.Series("", index=raw.index)).fillna("").astype(str).str.lower()

    matched = 0
    for i, row in events.iterrows():
        state = str(row["state"]).lower()
        onset = row["onset_date"]
        mask = (
            (loc.str.contains(state, regex=False) | admin.str.contains(state, regex=False))
            & ((raw["start_dt"] - onset).abs().dt.days <= 45)
        )
        hits = raw.loc[mask, "Total Deaths"].dropna()
        if len(hits):
            deaths.loc[i] = float(hits.max())
            matched += 1

    print(f"EM-DAT deaths matched for {matched}/{len(events)} events "
          f"({deaths.notna().mean():.0%} coverage)")
    return deaths


def build_analysis_frame() -> pd.DataFrame:
    events = pd.read_csv("data/events.csv")
    sev = pd.read_csv("data/severity_raw.csv")[
        ["event_id", "adjusted_flood_area_km2", "population_exposed"]
    ]
    mss = pd.read_csv("data/mss_results.csv")[
        ["event_id", "total_articles", "en_articles"]
    ]

    df = (
        events.merge(sev, on="event_id", how="left")
        .merge(mss, on="event_id", how="left")
    )
    df["onset_date"] = pd.to_datetime(df["start_date"])
    df["onset_year"] = df["onset_date"].dt.year.astype(int)
    df["onset_month"] = df["onset_date"].dt.month.astype(int)
    df["monsoon_flag"] = df["onset_month"].isin(MONSOON_MONTHS).astype(int)
    df["media_window_days"] = MEDIA_WINDOW_DAYS
    # Interim proxy until fixed-window re-extract exists
    df["n_articles_0_14"] = df["total_articles"]
    df["total_deaths"] = attach_deaths_from_emdat(df)

    quarantine_ids = load_quarantine_ids()
    n_q = df["event_id"].isin(quarantine_ids).sum()
    if n_q:
        print(
            "Excluding quarantined events: "
            f"{sorted(df.loc[df['event_id'].isin(quarantine_ids), 'event_id'].tolist())}"
        )
        df = df[~df["event_id"].isin(quarantine_ids)].copy()

    before = len(df)
    # Never impute missing media as zero
    df = df.dropna(
        subset=[
            "n_articles_0_14",
            "population_exposed",
            "adjusted_flood_area_km2",
            "onset_year",
            "monsoon_flag",
        ]
    )
    print(f"Dropped {before - len(df)} rows with missing media/severity "
          f"(no zero-imputation)")
    print(f"Analysis rows: {len(df)}")
    return df.reset_index(drop=True)


def design_matrix(df: pd.DataFrame, severity_col: str, include_deaths: bool) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    X["log1p_severity"] = np.log1p(df[severity_col].astype(float))
    if include_deaths:
        X["log1p_deaths"] = np.log1p(df["total_deaths"].astype(float))
    X["monsoon_flag"] = df["monsoon_flag"].astype(float)
    year_dummies = pd.get_dummies(df["onset_year"], prefix="year", drop_first=True)
    X = pd.concat([X, year_dummies.astype(float)], axis=1)
    return sm.add_constant(X, has_constant="add")


def fit_negbin(
    y: pd.Series,
    X: pd.DataFrame,
    groups: pd.Series,
) -> GLMResultsWrapper:
    # Estimate dispersion via NB2 MLE, then GLM with cluster-robust SE
    nb = sm.NegativeBinomial(y, X).fit(disp=False, maxiter=200)
    alpha = float(nb.params.get("alpha", 1.0))
    if not np.isfinite(alpha) or alpha <= 0:
        alpha = 1.0
    model = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha))
    return model.fit(cov_type="cluster", cov_kwds={"groups": groups})


def choose_severity_proxy(df: pd.DataFrame, include_deaths: bool) -> str:
    y = df["n_articles_0_14"].astype(float)
    groups = df["state"]
    candidates = {
        "population_exposed": "log1p(population_exposed)",
        "adjusted_flood_area_km2": "log1p(flood_area_km2)",
    }
    scores = {}
    for col, label in candidates.items():
        X = design_matrix(df, col, include_deaths=include_deaths)
        try:
            res = fit_negbin(y, X, groups)
            scores[col] = (float(res.aic), label, res)
            print(f"  Candidate {label}: AIC={res.aic:.1f}")
        except Exception as exc:
            print(f"  Candidate {label}: FAILED ({exc})")
    if not scores:
        raise RuntimeError("No NegBin specification converged")
    best = min(scores, key=lambda k: scores[k][0])
    print(f"Selected severity proxy: {scores[best][1]} (lowest AIC)")
    return best


def percentile_tier(resid: pd.Series) -> pd.Series:
    lo = resid.quantile(0.20)
    hi = resid.quantile(0.80)
    return pd.Series(
        np.where(resid <= lo, "low", np.where(resid >= hi, "high", "mid")),
        index=resid.index,
    )


def income_cluster_robust(df: pd.DataFrame) -> None:
    """log_ratio ~ income dummies with cluster-robust SE by state."""
    print("\n[Income contrast] log_ratio ~ income_group (cluster-robust by state)")
    print("-" * 55)
    dummies = pd.get_dummies(df["income_group"], drop_first=True)
    X = sm.add_constant(dummies.astype(float))
    ols = sm.OLS(df["log_ratio"].astype(float), X).fit(
        cov_type="cluster", cov_kwds={"groups": df["state"]}
    )
    print(ols.summary2())

    # Low vs High contrast if both present
    if "Low" in dummies.columns or "High" not in df["income_group"].unique():
        # With drop_first, reference is usually High alphabetically? 
        # get_dummies drop_first drops first category alphabetically: High
        pass

    any_sig = False
    for name, param, ci_lo, ci_hi, pval in zip(
        ols.params.index,
        ols.params.values,
        ols.conf_int()[0],
        ols.conf_int()[1],
        ols.pvalues.values,
    ):
        if name == "const":
            continue
        covers_zero = (ci_lo <= 0 <= ci_hi)
        print(
            f"  {name}: coef={param:.4f}, 95% CI [{ci_lo:.4f}, {ci_hi:.4f}], "
            f"p={pval:.4f}, CI_covers_0={covers_zero}"
        )
        if not covers_zero:
            any_sig = True

    if any_sig:
        print("  → Detectable income gradient in this GDELT-monitored system "
              "(at least one CI excludes 0).")
    else:
        print("  → No detectable income gradient in this GDELT system "
              "(all income CIs cover 0) — do not claim bias.")


def main() -> None:
    print("=" * 60)
    print("EXPECTED COVERAGE — sparse Negative-Binomial")
    print("=" * 60)
    print(f"Media window (design): onset + {MEDIA_WINDOW_DAYS}d "
          "(interim outcome = total_articles from MSS)")
    print("Primary model: NO GDELT volume offset")

    df = build_analysis_frame()

    death_coverage = df["total_deaths"].notna().mean()
    include_deaths = death_coverage >= 0.5
    if include_deaths:
        # For rows still missing deaths after match, drop (no zero-impute)
        before = len(df)
        df = df.dropna(subset=["total_deaths"]).copy()
        print(f"Deaths included; dropped {before - len(df)} rows still missing deaths")
    else:
        print(f"Death coverage {death_coverage:.0%} < 50% — omitting log1p(deaths) "
              f"from primary model")

    severity_col = choose_severity_proxy(df, include_deaths=include_deaths)
    y = df["n_articles_0_14"].astype(float)
    X = design_matrix(df, severity_col, include_deaths=include_deaths)
    result = fit_negbin(y, X, df["state"])

    print("\n[Primary NegBin / GLM cluster-robust by state]")
    print(result.summary2())

    mu = np.asarray(result.fittedvalues, dtype=float)
    # Guard against non-positive fitted means
    mu = np.clip(mu, 1e-8, None)
    log_ratio = np.log((y.values + 0.5) / (mu + 0.5))
    pearson = (y.values - mu) / np.sqrt(mu + result.scale * mu ** 2 + 1e-12)

    out = df[
        [
            "event_id",
            "state",
            "income_group",
            "onset_year",
            "monsoon_flag",
            "n_articles_0_14",
            "population_exposed",
            "adjusted_flood_area_km2",
            "total_deaths",
        ]
    ].copy()
    out["severity_proxy"] = severity_col
    out["observed"] = y.values
    out["expected"] = mu
    out["log_ratio"] = log_ratio
    out["pearson_resid"] = pearson
    out["deviance_resid"] = result.resid_deviance
    out["tier"] = percentile_tier(out["log_ratio"])
    out["rank_undercovered"] = out["log_ratio"].rank(method="average", ascending=True).astype(int)

    out = out.sort_values("log_ratio")

    print("\nMost UNDER-covered (lowest log_ratio):")
    print(
        out.head(15)[
            ["event_id", "state", "income_group", "observed", "expected", "log_ratio", "tier"]
        ].to_string(index=False)
    )
    print("\nMost OVER-covered (highest log_ratio):")
    print(
        out.tail(15)[
            ["event_id", "state", "income_group", "observed", "expected", "log_ratio", "tier"]
        ].to_string(index=False)
    )

    income_cluster_robust(out)

    state_agg = (
        out.groupby(["state", "income_group"], as_index=False)
        .agg(
            mean_log_ratio=("log_ratio", "mean"),
            median_log_ratio=("log_ratio", "median"),
            n_events=("log_ratio", "count"),
            mean_observed=("observed", "mean"),
            mean_expected=("expected", "mean"),
        )
        .sort_values("mean_log_ratio")
    )

    os.makedirs("data", exist_ok=True)
    out.to_csv("data/expected_coverage.csv", index=False)
    state_agg.to_csv("data/state_expected_coverage.csv", index=False)
    print(f"\nSAVED: data/expected_coverage.csv ({len(out)} events)")
    print(f"SAVED: data/state_expected_coverage.csv ({len(state_agg)} states)")
    print("\nEXPECTED COVERAGE COMPLETE")


if __name__ == "__main__":
    main()
