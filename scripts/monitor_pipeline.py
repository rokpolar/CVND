#!/usr/bin/env python3
"""Write a lightweight status report while a pipeline process is running."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def tail(path: Path, limit: int = 12) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def artifact_counts(root: Path) -> list[str]:
    paths = [
        root / "data/intermediate/event_districts.csv",
        root / "data/intermediate/district_covariates.csv",
        root / "data/cache/district/flood_extent.csv",
        root / "data/cache/district/sits_patches_index.csv",
        root / "data/intermediate/district_flood_combined.csv",
        root / "data/intermediate/district_flood_area.csv",
        root / "data/intermediate/article_qa/manifest.json",
        root / "data/intermediate/article_qa/batches.json",
        root / "data/intermediate/article_qa/results.json",
        root / "data/results/primary_30d/district_flood_articles.csv",
        root / "data/results/sensitivity_14d/district_flood_articles.csv",
    ]
    rows = []
    for path in paths:
        if not path.exists():
            rows.append(f"- {path.relative_to(root)}: missing")
            continue
        detail = f"{path.stat().st_size:,} bytes"
        if path.suffix == ".csv":
            try:
                import pandas as pd
                detail = f"{len(pd.read_csv(path)):,} rows"
            except Exception as exc:
                detail = f"unreadable ({type(exc).__name__})"
        elif path.name in {"manifest.json", "batches.json", "results.json"}:
            try:
                payload = json.loads(path.read_text())
                fields = []
                for key in ("request_count", "missing_count", "model", "status"):
                    if key in payload:
                        fields.append(f"{key}={payload[key]}")
                detail = ", ".join(fields) or detail
            except Exception:
                pass
        rows.append(f"- {path.relative_to(root)}: {detail}")
    return rows


def satellite_cache_counts(root: Path) -> list[str]:
    """Report resumable H5/score progress without opening large arrays."""
    patch_dir = root / "data/cache/district/sits_patches"
    score_dir = root / "data/cache/district/sits_scores"
    checkpoint = root / "data/cache/district/satellite_checkpoint_b.json"
    h5 = list(patch_dir.glob("*.h5")) if patch_dir.exists() else []
    partial = list(patch_dir.glob("*.h5.blocks.json")) if patch_dir.exists() else []
    scores = list(score_dir.glob("*.npz")) if score_dir.exists() else []
    done = None
    if checkpoint.exists():
        try:
            done = len(json.loads(checkpoint.read_text()))
        except (OSError, TypeError, ValueError):
            done = None
    done_text = "unknown" if done is None else str(done)
    return [
        "",
        "### 위성 캐시/추론 진행",
        f"- Track-B checkpoint: {done_text} event-districts",
        f"- H5: {len(h5):,} total ({len(partial):,} partial/resumable)",
        f"- SITS score NPZ: {len(scores):,}",
    ]


def snapshot(pid: int, log: Path, root: Path) -> str:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    lines = [
        f"## {now}",
        f"- pipeline PID: {pid}; state: {'running' if alive(pid) else 'stopped'}",
        "",
        "### 산출물",
        *artifact_counts(root),
        *satellite_cache_counts(root),
        "",
        "### 최근 로그",
        "---",
        *tail(log),
        "---",
        "",
    ]
    return "\n".join(lines)


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pipeline-report-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    header = "# CVND 전체 파이프라인 감독 보고서\n\n"
    snapshots = []
    while True:
        snapshots.append(snapshot(args.pid, args.log, args.root))
        write_report(args.report, header + "\n".join(snapshots))
        if not alive(args.pid):
            break
        time.sleep(max(1, args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
