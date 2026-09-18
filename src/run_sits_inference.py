"""Run SITS-Extreme-VAE inference locally on completed CVND HDF5 patches.

The HDF5 inputs are never deleted. A file with a sibling .blocks.json is
still being downloaded and is skipped. Each completed input produces two
artifacts:
  data/cache/district/sits_scores/<cache_stem(event_district_id)>.npz
      per-tile detail (score and areas per 64x64 tile), for compare_tracks.py
      and for re-deriving the district numbers under another gate
  data/results/district_sits_measurements.csv
      one row of district-level measured values (sits_measure.py), upserted,
      which is what merge_results.py reads

The measurement is a table row first: losing the NPZ must not lose hours of
download and inference, and a re-merge must not depend on the archives.

Scores use the encoder mean (no sampling), so batch size, device and
resumption change them only by floating-point rounding. NDWI areas are counted only on usable pixels
(eligible, inside the AOI, clear in every timestep, observed pre and post) and
converted with each tile's pixel area, under the same flood_spec.SPEC as Track
A. S1 new water is counted on the same usable pixels with the Otsu threshold
Track B recorded (Track A's function on the same grid), which makes it S1's
paired value for the SITS footprint; WorldCover strata are counted alongside.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from functools import wraps
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

import h5py
import numpy as np
from tqdm import tqdm

try:
    import torch
    import torch.nn.functional as F
except ImportError:  # area/QA helpers stay importable for audits and tests
    torch = F = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataclasses import dataclass  # noqa: E402

import sits_measure  # noqa: E402
from cvnd_layout import ROOT, data_path  # noqa: E402

try:    # CVND_SITS_CHECKPOINT lives in .env like the other machine-local settings
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv(ROOT / ".env")   # never overrides a variable already exported

from district_keys import cache_stem, key_from_stem  # noqa: E402
from flood_spec import (H5_LAYOUT_VERSION, SPEC, SPEC_VERSION,  # noqa: E402
                        ndwi_new_water, s1_new_water)

SITS_NORM = 10000.0   # H5 reflectance is uint16 DN = reflectance × 10,000
MEASUREMENT_DATASETS = ("mask", "ndwi_ref", "s1_ref", "landcover", "pixel_area_m2",
                        "block_id", "block_stats")


class StaleSpecError(ValueError):
    """The H5 was prepared under another measurement spec or old layout."""


PATCH_DIR = data_path("district_sits_patches")
SCORE_DIR = data_path("district_sits_scores")
INFERENCE_LOCK = SCORE_DIR / ".inference.lock"
MEASUREMENT_CSV = Path(sits_measure.MEASUREMENT_CSV)

# Where a clone looks for the checkpoint, in order. Nothing here is specific to
# one machine: an explicit --checkpoint, then the environment variable a clone
# is expected to set, then the documented convention inside and beside the
# repository. The file itself is never downloaded by the pipeline.
CHECKPOINT_ENV = "CVND_SITS_CHECKPOINT"
CHECKPOINT_SUBDIR = Path("SITS-ExtremeEvents-main") / "checkpoints" / "ravaen"
UPSTREAM_URL = "https://github.com/hfangcat/SITS-ExtremeEvents"

# Official SITS-Extreme-VAE RaVAEn checkpoints stored in the local upstream tree.
CHECKPOINT_SHA256 = {
    "checkpoint_vae_contrastive_42.pth": (
        "e8b819eb68d03a293b566321e4e5457b146903a97e3d08f837233a06f6886d2d"
    ),
    "checkpoint_vae_contrastive_43.pth": (
        "2442a3424bce0901226faf375626843b8e8cf7d85965a31ba119410b7152aebf"
    ),
    "checkpoint_vae_contrastive_44.pth": (
        "941b8f8c004a075e8796f7a120ea20067250451d7f785d1fc49fe91de7631973"
    ),
}
UPSTREAM_COMMIT = "637423d6370a31701612fc258782615c0c82e4e9"

# Published RaVAEn RGB normalization. CVND stores reflectance divided by
# 10,000, so inference converts RGB back to the original DN scale first.
RGB_MEAN = np.array([834.3116, 1000.4049, 1154.5111], dtype=np.float32)
RGB_STD = np.array([703.7989, 636.1837, 641.6929], dtype=np.float32)

MODEL_CONFIG = {
    "datasets": {"img_size": [64, 64], "in_chans": 3},
    "encoder": {
        "patch_size": 8,
        "embed_dim": 256,
        "depth": 4,
        "num_heads": 8,
        "mlp_ratio": 4,
        "qkv_bias": True,
    },
    "decoder": {
        "d_model": 256,
        "nhead": 8,
        "dim_feedforward": 1024,
        "dropout": 0.1,
        "activation": "relu",
        "normalize_before": False,
        "use_self_attn": False,
        "num_layers": 4,
        "return_intermediate": False,
    },
    "upsampling_layer": {"num_layers": 3},
    "latent_dim": 256,
    "losses": {"types": ["loss_recon_output", "loss_kl_divergence", "loss_z"]},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def with_inference_lock(function):
    """Serialize watcher, wrapper, and manually launched inference runs."""
    @wraps(function)
    def locked(*args, **kwargs):
        SCORE_DIR.mkdir(parents=True, exist_ok=True)
        if fcntl is None:
            return function(*args, **kwargs)
        with INFERENCE_LOCK.open("w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                return function(*args, **kwargs)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return locked


def checkpoint_candidates(explicit: Path | str | None = None,
                          environment: str | None = None) -> list[Path]:
    """Every path a checkpoint is looked for, in order, for this clone.

    A directory (given by --checkpoint, by ``CVND_SITS_CHECKPOINT`` or by
    convention) contributes the verified file names it may contain.
    """
    roots: list[Path] = []
    if explicit:
        roots.append(Path(explicit))
    environment = os.environ.get(CHECKPOINT_ENV) if environment is None else environment
    if environment:
        roots.append(Path(environment))
    roots.append(ROOT / CHECKPOINT_SUBDIR)
    roots.append(ROOT.parent / CHECKPOINT_SUBDIR)

    candidates: list[Path] = []
    for root in roots:
        # A path that names a file is tried as given, even when it does not
        # exist, so the error message repeats what the caller actually asked for.
        entries = ([root / name for name in CHECKPOINT_SHA256]
                   if root.is_dir() or not root.suffix else [root])
        for entry in entries:
            if entry not in candidates:
                candidates.append(entry)
    return candidates


def resolve_checkpoint(explicit: Path | str | None = None,
                       environment: str | None = None) -> Path:
    """First existing checkpoint among ``checkpoint_candidates``.

    Raises with every path tried, so a clone can see what to set instead of
    guessing which machine's layout the code assumes.
    """
    candidates = checkpoint_candidates(explicit, environment)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    tried = "\n  ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        "No SITS-Extreme-VAE checkpoint found. Tried:\n  "
        f"{tried}\n"
        f"Expected one of: {', '.join(sorted(CHECKPOINT_SHA256))}\n"
        f"Obtain them from {UPSTREAM_URL} (upstream commit {UPSTREAM_COMMIT}), "
        f"then either put the file under {CHECKPOINT_SUBDIR.as_posix()}/ or point "
        f"{CHECKPOINT_ENV} at the file or its directory, e.g. "
        f"{CHECKPOINT_ENV}=/path/to/checkpoints/ravaen. "
        "--checkpoint overrides both."
    )


def ensure_checkpoint(
    path: Path, *, offline: bool = False, expected_sha256: str | None = None
) -> Path:
    """Require and verify a checkpoint from the local upstream repository.

    A file name outside the verified table is rejected unless the caller
    supplies the expected SHA-256 explicitly.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Local SITS checkpoint not found: {path}. Put it under "
            f"{CHECKPOINT_SUBDIR.as_posix()}/, set {CHECKPOINT_ENV}, or pass "
            f"--checkpoint. Source: {UPSTREAM_URL} (commit {UPSTREAM_COMMIT})."
        )

    expected = expected_sha256 or CHECKPOINT_SHA256.get(path.name)
    if expected is None:
        raise RuntimeError(
            f"Unverified SITS checkpoint name {path.name!r}; expected one of "
            f"{sorted(CHECKPOINT_SHA256)} or pass --expected-sha256"
        )
    actual = sha256_file(path)
    if actual != expected.lower():
        raise RuntimeError(
            f"SITS checkpoint hash mismatch: expected {expected}, got {actual}"
        )
    return path


