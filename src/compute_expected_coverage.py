"""
compute_expected_coverage.py  —  Sparse Negative-Binomial expected coverage

Primary model (no GDELT volume offset):
    n_articles ~ NegBin(
        log1p(physical_severity),   # pop_exposed OR flood_area via AIC
        log1p(total_deaths),
        C(onset_year)
    )

Branch note (feat/expected-coverage-no-monsoon):
    monsoon_flag is retained as a metadata column but is NOT a NegBin regressor.

Discrepancy (continuous, primary):
    log_ratio = ln( (y + 0.5) / (mu_hat + 0.5) )

Hybrid labels:
    under_flag     = log_ratio < 0          # absolute under-coverage
    over_flag      = log_ratio > 0
    severity_tier  = tertile low/mid/high   # severe-neglect exploration pool (P33/P67)

Deaths (option C):
    Keep rows with missing EM-DAT deaths.
    log1p_deaths = log1p(fillna(total_deaths, 0)) enters NegBin.
    deaths_missing is kept as metadata only (not a regressor).

Notes:
- Respects data/events_quarantine.csv (#17).
- Does not impute missing article counts as zero.
- Interim outcome: mss_results.total_articles (fixed 0–14 window not yet
  re-extracted; treated as GDELT-monitored volume proxy).
"""

from __future__ import annotations

import json
import os
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.genmod.generalized_linear_model import GLMResultsWrapper

warnings.filterwarnings("ignore", category=RuntimeWarning)

QUARANTINE_PATH = "data/events_quarantine.csv"
EMDAT_PATH = "data/emdat_raw.xlsx"
MSS_WEIGHT_META_PATH = "data/mss_weight_sensitivity.json"
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
        # Option C: fill missing deaths with 0; do not add deaths_missing flag
        X["log1p_deaths"] = np.log1p(df["total_deaths"].astype(float))
    # monsoon_flag excluded from NegBin (sensitivity: feat/expected-coverage-no-monsoon)
    # deaths_missing excluded from NegBin (option C; metadata only)
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


def severity_tier_tertile(resid: pd.Series) -> pd.Series:
    """Exploratory tertile buckets on log_ratio (severe-neglect pool, not significance).

    - low  = bottom tertile  (≤ 33rd percentile) — severe under-coverage exploration pool
    - high = top tertile     (≥ 67th percentile)
    - mid  = middle tertile

    Binary under/over uses under_flag / over_flag (log_ratio <> 0), not these tiers.
    """
    lo = resid.quantile(1.0 / 3.0)
    hi = resid.quantile(2.0 / 3.0)
    return pd.Series(
        np.where(resid <= lo, "low", np.where(resid >= hi, "high", "mid")),
        index=resid.index,
    )


# Back-compat alias
percentile_tier = severity_tier_tertile


def income_cluster_robust(df: pd.DataFrame) -> dict:
    """log_ratio ~ income dummies with cluster-robust SE by state."""
    print("\n[Income contrast] log_ratio ~ income_group (cluster-robust by state)")
    print("-" * 55)
    dummies = pd.get_dummies(df["income_group"], drop_first=True)
    X = sm.add_constant(dummies.astype(float))
    ols = sm.OLS(df["log_ratio"].astype(float), X).fit(
        cov_type="cluster", cov_kwds={"groups": df["state"]}
    )
    print(ols.summary2())

    rows = []
    any_sig = False
    for name in ols.params.index:
        if name == "const":
            continue
        ci_lo, ci_hi = ols.conf_int().loc[name]
        covers_zero = bool(ci_lo <= 0 <= ci_hi)
        rows.append(
            {
                "term": name,
                "coef": float(ols.params[name]),
                "ci_lo": float(ci_lo),
                "ci_hi": float(ci_hi),
                "p": float(ols.pvalues[name]),
                "ci_covers_0": covers_zero,
            }
        )
        print(
            f"  {name}: coef={ols.params[name]:.4f}, 95% CI [{ci_lo:.4f}, {ci_hi:.4f}], "
            f"p={ols.pvalues[name]:.4f}, CI_covers_0={covers_zero}"
        )
        if not covers_zero:
            any_sig = True

    if any_sig:
        verdict = (
            "Detectable income gradient in this GDELT-monitored system "
            "(at least one CI excludes 0)."
        )
    else:
        verdict = (
            "No detectable income gradient in this GDELT system "
            "(all income CIs cover 0) — do not claim bias."
        )
    print(f"  → {verdict}")
    return {"terms": rows, "verdict": verdict, "r2": float(ols.rsquared)}


