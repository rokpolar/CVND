#!/usr/bin/env python3
"""One-time migration of the verified pre-marker Track-A district cache.

The historical checkpoint was produced by a run that queried both sensors but
predates ``s1_attempted``/``s2_attempted``.  Mark S1 for every current row and
S2 only for the production fallback cohort (matched AOI and missing S1).  This
prevents immutable NO_IMAGERY results from being downloaded on every rerun.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cvnd_layout import data_path  # noqa: E402
from district_keys import analysis_key  # noqa: E402
from flood_spec import SPEC_VERSION  # noqa: E402
from satellite import save_checkpoint  # noqa: E402


def observed(value) -> bool:
    try:
        return value is not None and math.isfinite(float(value)) and float(value) >= 0
    except (TypeError, ValueError):
        return False


def migrate(path: Path | None = None) -> tuple[int, int]:
    path = path or data_path("district_satellite_checkpoint_a")
    registry = pd.read_csv(data_path("event_districts"), dtype=str, keep_default_na=False)
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    expected = set(registry.apply(analysis_key, axis=1))
    if set(checkpoint) != expected:
        raise ValueError(
            f"checkpoint/registry key mismatch: missing={len(expected-set(checkpoint))} "
            f"extra={len(set(checkpoint)-expected)}"
        )
    s2_count = 0
    for key, entry in checkpoint.items():
        if entry.get("spec_version") != SPEC_VERSION:
            raise ValueError(f"stale Track-A spec for {key}: {entry.get('spec_version')}")
        entry["s1_attempted"] = True
        fallback = (str(entry.get("aoi_match_status", "")).strip().lower() == "matched"
                    and not observed(entry.get("area_s1_km2")))
        if fallback:
            entry["s2_attempted"] = True
            s2_count += 1
        elif "s2_attempted" not in entry:
            entry["s2_attempted"] = False
    save_checkpoint(checkpoint, str(path))
    return len(checkpoint), s2_count


if __name__ == "__main__":
    total, fallback = migrate()
    print(f"Migrated Track-A attempt markers: s1={total}, s2_fallback={fallback}")
