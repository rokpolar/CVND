"""
join_flood_articles.py — LEGACY state-event join.
Primary: use join_district_flood_articles.py for the strict district contract.

Inputs:
    data/intermediate/severity_raw.csv
    data/results/event_article_counts.heuristic.csv

Outputs:
    data/results/event_flood_articles.csv   (one row per official state-event)
    data/results/state_flood_articles.csv   (aggregated by state)
"""

from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cvnd_layout import data_path  # noqa: E402


EVENT_COLUMNS = [
    "event_id",
    "state",
    "district",
    "start_date",
    "adjusted_flood_area_km2",
    "flood_ratio",
    "aoi_km2",
    "combined_source",
    "article_count",
    "count_source",
]


def load_article_counts(path: os.PathLike | str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Missing heuristic article counts: {path}\n"
            "Run classify_event_articles.py prepare and export "
            "--count-source heuristic first."
        )
    counts = pd.read_csv(path)
    if "final_article_count" not in counts.columns:
        raise ValueError(f"{path} lacks final_article_count column")
    counts = counts[["event_id", "final_article_count"]].copy()
    counts["article_count"] = counts["final_article_count"].fillna(0).astype(int)
    counts["count_source"] = "heuristic"
    return counts[["event_id", "article_count", "count_source"]]


def build_event_table(
    severity: pd.DataFrame, articles: pd.DataFrame,
) -> pd.DataFrame:
    merged = severity.merge(articles, on="event_id", how="left")
    merged["article_count"] = merged["article_count"].fillna(0).astype(int)
    merged["count_source"] = merged["count_source"].fillna("heuristic")

    available = [column for column in EVENT_COLUMNS if column in merged.columns]
    return merged[available].sort_values("event_id").reset_index(drop=True)


def build_state_table(events: pd.DataFrame) -> pd.DataFrame:
    grouped = events.groupby("state", as_index=False).agg(
        event_count=("event_id", "count"),
        article_count=("article_count", "sum"),
        total_flood_area_km2=("adjusted_flood_area_km2", "sum"),
        mean_flood_area_km2=("adjusted_flood_area_km2", "mean"),
        events_with_flood_area=(
            "adjusted_flood_area_km2",
            lambda s: int(s.notna().sum()),
        ),
    )
    grouped["mean_flood_area_km2"] = grouped["mean_flood_area_km2"].round(2)
    grouped["total_flood_area_km2"] = grouped["total_flood_area_km2"].round(2)
    return grouped.sort_values("state").reset_index(drop=True)


def main() -> None:
    print("=" * 60)
    print("JOIN FLOOD AREA + HEURISTIC ARTICLE COUNTS")
    print("=" * 60)

    severity_path = data_path("severity_raw")
    articles_path = data_path("event_article_counts_heuristic")
    event_out = data_path("event_flood_articles")
    state_out = data_path("state_flood_articles")

    if not severity_path.exists():
        raise FileNotFoundError(
            f"Missing {severity_path}; run compute_population.py first."
        )

    severity = pd.read_csv(severity_path)
    articles = load_article_counts(articles_path)
    events = build_event_table(severity, articles)
    states = build_state_table(events)

    event_out.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(event_out, index=False)
    states.to_csv(state_out, index=False)

    n_with_area = events["adjusted_flood_area_km2"].notna().sum()
    n_with_articles = int((events["article_count"] > 0).sum())
    print(f"\nSAVED: {event_out} — {len(events)} events")
    print(f"  with flood area    : {n_with_area}")
    print(f"  with article_count : {n_with_articles}")
    print(f"SAVED: {state_out} — {len(states)} states")
    print("\nPreview (events):")
    print(
        events.head(10)[
            ["event_id", "state", "adjusted_flood_area_km2", "article_count"]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
