"""
compute_population.py  v2

Reads flood_area_results.csv (which now includes bbox columns) and
state_population.csv, then computes population_exposed.

Method:
    1. Clip flood_area_km2 to the actual state area using the bbox's
       overlap fraction with the state boundary (approximated via the
       bbox-to-state-area ratio as a cap).
    2. exposure_rate = clipped_flood_area / state_area  (capped at 1.0)
    3. population_exposed = exposure_rate * state_population

Inputs:
    data/flood_area_results.csv   -- event_id, state, district, start_date,
                                     flood_area_km2, bbox_minlon, bbox_minlat,
                                     bbox_maxlon, bbox_maxlat
    data/state_population.csv     -- State/UT, Population (2025), ...

Output:
    data/severity_raw.csv
"""

import pandas as pd
import numpy as np
import difflib
import math

# ── state areas km2 (Survey of India) ────────────────────────────────────────
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
    m = difflib.get_close_matches(name, known, n=1, cutoff=0.75)
    return m[0] if m else None

def parse_pop(v):
    return int(str(v).replace(",", "").strip())

def bbox_area_km2(minlon, minlat, maxlon, maxlat):
    """
    Approximate bbox area in km2 using the midpoint latitude for scaling.
    1 degree latitude ≈ 111 km everywhere.
    1 degree longitude ≈ 111 * cos(lat) km.
    """
    mid_lat = math.radians((minlat + maxlat) / 2)
    lat_km  = (maxlat - minlat) * 111.0
    lon_km  = (maxlon - minlon) * 111.0 * math.cos(mid_lat)
    return lat_km * lon_km

# ── load ─────────────────────────────────────────────────────────────────────
flood   = pd.read_csv("data/flood_area_results.csv")
pop_raw = pd.read_csv("data/population.csv")
known   = list(STATE_AREA_KM2.keys())

pop_lookup = {}
for _, row in pop_raw.iterrows():
    canonical = resolve(str(row["State/UT"]), known)
    if canonical:
        pop_lookup[canonical] = parse_pop(row["Population (2025)"])
    else:
        print(f"WARNING: could not match '{row['State/UT']}' — skipped")

# ── compute ───────────────────────────────────────────────────────────────────
rows = []
for _, r in flood.iterrows():
    canonical  = resolve(r["state"], known)
    state_pop  = pop_lookup.get(canonical)
    state_area = STATE_AREA_KM2.get(canonical)
    raw_flood  = r.get("flood_area_km2")
    warnings   = []

    if canonical is None:
        warnings.append(f"STATE MATCH FAILED: '{r['state']}'")

    # ── no S1 data sentinel ───────────────────────────────────────────────────
    no_data = pd.isna(raw_flood) or (raw_flood is not None and float(raw_flood) < 0)
    if no_data:
        warnings.append("NO S1 DATA: no Sentinel-1 imagery for this event window")
        rows.append({
            "event_id": r["event_id"], "state": r["state"],
            "district": r.get("district",""), "canonical_state": canonical,
            "start_date": r.get("start_date",""),
            "bbox_area_km2": None, "state_area_km2": state_area,
            "raw_flood_area_km2": None,
            "adjusted_flood_area_km2": None,
            "region_total_population": state_pop,
            "population_exposed": None, "exposure_rate": None,
            "warnings": "; ".join(warnings),
        })
        continue

    raw_flood = float(raw_flood)

    # ── bbox area ─────────────────────────────────────────────────────────────
    try:
        bb_area = bbox_area_km2(
            float(r["bbox_minlon"]), float(r["bbox_minlat"]),
            float(r["bbox_maxlon"]), float(r["bbox_maxlat"])
        )
    except Exception:
        bb_area = None
        warnings.append("BBOX COLUMNS MISSING OR INVALID")

    # ── adjust flood area for bbox overflow ───────────────────────────────────
    # If bbox is larger than the state, the flood mask contains pixels from
    # neighbouring states/countries. Scale the flood area down proportionally:
    #   adjusted = raw_flood * (state_area / bbox_area)
    # This assumes flood pixels are uniformly distributed across the bbox,
    # which is a simplification — but it's far better than clamping to 1.0.
    # Note in your methods section.
    if bb_area and state_area and bb_area > state_area * 1.05:
        scale_factor = state_area / bb_area
        adjusted_flood = raw_flood * scale_factor
        warnings.append(
            f"BBOX OVERFLOW: bbox={bb_area:.0f} km2 > state={state_area} km2 "
            f"(scale factor={scale_factor:.3f}). Flood area scaled from "
            f"{raw_flood:.1f} to {adjusted_flood:.1f} km2."
        )
    else:
        adjusted_flood = raw_flood

    # ── exposure rate and population ──────────────────────────────────────────
    if state_area and state_pop:
        fraction = adjusted_flood / state_area
        if fraction > 1.0:
            warnings.append(
                f"FRACTION STILL >1 after scaling ({fraction:.2f}). Clamping."
            )
            fraction = 1.0
        exposed      = round(fraction * state_pop)
        exposure_rate = round(fraction, 6)
    else:
        exposed = None
        exposure_rate = None
        if not state_pop:
            warnings.append(f"NO POPULATION DATA for '{canonical}'")
        if not state_area:
            warnings.append(f"NO AREA DATA for '{canonical}'")

    rows.append({
        "event_id":                  r["event_id"],
        "state":                     r["state"],
        "district":                  r.get("district", ""),
        "canonical_state":           canonical,
        "start_date":                r.get("start_date", ""),
        "bbox_area_km2":             round(bb_area, 1) if bb_area else None,
        "state_area_km2":            state_area,
        "raw_flood_area_km2":        round(raw_flood, 2),
        "adjusted_flood_area_km2":   round(adjusted_flood, 2),
        "region_total_population":   state_pop,
        "population_exposed":        exposed,
        "exposure_rate":             exposure_rate,
        "warnings":                  "; ".join(warnings),
    })

out = pd.DataFrame(rows)
out.to_csv("data/severity_raw.csv", index=False)

# ── summary ───────────────────────────────────────────────────────────────────
no_s1     = out["warnings"].str.contains("NO S1 DATA", na=False).sum()
scaled    = out["warnings"].str.contains("BBOX OVERFLOW", na=False).sum()
clamped   = out["warnings"].str.contains("FRACTION STILL", na=False).sum()
match_fail= out["warnings"].str.contains("STATE MATCH FAILED", na=False).sum()

print(f"\nSaved data/severity_raw.csv — {len(out)} events")
print(f"  {no_s1}    events with no S1 data (null)")
print(f"  {scaled}   events with bbox overflow — flood area scaled by state/bbox ratio")
print(f"  {clamped}  events still clamped after scaling (bbox much larger than state)")
print(f"  {match_fail} state name match failures")

# Preview
preview_cols = ["event_id","state","raw_flood_area_km2","adjusted_flood_area_km2",
                "region_total_population","population_exposed","exposure_rate"]
print()
print(out[preview_cols].to_string(index=False))