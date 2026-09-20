#!/usr/bin/env python3
"""Build the explicit 35-district Track-B/SITS sensitivity package.

This is an opt-in research package.  It never replaces the production Track-A
tables.  It reuses the already downloaded Track-B H5/score checkpoints and the
durable SITS measurement table, routes only the recorded cohort through
``sits_primary``, and overlays those satellite fields on the frozen 30-day
article input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import build_flood_area_table as flood_area  # noqa: E402
import merge_results as merge  # noqa: E402
from cvnd_layout import data_path  # noqa: E402
from flood_spec import COMBINED_COLUMNS, SPEC  # noqa: E402


PACKAGE_DIR = ROOT / "data" / "results" / "track_b_35_sensitivity"
COHORT_PATH = PACKAGE_DIR / "cohort.csv"
BASELINE_PATH = Path(data_path("district_flood_articles"))
SATELLITE_COLUMNS = (
    "flood_area_km2", "flood_ratio", "flood_ratio_eligible", "aoi_area_km2",
    "eligible_km2", "satellite_source", "satellite_status",
    "district_match_status", "aoi_match_status", "geometry_id", "route_reason",
    "cloud_pct", "otsu_fallback_used", "s1_orbit", "sits_status",
    "converter_decision", "spec_version", "legacy_flood_area_km2",
    "legacy_satellite_source", "analysis_observation_status",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def overlay_articles(baseline: pd.DataFrame, measured: pd.DataFrame,
                     keys: list[str]) -> pd.DataFrame:
    result = baseline.copy()
    measured = measured.set_index("event_district_id")
    columns = [c for c in SATELLITE_COLUMNS if c in result and c in measured]
    target = result["event_district_id"].isin(keys)
    if int(target.sum()) != len(keys):
        raise ValueError("not every Track-B cohort key exists in the 30-day baseline")
    for index in result.index[target]:
        key = result.at[index, "event_district_id"]
        for column in columns:
            value = measured.at[key, column]
            result.at[index, column] = "" if pd.isna(value) else str(value)
    return result


def main(package_dir: Path = PACKAGE_DIR, cohort_path: Path = COHORT_PATH,
         gate_usable_min_frac: float = 0.0) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    cohort = pd.read_csv(cohort_path, dtype=str)
    keys = cohort["event_district_id"].astype(str).tolist()
    if len(keys) != 35 or len(set(keys)) != 35:
        raise ValueError(f"expected 35 unique cohort keys, found {len(keys)}/{len(set(keys))}")

    registry = merge.load_registry()
    track_a = merge.load_track_a()
    aoi = merge.load_aoi()
    index = merge.load_sits_index()
    measurements = merge.load_sits_measurements()
    sits_by_key = merge._sits_from_table(measurements, track_a, registry)
    missing = sorted(set(keys) - set(sits_by_key))
    if missing:
        raise ValueError(f"Track-B measurement missing for cohort: {missing}")

    sensitivity_spec = replace(SPEC, sits_usable_min_frac=gate_usable_min_frac)
    rows = []
    for key in keys:
        if key not in track_a or key not in registry:
            raise ValueError(f"Track-A/registry input missing for {key}")
        rows.append(merge.merge_row(
            registry[key], a=track_a[key], sits=sits_by_key[key],
            index_entry=index.get(key), converter=None, spec=sensitivity_spec,
            routing="sits_primary", aoi=aoi.get(key), track_a_status="measured",
        ))

    combined_path = package_dir / "district_flood_combined.csv"
    combined = pd.DataFrame(rows, columns=list(COMBINED_COLUMNS))
    combined.to_csv(combined_path, index=False)
    if (combined["satellite_source"] == "NONE").any():
        failed = combined.loc[combined["satellite_source"] == "NONE",
                              "event_district_id"].tolist()
        raise ValueError(f"non-SITS cohort rows remain: {failed}")

    registry_frame = pd.read_csv(data_path("event_districts"), dtype=merge.TEXT_DTYPES)
    registry_frame = registry_frame[registry_frame["event_district_id"].isin(keys)].copy()
    aoi_frame = pd.read_csv(data_path("district_aoi"), dtype=merge.TEXT_DTYPES)
    area = flood_area.build_flood_area_table(combined, registry_frame, aoi_frame)
    area_path = package_dir / "district_flood_area.csv"
    area.to_csv(area_path, index=False)
    if set(area["satellite_status"]) != {"observed"}:
        raise ValueError("the Track-B package contains a non-observed area row")

    selected_measurements = pd.DataFrame(
        [measurements[key] for key in keys]
    ).sort_values("event_district_id")
    measurement_path = package_dir / "district_sits_measurements.csv"
    selected_measurements.to_csv(measurement_path, index=False)

    baseline = pd.read_csv(BASELINE_PATH, dtype=str, keep_default_na=False,
                           na_filter=False)
    articles = overlay_articles(baseline, area, keys)
    article_path = package_dir / "district_flood_articles_30d.csv"
    articles.to_csv(article_path, index=False)

    base_rows = baseline[baseline["event_district_id"].isin(keys)].set_index(
        "event_district_id")
    sits_rows = articles[articles["event_district_id"].isin(keys)].set_index(
        "event_district_id")
    comparison = pd.DataFrame(index=keys)
    comparison.index.name = "event_district_id"
    for column in ("event_id", "state", "district", "start_date", "article_count",
                   "urban_population_share"):
        comparison[column] = base_rows[column]
    comparison["track_a_source"] = base_rows["satellite_source"]
    comparison["track_a_flood_km2"] = pd.to_numeric(
        base_rows["flood_area_km2"], errors="coerce")
    comparison["track_b_source"] = sits_rows["satellite_source"]
    comparison["track_b_flood_km2"] = pd.to_numeric(
        sits_rows["flood_area_km2"], errors="coerce")
    comparison["delta_track_b_minus_a_km2"] = (
        comparison["track_b_flood_km2"] - comparison["track_a_flood_km2"])
    comparison["track_b_to_a_ratio"] = np.where(
        comparison["track_a_flood_km2"] > 0,
        comparison["track_b_flood_km2"] / comparison["track_a_flood_km2"],
        np.nan,
    )
    combined_index = combined.set_index("event_district_id")
    comparison["sits_method"] = combined_index["sits_method"]
    comparison["sits_usable_frac"] = combined_index["sits_usable_frac"]
    comparison_path = package_dir / "track_a_vs_track_b.csv"
    comparison.reset_index().to_csv(comparison_path, index=False)

    if not (base_rows["article_count"].astype(str)
            == sits_rows["article_count"].astype(str)).all():
        raise ValueError("article counts changed while building a satellite-only package")

    manifest_path = package_dir / "manifest.json"
    manifest = {
        "purpose": "Opt-in Track-B/SITS sensitivity; production remains Track A s1_then_s2",
        "cohort_rule": {
            "source": "data/results/sits_feasibility.csv",
            "aoi_status": "matched",
            "sr_status": "ok",
            "sr_usable_frac_min": 0.4,
            "current_registry_rows": 35,
        },
        "routing": "sits_primary",
        "sits_usable_min_frac_override": gate_usable_min_frac,
        "satellite_post_window_days": 14,
        "news_window_days": 30,
        "rows": {
            "cohort": len(keys),
            "track_b_observed": int((area["satellite_status"] == "observed").sum()),
            "joined_input": len(articles),
            "analysis_eligible": int(articles["analysis_eligible"].eq("True").sum()),
        },
        "satellite_sources": combined["satellite_source"].value_counts().to_dict(),
        "sits_methods": combined["sits_method"].value_counts().to_dict(),
        "comparison": {
            "track_a_sum_km2": float(comparison["track_a_flood_km2"].sum()),
            "track_b_sum_km2": float(comparison["track_b_flood_km2"].sum()),
            "track_a_median_km2": float(comparison["track_a_flood_km2"].median()),
            "track_b_median_km2": float(comparison["track_b_flood_km2"].median()),
            "track_b_to_a_ratio_median": float(comparison["track_b_to_a_ratio"].median()),
            "track_b_lower_rows": int((comparison["delta_track_b_minus_a_km2"] < 0).sum()),
            "track_b_higher_rows": int((comparison["delta_track_b_minus_a_km2"] > 0).sum()),
        },
        "files_sha256": {},
    }
    for path in (cohort_path, measurement_path, combined_path, area_path,
                 article_path, comparison_path):
        manifest["files_sha256"][str(path.relative_to(ROOT))] = sha256(path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(f"Built Track-B sensitivity package: {package_dir}")
    print(json.dumps(manifest["rows"], sort_keys=True))
    print(json.dumps(manifest["satellite_sources"], sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=PACKAGE_DIR)
    parser.add_argument("--cohort", type=Path, default=COHORT_PATH)
    parser.add_argument("--gate-usable-min-frac", type=float, default=0.0)
    arguments = parser.parse_args()
    main(arguments.package_dir, arguments.cohort, arguments.gate_usable_min_frac)
