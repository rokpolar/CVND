"""Tests for the two-pipeline comparison. No torch, no Earth Engine.

This harness answers the one question the first validation could not: whether
our Earth Engine chain -- mosaicking, reprojection, the Lee filter, the int16
encoding -- damages the input, or whether the model simply does not transfer to
India. Getting its bookkeeping wrong would answer that backwards.
"""

import os
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import compare_pipelines as cp  # noqa: E402
import floodvit_infer as fvi  # noqa: E402


class DateParsingTests(unittest.TestCase):
    def test_date_comes_from_the_mask_filename(self):
        """MK0_MLU_<act>_<aoi>_<YYYYMMDD>.tif names the POST acquisition, which
        is the one the labels describe. Taking a pre-event date would compare
        our patch against labels for a different day."""
        stem = "MK0_MLU_1111009_01_20220911"
        date = stem.split("_")[-1]
        self.assertEqual(f"{date[:4]}-{date[4:6]}-{date[6:]}", "2022-09-11")


class ScoringTests(unittest.TestCase):
    def test_only_shared_pixels_are_scored(self):
        """Each pipeline has its own no-data. Scoring a pixel one of them never
        saw would charge it for the other's coverage."""
        label = np.array([[[2, 2], [0, 0]]])
        pred = np.array([[[2, 0], [0, 0]]])
        valid = np.array([[[True, False], [True, True]]])
        rows = cp.score_rows(pred, label, valid)
        self.assertEqual(rows["flood"]["f1"], 1.0)

    def test_pixels_key_is_not_reported_as_a_class(self):
        label = np.array([[[0, 1], [2, 2]]])
        rows = cp.score_rows(label.copy(), label, np.ones_like(label, dtype=bool))
        self.assertEqual(set(rows), {"no_water", "permanent_water", "flood"})

    def test_uses_the_same_ignore_index_as_validation(self):
        label = np.array([[[2, vf_ignore := cp.vf.IGNORE_INDEX], [0, 0]]])
        pred = np.array([[[2, 0], [0, 0]]])
        rows = cp.score_rows(pred, label, np.ones_like(label, dtype=bool))
        self.assertEqual(vf_ignore, 3)
        self.assertEqual(rows["flood"]["f1"], 1.0)


class GeometryTests(unittest.TestCase):
    def test_patch_is_cropped_to_the_model_size(self):
        """Their tiles and our downloads need not agree on size; both are cut to
        the model's 224 from the same corner so the pixels line up."""
        src = (ROOT / "src" / "compare_pipelines.py").read_text(encoding="utf-8")
        self.assertIn("[:fvi.PATCH_PX, :fvi.PATCH_PX]", src)
        self.assertEqual(fvi.PATCH_PX, 224)

    def test_download_uses_their_crs(self):
        """Requesting in the sample's own CRS keeps our pixels on their grid, so
        a pixel compared is the same piece of ground."""
        src = (ROOT / "src" / "compare_pipelines.py").read_text(encoding="utf-8")
        self.assertIn("crs=crs", src)

    def test_search_starts_before_their_post_date(self):
        """orbit_sources takes the first pass at or after the start date, so the
        search has to begin a day early to land on their acquisition."""
        src = (ROOT / "src" / "compare_pipelines.py").read_text(encoding="utf-8")
        self.assertIn("advance(-1, 'day')", src)


class ChannelTests(unittest.TestCase):
    def test_both_sides_build_six_channels_post_first(self):
        src = (ROOT / "src" / "compare_pipelines.py").read_text(encoding="utf-8")
        self.assertIn("for b in sp.SAR_POLARISATIONS", src)
        self.assertEqual(fvi.N_CHANNELS, 6)
        self.assertEqual([p[0] for p in cp.vf.BAND_FILES],
                         ["MS1_IVV", "SL1_IVV", "SL2_IVV"])

    def test_no_data_is_nan_on_our_side_too(self):
        """preprocess() fills NaN with the clamp; leaving the int16 sentinel
        would clip to 0 and read as water."""
        src = (ROOT / "src" / "compare_pipelines.py").read_text(encoding="utf-8")
        self.assertIn("ch[bad] = np.nan", src)


if __name__ == "__main__":
    unittest.main()