def _md_table(df: pd.DataFrame, cols: list[str], float_cols: dict[str, str] | None = None) -> str:
    """Render a small markdown table."""
    float_cols = float_cols or {}
    view = df[cols].copy()
    for c, fmt in float_cols.items():
        if c in view.columns:
            view[c] = view[c].map(lambda x, f=fmt: f.format(x) if pd.notna(x) else "")
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [header, sep]
    for _, row in view.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def format_mss_weight_section() -> str:
    """Legacy MSS weight sensitivity block (from compute_mss.py / EWM)."""
    if not os.path.exists(MSS_WEIGHT_META_PATH):
        return ""

    with open(MSS_WEIGHT_META_PATH, encoding="utf-8") as f:
        meta = json.load(f)

    feats = meta.get("features", ["S_vol", "S_sov", "S_TTFR", "S_CD"])
    w = meta.get("weights", {})
    sens = meta.get("sensitivity_vs_fixed", {})
    n_events = meta.get("n_events", "n/a")

    def _row(label: str, key: str) -> str:
        vals = w.get(key, [])
        if len(vals) != len(feats):
            return ""
        cells = " | ".join(f"{v:.4f}" for v in vals)
        return f"| {label} | {cells} |"

    weight_rows = "\n".join(
        r for r in [_row("Fixed (primary)", "fixed"), _row("EWM", "ewm"), _row("PCA loadings", "pca")]
        if r
    )

    ewm = sens.get("ewm", {})
    pca = sens.get("pca", {})
    pca_ev = meta.get("pca_explained_variance")
    pca_ev_str = f"{pca_ev:.4f}" if pca_ev is not None else "n/a"

    return f"""## Legacy MSS weight sensitivity (CP-09)

Primary `MSS` in `data/mss_results.csv` uses **fixed** weights (0.3/0.3/0.2/0.2).
Entropy Weight Method (EWM) and PCA loadings are computed on the same scaled
components for sensitivity only (`MSS_ewm`, `MSS_pca` columns).

| Scheme | {' | '.join(feats)} |
| --- | {' | '.join('---' for _ in feats)} |
{weight_rows}

| vs fixed MSS | Pearson r | max rank shift | mean rank shift |
| --- | --- | --- | --- |
| EWM | {ewm.get('pearson_r', float('nan')):.4f} | {ewm.get('max_rank_shift', float('nan')):.0f} | {ewm.get('mean_rank_shift', float('nan')):.2f} |
| PCA | {pca.get('pearson_r', float('nan')):.4f} | {pca.get('max_rank_shift', float('nan')):.0f} | {pca.get('mean_rank_shift', float('nan')):.2f} |

- MSS events: {n_events}
- PCA PC1 explained variance: {pca_ev_str}
- Primary coverage metric remains NegBin `log_ratio` (not MSS).

"""


def write_markdown_report(
    out: pd.DataFrame,
    state_agg: pd.DataFrame,
    result,
    severity_col: str,
    include_deaths: bool,
    income_summary: dict,
    path: str = "outputs/pipeline_result.md",
) -> str:
    """Write final expected-coverage results to a markdown file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    generated = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    income_means = (
        out.groupby("income_group")["log_ratio"]
        .agg(mean="mean", median="median", std="std", n="count")
        .reindex(["High", "Middle", "Low"])
        .reset_index()
    )

    under = out.nsmallest(15, "log_ratio")
    over = out.nlargest(15, "log_ratio")

    n_under = int(out["under_flag"].sum())
    n_over = int(out["over_flag"].sum())
    under_by_income = (
        out.groupby("income_group")["under_flag"]
        .agg(n_under="sum", n="count", share="mean")
        .reindex(["High", "Middle", "Low"])
        .reset_index()
    )

    income_rows = []
    for t in income_summary["terms"]:
        income_rows.append(
            f"| {t['term']} | {t['coef']:.4f} | [{t['ci_lo']:.4f}, {t['ci_hi']:.4f}] | "
            f"{t['p']:.4f} | {t['ci_covers_0']} |"
        )

    plot_links = []
    for fname, label in [
        ("plot5_observed_vs_expected.png", "Observed vs expected calibration"),
        ("plot6_log_ratio_histogram.png", "log_ratio residual histogram"),
        ("plot7_log_ratio_ranking.png", "Coverage imbalance ranking (extremes)"),
        ("plot8_log_ratio_by_income.png", "log_ratio by income group"),
    ]:
        p = os.path.join("outputs", fname)
        if os.path.exists(p):
            plot_links.append(f"- [{label}]({fname})")

    md = f"""# CVND Pipeline Results — Expected Coverage

