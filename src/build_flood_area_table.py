"""Build the primary event-district flood-area table.

The merge output contains the existing S1/S2/SITS routing result. This module
only reshapes that result into one row per registry event-district and keeps
unobserved flood area as NA. It never turns a failed observation into zero and
never broadcasts an event-only state result to district rows.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cvnd_layout import data_path  # noqa: E402


def analysis_key(row) -> str:
    value = row.get("event_district_id")
    if value is not None and str(value).strip() not in {"", "nan", "None"}:
        return str(value)
    return str(row.get("event_id"))


REQUIRED_COLUMNS = [
    "event_district_id", "event_id", "source_record_id", "state", "district",
    "start_date", "flood_area_km2", "flood_ratio", "aoi_area_km2",
    "satellite_source", "satellite_status",
]


def build_flood_area_table(combined: pd.DataFrame, registry: pd.DataFrame,
                           aoi: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return a cardinality-preserving event-district area table.

    ``registry`` is the authoritative row set. District registries must have
    ``event_district_id``; joining on parent ``event_id`` alone is rejected to
    prevent state values from being copied across districts.
    """
    registry = registry.copy()
    combined = combined.copy()
    if "event_district_id" not in registry.columns:
        raise ValueError("event registry missing required event_district_id")
    is_district_registry = registry["event_district_id"].notna().any() and (
        registry["event_district_id"].astype(str).str.strip() != ""
    ).any()
    if is_district_registry:
        required_measurement = {
            "event_district_id", "event_id", "source_record_id", "state",
            "district", "start_date",
        }
        missing_measurement = required_measurement - set(combined.columns)
        if missing_measurement:
            raise ValueError(
                "district satellite merge missing required provenance columns: "
                f"{sorted(missing_measurement)}"
            )
    registry["_analysis_key"] = registry.apply(analysis_key, axis=1)
    combined["_analysis_key"] = combined.apply(analysis_key, axis=1)
    if registry["_analysis_key"].duplicated().any():
        raise ValueError("event registry contains duplicate analysis keys")
    if combined["_analysis_key"].duplicated().any():
        raise ValueError("satellite merge contains duplicate analysis keys")

    if is_district_registry:
        unknown = set(combined["_analysis_key"]) - set(registry["_analysis_key"])
        if unknown:
            raise ValueError(
                "district satellite merge contains keys outside current registry: "
                f"{sorted(unknown)[:5]}"
            )

    if aoi is not None and not aoi.empty:
        aoi = aoi.copy()
        aoi["_analysis_key"] = aoi.apply(analysis_key, axis=1)
        if aoi["_analysis_key"].duplicated().any():
            duplicate_keys = aoi.loc[aoi["_analysis_key"].duplicated(keep=False), "_analysis_key"].tolist()
            raise ValueError(f"AOI table contains duplicate analysis keys: {duplicate_keys}")
        aoi_cols = [c for c in ["_analysis_key", "aoi_area_km2", "aoi_km2",
                                "aoi_match_status", "geometry_id"] if c in aoi.columns]
        aoi = aoi[aoi_cols]
    else:
        aoi = pd.DataFrame(columns=["_analysis_key"])

    # Registry AOI status is a pre-resolution placeholder. Let the satellite
    # merge/AOI artifact provide the authoritative status instead.
    registry = registry.drop(columns=["aoi_match_status"], errors="ignore")
    merged = registry.merge(combined, on="_analysis_key", how="left",
                            suffixes=("", "_sat"), validate="one_to_one")
    merged = merged.merge(aoi, on="_analysis_key", how="left",
                          suffixes=("", "_aoi"), validate="one_to_one")
    aoi_keys = set(aoi["_analysis_key"]) if aoi is not None and not aoi.empty else set()
    merged["_aoi_present"] = merged["_analysis_key"].isin(aoi_keys)

    def first(*names):
        for name in names:
            if name in merged:
                return merged[name]
        return pd.Series([None] * len(merged), index=merged.index)

    def coalesce(*names):
        result = pd.Series([None] * len(merged), index=merged.index, dtype=object)
        for name in names:
            if name in merged:
                result = result.where(result.notna(), merged[name])
        return result

    area = first("combined_km2", "affected_area_km2")
    if aoi is not None and "aoi_area_km2_aoi" in merged:
        aoi_area = merged["aoi_area_km2_aoi"]
    elif aoi is not None and "aoi_km2_aoi" in merged:
        aoi_area = merged["aoi_km2_aoi"]
    elif "aoi_area_km2" in merged:
        aoi_area = merged["aoi_area_km2"]
    elif "aoi_km2" in merged:
        aoi_area = merged["aoi_km2"]
    elif "aoi_km2_sat" in merged:
        aoi_area = merged["aoi_km2_sat"]
    else:
        aoi_area = pd.Series([None] * len(merged), index=merged.index)
    ratio = first("flood_ratio")
    derived_ratio = area / aoi_area.where(aoi_area > 0)
    # Recompute against the authoritative AOI artifact whenever both values
    # exist; a stale merge ratio must not survive a changed geometry area.
    ratio = derived_ratio.where(derived_ratio.notna(), ratio)

    if aoi is not None:
        # If an AOI artifact was supplied, absent keys are unknown even when a
        # stale satellite merge contains a numeric area for that parent event.
        aoi_status = merged.get("aoi_match_status_aoi", merged.get(
            "aoi_match_status", pd.Series([None] * len(merged), index=merged.index)))
        aoi_status = aoi_status.where(merged["_aoi_present"], "unknown").fillna("unknown")
    else:
        aoi_status = coalesce("aoi_match_status", "aoi_match_status_sat").fillna("unknown")
    source = first("combined_source", "satellite_source")
    status = first("baseline_status", "satellite_status")
    status = status.where(status.notna(), source)

    result = pd.DataFrame({
        "event_district_id": merged.get("event_district_id"),
        "event_id": merged.get("event_id"),
        "source_record_id": first("source_record_id"),
        "state": merged.get("state"),
        "district": merged.get("district"),
        "start_date": first("start_date"),
        "flood_area_km2": area,
        "flood_ratio": ratio,
        "aoi_area_km2": aoi_area,
        "satellite_source": source,
        "satellite_status": status,
        "district_match_status": aoi_status,
        "geometry_id": first("geometry_id", "geometry_id_aoi"),
    })
    # Validate identity fields before allowing any area value into the output.
    for field in ("event_id", "state", "district", "start_date", "source_record_id"):
        reg_name = field
        sat_name = f"{field}_sat"
        if reg_name in merged and sat_name in merged:
            left = merged[reg_name].astype("string").str.strip()
            right = merged[sat_name].astype("string").str.strip()
            mismatch = left.notna() & right.notna() & (left != right)
            if mismatch.any():
                keys = merged.loc[mismatch, "_analysis_key"].tolist()
                raise ValueError(f"stale satellite identity for {field}: {keys}")
    result["satellite_status"] = result["satellite_status"].fillna("missing")
    failed_aoi = ~result["district_match_status"].astype(str).str.lower().isin({"matched", "ok"})
    result.loc[failed_aoi, ["flood_area_km2", "flood_ratio", "aoi_area_km2"]] = pd.NA
    result["satellite_status"] = result["satellite_status"].where(
        ~failed_aoi, "failed_aoi"
    )
    result.loc[~failed_aoi & result["flood_area_km2"].notna(), "satellite_status"] = "observed"
    result.loc[~failed_aoi & result["flood_area_km2"].isna(), "satellite_status"] = "missing"
    # Keep the exact AOI provenance name used by the registry and downstream
    # join. ``district_match_status`` remains as a readable compatibility alias.
    result["aoi_match_status"] = result["district_match_status"]
    result["analysis_observation_status"] = result["flood_area_km2"].map(
        lambda x: "observed_zero" if pd.notna(x) and float(x) == 0 else
        ("observed" if pd.notna(x) else "missing")
    )
    return result


