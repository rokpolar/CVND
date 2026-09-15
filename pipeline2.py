"""pipeline2.py - re-measure the satellite side only, on an S2-ready cohort,
force the SITS route, and write everything to `<원래이름>_2` copies.

What this does and does not do
------------------------------
RE-RUN   : AOI resolution, Track A, Track B, SITS inference, merge, flood-area
           table -- for a fixed cohort of district-events Sentinel-2 can measure.
COPY     : everything else -- article counts, census covariates, exclusion
           reasons -- straight from the previous result file, as text.
NEVER    : touch an original artifact, recompute an article count, re-join, or
           re-run the analysis. The previous result file is COPIED to
           `<원래이름>_2.csv` and only the satellite cells of the re-measured
           districts are rewritten in the copy. Every other row and column comes
           through byte-identical.

"Force SITS"
------------
`SPEC.sits_usable_min_frac` (0.4) is the only routing rule that can divert an
otherwise-measured SITS district to S1/NA. It is set to 0.0 for the merge step
only, via `dataclasses.replace`, so any district whose Track B finished is
routed SITS_NDWI regardless of how small its usable footprint is. The
module-level `SPEC_VERSION` is NOT touched: Track A rows, H5 and NPZ stay valid.

The Youden score gate (`sits_j_min`) is left on because it never rejects a
district -- it only chooses gated vs full extent, and both are SITS_NDWI.
`--full-extent` bypasses it too.

A district with no Track B measurement at all (`sits_pending`,
`sits_unavailable`) cannot be forced into SITS; there is no measurement to use.
Those stay NA and are reported. `--fail-on-non-sits` turns that into an error.

Usage
-----
    python pipeline2.py --dry-run           # plan + cohort, run nothing
    python pipeline2.py --limit 3           # 3 smallest districts (smoke test)
    python pipeline2.py                     # full cohort
    python pipeline2.py --from merge        # resume
    python pipeline2.py --only overlay      # just rebuild the _2 file
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from cvnd_layout import data_path  # noqa: E402

STEPS = ("aoi", "satellite", "inference", "merge", "area", "overlay")
SUFFIX = "_2"


def variant(path) -> Path:
    """data/x/name.csv -> data/x/name_2.csv (the `원래이름_2` convention)."""
    path = Path(path)
    return path.with_name(f"{path.stem}{SUFFIX}{path.suffix}")


# ==============================================================================
# COHORT
# ==============================================================================

def select_cohort(source: str = "sr", min_usable_frac: float = 0.4,
                  limit: int | None = None, probe_path: Path | None = None) -> pd.DataFrame:
    """District-events Sentinel-2 can measure today, from the feasibility probe.

    This threshold picks what is worth DOWNLOADING. It is not the routing gate;
    that one is disabled separately so nothing is rejected at merge time.
    """
    probe_path = Path(probe_path or data_path("district_sits_feasibility"))
    if not probe_path.exists():
        raise SystemExit(f"{probe_path} missing: run `python src/sits_feasibility.py` first, "
                         f"or pass --cohort-file with one event_district_id per line")
    probe = pd.read_csv(probe_path)
    status, frac = f"{source}_status", f"{source}_usable_frac"
    for column in ("aoi_status", status, frac):
        if column not in probe.columns:
            raise SystemExit(f"feasibility probe has no {column!r}; is --source {source!r} right?")
    usable = pd.to_numeric(probe[frac], errors="coerce")
    cohort = probe[
        (probe["aoi_status"].astype(str).str.strip().str.lower() == "matched")
        & (probe[status].astype(str).str.strip().str.lower() == "ok")
        & (usable >= min_usable_frac)
    ].copy()
    cohort["usable_frac"] = usable.loc[cohort.index].round(3)
    cohort = cohort.sort_values("usable_frac", ascending=False)
    if limit:
        # Smallest first: a smoke test should not start with a 323-block district.
        cohort = cohort.nsmallest(limit, "grid_blocks")
    return cohort.reset_index(drop=True)


def cohort_from_file(path: Path) -> pd.DataFrame:
    keys = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    if not keys:
        raise SystemExit(f"{path} contains no event_district_id")
    return pd.DataFrame({"event_district_id": keys})


def write_cohort(cohort: pd.DataFrame) -> Path:
    out = Path(data_path("event_districts")).with_name("pipeline2_cohort.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = [c for c in ("event_district_id", "event_id", "state", "district", "start_date",
                           "usable_frac", "grid_blocks", "eligible_km2") if c in cohort.columns]
    cohort[columns].to_csv(out, index=False)
    return out


# ==============================================================================
# STEP RUNNER
# ==============================================================================

class Runner:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.env = dict(os.environ)
        existing = self.env.get("PYTHONPATH")
        self.env["PYTHONPATH"] = os.pathsep.join([str(SRC)] + ([existing] if existing else []))

    def script(self, name: str, *args: str) -> None:
        shown = " ".join([name, *args])
        if len(shown) > 360:
            shown = shown[:360] + f" ... (+{len(args)} args total)"
        print(f"\n$ python src/{shown}", flush=True)
        if self.dry_run:
            return
        result = subprocess.run([sys.executable, str(SRC / name), *args],
                                cwd=str(ROOT), env=self.env)
        if result.returncode != 0:
            raise SystemExit(f"step failed: {name} (exit {result.returncode})")


# ==============================================================================
# AOI (non-destructive)
# ==============================================================================

def run_aoi(runner: "Runner", keys: list[str]) -> None:
    """Resolve the cohort's AOIs without losing the other districts' rows.

    ``event_aoi_area.py`` rewrites the whole district_aoi.csv from whatever rows
    it was asked to resolve, so running it on a subset would drop every other
    district. The table is snapshotted first and the cohort's freshly resolved
    rows are merged back into it.
    """
    table = Path(data_path("district_aoi"))
    before = pd.read_csv(table, dtype=str, keep_default_na=False,
                         na_filter=False) if table.exists() else None
    if runner.dry_run:
        runner.script("event_aoi_area.py", *keys)
        return
    backup = table.with_suffix(".bak.csv")
    if before is not None:
        before.to_csv(backup, index=False)
    try:
        runner.script("event_aoi_area.py", *keys)
    except SystemExit:
        if before is not None:
            before.to_csv(table, index=False)
            print(f"[aoi] step failed; restored {len(before)} rows from the snapshot")
        raise
    fresh = pd.read_csv(table, dtype=str, keep_default_na=False, na_filter=False)
    if before is None:
        return
    key = "event_district_id"
    merged = pd.concat([before[~before[key].isin(set(fresh[key]))], fresh], ignore_index=True)
    merged = merged.sort_values(key).reset_index(drop=True)
    merged.to_csv(table, index=False)
    print(f"[aoi] merged {len(fresh)} resolved row(s) back into {table} "
          f"({len(before)} -> {len(merged)} rows); snapshot kept at {backup.name}")


# ==============================================================================
# MERGE (forced SITS)
# ==============================================================================

def run_merge(keys: list[str], gate_frac: float, full_extent: bool, fail_on_non_sits: bool,
              dry_run: bool = False) -> None:
    """`merge_results.main()` with the routing footprint gate relaxed, into `_2`.

    Reimplemented here only because upstream `main()` takes no spec argument and
    no output path. Every number still comes from upstream functions unchanged.
    """
    import merge_results as mr
    from flood_spec import (COMBINED_COLUMNS, SATELLITE_SOURCES, SITS_SOURCES, SPEC,
                            SPEC_VERSION)

    spec = replace(SPEC, sits_usable_min_frac=gate_frac)
    if full_extent:
        # Unreachable J, so sits_threshold() never returns 'ndwi-calib' and
        # route_area() takes the full retained-tile extent.
        spec = replace(spec, sits_j_min=2.0)
    out = variant(data_path("district_flood_combined"))
    print(f"\n[merge] routing=sits_primary  sits_usable_min_frac="
          f"{SPEC.sits_usable_min_frac} -> {spec.sits_usable_min_frac}"
          + ("  + Youden gate bypassed (full extent)" if full_extent else ""))
    print(f"[merge] SPEC_VERSION unchanged ({SPEC_VERSION}); satellite caches stay valid")
    print(f"[merge] output -> {out}")
    if dry_run:
        return

    track_a = mr.load_track_a()
    archives = mr._score_archives(track_a)
    index = mr.load_sits_index()
    selected, rows, skipped = set(keys), [], 0
    for key in sorted(track_a):
        if key not in selected:
            skipped += 1
            continue
        a = track_a[key]
        archive = np.load(archives[key], allow_pickle=False) if key in archives else None
        try:
            row = mr.merge_row(a, archive, index.get(key), converter=None, spec=spec,
                               routing="sits_primary")
        finally:
            if archive is not None:
                archive.close()
        assert row["satellite_source"] in SATELLITE_SOURCES
        rows.append(row)
        print(f"  {key}: sits={row['sits_status']}/{row['sits_method']} "
              f"usable_frac={row['sits_usable_frac']} -> {row['combined_km2']} km2 "
              f"({row['satellite_source']}, {row['route_reason']})")
    if skipped:
        print(f"  ({skipped} Track-A rows outside the cohort were not merged)")

    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=list(COMBINED_COLUMNS)).to_csv(out, index=False)
    print(f"\n[merge] Saved -> {out}  ({len(rows)} rows)")
    if not rows:
        print("[merge] WARNING: no cohort row had a Track-A measurement under the current spec")
        return
    sources = pd.Series([r["satellite_source"] for r in rows]).value_counts()
    print("[merge] satellite_source: " + ", ".join(f"{k}={v}" for k, v in sources.items()))
    print("[merge] route_reason: " + ", ".join(
        f"{k}={v}" for k, v in pd.Series([r["route_reason"] for r in rows]).value_counts().items()))
    non_sits = [r for r in rows if r["satellite_source"] not in SITS_SOURCES]
    if non_sits:
        print(f"[merge] {len(non_sits)} row(s) could NOT be routed to SITS "
              f"(no Track-B measurement exists for them):")
        for r in non_sits[:10]:
            print(f"    {r['event_district_id']}: {r['sits_status']}/{r['sits_reason']} "
                  f"-> {r['route_reason']}")
        if fail_on_non_sits:
            raise SystemExit("--fail-on-non-sits: not every cohort district is on the SITS route")


# ==============================================================================
# OVERLAY - previous result + new satellite columns
# ==============================================================================

# Satellite columns of the result table. These are the ONLY cells the overlay
# rewrites; every other column and every other row is copied through untouched.
SATELLITE_COLUMNS = ("flood_area_km2", "flood_ratio", "flood_ratio_eligible", "aoi_area_km2",
                     "eligible_km2", "satellite_source", "satellite_status",
                     "district_match_status", "aoi_match_status", "geometry_id",
                     "route_reason", "cloud_pct", "otsu_fallback_used", "s1_orbit",
                     "sits_status", "converter_decision", "spec_version",
                     "legacy_flood_area_km2", "legacy_satellite_source",
                     "analysis_observation_status")


def run_overlay(baseline_path: Path, area_path: Path, out_path: Path, keys: list[str],
                dry_run: bool = False) -> None:
    """Copy the previous result file and rewrite only its satellite cells.

    Every value is read and written as text, so untouched columns and untouched
    rows come out byte-identical to the baseline. Nothing is recomputed, nothing
    is re-joined, no row is added or dropped: this replaces satellite cells of
    the re-measured districts and does nothing else.
    """
    print(f"\n[overlay] copy    : {baseline_path}")
    print(f"[overlay] satellite: {area_path}")
    print(f"[overlay] write to : {out_path}")
    if dry_run:
        return
    for path in (baseline_path, area_path):
        if not Path(path).exists():
            raise SystemExit(f"[overlay] missing {path}")

    key = "event_district_id"
    # dtype=str everywhere: pandas must not reformat a number it is only copying.
    baseline = pd.read_csv(baseline_path, dtype=str, keep_default_na=False, na_filter=False)
    measured = pd.read_csv(area_path, dtype=str, keep_default_na=False, na_filter=False)
    measured = measured.set_index(key)

    columns = [c for c in SATELLITE_COLUMNS if c in baseline.columns and c in measured.columns]
    skipped = [c for c in SATELLITE_COLUMNS if c in baseline.columns and c not in measured.columns]
    if skipped:
        print(f"[overlay] not in the new table, left as-is: {skipped}")

    cohort = set(keys)
    target = baseline[key].isin(cohort) & baseline[key].isin(measured.index)
    absent = sorted(cohort - set(baseline[key]))
    if absent:
        print(f"[overlay] {len(absent)} re-measured district(s) are not rows of the baseline "
              f"and were not added: {absent[:5]}")

    changed_cells, changed_rows = 0, 0
    result = baseline.copy()
    for i in baseline.index[target]:
        row_key = baseline.at[i, key]
        row_changed = False
        for column in columns:
            old, new_value = baseline.at[i, column], measured.at[row_key, column]
            if old != new_value:
                result.at[i, column] = new_value
                changed_cells += 1
                row_changed = True
        changed_rows += int(row_changed)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False)
    print(f"[overlay] Saved -> {out_path}")
    print(f"[overlay] {len(result)} rows total | {int(target.sum())} rows in scope | "
          f"{changed_rows} rows changed | {changed_cells} cells rewritten")
    print(f"[overlay] {len(result) - changed_rows} rows are byte-identical to the baseline")
    if changed_rows:
        view = result.loc[baseline[key].isin(cohort),
                          [key, "flood_area_km2", "satellite_source", "satellite_status"]]
        print(view.to_string(index=False))


# ==============================================================================
# MAIN
# ==============================================================================

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["sr", "l1c"], default="sr",
                   help="feasibility probe column set (default: sr = Sentinel-2 L2A)")
    p.add_argument("--min-usable-frac", type=float, default=0.4,
                   help="COHORT download threshold on the probe (default: 0.4); not the gate")
    p.add_argument("--cohort-file", type=Path,
                   help="explicit cohort: one event_district_id per line (skips the probe)")
    p.add_argument("--limit", type=int, help="keep only the N smallest districts (smoke test)")
    p.add_argument("--gate-usable-min-frac", type=float, default=0.0,
                   help="routing footprint gate for this run (default: 0.0 = forced SITS)")
    p.add_argument("--full-extent", action="store_true",
                   help="also bypass the Youden score gate: every retained tile counts")
    p.add_argument("--fail-on-non-sits", action="store_true",
                   help="error out if any cohort district ends up off the SITS route")
    p.add_argument("--baseline", type=Path, default=data_path("district_flood_articles"),
                   help="the previous result file to clone; only its satellite cells are "
                        "rewritten (default: data/results/district_flood_articles.csv)")
    p.add_argument("--from", dest="start", choices=STEPS, help="resume from this step")
    p.add_argument("--only", nargs="+", choices=STEPS, help="run only these steps")
    p.add_argument("--skip", nargs="+", choices=STEPS, default=[], help="steps to skip")
    p.add_argument("--workers", type=int, default=4, help="Track A concurrency")
    p.add_argument("--batch-size", type=int, default=64, help="SITS inference batch size")
    p.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    return p.parse_args(argv)


def resolve_steps(args) -> list[str]:
    if args.only:
        return [s for s in STEPS if s in set(args.only)]
    steps = list(STEPS)
    if args.start:
        steps = steps[STEPS.index(args.start):]
    return [s for s in steps if s not in set(args.skip)]


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.cohort_file:
        cohort, origin = cohort_from_file(args.cohort_file), str(args.cohort_file)
    else:
        cohort = select_cohort(args.source, args.min_usable_frac, args.limit)
        origin = (f"{data_path('district_sits_feasibility')} "
                  f"({args.source}, usable_frac >= {args.min_usable_frac})")
    keys = cohort["event_district_id"].astype(str).tolist()
    if not keys:
        raise SystemExit("cohort is empty; lower --min-usable-frac or pass --cohort-file")

    # Keep only keys the registry actually has. The feasibility probe was written
    # against GAUL 2015 spellings and a few districts have since been renamed in
    # the registry (Belgaum -> Belagavi, ...). Those are dropped, not remapped:
    # a name-matching rule here could silently pair the wrong district.
    registry_keys = set(pd.read_csv(data_path("event_districts"),
                                    dtype=str)["event_district_id"])
    unknown = [k for k in keys if k not in registry_keys]
    if unknown:
        print(f"Dropping {len(unknown)} cohort key(s) absent from the registry "
              f"(renamed since the feasibility probe): {unknown}")
        cohort = cohort[cohort["event_district_id"].astype(str).isin(registry_keys)]
        cohort = cohort.reset_index(drop=True)
        keys = cohort["event_district_id"].astype(str).tolist()

    steps = resolve_steps(args)
    cohort_csv = None if args.dry_run else write_cohort(cohort)

    combined_2 = variant(data_path("district_flood_combined"))
    area_2 = variant(data_path("district_flood_area"))
    articles_2 = variant(data_path("district_flood_articles"))

    print("=" * 74)
    print("CVND PIPELINE 2 - satellite re-measure only, forced SITS, `_2` outputs")
    print("=" * 74)
    print(f"  cohort source  : {origin}")
    print(f"  cohort size    : {len(keys)} district-events")
    if "grid_blocks" in cohort:
        blocks = int(pd.to_numeric(cohort["grid_blocks"], errors="coerce").fillna(0).sum())
        print(f"  download size  : {blocks} blocks")
    print(f"  routing        : sits_primary, sits_usable_min_frac={args.gate_usable_min_frac}"
          + ("  + full extent" if args.full_extent else ""))
    print(f"  baseline copy  : {args.baseline}")
    print(f"  steps          : {' -> '.join(steps)}")
    if cohort_csv:
        print(f"  cohort file    : {cohort_csv}")
    print("  outputs        : " + "\n                   ".join(
        str(p) for p in (combined_2, area_2, articles_2)))
    print()
    for i, key in enumerate(keys, 1):
        row = cohort.iloc[i - 1]
        extra = ""
        if "state" in cohort:
            extra += f"  {row.get('state')}/{row.get('district')}  {row.get('start_date')}"
        if "usable_frac" in cohort:
            extra += f"  usable={row.get('usable_frac')}  blocks={row.get('grid_blocks')}"
        print(f"  {i:>3}. {key}{extra}")

    run = Runner(args.dry_run)

    if "aoi" in steps:
        run_aoi(run, keys)
    if "satellite" in steps:
        run.script("satellite.py", "--track", "both", "--workers", str(args.workers),
                   "--events", *keys)
    if "inference" in steps:
        run.script("run_sits_inference.py", "--batch-size", str(args.batch_size),
                   "--events", *keys)
    if "merge" in steps:
        run_merge(keys, args.gate_usable_min_frac, args.full_extent,
                  args.fail_on_non_sits, args.dry_run)
    if "area" in steps:
        run.script("build_flood_area_table.py",
                   "--input", str(combined_2), "--output", str(area_2))
    if "overlay" in steps:
        run_overlay(args.baseline, area_2, articles_2, keys, args.dry_run)
    print("\n" + "=" * 74)
    print("DRY RUN COMPLETE - nothing was executed" if args.dry_run else "DONE")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