def build_local_model(checkpoint: Path, device: torch.device) -> torch.nn.Module:
    from sits_extreme_vendor.vae_variants import build_model

    model, _criterion = build_model(MODEL_CONFIG)
    try:
        payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    except TypeError:
        payload = torch.load(checkpoint, map_location="cpu")
    state = payload.get("model_state_dict", payload)
    state = {
        (key[7:] if key.startswith("module.") else key): value
        for key, value in state.items()
    }
    model.load_state_dict(state, strict=True)
    model.eval().to(device)
    return model


def complete_h5_files(
    patch_dir: Path, event_ids: set[str] | None = None
) -> list[Path]:
    files = []
    for path in sorted(patch_dir.glob("*.h5")):
        if event_ids and key_from_stem(path.stem) not in event_ids:
            continue
        block_checkpoint = Path(str(path) + ".blocks.json")
        if block_checkpoint.exists():
            print(f"SKIP partial H5 (download can resume): {path.name}")
            continue
        files.append(path)
    return files


def score_cache_is_current(input_path: Path, output_path: Path,
                           checkpoint_hash: str) -> bool:
    """A score cache is reusable only for these exact patches/model/spec/layout."""
    if not output_path.exists():
        return False
    try:
        with np.load(output_path, allow_pickle=False) as archive:
            expected = {
                "patches_sha256": sha256_file(input_path),
                "weights_sha256": checkpoint_hash,
                "checkpoint_sha256": checkpoint_hash,
                "spec_version": SPEC_VERSION,
                "layout_version": H5_LAYOUT_VERSION,
            }
            return all(field in archive and str(np.asarray(archive[field]).item()) == value
                       for field, value in expected.items())
    except (OSError, ValueError, KeyError):
        return False


