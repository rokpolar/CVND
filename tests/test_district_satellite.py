import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import build_flood_area_table  # noqa: E402
import merge_results  # noqa: E402
import satellite  # noqa: E402


class DistrictSatelliteTests(unittest.TestCase):
    def test_gaul_level2_unique_match(self):
        class Number:
            def __init__(self, value): self.value = value
            def getInfo(self): return self.value

        class Collection:
            def __init__(self, count=1, features=None):
                self.count = count
                self.features = features or []
            def filter(self, _): return self
            def size(self): return Number(self.count)
            def getInfo(self): return {"features": self.features}

        class FilterClass:
            @staticmethod
            def eq(*args): return args

        class FakeEE:
            Filter = FilterClass
            def FeatureCollection(self, asset):
                self.asset = asset
                if "level1" in asset:
                    raise AssertionError("district AOI unexpectedly used GAUL level1")
                return Collection(count=1)

        row = {"event_district_id": "E1__a", "state": "Assam", "district": "A",
               "aoi_level": "district"}
        with patch.object(satellite, "ee", FakeEE()):
            collection = satellite._feature_collection_for_aoi(row)
        self.assertEqual(collection.size().getInfo(), 1)

    def test_gaul_level2_missing_or_ambiguous_fails_without_state_fallback(self):
        class Number:
            def __init__(self, value): self.value = value
            def getInfo(self): return self.value

        class Collection:
            def __init__(self, count, features): self.count, self.features = count, features
            def filter(self, _): return self
            def size(self): return Number(self.count)
            def getInfo(self): return {"features": self.features}

        class FilterClass:
            @staticmethod
            def eq(*args): return args

        class FakeEE:
            Filter = FilterClass
            def __init__(self, count, features): self.count, self.features = count, features
            def FeatureCollection(self, asset):
                if "level1" in asset:
                    raise AssertionError("district AOI unexpectedly used GAUL level1")
                return Collection(self.count, self.features)

        row = {"event_district_id": "E1__a", "state": "Assam", "district": "A",
               "aoi_level": "district"}
        for count, features in [(0, []), (2, [{"properties": {"ADM2_NAME": "A"}},
                                               {"properties": {"ADM2_NAME": "A"}}])]:
            with self.subTest(count=count), patch.object(satellite, "ee", FakeEE(count, features)):
                with self.assertRaises(ValueError):
                    satellite._feature_collection_for_aoi(row)

    def test_district_key_forces_level2_even_when_name_equals_state(self):
        row = {"event_id": "E1", "event_district_id": "E1__assam",
               "state": "Assam", "district": "Assam", "aoi_level": "state"}
        self.assertTrue(satellite._is_district_row(row))

    def test_unicode_name_normalization_is_conservative(self):
        self.assertEqual(satellite._normalized_name("São José"), "são josé")
        self.assertNotEqual(satellite._normalized_name("São José"), satellite._normalized_name("Sao Jose"))

    def test_null_reduce_region_is_missing_but_zero_is_observed(self):
        self.assertIsNone(satellite._area_value_km2({}, "flood"))
        self.assertIsNone(satellite._area_value_km2({"flood": None}, "flood"))
        self.assertEqual(satellite._area_value_km2({"flood": 0}, "flood"), 0.0)
        self.assertEqual(satellite._area_value_km2({"flood": 2_000_000}, "flood"), 2.0)

    def test_area_table_keeps_zero_and_missing_distinct(self):
        registry = pd.DataFrame([
            {"event_district_id": "E1__a", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "A", "start_date": "2020-01-01"},
            {"event_district_id": "E1__b", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "B", "start_date": "2020-01-01"},
        ])
        combined = pd.DataFrame([
            {"event_district_id": "E1__a", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "A", "start_date": "2020-01-01",
             "combined_km2": 0.0, "flood_ratio": 0.0,
             "aoi_km2": 10.0, "aoi_match_status": "matched", "combined_source": "NDWI"},
            {"event_district_id": "E1__b", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "B", "start_date": "2020-01-01",
             "combined_km2": None, "aoi_km2": None,
             "aoi_match_status": "matched", "combined_source": "none"},
        ])
        aoi = pd.DataFrame([
            {"event_district_id": "E1__a", "aoi_area_km2": 10.0, "aoi_match_status": "matched"},
            {"event_district_id": "E1__b", "aoi_area_km2": 12.0, "aoi_match_status": "matched"},
        ])
        result = build_flood_area_table.build_flood_area_table(combined, registry, aoi)
        self.assertEqual(result.loc[0, "flood_area_km2"], 0.0)
        self.assertEqual(result.loc[0, "analysis_observation_status"], "observed_zero")
        self.assertTrue(pd.isna(result.loc[1, "flood_area_km2"]))
        self.assertEqual(result.loc[1, "satellite_status"], "missing")

    def test_failed_aoi_cannot_emit_numeric_area(self):
        registry = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "state": "Assam",
            "district": "A", "start_date": "2020-01-01",
        }])
        combined = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "source_record_id": "D1", "state": "Assam",
            "district": "A", "start_date": "2020-01-01", "combined_km2": 4.0,
            "aoi_match_status": "matched", "combined_source": "S1",
        }])
        aoi = pd.DataFrame([{
            "event_district_id": "E1__a", "aoi_area_km2": None,
            "aoi_match_status": "failed",
        }])
        result = build_flood_area_table.build_flood_area_table(combined, registry, aoi)
        self.assertTrue(pd.isna(result.loc[0, "flood_area_km2"]))
        self.assertEqual(result.loc[0, "satellite_status"], "failed_aoi")

    def test_state_combined_schema_cannot_feed_district_table(self):
        registry = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "state": "Assam",
            "district": "A", "start_date": "2020-01-01",
        }])
        combined = pd.DataFrame([{
            "event_id": "E1", "state": "Assam", "district": "A",
            "start_date": "2020-01-01", "combined_km2": 4.0,
        }])
        with self.assertRaises(ValueError):
            build_flood_area_table.build_flood_area_table(combined, registry)

    def test_identity_mismatch_is_rejected(self):
        registry = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "state": "Assam",
            "district": "A", "start_date": "2020-01-01",
        }])
        combined = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "source_record_id": "D1", "state": "Bihar",
            "district": "A", "start_date": "2020-01-01", "combined_km2": 4.0,
            "aoi_match_status": "matched",
        }])
        with self.assertRaises(ValueError):
            build_flood_area_table.build_flood_area_table(combined, registry)

    def test_district_merge_ignores_parent_event_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scores = root / "scores"
            scores.mkdir()
            import numpy as np
            np.savez(scores / "E1.npz", scores=np.array([0.1]), ndwi_flood=np.array([0]))
            track = root / "track.csv"
            cloud = root / "cloud.csv"
            area = root / "area.csv"
            output = root / "combined.csv"
            # The only cache is keyed by parent event_id. A district row must
            # remain missing instead of inheriting this state observation.
            pd.DataFrame([{"event_id": "E1", "area_s1_km2": 25.0,
                           "area_s2_km2": None, "s2_post_images": 0,
                           "event_district_id": "E1__a", "aoi_match_status": "matched",
                           "state": "Assam", "district": "A"}]).to_csv(track, index=False)
            pd.DataFrame([{"event_id": "E1", "event_district_id": "E1__a", "cloud_pct": 100.0}]).to_csv(cloud, index=False)
            pd.DataFrame([{"event_id": "E1", "event_district_id": "E1__a", "aoi_km2": 50.0}]).to_csv(area, index=False)
            # no npz and the keyed row is present, so this checks routing only
            with (patch.object(merge_results, "SCORES_DIR", str(scores)),
                  patch.object(merge_results, "TRACK_A_CSV", str(track)),
                  patch.object(merge_results, "POST_CLOUD_CSV", str(cloud)),
                  patch.object(merge_results, "AOI_AREA_CSV", str(area)),
                  patch.object(merge_results, "OUT_CSV", str(output))):
                merge_results.main()
            result = pd.read_csv(output)
            self.assertNotIn("E1", set(result["event_district_id"].dropna()))
            self.assertEqual(result.loc[0, "event_district_id"], "E1__a")
            self.assertEqual(result.loc[0, "combined_km2"], 25.0)


if __name__ == "__main__":
    unittest.main()
