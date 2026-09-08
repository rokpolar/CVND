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
        """GEE rejects a getDownloadURL response over 48 MiB (50,331,648 bytes).
        One request carries VV and VH as float32 plus two uint8 mask bands.
        The Lee filter first produced float64 and hit exactly this wall, so the
        budget is checked against the real limit, not a rounded 48 MB."""
        px = sp.SAR_BLOCK_PATCHES * sp.SAR_PATCH_SIZE
        per_px = len(sp.SAR_POLARISATIONS) * 2 + 2      # int16 x2, uint8 x2
        self.assertLess(px * px * per_px, 48 * 1024 * 1024,
                        f"block request would be {px * px * per_px / 2**20:.1f} MiB")

    def test_float64_block_would_not_fit(self):
        """Guards the cast: if the filter output ever goes back to float64 the
        block size must be revisited, not silently retried 4 times per block."""
        px = sp.SAR_BLOCK_PATCHES * sp.SAR_PATCH_SIZE
        self.assertGreater(px * px * (len(sp.SAR_POLARISATIONS) * 8 + 2),
                           48 * 1024 * 1024)

    def test_no_data_is_handed_over_as_nan(self):
        """The int16 sentinel decodes to -3.2768 and would clip to 0, the
        darkest possible value. NaN lets preprocess fill it with the clamp."""
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        self.assertIn("ch[bad] = np.nan", src)

    def test_transfer_encoding_round_trips(self):
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        self.assertIn("multiply(SAR_SCALE_FACTOR).toInt16()", src)
        self.assertIn("/= SAR_SCALE_FACTOR", src)

    def test_clamp_matches_the_model(self):
        """Clamping at download is only safe because the model clamps to the same
        value; a mismatch would silently throw away signal it would have used."""
        import floodvit_infer as fi
        self.assertEqual(sp.SAR_CLAMP, fi.CLAMP)

    def test_encoded_clamp_fits_int16(self):
        """Sigma0 reaches 225 over built-up Bihar. Unclamped at 1/10000 that
        wrapped past int16 into negatives -- the brightest pixels in the scene
        became the darkest, which reads as water."""
        self.assertLess(sp.SAR_CLAMP * sp.SAR_SCALE_FACTOR, 32767)

    def test_precision_is_far_below_the_normalisation_std(self):
        self.assertLess(1.0 / sp.SAR_SCALE_FACTOR, 0.0215 / 1000)

    def test_values_are_clamped_before_encoding(self):
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        self.assertIn("clamp(0.0, SAR_CLAMP)", src)

    def test_validity_ignores_the_angle_band(self):
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        self.assertIn("image.select(SAR_POLARISATIONS).mask()", src)


class OrbitSourceTests(unittest.TestCase):
    """One relative orbit does not cover a large AOI: over Bihar the best reaches
    66% and the orbit that passes first after onset reaches 15%. Blocks are
    therefore assigned per orbit, best-covering first, so each is measured once
    and from one viewing geometry."""

    def test_iter_takes_sources_not_a_single_triplet(self):
        import inspect
        params = list(inspect.signature(sp.iter_patch_blocks).parameters)
        self.assertEqual(params[0], "sources")

    def test_single_triplet_entry_point_is_gone(self):
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        self.assertNotIn("def pick_triplet(", src)
        self.assertIn("def orbit_sources(", src)

    def test_acquisitions_group_by_time_gap(self):
        """Two Bihar frames land at 00:03 and 00:04 UTC. Grouping by calendar
        date would split a pass twenty minutes earlier across midnight."""
        import pandas as pd

        class FakeCol:
            def __init__(self, stamps):
                self._s = stamps

            def aggregate_array(self, _):
                return self

            def getInfo(self):
                return self._s

        base = int(pd.Timestamp("2024-09-22T00:03:00Z").value // 10 ** 6)
        same_pass = [base, base + 60_000]                 # one minute apart
        self.assertEqual(len(sp.acquisitions(FakeCol(same_pass))), 1)

        twelve_days = [base, base + 12 * 86_400_000]
        self.assertEqual(len(sp.acquisitions(FakeCol(twelve_days))), 2)

    def test_acquisition_spanning_midnight_stays_one(self):
        import pandas as pd

        class FakeCol:
            def __init__(self, stamps):
                self._s = stamps

            def aggregate_array(self, _):
                return self

            def getInfo(self):
                return self._s

        before = int(pd.Timestamp("2024-09-21T23:59:00Z").value // 10 ** 6)
        after = int(pd.Timestamp("2024-09-22T00:01:00Z").value // 10 ** 6)
        self.assertEqual(len(sp.acquisitions(FakeCol([before, after]))), 1)


class NoStorageTests(unittest.TestCase):
    def test_patch_storage_path_is_gone(self):
        """Keeping patches means ~3.9 TB, and two code paths that must tile
        identically drift apart. Only the streaming consumer remains."""
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        for gone in ("def prepare_event(", "def _tile_region(", "h5py"):
            self.assertNotIn(gone, src)


if __name__ == "__main__":
    unittest.main()