def _band_indices(hdf: h5py.File) -> list[int]:
    """RGB band positions for the model input."""
    raw = hdf["meta"].attrs.get("bands", "")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    bands = [item.strip() for item in str(raw).split(",") if item.strip()]
    # New H5 files store RGB only; legacy files may still include B8.  The
    # neural network consumes RGB, while B8 is retained only in legacy
    # metadata/validity semantics and is not read by the model.
    required = ["B4", "B3", "B2"]
    missing = [band for band in required if band not in bands]
    if missing:
        raise ValueError(f"H5 is missing required bands {missing}: found {bands}")
    return [bands.index(band) for band in ["B4", "B3", "B2"]]


def _attr_text(attrs, name: str) -> str:
    value = attrs.get(name, "")
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


@dataclass(frozen=True)
class Layout:
    ndwi_nodata: int
    ndwi_scale: float
    s1_nodata: int
    s1_scale: float
    s1_threshold_db: float | None
    builtup: int
    cropland: int


def check_measurement_layout(hdf: h5py.File) -> Layout:
    """Return the measurement-layer encoding or raise StaleSpecError."""
    attrs = hdf["meta"].attrs
    version = _attr_text(attrs, "spec_version")
    layout = _attr_text(attrs, "layout_version")
    missing = [n for n in MEASUREMENT_DATASETS if n not in hdf]
    if version != SPEC_VERSION or layout != H5_LAYOUT_VERSION or missing:
        raise StaleSpecError(
            f"spec {version or 'missing'} (expected {SPEC_VERSION}), layout "
            f"{layout or 'missing'} (expected {H5_LAYOUT_VERSION}); missing datasets "
            f"{missing}; rerun satellite.py --track B"
        )
    threshold = float(attrs.get("s1_threshold_db", np.nan))
    return Layout(int(attrs["ndwi_nodata"]), float(attrs["ndwi_scale"]),
                  int(attrs["s1_nodata"]), float(attrs["s1_scale"]),
                  threshold if np.isfinite(threshold) else None,
                  SPEC.worldcover_builtup, SPEC.worldcover_cropland)


