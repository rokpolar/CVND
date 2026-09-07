"""Preprocessing tests for the Kuro Siwo FloodViT path. No torch required.

Preprocessing is where a silent mistake costs the most: a wrong clamp or the
wrong channel order still produces a plausible flood mask, just a wrong one, and
there is no error to notice.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import floodvit_infer as fi  # noqa: E402


class ConstantTests(unittest.TestCase):
    """Values are hardcoded in Kuro Siwo's segmentation trainer, not in a config."""

    def test_normalisation_constants(self):
        self.assertEqual(fi.CLAMP, 0.15)
        self.assertEqual(fi.MEAN, (0.0953, 0.0264))
        self.assertEqual(fi.STD, (0.0427, 0.0215))

    def test_six_channels_from_three_acquisitions(self):
        self.assertEqual(fi.N_CHANNELS, 6)
        self.assertEqual(fi.N_CHANNELS, fi.N_ACQUISITIONS * fi.N_POL)

    def test_flood_is_class_two(self):
        """0 no water, 1 permanent water, 2 flood. Counting the wrong id would
        report permanent rivers as flood in every event."""
        self.assertEqual(fi.CLASS_FLOOD, 2)
        self.assertEqual(fi.CLASS_PERMANENT_WATER, 1)


class PreprocessTests(unittest.TestCase):
    @staticmethod
    def _patch(value=0.05, n=2):
        return np.full((n, fi.N_CHANNELS, 8, 8), value, dtype=np.float32)

    def test_clamps_high_values(self):
        out = fi.preprocess(self._patch(10.0))
        expected = (fi.CLAMP - fi.MEAN[0]) / fi.STD[0]
        self.assertAlmostEqual(float(out[0, 0].max()), expected, places=4)

    def test_clamps_negative_to_zero(self):
        out = fi.preprocess(self._patch(-5.0))
        self.assertAlmostEqual(float(out[0, 0].min()),
                               (0.0 - fi.MEAN[0]) / fi.STD[0], places=4)

    def test_nan_becomes_clamp_not_zero(self):
        """Dataset.concat does nan_to_num(image, CLAMP): NaN means 'no return',
        which is bright, not dark. Mapping it to 0 would look like water."""
        x = self._patch()
        x[0, 0, 0, 0] = np.nan
        out = fi.preprocess(x)
        self.assertAlmostEqual(float(out[0, 0, 0, 0]),
                               (fi.CLAMP - fi.MEAN[0]) / fi.STD[0], places=4)

    def test_polarisation_constants_alternate_by_channel(self):
        """Channels run VV,VH,VV,VH,VV,VH -- one mean per polarisation, reused
        across the three acquisitions."""
        out = fi.preprocess(self._patch(0.05))
        vv = (0.05 - fi.MEAN[0]) / fi.STD[0]
        vh = (0.05 - fi.MEAN[1]) / fi.STD[1]
        for c in range(fi.N_CHANNELS):
            want = vv if c % 2 == 0 else vh
            self.assertAlmostEqual(float(out[0, c].mean()), want, places=4,
                                   msg=f"channel {c}")

    def test_rejects_wrong_channel_count(self):
        with self.assertRaises(ValueError):
            fi.preprocess(np.zeros((1, 4, 8, 8), dtype=np.float32))

    def test_output_is_float32(self):
        self.assertEqual(fi.preprocess(self._patch()).dtype, np.float32)


class CountingTests(unittest.TestCase):
    def test_counts_each_class(self):
        pred = np.array([[0, 1], [2, 2]])
        c = fi.count_classes(pred)
        self.assertEqual(c['no_water_px'], 1)
        self.assertEqual(c['permanent_water_px'], 1)
        self.assertEqual(c['flood_px'], 2)

    def test_permanent_water_is_not_counted_as_flood(self):
        """The model separates the two, so no JRC mask is needed downstream --
        but only if we count class 2 alone."""
        pred = np.full((10, 10), fi.CLASS_PERMANENT_WATER)
        self.assertEqual(fi.count_classes(pred)['flood_px'], 0)

    def test_area_conversion(self):
        self.assertAlmostEqual(fi.px_to_km2(10_000, 10), 1.0)     # 100x100 @10m
        self.assertAlmostEqual(fi.px_to_km2(10_000, 20), 4.0)

    def test_one_full_patch_area(self):
        self.assertAlmostEqual(fi.px_to_km2(fi.PATCH_PX ** 2, 10), 5.0176, places=4)


if __name__ == "__main__":
    unittest.main()
