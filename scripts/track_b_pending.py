#!/usr/bin/env python3
"""Print the registry districts Track B has not finished, one key per line.

A district is finished once satellite.py recorded a non-ERROR result for it in
the Track B checkpoint (a patch file, or a decided skip such as no imagery) and
no ``.h5.blocks.json`` marker says its H5 is still partial. Everything else --
never attempted, ERROR, or blocks still missing -- is printed so the pipeline
reruns satellite.py --track B, which resumes exactly those districts.
Nothing is printed when Track B is complete. Reads files only; no Earth Engine.

Districts whose AOI match failed in district_aoi.csv have no boundary to
download, so no rerun can finish them; they are listed on stderr and left out.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cvnd_layout import data_path
from district_keys import analysis_key, key_from_stem


def pending_keys() -> list[str]:
    registry = pd.read_csv(data_path("event_districts"))
    keys = {analysis_key(row) for _, row in registry.iterrows()}

    checkpoint_path = Path(data_path("district_satellite_checkpoint_b"))
    checkpoint = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {}
    finished = {key for key, entry in checkpoint.items()
                if not str(entry.get("status", "")).startswith("ERROR")}

    patch_dir = Path(data_path("district_sits_patches"))
    partial = set()
    if patch_dir.exists():
        for marker in patch_dir.glob("*.h5.blocks.json"):
            partial.add(key_from_stem(marker.name[:-len(".h5.blocks.json")]))

    return sorted(((keys - finished) | (keys & partial)) - no_aoi_keys())


def no_aoi_keys() -> set[str]:
    """Registry keys whose district AOI match failed (nothing to download)."""
    # [변경 2026-09-19] AOI 매칭 실패(aoi_match_status == 'failed') 구역은
    # 재다운로드 대상에서 제외하도록 바꿨다. 경계가 없어 Track B가 매번
    # "district AOI match failed" ERROR를 내므로, 포함하면 run_pipeline.sh의
    # 재시도 루프가 끝나지 않고 매번 병합 전에 멈춘다 (당시 5개 구역:
    # Jogbani, Chengannur, Itanagar Capital Region, Chumoukedima 등).
    # 필요시 이 코드를 바꿀 것: AOI를 복구해 district_aoi.csv가 'matched'로
    # 바뀌면 자동으로 다시 대상에 포함되고, 이 구역들도 반드시 받아야
    # 한다면 pending_keys()에서 `- no_aoi_keys()`를 빼면 된다.
    path = Path(data_path("district_aoi"))
    if not path.exists():
        return set()
    aoi = pd.read_csv(path)
    failed = aoi[aoi["aoi_match_status"].astype(str).str.strip().str.lower() == "failed"]
    return {analysis_key(row) for _, row in failed.iterrows()}


def main() -> int:
    skipped = sorted(no_aoi_keys())
    if skipped:
        print(f"Track B: {len(skipped)} district(s) have no AOI (match failed) "
              f"and cannot be downloaded; not retried: {', '.join(skipped)}",
              file=sys.stderr)
    for key in pending_keys():
        print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