def _load(path_key: str, fallback_key: str) -> pd.DataFrame:
    return pd.read_csv(data_path(path_key))


def main(input_path: str | None = None, registry_path: str | None = None,
         output_path: str | None = None) -> pd.DataFrame:
    combined_path = Path(input_path) if input_path else data_path('district_flood_combined')
    if not combined_path.exists():
        raise FileNotFoundError(f'Missing district flood merge: {combined_path}. Run district satellite analysis and merge_results.py; legacy state caches are incompatible.')
    combined = pd.read_csv(combined_path)
    registry = pd.read_csv(registry_path) if registry_path else _load(
        "event_districts", "events"
    )
    try:
        aoi = _load("district_aoi_area", "event_aoi_area")
    except FileNotFoundError:
        # Keep registry rows for QC, but make the absence authoritative so a
        # stale merge cannot supply numeric district areas without AOI proof.
        aoi = pd.DataFrame(columns=["event_district_id", "aoi_area_km2", "aoi_match_status"])
    result = build_flood_area_table(combined, registry, aoi)
    output = Path(output_path) if output_path else data_path("district_flood_area")
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    print(f"Saved -> {output} ({len(result)} rows)")
    print(result["analysis_observation_status"].value_counts(dropna=False).to_string())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--registry")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        main(args.input, args.registry, args.output)
    except (OSError, ValueError, KeyError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise SystemExit(1)
