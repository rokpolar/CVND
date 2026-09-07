"""download_patches.py — parallel, resumable Track B patch download with progress.

Why this exists
---------------
`satellite.py --track B` downloads one block at a time and one event at a time.
Nearly all of that time is spent waiting on Earth Engine, so the process sits
idle. This runner splits the event list across several worker processes, which
turns a multi-day download into something that finishes overnight.

Resume is free: every event keeps its own `<event>.h5` plus a `.blocks.json`
recording which blocks finished, so an interrupted run picks up where it stopped.
Killing this script (Ctrl-C) stops the workers; re-running it continues.

Each worker gets its OWN Track B checkpoint file — several processes writing the
shared one would corrupt it — and this script merges them back at the end.

Usage
-----
    python scripts/download_patches.py                      # all events, 4 workers
    python scripts/download_patches.py --workers 6
    python scripts/download_patches.py --events E001 E002   # subset
    python scripts/download_patches.py --limit 3            # speed test: 3 events
    python scripts/download_patches.py --dry-run            # show the plan only

Start with `--limit 2` to measure the real download rate before committing to a
full run; the per-block timing assumed elsewhere in this repo is not measured.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cvnd_layout import data_path  # noqa: E402

PATCH_DIR = Path(data_path("sits_patches"))
WORKER_DIR = Path(data_path("satellite_checkpoint_b")).parent / "_workers"
LOG_DIR = ROOT / "logs" / "download"
POLL_SECONDS = 3


# ── event state ───────────────────────────────────────────────────────────────

def event_state(event_id: str) -> tuple[str, int, int]:
    """Return (status, done_blocks, total_blocks) for one event.

    status is 'done' when the .h5 exists with no outstanding block checkpoint,
    'running' when a partial checkpoint is present, 'todo' otherwise. total is 0
    when the event has not started, because the block count is only known once a
    worker has queried the AOI.
    """
    h5 = PATCH_DIR / f"{event_id}.h5"
    ckpt = PATCH_DIR / f"{event_id}.h5.blocks.json"
    if ckpt.exists():
        try:
            raw = json.loads(ckpt.read_text())
        except (json.JSONDecodeError, OSError):
            return "running", 0, 0
        if isinstance(raw, list):                      # legacy bare-list format
            return "running", len(raw), 0
        return "running", len(raw.get("done", [])), int(raw.get("total") or 0)
    if h5.exists():
        return "done", 1, 1
    return "todo", 0, 0


def load_events(args) -> list[str]:
    events = pd.read_csv(data_path("events"))
    ids = [str(e) for e in events["event_id"]]
    if args.events:
        wanted = set(args.events)
        missing = wanted - set(ids)
        if missing:
            sys.exit(f"unknown event_ids: {', '.join(sorted(missing))}")
        ids = [e for e in ids if e in wanted]
    if not args.redo:
        ids = [e for e in ids if event_state(e)[0] != "done"]
    if args.limit:
        ids = ids[: args.limit]
    return ids


def partition(items: list[str], n: int) -> list[list[str]]:
    """Round-robin so each worker gets a mix of large and small AOIs."""
    buckets: list[list[str]] = [[] for _ in range(n)]
    for i, item in enumerate(items):
        buckets[i % n].append(item)
    return [b for b in buckets if b]


# ── progress ──────────────────────────────────────────────────────────────────

def render(pending: list[str], finished_at_start: int, total_events: int,
           started: float, workers: list[dict]) -> str:
    done = finished_at_start
    in_flight = []
    for ev in pending:
        status, d, t = event_state(ev)
        if status == "done":
            done += 1
        elif status == "running" and d:
            in_flight.append(f"{ev} {d}/{t}" if t else f"{ev} {d}blk")

    width = 30
    frac = done / total_events if total_events else 1.0
    bar = "#" * int(frac * width) + "-" * (width - int(frac * width))
    elapsed = time.time() - started
    newly_done = done - finished_at_start
    if newly_done:
        eta = elapsed / newly_done * (total_events - done)
        eta_s = f"  ETA {eta / 3600:.1f}h" if eta > 3600 else f"  ETA {eta / 60:.0f}m"
    else:
        eta_s = "  ETA --"

    alive = sum(1 for w in workers if w["proc"].poll() is None)
    line = (f"\r[{bar}] {done}/{total_events} ({frac * 100:5.1f}%)"
            f"  {elapsed / 60:.0f}m{eta_s}  workers {alive}/{len(workers)}")
    if in_flight:
        line += "  | " + " ".join(in_flight[:4])
    return line.ljust(shutil.get_terminal_size((120, 20)).columns - 1)[
        : shutil.get_terminal_size((120, 20)).columns - 1]


# ── merge ─────────────────────────────────────────────────────────────────────

def merge_checkpoints() -> int:
    """Fold the per-worker Track B checkpoints into the shared one."""
    shared_path = Path(data_path("satellite_checkpoint_b"))
    merged: dict = {}
    if shared_path.exists():
        try:
            merged = json.loads(shared_path.read_text())
        except (json.JSONDecodeError, OSError):
            merged = {}
    for wf in sorted(WORKER_DIR.glob("checkpoint_b_*.json")):
        try:
            merged.update(json.loads(wf.read_text()))
        except (json.JSONDecodeError, OSError):
            print(f"  WARN unreadable worker checkpoint: {wf.name}")
    shared_path.parent.mkdir(parents=True, exist_ok=True)
    shared_path.write_text(json.dumps(merged))

    rows = [v for v in merged.values() if isinstance(v, dict)]
    if rows:
        index_path = Path(data_path("sits_patches_index"))
        index_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).sort_values("event_id").to_csv(index_path, index=False)
    return len(merged)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workers", type=int, default=4,
                   help="parallel processes (default 4). Earth Engine throttles "
                        "concurrent requests; more is not always faster.")
    p.add_argument("--events", nargs="*", help="only these event_ids")
    p.add_argument("--limit", type=int, help="cap the number of events (speed test)")
    p.add_argument("--redo", action="store_true",
                   help="include events already finished")
    p.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args = p.parse_args()

    pending = load_events(args)
    all_ids = pd.read_csv(data_path("events"))["event_id"].astype(str).tolist()
    if args.events:
        all_ids = [e for e in all_ids if e in set(args.events)]
    if args.limit:
        finished_at_start = 0
        total_events = len(pending)
    else:
        finished_at_start = sum(1 for e in all_ids if event_state(e)[0] == "done")
        total_events = len(all_ids)

    if not pending:
        print(f"nothing to do — {finished_at_start}/{total_events} events already complete")
        return

    groups = partition(pending, max(1, args.workers))
    print(f"events: {total_events} total, {finished_at_start} done, "
          f"{len(pending)} to download")
    print(f"workers: {len(groups)}")
    for i, g in enumerate(groups):
        preview = ", ".join(g[:5]) + (f" … (+{len(g) - 5})" if len(g) > 5 else "")
        print(f"  [{i}] {len(g):3d} events: {preview}")
    if args.dry_run:
        return

    WORKER_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PATCH_DIR.mkdir(parents=True, exist_ok=True)

    started = time.time()
    workers = []
    for i, group in enumerate(groups):
        log = LOG_DIR / f"worker{i}.log"
        cmd = [sys.executable, str(ROOT / "src" / "satellite.py"),
               "--track", "B", "--events", *group,
               "--checkpoint-b", str(WORKER_DIR / f"checkpoint_b_{i}.json"),
               "--sits-index", str(WORKER_DIR / f"index_{i}.csv")]
        handle = open(log, "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=handle,
                                stderr=subprocess.STDOUT)
        workers.append({"proc": proc, "log": handle, "path": log})
    print(f"logs: {LOG_DIR}\n")

    try:
        while any(w["proc"].poll() is None for w in workers):
            print(render(pending, finished_at_start, total_events, started, workers),
                  end="", flush=True)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\n\ninterrupted — stopping workers (progress is saved, re-run to resume)")
        for w in workers:
            if w["proc"].poll() is None:
                w["proc"].terminate()
        for w in workers:
            try:
                w["proc"].wait(timeout=30)
            except subprocess.TimeoutExpired:
                w["proc"].kill()
    finally:
        for w in workers:
            w["log"].close()

    print(render(pending, finished_at_start, total_events, started, workers))
    elapsed = time.time() - started

    done_now = sum(1 for e in all_ids if event_state(e)[0] == "done")
    newly = done_now - finished_at_start
    print(f"\n\nfinished {newly} events in {elapsed / 60:.1f} min", end="")
    if newly:
        print(f"  ({elapsed / newly / 60:.1f} min/event)")
        remaining = total_events - done_now
        if remaining:
            print(f"projected for the remaining {remaining}: "
                  f"{elapsed / newly * remaining / 3600:.1f} h "
                  f"at this worker count")
    else:
        print()

    failed = [w["path"].name for w in workers if w["proc"].returncode not in (0, None)]
    if failed:
        print(f"WARN workers exited non-zero: {', '.join(failed)} — check {LOG_DIR}")

    print(f"merged checkpoint entries: {merge_checkpoints()}")


if __name__ == "__main__":
    main()
