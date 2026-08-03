"""
compute_population.py — PRIMARY population/severity builder for the pipeline.
Build data/intermediate/severity_raw.csv from district-level flood_combined results.

Primary input:
    data/intermediate/flood_combined.csv
    data/raw/events.csv
    data/raw/population.csv
    data/raw/state_area.csv

Output:
    data/intermediate/severity_raw.csv
"""

from __future__ import annotations

import difflib
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cvnd_layout import data_path  # noqa: E402

STATE_ALIASES = {
    "jammu and kashmir": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "jammu & kashmir": "Jammu and Kashmir",
    "uttaranchal": "Uttarakhand",
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "national capital territory of delhi": "Delhi",
    "nct of delhi": "Delhi",
}


def resolve(name, known):
    key = str(name).strip().lower()
    if key in STATE_ALIASES:
        return STATE_ALIASES[key]
    for s in known:
        if s.lower() == key:
            return s
    m = difflib.get_close_matches(str(name), known, n=1, cutoff=0.75)
    return m[0] if m else None


def parse_pop(v):
    return int(str(v).replace(",", "").strip())


def load_state_area() -> dict[str, int]:
    area_raw = pd.read_csv(data_path("state_area"))
    lookup = {}
    for _, row in area_raw.iterrows():
        lookup[str(row["state"])] = int(row["area_km2"])
    return lookup


def load_pop_lookup(known_states) -> dict[str, int]:
    pop_raw = pd.read_csv(data_path("population"))
    pop_lookup = {}
    for _, row in pop_raw.iterrows():
        canonical = resolve(str(row["State/UT"]), known_states)
        if canonical:
            pop_lookup[canonical] = parse_pop(row["Population (2025)"])
        else:
            print(f"WARNING: could not match '{row['State/UT']}' — skipped")
    return pop_lookup


def from_flood_combined(
    pop_lookup: dict[str, int], state_area: dict[str, int]
) -> pd.DataFrame:
    """Primary path: district-level combined flood areas."""
    combined = pd.read_csv(data_path("flood_combined"))
    events = pd.read_csv(data_path("events"))[
        ["event_id", "state", "district", "start_date"]
    ]
    df = combined.merge(events, on="event_id", how="left")
    known = state_area.keys()

    rows = []
    for _, r in df.iterrows():
        canonical = resolve(r.get("state"), known)
        state_pop = pop_lookup.get(canonical)
        area_km2 = state_area.get(canonical)
        warnings = []

        combined_km2 = r.get("combined_km2")
        district_km2 = r.get("district_km2")
        flood_ratio = r.get("flood_ratio")
        source = r.get("combined_source", "")

        if canonical is None:
            warnings.append(f"STATE MATCH FAILED: '{r.get('state')}'")

        if pd.isna(combined_km2):
            warnings.append(f"NO COMBINED FLOOD: source={source}")
            rows.append({
                "event_id": r["event_id"],
                "state": r.get("state"),
                "district": r.get("district", ""),
                "canonical_state": canonical,
                "start_date": r.get("start_date", ""),
                "bbox_area_km2": None,
                "state_area_km2": area_km2,
                "district_km2": None if pd.isna(district_km2) else round(float(district_km2), 1),
                "raw_flood_area_km2": None,
                "adjusted_flood_area_km2": None,
                "flood_ratio": None,
                "combined_source": source,
                "region_total_population": state_pop,
                "population_exposed": None,
                "exposure_rate": None,
                "warnings": "; ".join(warnings),
            })
            continue

        flood_km2 = float(combined_km2)
        if pd.isna(flood_ratio) and not pd.isna(district_km2) and float(district_km2) > 0:
            flood_ratio = flood_km2 / float(district_km2)
        if not pd.isna(flood_ratio):
            flood_ratio = float(min(max(flood_ratio, 0.0), 1.0))

        if area_km2 and state_pop:
            exposed = round((flood_km2 / area_km2) * state_pop)
            exposure_rate = (
                round(flood_ratio, 6)
                if flood_ratio is not None and not pd.isna(flood_ratio)
                else round(min(flood_km2 / area_km2, 1.0), 6)
            )
        else:
            exposed = None
            exposure_rate = None
            if not state_pop:
                warnings.append(f"NO POPULATION DATA for '{canonical}'")
            if not area_km2:
                warnings.append(f"NO AREA DATA for '{canonical}'")

        if flood_km2 == 0:
            warnings.append("ZERO FLOOD AREA after combine")

        rows.append({
            "event_id": r["event_id"],
            "state": r.get("state"),
            "district": r.get("district", ""),
            "canonical_state": canonical,
            "start_date": r.get("start_date", ""),
            "bbox_area_km2": None,
            "state_area_km2": area_km2,
            "district_km2": None if pd.isna(district_km2) else round(float(district_km2), 1),
            "raw_flood_area_km2": round(flood_km2, 2),
            "adjusted_flood_area_km2": round(flood_km2, 2),
            "flood_ratio": flood_ratio,
            "combined_source": source,
            "region_total_population": state_pop,
            "population_exposed": exposed,
            "exposure_rate": exposure_rate,
            "warnings": "; ".join(warnings),
        })

    return pd.DataFrame(rows)


