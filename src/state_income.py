"""state_income.py — income group per state, derived from per-capita GSDP.

Why this exists
---------------
`income_group` was a hand-written string in build_emdat_events.py's
STATE_PROFILES table, with no source, and it did not track income at all. Against
`data/archive/state_covariates.csv`, which carries per-capita GSDP for 30 states:

    Sikkim            295,000  (3rd highest)  labelled "Low"
    Himachal Pradesh  187,000  (11th)         labelled "Low"
    Uttarakhand       170,000  (12th)         labelled "Low"
    Arunachal Pradesh 148,000  (14th)         labelled "Low"
    Mizoram           130,000  (16th)         labelled "Low"
    Kerala            213,000  (7th)          labelled "Middle"
    Maharashtra       198,000  (9th)          labelled "High"

Five states in the richer half sat in "Low", and Kerala ranked above a "High"
state while labelled "Middle". The paper regresses log_ratio on income_group to
ask whether poorer states are under-covered, so the explanatory variable has to
be income. Tertiles of per-capita GSDP split the 30 states exactly 10/10/10 with
no tie straddling a cut.

The labels stay High/Middle/Low so nothing downstream has to change.
"""

from __future__ import annotations

import pandas as pd

from cvnd_layout import DATA

COVARIATES = DATA / "archive" / "state_covariates.csv"
GROUPS = ("Low", "Middle", "High")
# States with no per-capita GSDP in the covariates file are labelled, not guessed.
# A silent NaN would get no dummy from get_dummies and so fall into the reference
# category, quietly counting as whatever the baseline group is.
UNKNOWN = "Unknown"


def load_gsdp(path=COVARIATES):
    """{state: per-capita GSDP}. Empty if the covariates file is missing."""
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if not {"state", "gsdp_per_capita"} <= set(df.columns):
        return {}
    df = df.dropna(subset=["state", "gsdp_per_capita"])
    return dict(zip(df["state"].astype(str), df["gsdp_per_capita"].astype(float)))


def income_groups(gsdp=None):
    """{state: 'Low'|'Middle'|'High'} by tertiles of per-capita GSDP.

    Cuts are on the VALUE, not on rank, so states sharing a GSDP always land in
    the same group -- Assam, Rajasthan and Tripura all sit at 95,000 and a
    rank-based split would have separated them arbitrarily.
    """
    gsdp = load_gsdp() if gsdp is None else gsdp
    if not gsdp:
        return {}
    s = pd.Series(gsdp, dtype=float)
    lo, hi = s.quantile(1 / 3), s.quantile(2 / 3)
    return {state: ("High" if v >= hi else "Low" if v <= lo else "Middle")
            for state, v in s.items()}


def apply_income_group(df, state_col="state", col="income_group", verbose=True):
    """Replace `col` with the GSDP-derived group, reporting what changed.

    Returns the same frame (copied). Reports rather than silently rewriting,
    because this moves events between the groups the headline contrast compares.
    """
    groups = income_groups()
    if not groups:
        if verbose:
            print(f"WARN: {COVARIATES} unusable -> income_group left as recorded "
                  "(hand-written labels that do not track per-capita GSDP)")
        return df
    out = df.copy()
    before = out[col] if col in out.columns else None
    out[col] = out[state_col].map(groups).fillna(UNKNOWN)
    if verbose:
        missing = sorted(set(out.loc[out[col] == UNKNOWN, state_col]))
        if missing:
            n = int((out[col] == UNKNOWN).sum())
            print(f"  income_group: {n} event(s) in {missing} have no per-capita "
                  f"GSDP -> '{UNKNOWN}' (kept as its own category, not folded "
                  "into the reference group)")
        if before is not None:
            moved = out[col] != before
            if moved.any():
                pairs = (pd.DataFrame({"from": before[moved], "to": out.loc[moved, col],
                                       "state": out.loc[moved, state_col]})
                         .drop_duplicates().sort_values("state"))
                print(f"  income_group: reassigned {int(moved.sum())} event(s) "
                      f"across {pairs['state'].nunique()} state(s) from the "
                      "hand-written labels to GSDP tertiles:")
                for _, r in pairs.iterrows():
                    print(f"      {r['state']}: {r['from']} -> {r['to']}")
    return out