def usable_pixels(ndwi_ref: np.ndarray, mask: np.ndarray, nodata: int) -> np.ndarray:
    """Eligible, inside the AOI, clear in every timestep, NDWI observed pre and post."""
    return (
        (mask & 1).astype(bool)
        & (mask & 2).astype(bool)
        & (mask & 4).astype(bool)
        & (ndwi_ref[:, 0] != nodata)
        & (ndwi_ref[:, 1] != nodata)
    )


def _ndwi_counts(
    ndwi_ref: np.ndarray, mask: np.ndarray, nodata: int, scale: float = 10000.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-patch (pre water, post water, new water, usable) pixel counts.

    ``ndwi_ref`` is (N, 2, H, W) pre/post NDWI ×scale; ``mask`` bit0 = eligible,
    bit1 = clear in every model timestep, bit2 = inside the AOI. Every count is
    restricted to usable pixels so the definition matches Track A's eligible
    new water.
    """
    pre, post = ndwi_ref[:, 0], ndwi_ref[:, 1]
    cut = SPEC.ndwi_water_gt * scale
    usable = usable_pixels(ndwi_ref, mask, nodata)
    new_water, _observed = ndwi_new_water(pre, post, nodata, scale)
    axes = (1, 2)
    return (
        ((pre > cut) & usable).sum(axis=axes, dtype=np.int32),
        ((post > cut) & usable).sum(axis=axes, dtype=np.int32),
        (new_water & usable).sum(axis=axes, dtype=np.int32),
        usable.sum(axis=axes, dtype=np.int32),
    )


PAIRED_COUNTS = ("s1_flood", "s1_flood_tile", "both_flood", "builtup_px", "cropland_px",
                 "ndwi_flood_builtup", "s1_flood_builtup")


def _paired_counts(ndwi_ref, s1_ref, mask, landcover, layout: Layout) -> dict:
    """Per-patch S1 and land-cover pixel counts paired with the NDWI counts.

    s1_flood / both_flood / strata are on the usable pixels (the paired
    footprint C); s1_flood_tile is S1 new water on every eligible AOI pixel of
    the tile, whatever the optical validity.
    """
    usable = usable_pixels(ndwi_ref, mask, layout.ndwi_nodata)
    ndwi_new, _ = ndwi_new_water(ndwi_ref[:, 0], ndwi_ref[:, 1],
                                 layout.ndwi_nodata, layout.ndwi_scale)
    s1_new = s1_new_water(s1_ref[:, 0], s1_ref[:, 1], layout.s1_nodata,
                          layout.s1_scale, layout.s1_threshold_db)
    eligible_inside = (mask & 1).astype(bool) & (mask & 4).astype(bool)
    builtup, cropland = landcover == layout.builtup, landcover == layout.cropland
    axes = (1, 2)

    def count(pixels):
        return pixels.sum(axis=axes, dtype=np.int32)

    return {
        "s1_flood": count(s1_new & usable),
        "s1_flood_tile": count(s1_new & eligible_inside),
        "both_flood": count(s1_new & ndwi_new & usable),
        "builtup_px": count(builtup & usable),
        "cropland_px": count(cropland & usable),
        "ndwi_flood_builtup": count(ndwi_new & usable & builtup),
        "s1_flood_builtup": count(s1_new & usable & builtup),
    }


def _px_to_km2(pixels: np.ndarray, pixel_area_m2: np.ndarray) -> np.ndarray:
    return pixels.astype(np.float64) * pixel_area_m2.astype(np.float64) / 1e6


def _normalize_rgb(array: np.ndarray, rgb_indices: list[int]) -> torch.Tensor:
    """RaVAEn normalization of uint16 DN, clipped to the unit-reflectance range."""
    rgb_dn = np.clip(array[:, rgb_indices].astype(np.float32), 0, SITS_NORM)
    rgb_dn = (
        rgb_dn - RGB_MEAN[None, :, None, None]
    ) / RGB_STD[None, :, None, None]
    return torch.from_numpy(np.ascontiguousarray(rgb_dn, dtype=np.float32))


def _latent(model: torch.nn.Module, image: torch.Tensor) -> torch.Tensor:
    """Posterior mean. A reparameterized sample would make scores, the Youden
    gate and therefore source routing depend on batch size and device."""
    embedding, _position_encodings = model.encoder(image)
    embedding = torch.flatten(embedding, start_dim=1)
    return model.fc_mu(embedding)


def infer_h5(
    input_path: Path,
    output_path: Path,
    model: torch.nn.Module,
    device: torch.device,
    batch_size: int,
    checkpoint_hash: str,
    patches_hash: str | None = None,
    measurements_path: Path | str | None = None,
) -> int:
    """Score one district's patches; write the NPZ and, when asked, its table row.

    ``measurements_path`` is explicit so only the pipeline writes the shared
    measurement table; callers that just want scores (tests, audits) do not.
    """
    score_parts: list[np.ndarray] = []
    count_parts: list[tuple[np.ndarray, ...]] = []
    paired_parts: list[dict] = []

    with h5py.File(input_path, "r") as hdf:
        layout = check_measurement_layout(hdf)
        pre_ds, post_ds = hdf["pre"], hdf["post"]
        n_pre = SPEC.sits_n_pre
        tile_datasets = ("post", "mask", "ndwi_ref", "s1_ref", "landcover",
                         "pixel_area_m2", "block_id", "coords")
        if (
            pre_ds.shape[1] != n_pre
            or post_ds.shape[1] != 1
            or any(hdf[name].shape[0] != pre_ds.shape[0] for name in tile_datasets)
        ):
            raise ValueError(
                f"Unexpected H5 dimensions: pre={pre_ds.shape}, "
                + ", ".join(f"{name}={hdf[name].shape}" for name in tile_datasets)
            )
        rgb_indices = _band_indices(hdf)
        total = int(pre_ds.shape[0])
        pixel_area_m2 = hdf["pixel_area_m2"][:]

        with torch.inference_mode():
            iterator = range(0, total, batch_size)
            for start in tqdm(
                iterator, desc=f"infer {input_path.stem}", unit="batch"
            ):
                stop = min(start + batch_size, total)
                pre = pre_ds[start:stop]
                post = post_ds[start:stop, 0]
                ndwi_ref, mask = hdf["ndwi_ref"][start:stop], hdf["mask"][start:stop]
                count_parts.append(_ndwi_counts(
                    ndwi_ref, mask, layout.ndwi_nodata, layout.ndwi_scale,
                ))
                paired_parts.append(_paired_counts(
                    ndwi_ref, hdf["s1_ref"][start:stop], mask,
                    hdf["landcover"][start:stop], layout,
                ))

                tensors = [
                    _normalize_rgb(pre[:, timestep], rgb_indices).to(device)
                    for timestep in range(n_pre)
                ]
                post_tensor = _normalize_rgb(post, rgb_indices).to(device)
                post_latent = _latent(model, post_tensor)
                distances = [
                    1.0
                    - torch.abs(
                        F.cosine_similarity(
                            _latent(model, image), post_latent, dim=1
                        )
                    )
                    for image in tensors
                ]
                score = torch.stack(distances, dim=1).mean(dim=1)
                score_parts.append(
                    score.cpu().numpy().astype(np.float32, copy=False)
                )

        coords = hdf["coords"][:]
        block_id = hdf["block_id"][:]
        attrs = hdf["meta"].attrs
        event_id = _attr_text(attrs, "event_id") or input_path.stem
        event_district_id = _attr_text(attrs, "event_district_id")
        source_record_id = _attr_text(attrs, "source_record_id")
        state = _attr_text(attrs, "state")
        district = _attr_text(attrs, "district")
        start_date = _attr_text(attrs, "start_date")
        geometry_id = _attr_text(attrs, "geometry_id")
        # H5 provenance merge_results needs to reject a stale tile pre-screen
        # without reopening the H5; stored in the measurement row only.
        h5_provenance = {"bands": _attr_text(attrs, "bands").replace(" ", ""),
                         "tile_selection_rule": _attr_text(attrs, "tile_selection_rule")}

    scores = (
        np.concatenate(score_parts)
        if score_parts
        else np.empty(0, dtype=np.float32)
    )
    if count_parts:
        ndwi_pre, ndwi_during, ndwi_flood, usable_px = (
            np.concatenate(parts) for parts in zip(*count_parts)
        )
        paired = {name: np.concatenate([part[name] for part in paired_parts])
                  for name in PAIRED_COUNTS}
    else:
        ndwi_pre = ndwi_during = ndwi_flood = usable_px = np.empty(0, dtype=np.int32)
        paired = {name: np.empty(0, dtype=np.int32) for name in PAIRED_COUNTS}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if patches_hash is None:
        patches_hash = sha256_file(input_path)
    payload = dict(
        scores=scores,
        ndwi_pre=ndwi_pre,
        ndwi_during=ndwi_during,
        ndwi_flood=ndwi_flood,
        usable_px=usable_px,
        ndwi_pre_km2=_px_to_km2(ndwi_pre, pixel_area_m2),
        ndwi_during_km2=_px_to_km2(ndwi_during, pixel_area_m2),
        ndwi_flood_km2=_px_to_km2(ndwi_flood, pixel_area_m2),
        tile_area_km2=_px_to_km2(
            np.full(total, SPEC.sits_patch_pixels), pixel_area_m2
        ),
        usable_km2=_px_to_km2(usable_px, pixel_area_m2),
        **paired,
        s1_flood_km2=_px_to_km2(paired["s1_flood"], pixel_area_m2),
        s1_flood_tile_km2=_px_to_km2(paired["s1_flood_tile"], pixel_area_m2),
        s1_threshold_db=np.array(
            np.nan if layout.s1_threshold_db is None else layout.s1_threshold_db),
        block_id=block_id,
        spec_version=np.array(SPEC_VERSION),
        layout_version=np.array(H5_LAYOUT_VERSION),
        latent=np.array("mu"),
        coords=coords,
        event_id=np.array(event_id),
        event_district_id=np.array(event_district_id),
        source_record_id=np.array(source_record_id),
        state=np.array(state),
        district=np.array(district),
        start_date=np.array(start_date),
        geometry_id=np.array(geometry_id),
        model=np.array("SITS-Extreme-VAE"),
        model_id=np.array("SITS-Extreme-VAE-RaVAEn-seed42"),
        checkpoint_sha256=np.array(checkpoint_hash),
        weights_sha256=np.array(checkpoint_hash),
        patches_sha256=np.array(patches_hash),
        upstream_commit=np.array(UPSTREAM_COMMIT),
    )
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **payload)
    temporary.replace(output_path)
    if measurements_path is not None:
        # The same aggregation the merge would have done, stored once so the
        # merge never has to open this archive again.
        row = sits_measure.measurement_row(payload, provenance=h5_provenance)
        sits_measure.upsert_measurements([row], measurements_path)
        print(f"    measurement -> {measurements_path} "
              f"({row['sits_method'] or 'no usable tiles'}, {row['n_tiles']} tiles)")
    return len(scores)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", nargs="*", help="Only infer selected event IDs")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help=f"Checkpoint file or directory; else ${CHECKPOINT_ENV}, else "
             f"{CHECKPOINT_SUBDIR.as_posix()}/ inside or beside the repository",
    )
    parser.add_argument(
        "--expected-sha256",
        help="Verify a checkpoint whose file name is not in the built-in table",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--device", choices=["auto", "cuda", "cpu"], default="auto"
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Never download a missing checkpoint",
    )
    return parser.parse_args()


def missing_input_reasons(event_ids, patch_dir: Path | None = None,
                          score_dir: Path | None = None) -> dict[str, str]:
    """Why each requested district has no completed H5 to infer."""
    patch_dir = Path(patch_dir or PATCH_DIR)
    score_dir = Path(score_dir or SCORE_DIR)
    reasons = {}
    for key in sorted(event_ids):
        h5_path = patch_dir / f"{cache_stem(key)}.h5"
        if Path(str(h5_path) + ".blocks.json").exists():
            reasons[key] = f"partial download, resume satellite.py --track B ({h5_path.name}.blocks.json)"
        elif not h5_path.exists():
            reasons[key] = f"no patch file {h5_path.name}; run satellite.py --track B for it"
        elif (score_dir / f"{h5_path.stem}.npz").exists():
            reasons[key] = "already scored; pass --overwrite to redo it"
        else:
            reasons[key] = "patch file found but not selected; check the spec it was prepared under"
    return reasons


@with_inference_lock
def main() -> int:
    args = parse_args()
    # Resolved and verified before any early return: a run that finds nothing to
    # do must still fail loudly when the checkpoint this machine would use is
    # missing, instead of exiting 0 and looking like a completed Track B.
    try:
        checkpoint = ensure_checkpoint(
            resolve_checkpoint(args.checkpoint),
            offline=args.offline,
            expected_sha256=args.expected_sha256,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"SITS checkpoint: {checkpoint}")
    checkpoint_hash = sha256_file(checkpoint)

    event_ids = set(args.events) if args.events else None
    inputs = complete_h5_files(PATCH_DIR, event_ids)
    if event_ids and not inputs:
        print(f"No completed H5 input for any of the {len(event_ids)} requested district(s):")
        for key, reason in missing_input_reasons(event_ids).items():
            print(f"  {key}: {reason}")
        return 2
    if not inputs:
        print("No completed H5 files are available for local inference.")
        return 0
    pending = [
        path
        for path in inputs
        if args.overwrite
        or not score_cache_is_current(
            path, SCORE_DIR / f"{path.stem}.npz", checkpoint_hash)
    ]
    if not pending:
        print(
            "No completed H5 files need local inference. "
            "H5 inputs were kept unchanged."
        )
        return 0

    if torch is None:
        raise RuntimeError("SITS inference requires PyTorch (pip install torch)")
    if args.device == "auto":
        device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
    else:
        device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA requested but PyTorch cannot access a CUDA device"
        )
    print(f"Local SITS inference device: {device}")
    model = build_local_model(checkpoint, device)
    completed, stale = 0, []
    for input_path in pending:
        output_path = SCORE_DIR / f"{input_path.stem}.npz"
        try:
            count = infer_h5(
                input_path,
                output_path,
                model,
                device,
                args.batch_size,
                checkpoint_hash,
                patches_hash=sha256_file(input_path),
                measurements_path=MEASUREMENT_CSV,
            )
        except StaleSpecError as exc:
            print(f"STALE SPEC {input_path.name}: {exc}")
            stale.append(input_path.name)
            continue
        completed += 1
        print(
            f"Saved {output_path} ({count} patches); kept {input_path}"
        )

    print(f"Local SITS inference complete: {completed} event(s)")
    if stale:
        print(f"Skipped {len(stale)} H5 file(s) prepared under another spec")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
