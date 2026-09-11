"""Build the primary event-district flood-area table.

The merge output contains the S1/NDWI/SITS routing result. This module only
reshapes that result into one row per registry event-district and keeps
unobserved flood area as NA. It never turns a failed observation into zero and
never broadcasts an event-only state result to district rows. ``flood_ratio`` is
computed here, once, from the authoritative AOI area.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cvnd_layout import data_path  # noqa: E402
from district_keys import AOI_MATCHED, analysis_key  # noqa: E402
from flood_spec import (FLOOD_AREA_COLUMNS, LEGACY_SATELLITE_SOURCES,  # noqa: E402
                        MEASURED_SOURCES, TEXT_DTYPES, require_spec)

PASSTHROUGH = ["route_reason", "cloud_pct", "otsu_fallback_used", "s1_orbit",
               "sits_status", "converter_decision", "spec_version"]


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
    for column in ("combined_km2", "satellite_source"):
        if column not in combined.columns:
            raise ValueError(f"district satellite merge missing {column}; rerun merge_results.py")
    require_spec(combined, "district satellite merge")
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

    aoi_supplied = aoi is not None
    if aoi is not None and not aoi.empty:
        require_spec(aoi, "district AOI table")
        aoi = aoi.copy()
        aoi["_analysis_key"] = aoi.apply(analysis_key, axis=1)
        if aoi["_analysis_key"].duplicated().any():
            duplicate_keys = aoi.loc[aoi["_analysis_key"].duplicated(keep=False), "_analysis_key"].tolist()
            raise ValueError(f"AOI table contains duplicate analysis keys: {duplicate_keys}")
        aoi_cols = [c for c in ["aoi_area_km2", "aoi_match_status", "geometry_id"]
                    if c in aoi.columns]
        # Always suffix AOI-artifact columns so they never shadow merge columns.
        aoi = aoi[["_analysis_key"] + aoi_cols].rename(columns={c: c + "_aoi" for c in aoi_cols})
    else:
        aoi = pd.DataFrame(columns=["_analysis_key"])

    # Registry AOI status is a pre-resolution placeholder. Let the satellite
    # merge/AOI artifact provide the authoritative status instead.
    registry = registry.drop(columns=["aoi_match_status"], errors="ignore")
    merged = registry.merge(combined, on="_analysis_key", how="left",
                            suffixes=("", "_sat"), validate="one_to_one")
    merged = merged.merge(aoi, on="_analysis_key", how="left", validate="one_to_one")
    merged["_aoi_present"] = merged["_analysis_key"].isin(set(aoi["_analysis_key"]))

    def column(name):
        if name in merged:
            return merged[name]
        return pd.Series([pd.NA] * len(merged), index=merged.index, dtype=object)

    # Validate identity fields before allowing any area value into the output.
    for field in ("event_id", "state", "district", "start_date", "source_record_id"):
        sat_name = f"{field}_sat"
        if field in merged and sat_name in merged:
            left = merged[field].astype("string").str.strip()
            right = merged[sat_name].astype("string").str.strip()
            mismatch = left.notna() & right.notna() & (left != right)
            if mismatch.any():
                keys = merged.loc[mismatch, "_analysis_key"].tolist()
                raise ValueError(f"stale satellite identity for {field}: {keys}")

    area = pd.to_numeric(merged["combined_km2"], errors="coerce")
    # Row-wise: the AOI artifact is authoritative; the merge's copy fills gaps.
    aoi_area = pd.to_numeric(column("aoi_area_km2_aoi"), errors="coerce").combine_first(
        pd.to_numeric(column("aoi_area_km2"), errors="coerce"))
    if aoi_supplied:
        # If an AOI artifact was supplied, absent keys are unknown even when a
        # stale satellite merge contains a numeric area for that parent event.
        aoi_status = column("aoi_match_status_aoi").where(merged["_aoi_present"], "unknown")
    else:
        aoi_status = column("aoi_match_status")
    aoi_status = aoi_status.fillna("unknown")
    source = column("satellite_source").fillna("NONE")

    matched = aoi_status.astype(str).str.strip().str.lower().isin(AOI_MATCHED)
    observed = matched & area.notna() & source.isin(MEASURED_SOURCES)
    status = pd.Series("missing", index=merged.index, dtype=object)
    status[~matched] = "failed_aoi"
    status[observed] = "observed"
    area = area.where(observed)
    ratio = (area / aoi_area.where(aoi_area > 0)).round(4)
    eligible_area = pd.to_numeric(column("eligible_km2"), errors="coerce")
    ratio_eligible = (area / eligible_area.where(eligible_area > 0)).round(4)
    # The pre-refactor routing's area, under the same AOI rule, for the
    # before/after comparison only.
    legacy_source = column("legacy_satellite_source").fillna("NONE")
    legacy_area = pd.to_numeric(column("legacy_combined_km2"), errors="coerce").where(
        matched & legacy_source.isin(LEGACY_SATELLITE_SOURCES[:-1]))

    result = pd.DataFrame({
        "event_district_id": merged.get("event_district_id"),
        "event_id": merged.get("event_id"),
        "source_record_id": column("source_record_id"),
        "start_date": column("start_date"),
        "state": merged.get("state"),
        "district": merged.get("district"),
        "flood_area_km2": area,
        "flood_ratio": ratio,
        "aoi_area_km2": aoi_area,
        "satellite_source": source,
        "satellite_status": status,
        "district_match_status": aoi_status,
        "geometry_id": column("geometry_id_aoi").combine_first(column("geometry_id")),
        # Keep the exact AOI provenance name used by the registry and downstream
        # join. ``district_match_status`` remains as a readable compatibility alias.
        "aoi_match_status": aoi_status,
        "analysis_observation_status": area.map(
            lambda x: "observed_zero" if pd.notna(x) and float(x) == 0 else
            ("observed" if pd.notna(x) else "missing")),
        "eligible_km2": eligible_area,
        "flood_ratio_eligible": ratio_eligible,
        "legacy_flood_area_km2": legacy_area,
        "legacy_satellite_source": legacy_source.where(legacy_area.notna(), "NONE"),
        **{name: column(name) for name in PASSTHROUGH},
    })
    return result[list(FLOOD_AREA_COLUMNS)]


def main(input_path: str | None = None, registry_path: str | None = None,
         output_path: str | None = None) -> pd.DataFrame:
    combined_path = Path(input_path) if input_path else data_path('district_flood_combined')
    if not combined_path.exists():
        raise FileNotFoundError(f'Missing district flood merge: {combined_path}. Run district satellite analysis and merge_results.py; legacy state caches are incompatible.')
    combined = pd.read_csv(combined_path, dtype=TEXT_DTYPES)
    registry = pd.read_csv(registry_path or data_path("event_districts"), dtype=TEXT_DTYPES)
    try:
        aoi = pd.read_csv(data_path("district_aoi"), dtype=TEXT_DTYPES)
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
