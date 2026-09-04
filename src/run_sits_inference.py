"""Run SITS-Extreme-VAE inference locally on completed CVND HDF5 patches.

The HDF5 inputs are never deleted. A file with a sibling .blocks.json is
still being downloaded and is skipped. Each completed input produces one
data/cache/sits_scores/<event_id>.npz file consumed by merge_results.py.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import h5py
import numpy as np
import torch
import torch.nn.functional as F
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cvnd_layout import ROOT, data_path  # noqa: E402
from sits_extreme_vendor.vae_variants import build_model  # noqa: E402


PATCH_DIR = data_path("sits_patches")
SCORE_DIR = data_path("sits_scores")
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


def ensure_checkpoint(path: Path, *, offline: bool = False) -> Path:
    """Require and verify a checkpoint from the local upstream repository."""
    if not path.exists():
        raise FileNotFoundError(
            "Local SITS checkpoint not found: "
            f"{path}. Put it under SITS-ExtremeEvents-main/checkpoints/ravaen/ "
            "or pass --checkpoint."
        )

    actual = sha256_file(path)
    expected = CHECKPOINT_SHA256.get(path.name)
    if expected is not None and actual != expected:
        raise RuntimeError(
            f"SITS checkpoint hash mismatch: expected {expected}, got {actual}"
        )
    return path


def build_local_model(checkpoint: Path, device: torch.device) -> torch.nn.Module:
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
        if event_ids and path.stem not in event_ids:
            continue
        block_checkpoint = Path(str(path) + ".blocks.json")
        if block_checkpoint.exists():
            print(f"SKIP partial H5 (download can resume): {path.name}")
            continue
        files.append(path)
    return files


def _band_indices(hdf: h5py.File) -> tuple[list[int], int, int]:
    raw = hdf["meta"].attrs.get("bands", "")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    bands = [item.strip() for item in str(raw).split(",") if item.strip()]
    required = ["B4", "B3", "B2", "B8"]
    missing = [band for band in required if band not in bands]
    if missing:
        raise ValueError(f"H5 is missing required bands {missing}: found {bands}")
    rgb = [bands.index(band) for band in ["B4", "B3", "B2"]]
    return rgb, bands.index("B3"), bands.index("B8")


def _ndwi_counts(
    pre: np.ndarray, post: np.ndarray, green_idx: int, nir_idx: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return per-patch pre-water, post-water and new-water pixel counts."""
    eps = np.float32(1e-6)
    pre_g, pre_n = pre[:, :, green_idx], pre[:, :, nir_idx]
    post_g, post_n = post[:, green_idx], post[:, nir_idx]
    pre_ndwi_each = (pre_g - pre_n) / (pre_g + pre_n + eps)
    pre_ndwi = np.median(pre_ndwi_each, axis=1)
    post_ndwi = (post_g - post_n) / (post_g + post_n + eps)
    pre_water = (pre_ndwi > 0).sum(axis=(1, 2), dtype=np.int32)
    during_water = (post_ndwi > 0).sum(axis=(1, 2), dtype=np.int32)
    new_water = ((post_ndwi > 0) & (pre_ndwi <= 0)).sum(
        axis=(1, 2), dtype=np.int32
    )
    return pre_water, during_water, new_water


def _normalize_rgb(array: np.ndarray, rgb_indices: list[int]) -> torch.Tensor:
    rgb_dn = array[:, rgb_indices] * np.float32(10000.0)
    rgb_dn = (
        rgb_dn - RGB_MEAN[None, :, None, None]
    ) / RGB_STD[None, :, None, None]
    return torch.from_numpy(np.ascontiguousarray(rgb_dn, dtype=np.float32))


def _latent(model: torch.nn.Module, image: torch.Tensor) -> torch.Tensor:
    embedding, _position_encodings = model.encoder(image)
    embedding = torch.flatten(embedding, start_dim=1)
    mu = model.fc_mu(embedding)
    log_var = model.fc_var(embedding)
    return model.reparameterize(mu, log_var)


def infer_h5(
    input_path: Path,
    output_path: Path,
    model: torch.nn.Module,
    device: torch.device,
    batch_size: int,
    checkpoint_hash: str,
) -> int:
    score_parts: list[np.ndarray] = []
    pre_parts: list[np.ndarray] = []
    during_parts: list[np.ndarray] = []
    flood_parts: list[np.ndarray] = []

    with h5py.File(input_path, "r") as hdf:
        pre_ds, post_ds = hdf["pre"], hdf["post"]
        if (
            pre_ds.shape[0] != post_ds.shape[0]
            or pre_ds.shape[1] != 4
            or post_ds.shape[1] != 1
        ):
            raise ValueError(
                f"Unexpected H5 time dimensions: pre={pre_ds.shape}, "
                f"post={post_ds.shape}"
            )
        rgb_indices, green_idx, nir_idx = _band_indices(hdf)
        total = int(pre_ds.shape[0])

        torch.manual_seed(42)
        if device.type == "cuda":
            torch.cuda.manual_seed_all(42)

        with torch.inference_mode():
            iterator = range(0, total, batch_size)
            for start in tqdm(
                iterator, desc=f"infer {input_path.stem}", unit="batch"
            ):
                stop = min(start + batch_size, total)
                pre = pre_ds[start:stop]
                post = post_ds[start:stop, 0]
                p, d, f = _ndwi_counts(pre, post, green_idx, nir_idx)
                pre_parts.append(p)
                during_parts.append(d)
                flood_parts.append(f)

                tensors = [
                    _normalize_rgb(pre[:, timestep], rgb_indices).to(device)
                    for timestep in range(4)
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
        event_id = str(
            hdf["meta"].attrs.get("event_id", input_path.stem)
        )

    scores = (
        np.concatenate(score_parts)
        if score_parts
        else np.empty(0, dtype=np.float32)
    )
    ndwi_pre = (
        np.concatenate(pre_parts)
        if pre_parts
        else np.empty(0, dtype=np.int32)
    )
    ndwi_during = (
        np.concatenate(during_parts)
        if during_parts
        else np.empty(0, dtype=np.int32)
    )
    ndwi_flood = (
        np.concatenate(flood_parts)
        if flood_parts
        else np.empty(0, dtype=np.int32)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
            scores=scores,
            ndwi_pre=ndwi_pre,
            ndwi_during=ndwi_during,
            ndwi_flood=ndwi_flood,
            coords=coords,
            event_id=np.array(event_id),
            model=np.array("SITS-Extreme-VAE"),
            checkpoint_sha256=np.array(checkpoint_hash),
            upstream_commit=np.array(UPSTREAM_COMMIT),
        )
    temporary.replace(output_path)
    return len(scores)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", nargs="*", help="Only infer selected event IDs")
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
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

    checkpoint = ensure_checkpoint(args.checkpoint, offline=args.offline)
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

    completed = 0
    for input_path in pending:
        output_path = SCORE_DIR / f"{input_path.stem}.npz"
        count = infer_h5(
            input_path,
            output_path,
            model,
            device,
            args.batch_size,
            checkpoint_hash,
        )
        completed += 1
        print(
            f"Saved {output_path} ({count} patches); kept {input_path}"
        )

    print(f"Local SITS inference complete: {completed} event(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
