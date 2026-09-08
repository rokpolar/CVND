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
    """The grid is metres in the same UTM CRS the blocks are downloaded in. In
    degrees, each block was a lat/lon rectangle whose projected bounding box
    overlapped its neighbours', so adjacent blocks could count the same ground
    twice and leave slivers between them uncounted."""

    def test_grid_counts_whole_patches(self):
        rows, cols = sp.grid_dims(0, 0, 224 * 10 * 3, 224 * 10 * 2)
        self.assertEqual((rows, cols), (2, 3))

    def test_partial_patch_is_not_counted(self):
        side = 224 * 10
        rows, cols = sp.grid_dims(0, 0, side * 2 + 1, side + side // 2)
        self.assertEqual((rows, cols), (1, 2))

    def test_no_latitude_term_remains(self):
        """A metric grid must give the same answer wherever it sits."""
        side = 224 * 10
        south = sp.grid_dims(0, 0, side * 4, side * 4)
        north = sp.grid_dims(500_000, 3_700_000,
                             500_000 + side * 4, 3_700_000 + side * 4)
        self.assertEqual(south, north)

    def test_coarser_scale_needs_fewer_patches(self):
        side = 224 * 10 * 4
        r10, c10 = sp.grid_dims(0, 0, side, side, 224, 10)
        r20, c20 = sp.grid_dims(0, 0, side, side, 224, 20)
        self.assertEqual((r10, c10), (4, 4))
        self.assertEqual((r20, c20), (2, 2))

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


class ValidityThresholdTests(unittest.TestCase):
    def test_threshold_leaves_little_room_for_invented_pixels(self):
        """No-data is filled with the clamp, a guess either way. At 0.70 almost a
        third of a patch fed to the model could be invented."""
        self.assertGreaterEqual(sp.SAR_KEEP_VALID, 0.9)
        self.assertLessEqual(sp.SAR_KEEP_VALID, 1.0)


class ProjectionTests(unittest.TestCase):
    """mosaic() drops the source projection: it reports EPSG:4326 with a 1-degree
    transform, so getDownloadURL(scale=10) lays a grid square in DEGREES. At
    Bihar's latitude that is 9.93 m north-south and 9.02 m east-west -- 89.6 m2
    per pixel against the 100 assumed, an 11% area error growing with latitude --
    and the native UTM imagery is resampled onto that skewed grid before either
    the speckle filter or the model sees it."""

    def test_utm_zone_from_longitude(self):
        cases = {77.0: 43, 84.5: 45, 92.9: 46, 71.35: 42}
        for lon, zone in cases.items():
            class FakeRegion:
                def centroid(self, _):
                    return self

                def coordinates(self):
                    return self

                def getInfo(self, _lon=lon):
                    return [_lon, 25.0]
            self.assertEqual(sp.utm_crs(FakeRegion()), f"EPSG:326{zone:02d}")

    def test_southern_hemisphere_uses_327xx(self):
        class FakeRegion:
            def centroid(self, _):
                return self

            def coordinates(self):
                return self

            def getInfo(self):
                return [77.0, -25.0]
        self.assertTrue(sp.utm_crs(FakeRegion()).startswith("EPSG:327"))

    def test_download_pins_the_crs(self):
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        self.assertIn("params['crs'] = crs", src)

    def test_filter_runs_on_the_pinned_grid(self):
        """reduceNeighborhood works in the image's projection, so on a mosaic's
        default 1-degree grid a 3x3 window is not 3x3 native pixels."""
        src = (ROOT / "src" / "sar_patches.py").read_text(encoding="utf-8")
        i_proj = src.index("setDefaultProjection")
        i_lee = src.index("sar = lee_filter(sar)")
        self.assertLess(i_proj, i_lee)


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
