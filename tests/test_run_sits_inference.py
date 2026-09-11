from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import run_sits_inference as inference  # noqa: E402
from flood_spec import SPEC, SPEC_VERSION  # noqa: E402

HAS_TORCH = importlib.util.find_spec("torch") is not None
NODATA = -32768


def write_h5(path: Path, n: int = 2, spec_version: str = SPEC_VERSION,
             measurement_layers: bool = True, pixel_area_m2: float = 90.6) -> None:
    P = 4
    pre = np.full((n, SPEC.sits_n_pre, 4, P, P), 0.2, dtype=np.float32)
    post = np.full((n, 1, 4, P, P), 0.3, dtype=np.float32)
    for i in range(n):
        post[i] += 0.01 * i
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("pre", data=pre)
        hdf.create_dataset("post", data=post)
        hdf.create_dataset("coords", data=np.zeros((n, 4)))
        if measurement_layers:
            ndwi = np.zeros((n, 2, P, P), dtype=np.int16)
            ndwi[:, 0] = -500          # dry before
            ndwi[:, 1, :2, :2] = 800   # 4 px of new water after
            ndwi[:, 1, 2:, 2:] = -100
            hdf.create_dataset("ndwi_ref", data=ndwi)
            hdf.create_dataset("mask", data=np.full((n, P, P), 3, dtype=np.uint8))
            hdf.create_dataset("pixel_area_m2", data=np.full(n, pixel_area_m2, dtype=np.float32))
        meta = hdf.create_group("meta")
        meta.attrs["event_id"] = "E001"
        meta.attrs["bands"] = "B4,B3,B2,B8"
        meta.attrs["spec_version"] = spec_version
        meta.attrs["ndwi_scale"] = 10000
        meta.attrs["ndwi_nodata"] = NODATA


class MeasurementLayerTests(unittest.TestCase):
    def test_default_checkpoint_uses_local_upstream_tree(self):
        self.assertEqual(
            inference.CHECKPOINT,
            ROOT / "SITS-ExtremeEvents-main" / "checkpoints" / "ravaen"
            / "checkpoint_vae_contrastive_42.pth",
        )

    def test_partial_h5_is_not_inferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            complete = root / "E001.h5"
            partial = root / "E002.h5"
            complete.touch()
            partial.touch()
            Path(str(partial) + ".blocks.json").write_text("[]")
            self.assertEqual(inference.complete_h5_files(root), [complete])

    def test_event_filter_decodes_cache_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "E1%3A%3Aa.h5").touch()
            (root / "E1%3A%3Ab.h5").touch()
            self.assertEqual([p.name for p in inference.complete_h5_files(root, {"E1::a"})],
                             ["E1%3A%3Aa.h5"])

    def test_ndwi_counts_restricted_to_usable_pixels(self):
        ndwi = np.zeros((1, 2, 2, 2), dtype=np.int16)
        ndwi[0, 0] = [[-500, -500], [600, NODATA]]   # pre
        ndwi[0, 1] = [[800, 800], [800, 800]]        # post
        mask = np.array([[[3, 1], [3, 3]]], dtype=np.uint8)   # (0,1) not clear in all timesteps
        pre, during, new, usable = inference._ndwi_counts(ndwi, mask, NODATA)
        np.testing.assert_array_equal(usable, [2])   # (0,0) and (1,0)
        np.testing.assert_array_equal(pre, [1])      # (1,0) was already water
        np.testing.assert_array_equal(during, [2])
        np.testing.assert_array_equal(new, [1])      # only (0,0) is new water

    def test_ndwi_km2_uses_pixel_area(self):
        km2 = inference._px_to_km2(np.array([4]), np.array([90.6], dtype=np.float32))
        self.assertAlmostEqual(float(km2[0]), 4 * 90.6 / 1e6, places=9)
        self.assertNotAlmostEqual(float(km2[0]), 4e-4, places=6)

    def test_stale_spec_h5_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, kwargs in [("old.h5", {"spec_version": "fs1-000000000000"}),
                                 ("nolayers.h5", {"measurement_layers": False})]:
                write_h5(root / name, **kwargs)
                with self.subTest(name), self.assertRaises(inference.StaleSpecError):
                    inference.infer_h5(root / name, root / "out.npz", None, None, 1, "test")
            self.assertFalse((root / "out.npz").exists())

    def test_unknown_checkpoint_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "my_weights.pth"
            checkpoint.write_bytes(b"weights")
            with self.assertRaisesRegex(RuntimeError, "Unverified"):
                inference.ensure_checkpoint(checkpoint)
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                inference.ensure_checkpoint(checkpoint, expected_sha256="0" * 64)
            digest = inference.sha256_file(checkpoint)
            self.assertEqual(inference.ensure_checkpoint(checkpoint, expected_sha256=digest), checkpoint)


if HAS_TORCH:
    import torch

    class TinyEncoder(torch.nn.Module):
        def forward(self, image):
            return image.mean(dim=(2, 3)).unsqueeze(1), None

    class TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = TinyEncoder()
            self.fc_mu = torch.nn.Linear(3, 3)
            self.fc_var = torch.nn.Identity()

        @staticmethod
        def reparameterize(mu, _log_var):
            return mu + 1000.0     # must never be used for scores


@unittest.skipUnless(HAS_TORCH, "optional SITS model tests require torch")
class LocalSitsInferenceTests(unittest.TestCase):
    def test_latent_uses_mu_not_reparameterized(self):
        model = TinyModel()
        image = torch.rand(2, 3, 4, 4)
        with torch.inference_mode():
            expected = model.fc_mu(torch.flatten(model.encoder(image)[0], start_dim=1))
            torch.testing.assert_close(inference._latent(model, image), expected)

    def test_scores_deterministic_across_batch_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_h5(root / "E001.h5", n=3)
            model = TinyModel()
            inference.infer_h5(root / "E001.h5", root / "a.npz", model, torch.device("cpu"), 1, "t")
            inference.infer_h5(root / "E001.h5", root / "b.npz", model, torch.device("cpu"), 2, "t")
            # Batched BLAS kernels round differently (~1 float32 ulp); sampling
            # used to change scores at O(1).
            with np.load(root / "a.npz") as a, np.load(root / "b.npz") as b:
                np.testing.assert_allclose(a["scores"], b["scores"], rtol=0, atol=1e-6)

    def test_inference_writes_npz_with_areas_and_keeps_h5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path, output_path = root / "E001.h5", root / "E001.npz"
            write_h5(input_path)
            count = inference.infer_h5(input_path, output_path, TinyModel(),
                                       torch.device("cpu"), batch_size=1, checkpoint_hash="test")
            self.assertEqual(count, 2)
            self.assertTrue(input_path.exists())
            with np.load(output_path) as result:
                self.assertEqual(result["scores"].shape, (2,))
                np.testing.assert_array_equal(result["ndwi_flood"], [4, 4])
                np.testing.assert_allclose(result["ndwi_flood_km2"], 4 * 90.6 / 1e6, rtol=1e-6)
                np.testing.assert_allclose(result["tile_area_km2"], SPEC.sits_patch_pixels * 90.6 / 1e6, rtol=1e-6)
                self.assertEqual(str(result["spec_version"]), SPEC_VERSION)
                self.assertEqual(str(result["latent"]), "mu")
                self.assertEqual(str(result["event_id"]), "E001")


if __name__ == "__main__":
    unittest.main()
