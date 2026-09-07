"""SAR patch preparation tests that run without Earth Engine credentials.

The module must stay importable without GEE so the geometry and contract can be
checked in CI; satellite.py is imported lazily for that reason.
"""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sar_patches as sp  # noqa: E402


class ModelContractTests(unittest.TestCase):
    """These constants are read from floodvit.pt's own stored config
    (image_size 224, num_channels 6, num_classes 3). If they drift, the
    checkpoint will not load and the flood areas would be silently wrong."""

    def test_channels_match_the_checkpoint(self):
        self.assertEqual(sp.SAR_PATCH_SIZE, 224)
        self.assertEqual(sp.SAR_CHANNELS, 6)
        self.assertEqual(sp.SAR_N_PRE, 2)
        self.assertEqual(sp.SAR_POLARISATIONS, ["VV", "VH"])

    def test_channel_count_is_derived_not_hardcoded(self):
        self.assertEqual(
            sp.SAR_CHANNELS,
            (sp.SAR_N_PRE + 1) * len(sp.SAR_POLARISATIONS),
        )

    def test_scale_matches_kuro_siwo_preprocessing(self):
        """Their SNAP graph terrain-corrects to 10 m; the model never saw another."""
        self.assertEqual(sp.SAR_SCALE_M, 10)

    def test_linear_not_db_collection(self):
        """Normalisation (mean 0.0953, clamp 0.15) is on linear sigma0, so the
        dB product would be off by orders of magnitude."""
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        self.assertIn("COPERNICUS/S1_GRD_FLOAT", src)
        self.assertNotIn("'COPERNICUS/S1_GRD'", src)


class SpeckleTests(unittest.TestCase):
    """Kuro Siwo trains on Lee-filtered imagery. Unfiltered input leaves speckle
    darkening random pixels, which the model reads as water -- measured at 30% of
    flat ground called flood in a Sikkim year with no flood."""

    def test_window_matches_kuro_siwo(self):
        self.assertEqual(sp.SPECKLE_WINDOW, 3)

    def test_enl_is_plausible_for_iw_grd(self):
        """Sentinel-1 IW GRD is roughly 4-5 looks; a wrong ENL mis-weights how
        much of the local variance counts as signal."""
        self.assertTrue(3.0 <= sp.SPECKLE_ENL <= 6.0)

    def test_filter_is_on_by_default(self):
        import inspect
        sig = inspect.signature(sp.iter_patch_blocks)
        self.assertIs(sig.parameters["speckle"].default, True)
        self.assertIs(inspect.signature(sp._download_block)
                      .parameters["speckle"].default, True)


class GridTests(unittest.TestCase):
    def test_patch_spans_expected_ground_distance(self):
        dlat, dlon, _, _ = sp.grid_dims(77.0, 23.0, 84.0, 30.0, 224, 10)
        self.assertAlmostEqual(dlat * 110540.0, 224 * 10, delta=1.0)

    def test_longitude_step_widens_toward_the_pole(self):
        """Degrees of longitude shrink with latitude, so the step must grow."""
        _, dlon_south, _, _ = sp.grid_dims(77.0, 8.0, 78.0, 9.0, 224, 10)
        _, dlon_north, _, _ = sp.grid_dims(77.0, 34.0, 78.0, 35.0, 224, 10)
        self.assertGreater(dlon_north, dlon_south)

    def test_coarser_scale_needs_fewer_patches(self):
        _, _, r10, c10 = sp.grid_dims(77.0, 23.0, 84.0, 30.0, 224, 10)
        _, _, r20, c20 = sp.grid_dims(77.0, 23.0, 84.0, 30.0, 224, 20)
        self.assertAlmostEqual(r10 / r20, 2.0, delta=0.05)
        self.assertAlmostEqual(c10 / c20, 2.0, delta=0.05)

    def test_block_request_stays_under_the_gee_limit(self):
        """One timestep is (block px)^2 x 2 bands x float32; GEE caps a
        getDownloadURL response at 48 MB."""
        px = sp.SAR_BLOCK_PATCHES * sp.SAR_PATCH_SIZE
        mb = px * px * len(sp.SAR_POLARISATIONS) * 4 / 1e6
        self.assertLess(mb, 48.0, f"block request would be {mb:.1f} MB")


class AppendTests(unittest.TestCase):
    def test_append_grows_both_datasets(self):
        import numpy as np
        import tempfile
        import h5py

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.h5"
            P, C = 8, sp.SAR_CHANNELS
            with h5py.File(path, "w") as f:
                f.create_dataset("patches", shape=(0, C, P, P),
                                 maxshape=(None, C, P, P), dtype="float32")
                f.create_dataset("coords", shape=(0, 4),
                                 maxshape=(None, 4), dtype="float64")
                sp._append(f, np.zeros((3, C, P, P), "float32"),
                           np.zeros((3, 4), "float64"))
                sp._append(f, np.ones((2, C, P, P), "float32"),
                           np.ones((2, 4), "float64"))
                self.assertEqual(f["patches"].shape[0], 5)
                self.assertEqual(f["coords"].shape[0], 5)
                self.assertEqual(f["patches"][4, 0, 0, 0], 1.0)


if __name__ == "__main__":
    unittest.main()