Generated: `{generated}`

## Analysis standard (hybrid)

- **Primary metric:** continuous `log_ratio = ln((y+0.5)/(μ̂+0.5))` rankings
- **Binary under-coverage:** `under_flag` when `log_ratio < 0` (observed &lt; expected)
- **Severe-neglect exploration pool:** `severity_tier == low` (bottom tertile ≤ P33)

## Summary

| Item | Value |
| --- | --- |
| Primary metric | `log_ratio = ln((y+0.5)/(μ̂+0.5))` |
| Model | Sparse Negative-Binomial (cluster-robust SE by state) |
| Monsoon flag | **Excluded** from NegBin (metadata only; sensitivity branch) |
| GDELT volume offset | **None** (primary) |
| Media window (design) | onset + {MEDIA_WINDOW_DAYS} days |
| Outcome (interim) | `mss_results.total_articles` as `n_articles_0_14` proxy |
| Severity proxy (AIC) | `{severity_col}` |
| Flood area source | `flood_combined.combined_km2` (district-level; via severity_raw) |
| Deaths handling | Option C: `log1p(deaths)` with `fillna(0)`; `deaths_missing` metadata only (not in NegBin) |
| Deaths missing (metadata) | {int(out['deaths_missing'].sum()) if 'deaths_missing' in out.columns else 'n/a'} / {len(out)} |
| N events | {len(out)} |
| NegBin AIC | {float(result.aic):.1f} |
| NegBin log-likelihood | {float(result.llf):.1f} |
| under_flag (log_ratio &lt; 0) | {n_under} ({n_under / len(out):.1%}) |
| over_flag (log_ratio &gt; 0) | {n_over} ({n_over / len(out):.1%}) |
| severity_tier | Tertiles (low ≤ P33, high ≥ P67; exploratory only) |

{format_mss_weight_section()}## Absolute under-coverage (`under_flag`)

{_md_table(
    under_by_income,
    ["income_group", "n_under", "n", "share"],
    {"n_under": "{:.0f}", "n": "{:.0f}", "share": "{:.1%}"},
)}

## Severe-neglect exploration pool (`severity_tier`)

| Tier | Meaning | n |
| --- | --- | --- |
| low | Bottom tertile (≤ 33rd pct) — severe under-coverage pool | {(out['severity_tier'] == 'low').sum()} |
| mid | Middle tertile | {(out['severity_tier'] == 'mid').sum()} |
| high | Top tertile (≥ 67th pct) — over-coverage pool | {(out['severity_tier'] == 'high').sum()} |

## Model coefficients (cluster-robust)

```
{result.summary2().as_text()}
```

## log_ratio by income group

{_md_table(
    income_means,
    ["income_group", "mean", "median", "std", "n"],
    {"mean": "{:.4f}", "median": "{:.4f}", "std": "{:.4f}"},
)}

## Income contrast (cluster-robust OLS on log_ratio)

Reference category = first dummy dropped by `get_dummies` (alphabetical; typically High).

| Term | Coef | 95% CI | p | CI covers 0 |
| --- | --- | --- | --- | --- |
{chr(10).join(income_rows)}

**Verdict:** {income_summary["verdict"]}  
R² = {income_summary["r2"]:.4f}

## Most under-covered (lowest log_ratio)

{_md_table(
    under,
    ["event_id", "state", "income_group", "observed", "expected", "log_ratio", "under_flag", "severity_tier"],
    {"observed": "{:.0f}", "expected": "{:.1f}", "log_ratio": "{:.4f}"},
)}

## Most over-covered (highest log_ratio)

{_md_table(
    over,
    ["event_id", "state", "income_group", "observed", "expected", "log_ratio", "under_flag", "severity_tier"],
    {"observed": "{:.0f}", "expected": "{:.1f}", "log_ratio": "{:.4f}"},
)}

