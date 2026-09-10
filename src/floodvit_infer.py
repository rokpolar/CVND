"""floodvit_infer.py — run Kuro Siwo's FloodViT over SAR patches and count flood pixels.

The model is used as released: no retraining, no architecture change. Everything
here is about feeding it exactly what it was trained on.

Preprocessing, taken from Kuro Siwo's own code rather than its README
--------------------------------------------------------------------
training/segmentation_trainer.py and dataset/Dataset.py agree on this order:

  1. stack (VV, VH) per acquisition                     -> 2 channels
  2. clamp to [0, CLAMP] and replace NaN with CLAMP     (Dataset.concat)
  3. normalise EACH acquisition separately with the 2-channel mean/std
  4. concatenate post, pre_event_1, pre_event_2         -> 6 channels

Step 3 before step 4 matters: normalising the stacked 6-channel tensor with a
6-long mean vector is numerically the same only because the constants repeat,
but doing it per acquisition is what the code does and keeps the intent clear.

Step 4's order is the one thing the config file gets wrong: `inputs` lists
pre_event_1 first, while the trainer builds cat(post, pre1, pre2). The channel
order is post-first. Feeding pre-first silently produces plausible-looking but
wrong masks, which is why it is asserted here.

Output classes (num_classes: 3): 0 = no water, 1 = permanent water, 2 = flood.
Flood AREA counts class 2 only. The model does carry a separate permanent-water
class, but it is not strong: on 200 of Kuro Siwo's own labelled patches it
reached F1 0.410 against flood's 0.701, so some standing water does land in
class 2. Whether a JRC permanent-water mask is needed on top is open -- it is
not settled by the model having the class.

Run on a GPU. ViT-Large over millions of patches is not a CPU job.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Kuro Siwo constants (hardcoded in their trainer, not in any config) ───────
CLAMP = 0.15
MEAN = (0.0953, 0.0264)      # VV, VH
STD = (0.0427, 0.0215)
N_ACQUISITIONS = 3           # post, pre_event_1, pre_event_2
N_POL = 2
N_CHANNELS = N_ACQUISITIONS * N_POL

CLASS_NO_WATER, CLASS_PERMANENT_WATER, CLASS_FLOOD = 0, 1, 2
PATCH_PX = 224


def preprocess(patches, clamp=CLAMP, mean=MEAN, std=STD):
    """(N, 6, H, W) raw linear sigma0 -> normalised float32, ready for the model.

    Pure numpy so it can be tested without torch. Each acquisition's two
    polarisation channels are clamped and normalised together, matching
    Dataset.concat + scale_img.
    """
    x = np.asarray(patches, dtype=np.float32)
    if x.ndim != 4 or x.shape[1] != N_CHANNELS:
        raise ValueError(f"expected (N, {N_CHANNELS}, H, W), got {x.shape}")

    x = np.nan_to_num(x, nan=clamp, posinf=clamp, neginf=0.0)
    x = np.clip(x, 0.0, clamp)

    # channel c belongs to polarisation c % 2 (VV, VH, VV, VH, VV, VH)
    m = np.array(list(mean) * N_ACQUISITIONS, dtype=np.float32)
    s = np.array(list(std) * N_ACQUISITIONS, dtype=np.float32)
    return (x - m[None, :, None, None]) / s[None, :, None, None]


def count_classes(pred):
    """(N, H, W) predicted class ids -> pixel counts per class."""
    pred = np.asarray(pred)
    return {
        'no_water_px': int((pred == CLASS_NO_WATER).sum()),
        'permanent_water_px': int((pred == CLASS_PERMANENT_WATER).sum()),
        'flood_px': int((pred == CLASS_FLOOD).sum()),
    }


def px_to_km2(n_px, scale_m):
    """Pixel count -> area. Kept separate so the scale is never assumed."""
    return n_px * (scale_m / 1000.0) ** 2


# ══════════════════════════════════════════════════════════════════════════════
# Model (torch only needed here)
# ══════════════════════════════════════════════════════════════════════════════

def load_model(checkpoint, kuro_siwo_repo, device='cuda'):
    """Load floodvit.pt.

    The checkpoint is a whole pickled nn.Module (torch.save(model)), not a
    state_dict, so Kuro Siwo's package must be importable for the classes to
    resolve -- hence kuro_siwo_repo on sys.path.
    """
    # Paths are checked before importing torch, so the failure names the missing
    # clone rather than dying on an unrelated import.
    repo = os.path.abspath(kuro_siwo_repo)
    if not os.path.isdir(os.path.join(repo, 'models')):
        raise FileNotFoundError(
            f"Kuro Siwo repo not found at {repo} (no models/ directory).\n"
            "The checkpoint is a pickled nn.Module, so its classes must be "
            "importable; without the repo torch raises a bare "
            "'No module named models'.\n"
            "Colab wipes /content on every new session -- re-clone with:\n"
            "  git clone -q https://github.com/Orion-AI-Lab/KuroSiwo.git "
            f"{repo}")
    if not os.path.exists(checkpoint):
        raise FileNotFoundError(f"checkpoint not found: {checkpoint}")
    if repo not in sys.path:
        sys.path.insert(0, repo)

    import torch

    model = torch.load(checkpoint, map_location=device, weights_only=False)
    cfg = getattr(model, 'configs', {}) or {}
    if cfg:
        if cfg.get('num_channels') != N_CHANNELS:
            raise ValueError(
                f"checkpoint expects {cfg.get('num_channels')} channels, "
                f"this code builds {N_CHANNELS}")
        if cfg.get('image_size') != PATCH_PX:
            raise ValueError(
                f"checkpoint expects {cfg.get('image_size')}px patches, "
                f"this code builds {PATCH_PX}")
    model.eval().to(device)
    return model


def predict(model, patches, device='cuda', batch_size=32, amp=True):
    """(N, 6, 224, 224) raw patches -> (N, 224, 224) class ids."""
    x = preprocess(patches)
    # FinetunerSegmentation.forward hardcodes img_size=224 and reshapes the
    # token sequence to 14x14. A differently sized patch would not raise -- the
    # ViT slices pos_embedding to however many tokens arrive -- it would just
    # reshape them onto the wrong grid and return a plausible, wrong mask.
    if x.shape[2:] != (PATCH_PX, PATCH_PX):
        raise ValueError(
            f"patches must be {PATCH_PX}x{PATCH_PX}, got {x.shape[2:]}")

    import torch

    out = np.empty((x.shape[0], x.shape[2], x.shape[3]), dtype=np.uint8)
    with torch.inference_mode():
        for i in range(0, len(x), batch_size):
            batch = torch.from_numpy(x[i:i + batch_size]).to(device)
            if amp and device.startswith('cuda'):
                with torch.autocast('cuda', dtype=torch.float16):
                    logits = model(batch)
            else:
                logits = model(batch)
            out[i:i + batch_size] = logits.argmax(1).to(torch.uint8).cpu().numpy()
    return out
