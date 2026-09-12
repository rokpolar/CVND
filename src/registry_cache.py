"""Preserve only unchanged district IDs and geometry when registry is rebuilt."""
from pathlib import Path
import json
import shutil
import pandas as pd
from cvnd_layout import ROOT, data_path
from district_articles import registry_fingerprint
from gdelt_backend import _atomic_write

ARTIFACTS = ("district_aoi", "district_flood_extent", "district_sits_patches_index",
             "district_flood_combined", "district_flood_area")
IDENTITY = ("event_id", "source_record_id", "state", "district", "start_date")


def compatible_rows(frame, old_registry, new_registry, aoi=None):
    old = old_registry.set_index("event_district_id")
    new = new_registry.set_index("event_district_id")
    retained = []
    for index, row in frame.iterrows():
        key = row.get("event_district_id")
        if key not in old.index or key not in new.index:
            continue
        if any(str(old.loc[key, col]) != str(new.loc[key, col]) for col in IDENTITY):
            continue
        if any(col in row and str(row[col]) != str(new.loc[key, col]) for col in IDENTITY):
            continue
        geometry = str(row.get("geometry_id", "") or "")
        if not geometry or geometry == "nan":
            continue
        if aoi is not None:
            match = aoi[aoi.event_district_id.eq(key)]
            if len(match) != 1 or str(match.iloc[0].get("geometry_id", "")) != geometry:
                continue
        retained.append(index)
    return frame.loc[retained].copy()


def reconcile(old_registry, new_registry):
    old_hash, new_hash = registry_fingerprint(old_registry), registry_fingerprint(new_registry)
    if old_hash == new_hash:
        return
    archive = ROOT / "data/archive/registry" / old_hash
    archive.mkdir(parents=True, exist_ok=True)
    records = []
    aoi_path = data_path("district_aoi")
    aoi = pd.read_csv(aoi_path, dtype=str, keep_default_na=False) if aoi_path.exists() else None
    for key in ARTIFACTS:
        path = data_path(key)
        if not path.exists():
            continue
        original = pd.read_csv(path, dtype=str, keep_default_na=False)
        if "event_district_id" not in original:
            continue
        kept = compatible_rows(original, old_registry, new_registry,
                               None if key == "district_aoi" else aoi)
        backup = archive / path.relative_to(ROOT / "data")
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(path, backup)
        _atomic_write(path, kept.to_csv(index=False))
        records.append({"artifact":key, "previous_rows":len(original),
                        "retained_rows":len(kept), "archive":str(backup)})
    _atomic_write(ROOT/"data/intermediate/registry_cache_migration.json",
                  json.dumps({"old_registry_sha256":old_hash, "registry_sha256":new_hash,
                              "status":"derived_outputs_stale",
                              "artifacts":records}, indent=2)+"\n")
