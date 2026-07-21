"""
compute_population.py — PRIMARY population/severity builder for the pipeline.

Build data/severity_raw.csv from district-level flood_combined results.

(Do not confuse with src/archive/population.py — legacy WorldPop GEE overlay.)

Primary input (preferred):
    data/flood_combined.csv  — combined_km2, district_km2, flood_ratio, combined_source
    data/events.csv          — state, district, start_date
    data/population.csv      — state population (2025)

Fallback (legacy, archived):
    data/archive/flood_area_results.csv with bbox overflow scaling

Method (primary):
    adjusted_flood_area_km2 = combined_km2   (already district-scoped; no bbox scale)
    exposure_rate           = flood_ratio    (= combined_km2 / district_km2)
    population_exposed      = (combined_km2 / state_area) * state_population
        (uniform state density applied only to the measured flood footprint)

Output:
    data/severity_raw.csv
"""

from __future__ import annotations

import difflib
import math
import os

import numpy as np
import pandas as pd

STATE_AREA_KM2 = {
    "Rajasthan": 342239, "Madhya Pradesh": 308252, "Maharashtra": 307713,
    "Uttar Pradesh": 240928, "Gujarat": 196024, "Karnataka": 191791,
    "Andhra Pradesh": 162975, "Odisha": 155707, "Chhattisgarh": 135192,
    "Tamil Nadu": 130058, "Telangana": 112077, "Bihar": 94163,
    "West Bengal": 88752, "Arunachal Pradesh": 83743, "Jharkhand": 79716,
    "Assam": 78438, "Himachal Pradesh": 55673, "Uttarakhand": 53483,
    "Punjab": 50362, "Haryana": 44212, "Kerala": 38852,
    "Meghalaya": 22429, "Manipur": 22327, "Mizoram": 21081,
    "Nagaland": 16579, "Tripura": 10486, "Sikkim": 7096, "Goa": 3702,
    "Jammu and Kashmir": 42241, "Ladakh": 59146,
    "Delhi": 1484, "Puducherry": 479, "Chandigarh": 114,
    "Dadra & Nagar Haveli and Daman & Diu": 603,
    "Andaman & Nicobar Islands": 8249, "Lakshadweep": 32,
}

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


def load_pop_lookup():
    pop_raw = pd.read_csv("data/population.csv")
    known = list(STATE_AREA_KM2.keys())
    pop_lookup = {}
    for _, row in pop_raw.iterrows():
        canonical = resolve(str(row["State/UT"]), known)
        if canonical:
            pop_lookup[canonical] = parse_pop(row["Population (2025)"])
        else:
            print(f"WARNING: could not match '{row['State/UT']}' — skipped")
    return pop_lookup


def from_flood_combined(pop_lookup: dict) -> pd.DataFrame:
    """Primary path: district-level combined flood areas."""
    combined = pd.read_csv("data/flood_combined.csv")
    events = pd.read_csv("data/events.csv")[
        ["event_id", "state", "district", "start_date"]
    ]
    df = combined.merge(events, on="event_id", how="left")

    rows = []
    for _, r in df.iterrows():
        canonical = resolve(r.get("state"), STATE_AREA_KM2.keys())
        state_pop = pop_lookup.get(canonical)
        state_area = STATE_AREA_KM2.get(canonical)
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
                "state_area_km2": state_area,
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

        if state_area and state_pop:
            # Density applied only over measured footprint (district-scoped area)
            exposed = round((flood_km2 / state_area) * state_pop)
            # Prefer district flood_ratio as exposure_rate when available
            exposure_rate = (
                round(flood_ratio, 6)
                if flood_ratio is not None and not pd.isna(flood_ratio)
                else round(min(flood_km2 / state_area, 1.0), 6)
            )
        else:
            exposed = None
            exposure_rate = None
            if not state_pop:
                warnings.append(f"NO POPULATION DATA for '{canonical}'")
            if not state_area:
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
            "state_area_km2": state_area,
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


def from_legacy_flood_area(pop_lookup: dict) -> pd.DataFrame:
    """Legacy bbox-scaled path (only if flood_combined.csv missing)."""
    flood = pd.read_csv("data/archive/flood_area_results.csv")
    rows = []
    for _, r in flood.iterrows():
        canonical = resolve(r["state"], STATE_AREA_KM2.keys())
        state_pop = pop_lookup.get(canonical)
        state_area = STATE_AREA_KM2.get(canonical)
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
                "bbox_area_km2": None, "state_area_km2": state_area,
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

        if bb_area and state_area and bb_area > state_area * 1.05:
            scale_factor = state_area / bb_area
            adjusted_flood = raw_flood * scale_factor
            warnings.append(
                f"BBOX OVERFLOW: bbox={bb_area:.0f} km2 > state={state_area} km2 "
                f"(scale factor={scale_factor:.3f})."
            )
        else:
            adjusted_flood = raw_flood

        if state_area and state_pop:
            fraction = min(adjusted_flood / state_area, 1.0)
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
            "state_area_km2": state_area,
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

    pop_lookup = load_pop_lookup()

    if os.path.exists("data/flood_combined.csv"):
        print("Using PRIMARY input: data/flood_combined.csv (district-level)")
        out = from_flood_combined(pop_lookup)
    elif os.path.exists("data/archive/flood_area_results.csv"):
        print("WARNING: flood_combined.csv missing — legacy data/archive/flood_area_results.csv")
        out = from_legacy_flood_area(pop_lookup)
    else:
        raise FileNotFoundError(
            "Need data/flood_combined.csv or data/archive/flood_area_results.csv"
        )

    os.makedirs("data", exist_ok=True)
    out.to_csv("data/severity_raw.csv", index=False)

    n_ok = out["adjusted_flood_area_km2"].notna().sum()
    n_null = out["adjusted_flood_area_km2"].isna().sum()
    print(f"\nSAVED: data/severity_raw.csv — {len(out)} events")
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
