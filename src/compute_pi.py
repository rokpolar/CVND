from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PSS_PATH = DATA_DIR / "pss_results.csv"
POPULATION_PATH = DATA_DIR / "population.csv"
OUTPUT_EVENT_PI = DATA_DIR / "pi_results.csv"
OUTPUT_STATE_PI = DATA_DIR / "state_pi.csv"


def clean_numeric(value: object) -> float:
    """Convert population strings like '241,265,000' to numeric values."""
    if pd.isna(value):
        return np.nan
    return float(str(value).replace(",", "").strip())


def normalize_state_name(name: object) -> str:
    """Create a stable, case-insensitive state key for joins.

    This removes punctuation, extra spacing, and normalizes the common
    Indian state naming variations so the join is resilient.
    """
    text = str(name).strip()
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(text.split())


def load_csv_strict(path: Path, required_columns: set[str]) -> pd.DataFrame:
    """Load a CSV with guardrails: file existence, non-empty content, and required columns."""
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if path.stat().st_size == 0:
        raise ValueError(
            f"The file '{path.name}' is empty. "
            "Restore the CSV content first, then rerun the script."
        )

    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        raise ValueError(f"The file '{path.name}' does not contain any rows.")

    missing = required_columns.difference(df.columns)
    if missing:
        raise ValueError(
            f"Missing required columns in '{path.name}': {sorted(missing)}. "
            f"Found columns: {list(df.columns)}"
        )

    return df


def build_state_population_lookup(population_df: pd.DataFrame) -> pd.Series:
    """Return a mapping from normalized state name to 2026 population."""
    population_df = population_df.copy()
    population_df["state_key"] = population_df["State/UT"].apply(normalize_state_name)
    population_df["population_2026"] = population_df["Population (2026)"].apply(clean_numeric)

    state_population = population_df.loc[:, ["state_key", "population_2026"]].dropna()
    return state_population.set_index("state_key")["population_2026"]


def main() -> None:
    pss_df = load_csv_strict(PSS_PATH, {"event_id", "state", "population_exposed"})
    population_df = load_csv_strict(POPULATION_PATH, {"State/UT", "Population (2026)"})

    # Normalized state key allows a resilient join even when spellings differ.
    pss_df["state_key"] = pss_df["state"].apply(normalize_state_name)
    state_population = build_state_population_lookup(population_df)

    # Attach 2026 population for every event row.
    pss_df["population_2026"] = pss_df["state_key"].map(state_population)

    # PI is defined as population_exposed / total population of the state.
    pss_df["PI"] = np.where(
        pss_df["population_2026"].gt(0),
        pss_df["population_exposed"] / pss_df["population_2026"],
        np.nan,
    )

    # A state present in the population file but missing in PSS should not break the run.
    # We surface that state-level fact as a zero-exposure row in the aggregated output.
    population_states = population_df[["State/UT"]].copy()
    population_states["state_key"] = population_states["State/UT"].apply(normalize_state_name)
    population_states = population_states.drop_duplicates(subset=["state_key"])

    state_summary = (
        pss_df.groupby("state_key", dropna=False)
        .agg(
            state=("state", "first"),
            total_population_exposed=("population_exposed", "sum"),
            event_count=("event_id", "count"),
        )
        .reset_index()
    )

    state_summary["population_2026"] = state_summary["state_key"].map(state_population)
    state_summary["PI_state"] = np.where(
        state_summary["population_2026"].gt(0),
        state_summary["total_population_exposed"] / state_summary["population_2026"],
        np.nan,
    )

    # Ensure every population state appears in the state-level results.
    state_summary = (
        population_states.merge(
            state_summary,
            on="state_key",
            how="left",
        )
        .rename(columns={"State/UT": "state"})
    )

    state_summary["total_population_exposed"] = state_summary["total_population_exposed"].fillna(0.0)
    state_summary["event_count"] = state_summary["event_count"].fillna(0).astype(int)
    state_summary["population_2026"] = state_summary["population_2026"].fillna(np.nan)
    state_summary["PI_state"] = state_summary["PI_state"].fillna(0.0)

    output_event = pss_df[[
        "event_id",
        "state",
        "population_exposed",
        "population_2026",
        "PI",
        "income_group",
    ]].copy()

    output_event = output_event.sort_values(["PI", "population_exposed"], ascending=[False, False])

    output_state = state_summary[[
        "state",
        "population_2026",
        "total_population_exposed",
        "event_count",
        "PI_state",
    ]].copy()

    output_state = output_state.sort_values("PI_state", ascending=False)

    output_event.to_csv(OUTPUT_EVENT_PI, index=False)
    output_state.to_csv(OUTPUT_STATE_PI, index=False)

    # Helpful diagnostics.
    missing_state_map = pss_df.loc[pss_df["population_2026"].isna(), ["state", "state_key"]].drop_duplicates()
    if not missing_state_map.empty:
        print("States in PSS missing from the population file:")
        print(missing_state_map.to_string(index=False))

    print(f"Saved event-level PI table to: {OUTPUT_EVENT_PI}")
    print(f"Saved state-level PI summary to: {OUTPUT_STATE_PI}")


if __name__ == "__main__":
    main()