def bbox_area_km2(minlon, minlat, maxlon, maxlat):
    mid_lat = math.radians((minlat + maxlat) / 2)
    lat_km = (maxlat - minlat) * 111.0
    lon_km = (maxlon - minlon) * 111.0 * math.cos(mid_lat)
    return lat_km * lon_km


def from_legacy_flood_area(
    pop_lookup: dict[str, int], state_area: dict[str, int]
) -> pd.DataFrame:
    """Legacy bbox-scaled path (only if flood_combined.csv missing)."""
    flood = pd.read_csv(data_path("flood_area_results"))
    known = state_area.keys()
    rows = []
    for _, r in flood.iterrows():
        canonical = resolve(r["state"], known)
        state_pop = pop_lookup.get(canonical)
        area_km2 = state_area.get(canonical)
        raw_flood = r.get("flood_area_km2")
        warnings = []

        if canonical is None:
            warnings.append(f"STATE MATCH FAILED: '{r['state']}'")

        no_data = pd.isna(raw_flood) or (raw_flood is not None and float(raw_flood) < 0)
        if no_data:
            warnings.append("NO S1 DATA: no Sentinel-1 imagery for this event window")
            rows.append({
                "event_id": r["event_id"], "state": r["state"],
                "district": r.get("district", ""), "canonical_state": canonical,
                "start_date": r.get("start_date", ""),
                "bbox_area_km2": None, "state_area_km2": area_km2,
                "district_km2": None,
                "raw_flood_area_km2": None, "adjusted_flood_area_km2": None,
                "flood_ratio": None, "combined_source": "legacy",
                "region_total_population": state_pop,
                "population_exposed": None, "exposure_rate": None,
                "warnings": "; ".join(warnings),
            })
            continue

        raw_flood = float(raw_flood)
        try:
            bb_area = bbox_area_km2(
                float(r["bbox_minlon"]), float(r["bbox_minlat"]),
                float(r["bbox_maxlon"]), float(r["bbox_maxlat"]),
            )
        except Exception:
            bb_area = None
            warnings.append("BBOX COLUMNS MISSING OR INVALID")

        if bb_area and area_km2 and bb_area > area_km2 * 1.05:
            scale_factor = area_km2 / bb_area
            adjusted_flood = raw_flood * scale_factor
            warnings.append(
                f"BBOX OVERFLOW: bbox={bb_area:.0f} km2 > state={area_km2} km2 "
                f"(scale factor={scale_factor:.3f})."
            )
        else:
            adjusted_flood = raw_flood

        if area_km2 and state_pop:
            fraction = min(adjusted_flood / area_km2, 1.0)
            exposed = round(fraction * state_pop)
            exposure_rate = round(fraction, 6)
        else:
            exposed = None
            exposure_rate = None

        rows.append({
            "event_id": r["event_id"], "state": r["state"],
            "district": r.get("district", ""), "canonical_state": canonical,
            "start_date": r.get("start_date", ""),
            "bbox_area_km2": round(bb_area, 1) if bb_area else None,
            "state_area_km2": area_km2,
            "district_km2": None,
            "raw_flood_area_km2": round(raw_flood, 2),
            "adjusted_flood_area_km2": round(adjusted_flood, 2),
            "flood_ratio": None, "combined_source": "legacy",
            "region_total_population": state_pop,
            "population_exposed": exposed, "exposure_rate": exposure_rate,
            "warnings": "; ".join(warnings),
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 60)
    print("COMPUTE POPULATION / SEVERITY RAW")
    print("=" * 60)

    state_area = load_state_area()
    pop_lookup = load_pop_lookup(state_area.keys())
    combined_path = data_path("flood_combined")
    legacy_path = data_path("flood_area_results")

    if combined_path.exists():
        print(f"Using PRIMARY input: {combined_path} (district-level)")
        out = from_flood_combined(pop_lookup, state_area)
    elif legacy_path.exists():
        print(f"WARNING: {combined_path.name} missing — legacy {legacy_path}")
        out = from_legacy_flood_area(pop_lookup, state_area)
    else:
        raise FileNotFoundError(
            f"Need {combined_path} or {legacy_path}"
        )

    out_path = data_path("severity_raw")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    n_ok = out["adjusted_flood_area_km2"].notna().sum()
    n_null = out["adjusted_flood_area_km2"].isna().sum()
    print(f"\nSAVED: {out_path} — {len(out)} events")
    print(f"  with flood area : {n_ok}")
    print(f"  missing flood   : {n_null}")
    if "combined_source" in out.columns:
        print("  sources:")
        print(out["combined_source"].fillna("NA").value_counts().to_string())

    preview = out.loc[
        out["adjusted_flood_area_km2"].notna(),
        [
            "event_id", "state", "adjusted_flood_area_km2", "flood_ratio",
            "population_exposed", "exposure_rate", "combined_source",
        ],
    ].head(15)
    print("\nPreview:")
    print(preview.to_string(index=False))


if __name__ == "__main__":
    main()
