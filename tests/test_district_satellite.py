import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_flood_area_table  # noqa: E402
import merge_results  # noqa: E402
import satellite  # noqa: E402
from district_keys import key_from_stem  # noqa: E402
from fake_ee import FakeEE, reducer_kind  # noqa: E402
from flood_spec import SPEC, SPEC_VERSION, TRACK_A_COLUMNS  # noqa: E402

S1_ASSET = SPEC.s1_collection
S2_ASSET = SPEC.s2_collection
ROW = {"event_district_id": "E1::a", "event_id": "E1", "source_record_id": "D1",
       "state": "Assam", "district": "A", "start_date": "2020-07-01",
       "aoi_level": "district"}


def fake_aoi(fake):
    return {"geometry": fake.Geometry.Polygon("district"), "aoi_level": "district",
            "aoi_source": SPEC.gaul_level2, "aoi_match_status": "matched",
            "geometry_id": "G1", "aoi_area_km2": 120.0}


def reduce_handler(s1=None, s2=None, clear=0.8, hist=None):
    def reduce(node, kwargs):
        kind = reducer_kind(kwargs)
        if kind == "Reducer.histogram":
            return hist or {}
        if kind == "Reducer.mean":
            return {"clear": clear}
        if S1_ASSET in node._origins:
            return s1 or {}
        if S2_ASSET in node._origins:
            return s2 or {}
        return {}
    return reduce


def run_track_a(fake, **patches):
    with patch.object(satellite, "ee", fake), \
            patch.object(satellite, "resolve_aoi", lambda row, spec=SPEC: fake_aoi(fake)):
        if "measurement_mask" in patches:
            with patch.object(satellite, "measurement_mask", patches["measurement_mask"]):
                return satellite.detect_flood_baseline(pd.Series(ROW))
        return satellite.detect_flood_baseline(pd.Series(ROW))


