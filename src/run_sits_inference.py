"""Run SITS-Extreme-VAE inference locally on completed CVND HDF5 patches.

The HDF5 inputs are never deleted. A file with a sibling .blocks.json is
still being downloaded and is skipped. Each completed input produces one
`data/cache/district/sits_scores/<cache_stem(event_district_id)>.npz` file
consumed by `merge_results.py`.

Scores use the encoder mean (no sampling), so batch size, device and
resumption change them only by floating-point rounding. NDWI areas are counted only on usable pixels
(eligible, clear in every timestep, observed pre and post) and converted with
each tile's pixel area, under the same flood_spec.SPEC as Track A.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import h5py
import numpy as np
from tqdm import tqdm

try:
    import torch
    import torch.nn.functional as F
except ImportError:  # area/QA helpers stay importable for audits and tests
    torch = F = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cvnd_layout import ROOT, data_path  # noqa: E402
from district_keys import key_from_stem  # noqa: E402
from flood_spec import SPEC, SPEC_VERSION  # noqa: E402


class StaleSpecError(ValueError):
    """The H5 was prepared under another measurement spec or old layout."""


PATCH_DIR = data_path("district_sits_patches")
SCORE_DIR = data_path("district_sits_scores")
CHECKPOINT = (
    ROOT
    / "SITS-ExtremeEvents-main"
    / "checkpoints"
    / "ravaen"
    / "checkpoint_vae_contrastive_42.pth"
)

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


def ensure_checkpoint(
    path: Path, *, offline: bool = False, expected_sha256: str | None = None
) -> Path:
    """Require and verify a checkpoint from the local upstream repository.

    A file name outside the verified table is rejected unless the caller
    supplies the expected SHA-256 explicitly.
    """
    if not path.exists():
        raise FileNotFoundError(
            "Local SITS checkpoint not found: "
            f"{path}. Put it under SITS-ExtremeEvents-main/checkpoints/ravaen/ "
            "or pass --checkpoint."
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


def _band_indices(hdf: h5py.File) -> list[int]:
    """RGB band positions for the model input."""
    raw = hdf["meta"].attrs.get("bands", "")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    bands = [item.strip() for item in str(raw).split(",") if item.strip()]
    required = ["B4", "B3", "B2", "B8"]
    missing = [band for band in required if band not in bands]
    if missing:
        raise ValueError(f"H5 is missing required bands {missing}: found {bands}")
    return [bands.index(band) for band in ["B4", "B3", "B2"]]


def check_measurement_layout(hdf: h5py.File) -> tuple[int, float]:
    """Return (ndwi_nodata, ndwi_scale) or raise StaleSpecError."""
    attrs = hdf["meta"].attrs
    version = attrs.get("spec_version", "")
    if isinstance(version, bytes):
        version = version.decode("utf-8")
    missing = [n for n in ("mask", "ndwi_ref", "pixel_area_m2") if n not in hdf]
    if str(version) != SPEC_VERSION or missing:
        raise StaleSpecError(
            f"spec {version or 'missing'} (expected {SPEC_VERSION}); "
            f"missing datasets {missing}; rerun satellite.py --track B"
        )
    return int(attrs["ndwi_nodata"]), float(attrs["ndwi_scale"])


def _ndwi_counts(
    ndwi_ref: np.ndarray, mask: np.ndarray, nodata: int, scale: float = 10000.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-patch (pre water, post water, new water, usable) pixel counts.

    ``ndwi_ref`` is (N, 2, H, W) pre/post NDWI ×scale; ``mask`` bit0 = eligible,
    bit1 = clear in every model timestep. Every count is restricted to usable
    pixels so the definition matches Track A's eligible new water.
    """
    pre, post = ndwi_ref[:, 0], ndwi_ref[:, 1]
    cut = SPEC.ndwi_water_gt * scale
    usable = (
        (mask & 1).astype(bool)
        & (mask & 2).astype(bool)
        & (pre != nodata)
        & (post != nodata)
    )
    pre_water = (pre > cut) & usable
    during = (post > cut) & usable
    new_water = during & (pre <= cut)
    axes = (1, 2)
    return (
        pre_water.sum(axis=axes, dtype=np.int32),
        during.sum(axis=axes, dtype=np.int32),
        new_water.sum(axis=axes, dtype=np.int32),
        usable.sum(axis=axes, dtype=np.int32),
    )


def _px_to_km2(pixels: np.ndarray, pixel_area_m2: np.ndarray) -> np.ndarray:
    return pixels.astype(np.float64) * pixel_area_m2.astype(np.float64) / 1e6


def _normalize_rgb(array: np.ndarray, rgb_indices: list[int]) -> torch.Tensor:
    rgb_dn = array[:, rgb_indices] * np.float32(10000.0)
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
) -> int:
    score_parts: list[np.ndarray] = []
    count_parts: list[tuple[np.ndarray, ...]] = []

    with h5py.File(input_path, "r") as hdf:
        nodata, ndwi_scale = check_measurement_layout(hdf)
        pre_ds, post_ds = hdf["pre"], hdf["post"]
        n_pre = SPEC.sits_n_pre
        if (
            pre_ds.shape[0] != post_ds.shape[0]
            or pre_ds.shape[1] != n_pre
            or post_ds.shape[1] != 1
            or hdf["mask"].shape[0] != pre_ds.shape[0]
            or hdf["ndwi_ref"].shape[0] != pre_ds.shape[0]
        ):
            raise ValueError(
                f"Unexpected H5 dimensions: pre={pre_ds.shape}, "
                f"post={post_ds.shape}, mask={hdf['mask'].shape}"
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
                count_parts.append(_ndwi_counts(
                    hdf["ndwi_ref"][start:stop], hdf["mask"][start:stop],
                    nodata, ndwi_scale,
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
        attrs = hdf["meta"].attrs

        def attr_text(name: str) -> str:
            value = attrs.get(name, "")
            if isinstance(value, bytes):
                return value.decode("utf-8")
            return str(value)

        event_id = attr_text("event_id") or input_path.stem
        event_district_id = attr_text("event_district_id")
        source_record_id = attr_text("source_record_id")
        state = attr_text("state")
        district = attr_text("district")
        start_date = attr_text("start_date")
        geometry_id = attr_text("geometry_id")

    scores = (
        np.concatenate(score_parts)
        if score_parts
        else np.empty(0, dtype=np.float32)
    )
    if count_parts:
        ndwi_pre, ndwi_during, ndwi_flood, usable_px = (
            np.concatenate(parts) for parts in zip(*count_parts)
        )
    else:
        ndwi_pre = ndwi_during = ndwi_flood = usable_px = np.empty(0, dtype=np.int32)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if patches_hash is None:
        patches_hash = sha256_file(input_path)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
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
            spec_version=np.array(SPEC_VERSION),
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
    temporary.replace(output_path)
    return len(scores)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", nargs="*", help="Only infer selected event IDs")
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
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


def main() -> int:
    args = parse_args()
    event_ids = set(args.events) if args.events else None
    inputs = complete_h5_files(PATCH_DIR, event_ids)
    pending = [
        path
        for path in inputs
        if args.overwrite
        or not (SCORE_DIR / f"{path.stem}.npz").exists()
    ]
    if not pending:
        print(
            "No completed H5 files need local inference. "
            "H5 inputs were kept unchanged."
        )
        return 0

    if torch is None:
        raise RuntimeError("SITS inference requires PyTorch (pip install torch)")
    checkpoint = ensure_checkpoint(
        args.checkpoint, offline=args.offline, expected_sha256=args.expected_sha256
    )
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
    checkpoint_hash = sha256_file(checkpoint)

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
