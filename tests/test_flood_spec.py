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
        for field, bad in [("pre_reference", "pre60d"), ("water_index", "awei"),
                           ("grid_crs", "EPSG:4326"), ("reduce_split_m", 1000)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(SPEC, **{field: bad})

    def test_measurement_constants_are_in_the_hash(self):
        # C8: constants that change numbers invalidate caches when changed.
        for field, value in [("sits_baseline_years", 2), ("sits_baseline_min_clear", 0.6),
                             ("sits_youden_steps", 40), ("sits_score_otsu_bins", 32),
                             ("sits_restore_gated_frac", 0.4), ("sits_usable_min_frac", 0.3),
                             ("otsu_bucket_db", 0.25), ("worldcover_asset", "ESA/WorldCover/v100")]:
            with self.subTest(field=field):
                self.assertNotEqual(spec_version(replace(SPEC, **{field: value})), SPEC_VERSION)

    def test_variants_differ_only_in_their_fields(self):
        for name, overrides in flood_spec.SPEC_VARIANTS.items():
            variant = flood_spec.variant_spec(name)
            self.assertNotEqual(spec_version(variant), SPEC_VERSION)
            self.assertEqual(replace(variant, **{k: getattr(SPEC, k) for k in overrides}), SPEC)
        self.assertEqual(flood_spec.variant_spec("mndwi").water_bands, ("B3", "B11"))
        with self.assertRaises(KeyError):
            flood_spec.variant_spec("nope")

    def test_source_vocabulary(self):
        self.assertEqual(flood_spec.MEASURED_SOURCES, ("SITS_NDWI", "SITS_NDWI_RESTORED", "S1_TO_SITS", "S1"))
        self.assertNotIn("NONE", flood_spec.MEASURED_SOURCES)
        self.assertIn(flood_spec.DEFAULT_ROUTING, flood_spec.ROUTING_MODES)
        self.assertTrue(set(flood_spec.CONVERTING_DECISIONS) < set(flood_spec.CONVERTER_DECISIONS))
        for columns in (flood_spec.COMBINED_COLUMNS, flood_spec.FLOOD_AREA_COLUMNS, flood_spec.TRACK_A_COLUMNS):
            self.assertEqual(len(set(columns)), len(columns))

    def test_pixel_new_water_definitions(self):
        nodata = -32768
        pre = np.array([-500, -500, 600, nodata, -500], dtype=np.int16)
        post = np.array([800, -100, 800, 800, nodata], dtype=np.int16)
        new, observed = flood_spec.ndwi_new_water(pre, post, nodata, 10000)
        np.testing.assert_array_equal(new, [True, False, False, False, False])
        np.testing.assert_array_equal(observed, [True, True, True, False, False])
        s1_pre = np.array([-1000, -2000, nodata, -1000], dtype=np.int16)
        s1_post = np.array([-2000, -2000, -2000, nodata], dtype=np.int16)
        np.testing.assert_array_equal(flood_spec.s1_new_water(s1_pre, s1_post, nodata, 100, -15.0),
                                      [True, False, False, False])
        self.assertFalse(flood_spec.s1_new_water(s1_pre, s1_post, nodata, 100, None).any())

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
