"""Tests for the Kuro Siwo validation harness. No torch, no data needed.

The harness exists to decide whether a null India result is our bug or domain
transfer, so its own scoring has to be right -- a wrong ignore index or a wrong
class id would answer that question backwards.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import floodvit_infer as fvi  # noqa: E402
import validate_floodvit as vf  # noqa: E402


class IgnoreIndexTests(unittest.TestCase):
    def test_ignore_index_matches_their_trainer(self):
        """segmentation_trainer.py passes ignore_index=3 to every metric. Scoring
        those pixels would make our numbers incomparable to the paper's."""
        self.assertEqual(vf.IGNORE_INDEX, 3)

    def test_ignored_pixels_are_excluded(self):
        label = np.array([[2, vf.IGNORE_INDEX], [0, 0]])
        pred = np.array([[2, 0], [0, 0]])
        valid = np.ones_like(label, dtype=bool)
        r = vf.score(pred, label, valid)
        self.assertEqual(r["_pixels"], 3)
        self.assertEqual(r["flood"]["f1"], 1.0)

    def test_invalid_pixels_are_excluded(self):
        label = np.array([[2, 2], [0, 0]])
        pred = np.array([[2, 0], [0, 0]])
        valid = np.array([[True, False], [True, True]])
        r = vf.score(pred, label, valid)
        self.assertEqual(r["_pixels"], 3)
        self.assertEqual(r["flood"]["f1"], 1.0)


class ChannelOrderTests(unittest.TestCase):
    def test_band_files_are_post_then_two_pre(self):
        """Their trainer builds cat(post, pre_event_1, pre_event_2); MS1 is the
        post-event ("master") image. Loading pre-first would score a model that
        never sees the arrangement it was trained on."""
        self.assertEqual([p[0] for p in vf.BAND_FILES],
                         ["MS1_IVV", "SL1_IVV", "SL2_IVV"])
        self.assertEqual(len(vf.BAND_FILES) * 2, fvi.N_CHANNELS)

    def test_vv_precedes_vh_within_each_acquisition(self):
        for vv, vh in vf.BAND_FILES:
            self.assertTrue(vv.endswith("IVV"))
            self.assertTrue(vh.endswith("IVH"))


class ScoringTests(unittest.TestCase):
    def test_perfect_prediction(self):
        label = np.array([[0, 1], [2, 2]])
        r = vf.score(label.copy(), label, np.ones_like(label, dtype=bool))
        for name in ("no_water", "permanent_water", "flood"):
            self.assertEqual(r[name]["f1"], 1.0, name)
            self.assertEqual(r[name]["iou"], 1.0, name)

    def test_permanent_water_called_flood_is_penalised(self):
        """Calling rivers flood is the failure mode that inflates every India
        area, so it must show as flood precision falling, not as a pass."""
        label = np.full((4, 4), fvi.CLASS_PERMANENT_WATER)
        pred = np.full((4, 4), fvi.CLASS_FLOOD)
        r = vf.score(pred, label, np.ones((4, 4), dtype=bool))
        self.assertEqual(r["flood"]["precision"], 0.0)
        self.assertEqual(r["permanent_water"]["recall"], 0.0)

    def test_counts_are_reported_for_context(self):
        label = np.array([[2, 2], [0, 0]])
        pred = np.array([[2, 0], [0, 0]])
        r = vf.score(pred, label, np.ones_like(label, dtype=bool))
        self.assertEqual(r["flood"]["n_true"], 2)
        self.assertEqual(r["flood"]["n_pred"], 1)


class SampleDiscoveryTests(unittest.TestCase):
    def test_finds_nested_sample_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "act470" / "aoi01" / "grid_a"
            good.mkdir(parents=True)
            for n in ("MK0_MLU_x.tif", "MS1_IVV_x.tif"):
                (good / n).touch()
            (Path(tmp) / "empty").mkdir()
            self.assertEqual(vf.find_samples(tmp), [str(good)])

    def test_directory_missing_a_band_is_not_a_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "partial"
            d.mkdir()
            (d / "MK0_MLU_x.tif").touch()
            self.assertEqual(vf.find_samples(tmp), [])


if __name__ == "__main__":
    unittest.main()