## State-level mean log_ratio

{_md_table(
    state_agg.sort_values("mean_log_ratio"),
    ["state", "income_group", "mean_log_ratio", "median_log_ratio", "n_events"],
    {"mean_log_ratio": "{:.4f}", "median_log_ratio": "{:.4f}"},
)}

## Figures

{(chr(10).join(plot_links) if plot_links else "_Run `src/visualize.py` to generate primary figures, then re-run this step or the pipeline to embed links._")}

## Output files

- `data/expected_coverage.csv` (primary)
- `data/state_expected_coverage.csv`
- `data/events_quarantine.csv`
- `{path}`
"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path


def main() -> None:
    print("=" * 60)
    print("EXPECTED COVERAGE — sparse Negative-Binomial")
    print("=" * 60)
    print(f"Media window (design): onset + {MEDIA_WINDOW_DAYS}d "
          "(interim outcome = total_articles from MSS)")
    print("Primary model: NO GDELT volume offset; monsoon_flag EXCLUDED from NegBin")

    df = build_analysis_frame()

    # Option C: keep missing-death rows; fill deaths with 0; flag is metadata only
    n_miss_deaths = int(df["total_deaths"].isna().sum())
    df["deaths_missing"] = df["total_deaths"].isna().astype(int)
    df["total_deaths"] = df["total_deaths"].fillna(0.0)
    include_deaths = True
    print(
        f"Deaths handling (option C): keep all rows; "
        f"log1p_deaths uses fillna(0); "
        f"deaths_missing metadata only ({n_miss_deaths}/{len(df)} events); "
        f"flag NOT in NegBin"
    )

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
            "deaths_missing",
        ]
    ].copy()
    out["severity_proxy"] = severity_col
    out["observed"] = y.values
    out["expected"] = mu
    out["log_ratio"] = log_ratio
    out["pearson_resid"] = pearson
    out["deviance_resid"] = result.resid_deviance
    out["under_flag"] = out["log_ratio"] < 0
    out["over_flag"] = out["log_ratio"] > 0
    out["severity_tier"] = severity_tier_tertile(out["log_ratio"])
    out["rank_undercovered"] = out["log_ratio"].rank(method="average", ascending=True).astype(int)

    # Severe tertile low should sit inside absolute under-coverage
    low_mask = out["severity_tier"] == "low"
    if low_mask.any() and not bool(out.loc[low_mask, "under_flag"].all()):
        raise AssertionError(
            "severity_tier==low is not a subset of under_flag (log_ratio<0); check tier cutpoints"
        )

    out = out.sort_values("log_ratio")
    tier_counts = out["severity_tier"].value_counts()
    n_under = int(out["under_flag"].sum())
    n_over = int(out["over_flag"].sum())
    print(
        f"\nHybrid labels: under_flag={n_under} ({n_under / len(out):.1%}), "
        f"over_flag={n_over} ({n_over / len(out):.1%})"
    )
    print(
        "severity_tier tertiles (low≤P33, high≥P67; exploratory): "
        f"{tier_counts.to_dict()}"
    )
    print(
        "under_flag by income:\n"
        + out.groupby("income_group")["under_flag"]
        .agg(n_under="sum", n="count", share="mean")
        .to_string()
    )

    print("\nMost UNDER-covered (lowest log_ratio):")
    print(
        out.head(15)[
            [
                "event_id",
                "state",
                "income_group",
                "observed",
                "expected",
                "log_ratio",
                "under_flag",
                "severity_tier",
            ]
        ].to_string(index=False)
    )
    print("\nMost OVER-covered (highest log_ratio):")
    print(
        out.tail(15)[
            [
                "event_id",
                "state",
                "income_group",
                "observed",
                "expected",
                "log_ratio",
                "under_flag",
                "severity_tier",
            ]
        ].to_string(index=False)
    )

    income_summary = income_cluster_robust(out)

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

    md_path = write_markdown_report(
        out=out,
        state_agg=state_agg,
        result=result,
        severity_col=severity_col,
        include_deaths=include_deaths,
        income_summary=income_summary,
        path="outputs/pipeline_result.md",
    )
    print(f"SAVED: {md_path}")
    print("\nEXPECTED COVERAGE COMPLETE")


if __name__ == "__main__":
    main()
