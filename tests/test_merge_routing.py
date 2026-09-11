import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import merge_results  # noqa: E402
from district_keys import cache_stem  # noqa: E402
from flood_spec import MEASURED_SOURCES, ROUTE_REASONS, SATELLITE_SOURCES, SPEC_VERSION  # noqa: E402
from merge_results import Candidates, Route, route_area  # noqa: E402

GOLDEN = [
    ("aoi failed", Candidates(aoi_matched=False, s1_km2=5.0, cloud_pct=10),
     Route(None, "NONE", "aoi_failed")),
    ("calib passes: gated NDWI", Candidates(True, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib", cloud_pct=20),
     Route(3, "SITS_NDWI", "sits_gate_passed", "sits_tiles")),
    ("calib restored by S1", Candidates(True, s1_km2=12, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib", cloud_pct=20),
     Route(10, "SITS_NDWI_RESTORED", "sits_restored_by_s1", "sits_tiles")),
    ("restore needs S1 >= full", Candidates(True, s1_km2=8, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib", cloud_pct=20),
     Route(3, "SITS_NDWI", "sits_gate_passed", "sits_tiles")),
    ("low-conf uses AOI-wide Track A NDWI", Candidates(True, ndwi_trackA_km2=7, sits_full_km2=6, sits_gated_km2=1, sits_method="low-conf", cloud_pct=20),
     Route(7, "NDWI", "sits_gate_failed", "aoi")),
    ("low-conf without Track A NDWI", Candidates(True, sits_full_km2=6, sits_gated_km2=1, sits_method="low-conf", cloud_pct=20),
     Route(6, "SITS_NDWI", "sits_gate_failed", "sits_tiles")),
    ("cloudy with S1", Candidates(True, s1_km2=9, sits_full_km2=6, sits_gated_km2=1, sits_method="ndwi-calib", cloud_pct=70),
     Route(9, "S1", "cloud_routed_to_s1")),
    ("cloudy without S1", Candidates(True, sits_full_km2=6, sits_gated_km2=1, sits_method="ndwi-calib", cloud_pct=70),
     Route(None, "NONE", "no_measurement")),
    ("unknown cloud routes to S1", Candidates(True, s1_km2=9, sits_full_km2=6, sits_gated_km2=1, sits_method="otsu", cloud_pct=float("nan")),
     Route(9, "S1", "cloud_routed_to_s1")),
    ("no SITS: S1", Candidates(True, s1_km2=25, ndwi_trackA_km2=4, cloud_pct=20),
     Route(25, "S1", "no_optical_s1")),
    ("no SITS: S1 observed zero", Candidates(True, s1_km2=0.0, cloud_pct=100),
     Route(0.0, "S1", "no_optical_s1")),
    ("no SITS, no S1: NDWI", Candidates(True, ndwi_trackA_km2=4, cloud_pct=20, s2_post_images=3),
     Route(4, "NDWI", "no_s1_ndwi", "aoi")),
    ("no SITS, no S1, cloudy", Candidates(True, ndwi_trackA_km2=4, cloud_pct=70, s2_post_images=3),
     Route(None, "NONE", "no_measurement")),
]

IDENTITY = {"event_district_id": "E1::a", "event_id": "E1", "source_record_id": "D1",
            "state": "Assam", "district": "A", "start_date": "2020-07-01",
            "geometry_id": "G1"}


def track_a_row(**changes):
    row = {**IDENTITY, "aoi_level": "district", "aoi_match_status": "matched",
           "aoi_area_km2": 100.0, "area_s1_km2": 12.0, "area_s2_km2": 5.0,
           "s2_post_images": 3, "cloud_pct": 20.0, "spec_version": SPEC_VERSION}
    row.update(changes)
    return row


def score_archive(path, **changes):
    n = 60
    rng = np.random.default_rng(3)
    flood_px = np.where(np.arange(n) < 25, 800, 10)
    scores = np.clip(np.where(flood_px > 400, 0.8, 0.2) + rng.normal(0, 0.02, n), 0, 1)
    payload = {**{k: np.array(v) for k, v in IDENTITY.items()},
               "model_id": np.array("m"), "weights_sha256": np.array("w"),
               "patches_sha256": np.array("p"), "spec_version": np.array(SPEC_VERSION),
               "scores": scores.astype(np.float32), "ndwi_flood": flood_px,
               "ndwi_flood_km2": flood_px * 90.0 / 1e6,
               "tile_area_km2": np.full(n, 4096 * 90.0 / 1e6),
               "usable_px": np.full(n, 4000)}
    payload.update(changes)
    payload = {k: v for k, v in payload.items() if v is not None}
    np.savez(path, **payload)


class RouteAreaTests(unittest.TestCase):
    def test_golden_routing_table(self):
        for label, candidates, expected in GOLDEN:
            with self.subTest(label):
                self.assertEqual(route_area(candidates), expected)

    def test_all_sources_in_closed_vocabulary(self):
        for _, candidates, _ in GOLDEN:
            route = route_area(candidates)
            self.assertIn(route.satellite_source, SATELLITE_SOURCES)
            self.assertIn(route.route_reason, ROUTE_REASONS)
            self.assertEqual(route.combined_km2 is None, route.satellite_source == "NONE")
        self.assertEqual({route_area(c).satellite_source for _, c, _ in GOLDEN} - {"NONE"},
                         set(MEASURED_SOURCES))


class MergeMainTests(unittest.TestCase):
    def run_merge(self, track_rows, archives=()):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scores = root / "scores"
            scores.mkdir()
            for key, changes in archives:
                score_archive(scores / f"{cache_stem(key)}.npz", **changes)
            track, output = root / "track.csv", root / "combined.csv"
            pd.DataFrame(track_rows).to_csv(track, index=False)
            with (patch.object(merge_results, "SCORES_DIR", str(scores)),
                  patch.object(merge_results, "TRACK_A_CSV", str(track)),
                  patch.object(merge_results, "OUT_CSV", str(output))):
                merge_results.main()
            return pd.read_csv(output) if output.exists() else None

    def test_sits_archive_routes_through_gate(self):
        result = self.run_merge([track_a_row()], [("E1::a", {})])
        row = result.iloc[0]
        self.assertEqual(row["sits_method"], "ndwi-calib")
        self.assertEqual(row["satellite_source"], "SITS_NDWI")
        self.assertAlmostEqual(row["sits_ndwi_full_km2"], (25 * 800 + 35 * 10) * 90 / 1e6, places=4)
        self.assertAlmostEqual(row["combined_km2"], 25 * 800 * 90 / 1e6, places=4)
        self.assertAlmostEqual(row["sits_footprint_km2"], 60 * 4096 * 90 / 1e6, places=4)
        self.assertEqual(list(result.columns), list(merge_results.COMBINED_COLUMNS))

    def test_stale_track_a_rows_are_dropped_not_reused(self):
        result = self.run_merge([track_a_row(),
                                 track_a_row(event_district_id="E1::b", district="B",
                                             spec_version="fs1-000000000000")])
        self.assertEqual(result["event_district_id"].tolist(), ["E1::a"])

    def test_track_a_error_rows_are_not_routed_as_no_measurement(self):
        result = self.run_merge([track_a_row(baseline_status="OK"),
                                 track_a_row(event_district_id="E1::b", district="B",
                                             area_s1_km2=None, area_s2_km2=None,
                                             baseline_status="ERROR: Computation timed out.")])
        self.assertEqual(result["event_district_id"].tolist(), ["E1::a"])
        self.assertEqual(result.loc[0, "geometry_id"], "G1")

    def test_missing_track_a_is_an_error(self):
        with patch.object(merge_results, "TRACK_A_CSV", "does/not/exist.csv"):
            with self.assertRaises(FileNotFoundError):
                merge_results.main()

    def test_npz_without_track_a_row_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no Track A row"):
            self.run_merge([track_a_row()], [("E1::zzz", {})])

    def test_npz_without_spec_version_rejected(self):
        with self.assertRaisesRegex(ValueError, "another spec"):
            self.run_merge([track_a_row()], [("E1::a", {"spec_version": None})])
        with self.assertRaisesRegex(ValueError, "ndwi_flood_km2"):
            self.run_merge([track_a_row()], [("E1::a", {"ndwi_flood_km2": None})])

    def test_aoi_failure_is_none(self):
        result = self.run_merge([track_a_row(aoi_match_status="failed")], [("E1::a", {})])
        row = result.iloc[0]
        self.assertTrue(pd.isna(row["combined_km2"]))
        self.assertEqual(row["satellite_source"], "NONE")
        self.assertEqual(row["route_reason"], "aoi_failed")


if __name__ == "__main__":
    unittest.main()