class TrackAMeasurementSpecTests(unittest.TestCase):
    def test_windows_are_spec_windows(self):
        fake = FakeEE(reduce=reduce_handler(s1={"flood": 1e6}, s2={"flood": 1e6, "pre": 0, "during": 1e6}))
        run_track_a(fake)
        advances = [call.args for call in fake.named("advance")]
        self.assertIn((14, "day"), advances)
        self.assertIn((-30, "day"), advances)
        self.assertNotIn(7, [args[0] for args in advances])

    def test_masks_applied_on_s2_and_s1_paths(self):
        fake = FakeEE(reduce=reduce_handler())
        eligible = fake.Image("ELIGIBLE")
        run_track_a(fake, measurement_mask=lambda spec=SPEC: eligible)
        masked = [call.target._origins for call in fake.named("And")
                  if call.args and call.args[0] is eligible]
        self.assertTrue(any(S2_ASSET in origins for origins in masked))
        self.assertTrue(any(S1_ASSET in origins for origins in masked))

    def test_s2_zero_does_not_override_positive_s1(self):
        fake = FakeEE(reduce=reduce_handler(s1={"flood": 2.5e6},
                                            s2={"flood": 0, "pre": 0, "during": 0}))
        row = run_track_a(fake)
        self.assertEqual(row["area_s1_km2"], 2.5)
        self.assertEqual(row["area_s2_km2"], 0.0)
        self.assertEqual(row["baseline_status"], "OK")
        self.assertEqual(row["cloud_pct"], 20.0)
        self.assertEqual(row["spec_version"], SPEC_VERSION)
        self.assertNotIn("affected_area_km2", row)
        self.assertTrue(set(TRACK_A_COLUMNS) <= set(row))

    def test_area_reduce_uses_pixel_area_and_no_best_effort(self):
        fake = FakeEE(reduce=reduce_handler(s1={"flood": 1e6}, s2={"flood": 1e6, "pre": 0, "during": 1e6}))
        run_track_a(fake)
        reductions = [call.target._kwargs for call in fake.named("getInfo")
                      if call.target._op == "reduceRegion"]
        self.assertTrue(reductions)
        for kwargs in reductions:
            self.assertIs(kwargs["bestEffort"], False)
            expected = SPEC.qa_scale_m if reducer_kind(kwargs) == "Reducer.mean" else SPEC.reduce_scale_m
            self.assertEqual(kwargs["scale"], expected)
            self.assertEqual(kwargs["maxPixels"], SPEC.max_pixels)
        self.assertTrue(fake.named("Image.pixelArea"))

    def test_otsu_fallback_flag_recorded(self):
        fake = FakeEE(reduce=reduce_handler(s1={"flood": 1e6}))
        row = run_track_a(fake)
        self.assertIs(row["otsu_fallback_used"], True)
        self.assertEqual(row["otsu_threshold_db"], SPEC.otsu_fallback_db)

        centers = list(np.arange(-24.0, -8.0, 0.5))
        counts = [np.exp(-((c + 19) ** 2)) * 50 + np.exp(-((c + 11) ** 2)) * 200 for c in centers]
        fake = FakeEE(reduce=reduce_handler(s1={"flood": 1e6},
                                            hist={"VV": {"histogram": counts, "bucketMeans": centers}}))
        row = run_track_a(fake)
        self.assertIs(row["otsu_fallback_used"], False)
        self.assertTrue(SPEC.otsu_lo_db <= row["otsu_threshold_db"] <= SPEC.otsu_hi_db)

    def test_s1_orbit_filter_includes_both_passes_and_records_orbit(self):
        fake = FakeEE(reduce=reduce_handler(s1={"flood": 1e6}), orbits=("ASCENDING", "DESCENDING"))
        row = run_track_a(fake)
        self.assertIn(("orbitProperties_pass", ["ASCENDING", "DESCENDING"]),
                      [call.args for call in fake.named("Filter.inList")])
        self.assertFalse([call for call in fake.named("Filter.eq")
                          if call.args and call.args[0] == "orbitProperties_pass"])
        self.assertEqual(row["s1_orbit"], "BOTH")

    def test_no_imagery_is_missing_not_zero(self):
        fake = FakeEE(reduce=reduce_handler(), size=lambda node: 0)
        row = run_track_a(fake)
        self.assertIsNone(row["area_s1_km2"])
        self.assertIsNone(row["area_s2_km2"])
        self.assertEqual(row["cloud_pct"], 100.0)
        self.assertEqual(row["baseline_status"], "NO_IMAGERY")

    def test_cache_row_with_stale_spec_is_discarded(self):
        self.assertTrue(satellite._cache_identity_matches({**ROW, "spec_version": SPEC_VERSION}, ROW))
        self.assertFalse(satellite._cache_identity_matches({**ROW, "spec_version": "fs1-000000000000"}, ROW))
        self.assertFalse(satellite._cache_identity_matches(dict(ROW), ROW))


