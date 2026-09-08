from __future__ import annotations

import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

import h5py
import numpy as np

if importlib.util.find_spec("torch") is None:
    raise unittest.SkipTest("optional SITS tests require torch")

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import run_sits_inference as inference


class TinyEncoder(torch.nn.Module):
    def forward(self, image):
        return image.mean(dim=(2, 3)).unsqueeze(1), None


class TinyModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = TinyEncoder()
        self.fc_mu = torch.nn.Identity()
        self.fc_var = torch.nn.Identity()

    @staticmethod
    def reparameterize(mu, _log_var):
        return mu


class LocalSitsInferenceTests(unittest.TestCase):
    def test_default_checkpoint_uses_local_upstream_tree(self):
        self.assertEqual(
            inference.CHECKPOINT,
            ROOT
            / "SITS-ExtremeEvents-main"
            / "checkpoints"
            / "ravaen"
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
            self.assertEqual(
                inference.complete_h5_files(root),
                [complete],
            )

    def test_ndwi_counts_new_water(self):
        pre = np.zeros((1, 4, 4, 2, 2), dtype=np.float32)
        post = np.zeros((1, 4, 2, 2), dtype=np.float32)
        pre[:, :, 1] = 0.2
        pre[:, :, 3] = 0.4
        post[:, 1] = 0.4
        post[:, 3] = 0.2

        before, during, flood = inference._ndwi_counts(pre, post, 1, 3)

        np.testing.assert_array_equal(before, [0])
        np.testing.assert_array_equal(during, [4])
        np.testing.assert_array_equal(flood, [4])

    def test_inference_writes_npz_and_keeps_h5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "E001.h5"
            output_path = root / "E001.npz"
            pre = np.full((2, 4, 4, 2, 2), 0.2, dtype=np.float32)
            post = np.full((2, 1, 4, 2, 2), 0.3, dtype=np.float32)
            with h5py.File(input_path, "w") as hdf:
                hdf.create_dataset("pre", data=pre)
                hdf.create_dataset("post", data=post)
                hdf.create_dataset("coords", data=np.zeros((2, 4)))
                meta = hdf.create_group("meta")
                meta.attrs["event_id"] = "E001"
                meta.attrs["bands"] = "B4,B3,B2,B8"

            count = inference.infer_h5(
                input_path,
                output_path,
                TinyModel(),
                torch.device("cpu"),
                batch_size=1,
                checkpoint_hash="test",
            )

            self.assertEqual(count, 2)
            self.assertTrue(input_path.exists())
            with np.load(output_path) as result:
                self.assertEqual(result["scores"].shape, (2,))
                self.assertEqual(result["ndwi_flood"].shape, (2,))
                self.assertEqual(str(result["event_id"]), "E001")


if __name__ == "__main__":
    unittest.main()
