import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import district_keys  # noqa: E402
import flood_spec  # noqa: E402
from cvnd_config import PRIMARY_MEDIA_WINDOW_DAYS  # noqa: E402
from flood_spec import SPEC, SPEC_VERSION, otsu_from_histogram, spec_version  # noqa: E402


class MeasurementSpecTests(unittest.TestCase):
    def test_spec_hash_is_stable_and_sensitive(self):
        self.assertEqual(spec_version(flood_spec.MeasurementSpec()), SPEC_VERSION)
        self.assertTrue(SPEC_VERSION.startswith("fs1-"))
        self.assertNotEqual(spec_version(replace(SPEC, post_window_days=7)), SPEC_VERSION)
        self.assertNotEqual(spec_version(replace(SPEC, post_composite="median")), SPEC_VERSION)

    def test_post_window_is_the_media_window(self):
        self.assertEqual(SPEC.post_window_days, PRIMARY_MEDIA_WINDOW_DAYS)
        self.assertEqual(SPEC.post_window_days, 14)

    def test_scale_off_the_sits_grid_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SITS grid"):
            replace(SPEC, reduce_scale_m=30)
        with self.assertRaises(ValueError):
            replace(SPEC, post_composite="mean")
        with self.assertRaises(ValueError):
            replace(SPEC, pre_window_days=0)

    def test_source_vocabulary(self):
        self.assertEqual(flood_spec.MEASURED_SOURCES, ("S1", "NDWI", "SITS_NDWI", "SITS_NDWI_RESTORED"))
        self.assertNotIn("NONE", flood_spec.MEASURED_SOURCES)
        self.assertEqual(len(set(flood_spec.COMBINED_COLUMNS)), len(flood_spec.COMBINED_COLUMNS))

    def test_otsu_bimodal_histogram(self):
        centers = np.arange(-25.0, -5.0, 0.5)
        counts = np.exp(-((centers + 20) ** 2)) * 100 + np.exp(-((centers + 10) ** 2)) * 300
        threshold, separability = otsu_from_histogram(counts, centers)
        self.assertGreater(threshold, -20)
        self.assertLess(threshold, -10)
        self.assertGreater(separability, 0.8)

    def test_otsu_degenerate_histograms(self):
        self.assertEqual(otsu_from_histogram([], []), (None, 0.0))
        self.assertEqual(otsu_from_histogram([0, 0, 0], [1, 2, 3]), (None, 0.0))
        self.assertEqual(otsu_from_histogram([0, 5, 0], [1, 2, 3]), (None, 0.0))

    def test_stale_spec_detection(self):
        frame = pd.DataFrame({"spec_version": [SPEC_VERSION, "fs1-old", None]})
        self.assertEqual(flood_spec.stale_spec_mask(frame).tolist(), [False, True, True])
        with self.assertRaisesRegex(ValueError, "another spec"):
            flood_spec.require_spec(frame, "cache")
        with self.assertRaisesRegex(ValueError, "no spec_version"):
            flood_spec.require_spec(pd.DataFrame({"x": [1]}), "cache")
        flood_spec.require_spec(frame.iloc[:1], "cache")


class AnalysisKeyTests(unittest.TestCase):
    def test_blank_district_keys_fall_back_to_event(self):
        for blank in [None, float("nan"), "nan", "None", "  ", "", pd.NA]:
            with self.subTest(blank=blank):
                self.assertEqual(district_keys.analysis_key({"event_district_id": blank, "event_id": "E1"}), "E1")
        self.assertEqual(district_keys.analysis_key(pd.Series({"event_district_id": "E1::a", "event_id": "E1"})), "E1::a")

    def test_analysis_key_has_one_source(self):
        import build_flood_area_table
        import merge_results
        import satellite

        self.assertIs(merge_results.analysis_key, district_keys.analysis_key)
        self.assertIs(build_flood_area_table.analysis_key, district_keys.analysis_key)
        self.assertIs(satellite.analysis_key, district_keys.analysis_key)


if __name__ == "__main__":
    unittest.main()