class TrackBPreparationTests(unittest.TestCase):
    def test_prepare_sits_patch_uses_analysis_key_and_spec_window(self):
        fake = FakeEE()
        baseline = [(f"2019-0{m}", fake.Image(f"t{m}"), 0.9, 0.1) for m in range(1, 5)]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(satellite, "ee", fake), \
                patch.object(satellite, "SITS_OUTPUT_DIR", tmp), \
                patch.object(satellite, "resolve_aoi", lambda row, spec=SPEC: fake_aoi(fake)), \
                patch.object(satellite, "_pick_baseline", lambda *a, **k: baseline), \
                patch.object(satellite, "_tile_region", lambda *a, **k: (0, 0)):
            path, complete = satellite.prepare_sits_patch(pd.Series(ROW))
            self.assertTrue(complete)
            self.assertEqual(key_from_stem(Path(path).stem), "E1::a")
            with h5py.File(path, "r") as hdf:
                self.assertEqual(hdf["meta"].attrs["spec_version"], SPEC_VERSION)
                self.assertEqual(hdf["meta"].attrs["geometry_id"], "G1")
                for name in ("mask", "ndwi_ref", "pixel_area_m2"):
                    self.assertIn(name, hdf)
            self.assertTrue(satellite._h5_identity_matches(path, ROW))
        advances = [call.args for call in fake.named("advance")]
        self.assertIn((14, "day"), advances)
        self.assertIn((-30, "day"), advances)

    def test_tiles_keep_measurement_layers(self):
        P = SPEC.sits_patch_px
        bands = np.dtype([("B4", "i2"), ("B3", "i2"), ("B2", "i2"), ("B8", "i2"), ("valid", "u1")])
        arrs = []
        for _ in range(5):
            block = np.zeros((P, 2 * P), dtype=bands)
            block["B3"] = 1000
            block["valid"] = 1
            block["valid"][: P // 2, P:] = 0          # second tile only 50% clear
            arrs.append(block)
        arrs[2]["valid"][0, 0] = 0                    # one pixel cloudy in one timestep
        aux = np.zeros((P, 2 * P), dtype=[("eligible", "u1"), ("area", "f4"),
                                          ("ndwi_pre", "i2"), ("ndwi_post", "i2")])
        aux["eligible"] = 1
        aux["eligible"][1, 1] = 0
        aux["area"] = 90.6
        aux["ndwi_pre"] = -500
        aux["ndwi_post"] = 800
        tiles = satellite._tiles_from_block(arrs, aux)
        self.assertEqual(tiles["rc"], [(0, 0)])
        mask = tiles["mask"][0]
        self.assertEqual(mask[0, 0], 1)               # eligible, not valid in every timestep
        self.assertEqual(mask[1, 1], 2)               # valid everywhere, not eligible
        self.assertEqual(mask[5, 5], 3)
        np.testing.assert_array_equal(tiles["ndwi_ref"][0][:, 5, 5], [-500, 800])
        self.assertAlmostEqual(float(tiles["pixel_area_m2"][0]), 90.6, places=3)
        self.assertEqual(tiles["pre"][0].shape, (SPEC.sits_n_pre, 4, P, P))

    def test_no_raw_string_dead_code(self):
        source = inspect.getsource(satellite)
        self.assertNotIn("_OLD_", source)
        self.assertNotIn("r'''", source)
        self.assertNotIn("state AOI", source)
        self.assertFalse(hasattr(satellite, "otsu_threshold"))
        self.assertFalse(hasattr(satellite, "get_masks"))


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
             "combined_km2": 0.0, "aoi_area_km2": 10.0, "aoi_match_status": "matched",
             "satellite_source": "NDWI", "spec_version": SPEC_VERSION},
            {"event_district_id": "E1__b", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "B", "start_date": "2020-01-01",
             "combined_km2": None, "aoi_area_km2": None,
             "aoi_match_status": "matched", "satellite_source": "NONE",
             "spec_version": SPEC_VERSION},
        ])
        aoi = pd.DataFrame([
            {"event_district_id": "E1__a", "aoi_area_km2": 10.0, "aoi_match_status": "matched",
             "spec_version": SPEC_VERSION},
            {"event_district_id": "E1__b", "aoi_area_km2": 12.0, "aoi_match_status": "matched",
             "spec_version": SPEC_VERSION},
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
            "aoi_area_km2": 12.0, "aoi_match_status": "matched", "satellite_source": "S1",
            "spec_version": SPEC_VERSION,
        }])
        aoi = pd.DataFrame([{
            "event_district_id": "E1__a", "aoi_area_km2": None,
            "aoi_match_status": "failed", "spec_version": SPEC_VERSION,
        }])
        result = build_flood_area_table.build_flood_area_table(combined, registry, aoi)
        self.assertTrue(pd.isna(result.loc[0, "flood_area_km2"]))
        self.assertTrue(pd.isna(result.loc[0, "flood_ratio"]))
        self.assertEqual(result.loc[0, "satellite_status"], "failed_aoi")
        # A failed AOI clears the flood observation, not an existing AOI area.
        self.assertEqual(result.loc[0, "aoi_area_km2"], 12.0)

    def _one_district(self, **combined):
        registry = pd.DataFrame([{
            "event_district_id": "E1::a", "event_id": "E1", "source_record_id": "D1",
            "state": "Assam", "district": "A", "start_date": "2020-01-01",
        }])
        row = {"event_district_id": "E1::a", "event_id": "E1", "source_record_id": "D1",
               "state": "Assam", "district": "A", "start_date": "2020-01-01",
               "combined_km2": 3.0, "aoi_area_km2": 99.0, "aoi_match_status": "matched",
               "satellite_source": "S1", "route_reason": "no_optical_s1",
               "spec_version": SPEC_VERSION}
        row.update(combined)
        aoi = pd.DataFrame([{"event_district_id": "E1::a", "aoi_area_km2": 12.0,
                             "aoi_match_status": "matched", "spec_version": SPEC_VERSION}])
        return build_flood_area_table.build_flood_area_table(pd.DataFrame([row]), registry, aoi)

    def test_area_table_rejects_stale_spec_version(self):
        with self.assertRaisesRegex(ValueError, "another spec"):
            self._one_district(spec_version="fs1-000000000000")
        with self.assertRaisesRegex(ValueError, "spec_version"):
            build_flood_area_table.build_flood_area_table(
                self._one_district().drop(columns=["spec_version"]).assign(combined_km2=1.0),
                self._one_district()[["event_district_id", "event_id", "source_record_id",
                                      "state", "district", "start_date"]])

    def test_ratio_computed_once_from_aoi_artifact(self):
        result = self._one_district()
        self.assertEqual(result.loc[0, "aoi_area_km2"], 12.0)
        self.assertEqual(result.loc[0, "flood_ratio"], 0.25)
        self.assertEqual(list(result.columns), list(build_flood_area_table.FLOOD_AREA_COLUMNS))

    def test_satellite_source_passthrough_and_status_vocab(self):
        result = self._one_district(combined_km2=None, satellite_source="NONE",
                                    route_reason="no_measurement")
        self.assertEqual(result.loc[0, "satellite_status"], "missing")
        self.assertEqual(result.loc[0, "route_reason"], "no_measurement")
        result = self._one_district(combined_km2=0.0)
        self.assertEqual(result.loc[0, "satellite_source"], "S1")
        self.assertEqual(result.loc[0, "satellite_status"], "observed")
        self.assertEqual(result.loc[0, "analysis_observation_status"], "observed_zero")
        self.assertEqual(result.loc[0, "spec_version"], SPEC_VERSION)
        # A numeric area without a measured source is not an observation.
        result = self._one_district(satellite_source="NONE")
        self.assertTrue(pd.isna(result.loc[0, "flood_area_km2"]))
        self.assertEqual(result.loc[0, "satellite_status"], "missing")

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
            "aoi_match_status": "matched", "satellite_source": "S1",
            "spec_version": SPEC_VERSION,
        }])
        with self.assertRaisesRegex(ValueError, "stale satellite identity"):
            build_flood_area_table.build_flood_area_table(combined, registry)

    def test_district_merge_ignores_parent_event_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scores = root / "scores"
            scores.mkdir()
            np.savez(scores / "E1.npz", scores=np.array([0.1]), ndwi_flood=np.array([0]))
            track = root / "track.csv"
            output = root / "combined.csv"
            # The only cache is keyed by parent event_id. A district row must
            # remain missing instead of inheriting this state observation.
            pd.DataFrame([{"event_id": "E1", "area_s1_km2": 25.0,
                           "area_s2_km2": None, "s2_post_images": 0, "cloud_pct": 100.0,
                           "event_district_id": "E1__a", "aoi_match_status": "matched",
                           "aoi_area_km2": 50.0, "state": "Assam", "district": "A",
                           "spec_version": SPEC_VERSION}]).to_csv(track, index=False)
            with (patch.object(merge_results, "SCORES_DIR", str(scores)),
                  patch.object(merge_results, "TRACK_A_CSV", str(track)),
                  patch.object(merge_results, "OUT_CSV", str(output))):
                merge_results.main()
            result = pd.read_csv(output)
            self.assertNotIn("E1", set(result["event_district_id"].dropna()))
            self.assertEqual(result.loc[0, "event_district_id"], "E1__a")
            self.assertEqual(result.loc[0, "combined_km2"], 25.0)
            self.assertEqual(result.loc[0, "satellite_source"], "S1")
            self.assertEqual(result.loc[0, "route_reason"], "no_optical_s1")
            self.assertEqual(result.loc[0, "spec_version"], SPEC_VERSION)


if __name__ == "__main__":
    unittest.main()
