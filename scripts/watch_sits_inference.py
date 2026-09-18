#!/usr/bin/env python3
"""Infer completed SITS H5 files while satellite downloads continue.

``satellite.py`` writes a sibling ``.blocks.json`` file for every H5 that is
still being downloaded.  This watcher repeatedly invokes the existing local
inference command; the command itself ignores those partial H5 files and
reuses score files whose input/model hashes are unchanged.  Consequently a
newly completed H5 can be scored without touching the downloader.

The watcher exits after the satellite process has stopped, following one final
scan.  H5 files still partial at that point (blocks that failed and are retried
on the next satellite.py run) are listed as a warning, not a failure: the
pipeline (run_pipeline.sh) reruns the download for them and refuses to merge
while any remains unfinished.  Only a failed inference run makes the exit
status non-zero.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from district_keys import key_from_stem


ROOT = Path(__file__).resolve().parents[1]
INFERENCE = ROOT / "src" / "run_sits_inference.py"
PATCH_DIR = ROOT / "data" / "cache" / "district" / "sits_patches"


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def partial_h5_paths() -> list[Path]:
    return sorted(PATCH_DIR.glob("*.h5.blocks.json")) if PATCH_DIR.exists() else []


def partial_h5_count() -> int:
    return len(partial_h5_paths())


def complete_h5_signatures() -> dict[Path, tuple[int, int]]:
    """Return stable signatures for H5 files whose block marker is gone."""
    if not PATCH_DIR.exists():
        return {}
    complete = {}
    for path in PATCH_DIR.glob("*.h5"):
        if Path(str(path) + ".blocks.json").exists():
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        complete[path] = (stat.st_size, stat.st_mtime_ns)
    return complete


def run_inference(args: argparse.Namespace, paths: list[Path]) -> int:
    command = [
        sys.executable,
        str(INFERENCE),
        "--device",
        args.device,
        "--batch-size",
        str(args.batch_size),
        "--offline",
    ]
    if paths:
        command.extend(["--events", *sorted(key_from_stem(path.stem) for path in paths)])
    if args.overwrite:
        command.append("--overwrite")
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(
        f"[{started}] inferring {len(paths)} newly completed/changed H5 file(s)",
        flush=True,
    )
    result = subprocess.run(command, cwd=ROOT, check=False)
    finished = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(
        f"[{finished}] inference scan exit={result.returncode}; "
        f"partial_h5={partial_h5_count()}",
        flush=True,
    )
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--satellite-pid",
        type=int,
        required=True,
        help="PID of the satellite.py process being watched",
    )
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    had_failure = False
    processed: dict[Path, tuple[int, int]] = {}

    while True:
        complete = complete_h5_signatures()
        pending = [path for path, signature in complete.items()
                   if processed.get(path) != signature]
        if pending and run_inference(args, pending) != 0:
            # Keep watching: a transient/stale file must not stop downloads.
            # The non-zero result is returned after the final scan so the
            # wrapper still exposes an integrity failure to the caller.
            had_failure = True
        elif pending:
            processed.update({path: complete[path] for path in pending})

        satellite_running = pid_alive(args.satellite_pid)
        if not satellite_running:
            # The last H5 may have become complete during the scan above.
            # One deterministic final snapshot closes that race. Partial H5s
            # left by the downloader are reported; run_pipeline.sh reruns
            # satellite.py --track B to resume their blocks.
            final_complete = complete_h5_signatures()
            final_pending = [path for path, signature in final_complete.items()
                             if processed.get(path) != signature]
            if final_pending:
                if run_inference(args, final_pending) != 0:
                    had_failure = True
                else:
                    processed.update(
                        {path: final_complete[path] for path in final_pending}
                    )
            partial = partial_h5_paths()
            if partial:
                keys = sorted(key_from_stem(Path(path.name[:-len(".blocks.json")]).stem)
                              for path in partial)
                print(
                    f"WARNING: satellite PID {args.satellite_pid} stopped with "
                    f"{len(partial)} partial H5 file(s); the next download "
                    f"round (satellite.py --track B) resumes them:",
                    file=sys.stderr,
                    flush=True,
                )
                for key in keys:
                    print(f"  {key}", file=sys.stderr, flush=True)
            return 1 if had_failure else 0

        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
