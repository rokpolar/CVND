import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import merge_results  # noqa: E402
import s1_converter  # noqa: E402
from district_keys import cache_stem  # noqa: E402
from flood_spec import (CONVERTER_RULES_VERSION, H5_LAYOUT_VERSION,  # noqa: E402
                        LEGACY_ROUTE_REASONS, LEGACY_SATELLITE_SOURCES, MEASURED_SOURCES,
                        ROUTE_REASONS, SATELLITE_SOURCES, SPEC_VERSION)
from merge_results import (Candidates, Route, interim_route_area, legacy_route_area,  # noqa: E402
                           route_area)

OK = dict(aoi_matched=True, sits_status="ok", eligible_km2=100.0, sits_usable_km2=80.0)
CONVERT = dict(converter_decision="linear", s1_km2=9.0, s1_converted_km2=7.5)

GOLDEN = [
    ("aoi failed", Candidates(aoi_matched=False, s1_km2=5.0, sits_status="ok"),
     Route(None, "NONE", "aoi_failed")),
    ("pending: never S1", Candidates(True, sits_status="pending", **CONVERT),
     Route(None, "NONE", "sits_pending")),
    ("calib passes: gated NDWI", Candidates(**OK, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib"),
     Route(3, "SITS_NDWI", "sits_gate_passed", "sits_tiles")),
    ("calib restored by S1 on the same pixels",
     Candidates(**OK, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib", sits_s1_usable_km2=12),
     Route(10, "SITS_NDWI_RESTORED", "sits_restored_by_s1", "sits_tiles")),
    ("restore ignores AOI-wide S1",
     Candidates(**OK, s1_km2=50, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib", sits_s1_usable_km2=8),
     Route(3, "SITS_NDWI", "sits_gate_passed", "sits_tiles")),
    ("low-conf: NDWI on all retained tiles",
     Candidates(**OK, ndwi_trackA_km2=7, sits_full_km2=6, sits_gated_km2=1, sits_method="low-conf"),
     Route(6, "SITS_NDWI", "sits_gate_failed", "sits_tiles")),
    ("otsu: NDWI on all retained tiles",
     Candidates(**OK, sits_full_km2=6, sits_gated_km2=1, sits_method="otsu"),
     Route(6, "SITS_NDWI", "sits_gate_failed", "sits_tiles")),
    ("small footprint -> converted S1",
     Candidates(True, sits_status="ok", eligible_km2=100.0, sits_usable_km2=10.0, sits_full_km2=6,
                sits_gated_km2=1, sits_method="ndwi-calib", **CONVERT),
     Route(7.5, "S1_TO_SITS", "sits_footprint_small", "aoi")),
    ("small footprint, excluded",
     Candidates(True, sits_status="ok", eligible_km2=100.0, sits_usable_km2=10.0, sits_full_km2=6,
                sits_method="ndwi-calib", converter_decision="excluded", s1_km2=9.0),
     Route(None, "NONE", "sits_footprint_small_excluded")),
    ("unavailable -> converted S1", Candidates(True, sits_status="unavailable", **CONVERT),
     Route(7.5, "S1_TO_SITS", "sits_unavailable_converted", "aoi")),
    ("unavailable, identity converter keeps the label",
     Candidates(True, sits_status="unavailable", converter_decision="identity", s1_km2=9.0, s1_converted_km2=9.0),
     Route(9.0, "S1_TO_SITS", "sits_unavailable_converted", "aoi")),
    ("unavailable, excluded", Candidates(True, sits_status="unavailable", converter_decision="excluded", s1_km2=9.0),
     Route(None, "NONE", "sits_unavailable_excluded")),
    ("unavailable, insufficient", Candidates(True, sits_status="unavailable", converter_decision="insufficient", s1_km2=9.0),
     Route(None, "NONE", "sits_unavailable_excluded")),
    ("unavailable, converter missing", Candidates(True, sits_status="unavailable", s1_km2=9.0),
     Route(None, "NONE", "converter_missing")),
    ("unavailable, no S1", Candidates(True, sits_status="unavailable", converter_decision="linear"),
     Route(None, "NONE", "no_s1")),
    ("unavailable, observed zero", Candidates(True, sits_status="unavailable", converter_decision="identity",
                                               s1_km2=0.0, s1_converted_km2=0.0),
     Route(0.0, "S1_TO_SITS", "sits_unavailable_converted", "aoi")),
]

LEGACY_GOLDEN = [
    ("calib passes: gated NDWI", Candidates(True, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib", cloud_pct=20),
     Route(3, "SITS_NDWI", "sits_gate_passed", "sits_tiles")),
    ("calib restored by S1", Candidates(True, s1_km2=12, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib", cloud_pct=20),
     Route(10, "SITS_NDWI_RESTORED", "sits_restored_by_s1", "sits_tiles")),
    ("low-conf uses AOI-wide Track A NDWI", Candidates(True, ndwi_trackA_km2=7, sits_full_km2=6, sits_gated_km2=1, sits_method="low-conf", cloud_pct=20),
     Route(7, "NDWI", "sits_gate_failed", "aoi")),
    ("low-conf without Track A NDWI", Candidates(True, sits_full_km2=6, sits_gated_km2=1, sits_method="low-conf", cloud_pct=20),
     Route(6, "SITS_NDWI", "sits_gate_failed", "sits_tiles")),
    ("cloudy with S1", Candidates(True, s1_km2=9, sits_full_km2=6, sits_gated_km2=1, sits_method="ndwi-calib", cloud_pct=70),
     Route(9, "S1", "cloud_routed_to_s1")),
    ("cloudy without S1", Candidates(True, sits_full_km2=6, sits_gated_km2=1, sits_method="ndwi-calib", cloud_pct=70),
     Route(None, "NONE", "no_measurement")),
    ("no SITS: S1", Candidates(True, s1_km2=25, ndwi_trackA_km2=4, cloud_pct=20),
     Route(25, "S1", "no_optical_s1")),
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
           "s2_post_images": 3, "cloud_pct": 20.0, "eligible_km2": 30.0,
           "builtup_km2": 3.0, "cropland_km2": 12.0, "spec_version": SPEC_VERSION}
    row.update(changes)
    return row


def score_archive(path, **changes):
    n = 60
    rng = np.random.default_rng(3)
    flood_px = np.where(np.arange(n) < 25, 800, 10)
    scores = np.clip(np.where(flood_px > 400, 0.8, 0.2) + rng.normal(0, 0.02, n), 0, 1)
    usable = np.full(n, 4000)
    payload = {**{k: np.array(v) for k, v in IDENTITY.items()},
               "model_id": np.array("m"), "weights_sha256": np.array("w"),
               "patches_sha256": np.array("p"), "spec_version": np.array(SPEC_VERSION),
               "layout_version": np.array(H5_LAYOUT_VERSION),
               "scores": scores.astype(np.float32), "ndwi_flood": flood_px,
               "ndwi_flood_km2": flood_px * 90.0 / 1e6,
               "tile_area_km2": np.full(n, 4096 * 90.0 / 1e6),
               "usable_px": usable, "usable_km2": usable * 90.0 / 1e6,
               "s1_flood_km2": np.full(n, 0.01), "block_id": np.zeros(n)}
    payload.update(changes)
    payload = {k: v for k, v in payload.items() if v is not None}
    np.savez(path, **payload)


def converter_json(path, decision="linear", **changes):
    model = {"type": "deming_loglog", "offset_km2": 0.1, "slope": 1.0, "intercept": np.log(0.5)}
    payload = {"decision": decision, "spec_version": SPEC_VERSION, "rules_version": CONVERTER_RULES_VERSION,
               "model": model if decision in ("identity", "linear", "stratified") else None}
    if decision == "identity":
        payload["model"] = {"type": "identity"}
    payload.update(changes)
    Path(path).write_text(json.dumps(payload))


class RouteAreaTests(unittest.TestCase):
    def test_golden_routing_table(self):
        for label, candidates, expected in GOLDEN:
            with self.subTest(label):
                self.assertEqual(route_area(candidates), expected)

    def test_legacy_routing_table(self):
        for label, candidates, expected in LEGACY_GOLDEN:
            with self.subTest(label):
                self.assertEqual(legacy_route_area(candidates), expected)
                self.assertIn(expected.satellite_source, LEGACY_SATELLITE_SOURCES)
                self.assertIn(expected.route_reason, LEGACY_ROUTE_REASONS)

    def test_all_sources_in_closed_vocabulary(self):
        for _, candidates, _ in GOLDEN:
            route = route_area(candidates)
            self.assertIn(route.satellite_source, SATELLITE_SOURCES)
            self.assertIn(route.route_reason, ROUTE_REASONS)
            self.assertEqual(route.combined_km2 is None, route.satellite_source == "NONE")
        self.assertEqual({route_area(c).satellite_source for _, c, _ in GOLDEN} - {"NONE"},
                         set(MEASURED_SOURCES) - {"S1"})

    def test_interim_routing_is_s1_for_every_district(self):
        for status in ("pending", "unavailable", "ok"):
            c = Candidates(True, sits_status=status, s1_km2=40.0, sits_full_km2=6, sits_gated_km2=3,
                           sits_method="ndwi-calib", eligible_km2=100.0, sits_usable_km2=90.0)
            self.assertEqual(interim_route_area(c), Route(40.0, "S1", "interim_s1_only", "aoi"))
        self.assertEqual(interim_route_area(Candidates(True, s1_km2=0.0)).combined_km2, 0.0)
        self.assertEqual(interim_route_area(Candidates(True)), Route(None, "NONE", "no_s1"))
        self.assertEqual(interim_route_area(Candidates(False, s1_km2=4.0)), Route(None, "NONE", "aoi_failed"))
        for route in (interim_route_area(Candidates(True, s1_km2=1.0)), interim_route_area(Candidates(True))):
            self.assertIn(route.satellite_source, SATELLITE_SOURCES)
            self.assertIn(route.route_reason, ROUTE_REASONS)

    def test_raw_s1_never_routes(self):
        # A1: whether Track B ran must not switch a district to raw S1.
        for status in ("pending", "unavailable", "ok"):
            for decision in (None, "excluded", "insufficient", "identity", "linear"):
                c = Candidates(True, sits_status=status, s1_km2=40.0, s1_converted_km2=11.0,
                               converter_decision=decision, eligible_km2=100.0, sits_usable_km2=1.0)
                route = route_area(c)
                self.assertNotIn(route.satellite_source, ("S1", "NDWI"))
                self.assertNotEqual(route.combined_km2, 40.0)

    def test_usable_fraction_threshold(self):
        base = dict(aoi_matched=True, sits_status="ok", eligible_km2=100.0, sits_full_km2=6,
                    sits_gated_km2=6, sits_method="ndwi-calib", **CONVERT)
        at = route_area(Candidates(**base, sits_usable_km2=40.0))
        below = route_area(Candidates(**base, sits_usable_km2=39.9))
        self.assertEqual(at.satellite_source, "SITS_NDWI")
        self.assertEqual(below.satellite_source, "S1_TO_SITS")


class TrackBStatusTests(unittest.TestCase):
    def test_status_from_index_and_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(merge_results, "PATCH_DIR", tmp):
            status = merge_results.track_b_status
            self.assertEqual(status("E1::a"), ("pending", "track_b_not_run"))
            self.assertEqual(status("E1::a", {"status": "SKIPPED_NO_IMAGERY", "reason": "no_post_imagery"}),
                             ("unavailable", "no_post_imagery"))
            self.assertEqual(status("E1::a", {"status": "OK", "kept_tiles": 0}),
                             ("unavailable", "no_retained_tiles"))
            self.assertEqual(status("E1::a", {"status": "OK", "kept_tiles": 12}),
                             ("pending", "inference_missing"))
            self.assertEqual(status("E1::a", {"status": "ERROR: boom"}), ("pending", "track_b_error"))
            self.assertEqual(status("E1::a", None, has_scores=True), ("ok", "ok"))
            Path(tmp, f"{cache_stem('E1::a')}.h5.blocks.json").write_text("[0]")
            self.assertEqual(status("E1::a", {"status": "OK"}, has_scores=True),
                             ("pending", "track_b_incomplete"))


class MergeMainTests(unittest.TestCase):
    def run_merge(self, track_rows, archives=(), index_rows=(), converter="linear",
                  routing="sits_primary"):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            scores = root / "scores"
            scores.mkdir()
            for key, changes in archives:
                score_archive(scores / f"{cache_stem(key)}.npz", **changes)
            track, output, index = root / "track.csv", root / "combined.csv", root / "index.csv"
            pd.DataFrame(track_rows).to_csv(track, index=False)
            if index_rows:
                pd.DataFrame([{**IDENTITY, "spec_version": SPEC_VERSION, **r} for r in index_rows]).to_csv(index, index=False)
            conv = root / "conv.json"
            if converter:
                converter_json(conv, converter)
            for name, value in [("SCORES_DIR", str(scores)), ("TRACK_A_CSV", str(track)),
                                ("OUT_CSV", str(output)), ("SITS_INDEX_CSV", str(index)),
                                ("PATCH_DIR", str(root))]:
                stack.enter_context(patch.object(merge_results, name, value))
            stack.enter_context(patch.object(s1_converter, "CONVERTER_JSON", str(conv)))
            merge_results.main(routing)
            return pd.read_csv(output) if output.exists() else None

    def test_sits_archive_routes_through_gate(self):
        result = self.run_merge([track_a_row()], [("E1::a", {})])
        row = result.iloc[0]
        self.assertEqual(row["sits_status"], "ok")
        self.assertEqual(row["sits_method"], "ndwi-calib")
        self.assertEqual(row["satellite_source"], "SITS_NDWI")
        self.assertAlmostEqual(row["sits_ndwi_full_km2"], (25 * 800 + 35 * 10) * 90 / 1e6, places=4)
        self.assertAlmostEqual(row["combined_km2"], 25 * 800 * 90 / 1e6, places=4)
        self.assertAlmostEqual(row["sits_footprint_km2"], 60 * 4096 * 90 / 1e6, places=4)
        self.assertAlmostEqual(row["sits_usable_frac"], 60 * 4000 * 90 / 1e6 / 30.0, places=3)
        self.assertEqual(row["legacy_satellite_source"], "SITS_NDWI")
        self.assertEqual(list(result.columns), list(merge_results.COMBINED_COLUMNS))

    def test_same_district_without_track_b_is_pending_not_s1(self):
        result = self.run_merge([track_a_row()])
        row = result.iloc[0]
        self.assertTrue(pd.isna(row["combined_km2"]))
        self.assertEqual((row["sits_status"], row["route_reason"]), ("pending", "sits_pending"))
        self.assertEqual((row["legacy_satellite_source"], row["legacy_combined_km2"]), ("S1", 12.0))

    def test_unavailable_district_is_converted(self):
        result = self.run_merge([track_a_row()], index_rows=[{"status": "SKIPPED_NO_IMAGERY",
                                                             "reason": "no_post_imagery"}])
        row = result.iloc[0]
        self.assertEqual(row["satellite_source"], "S1_TO_SITS")
        self.assertAlmostEqual(row["combined_km2"], (12.0 + 0.1) * 0.5 - 0.1, places=4)
        self.assertEqual(row["converter_decision"], "linear")
        self.assertEqual(row["sits_reason"], "no_post_imagery")

    def test_converter_missing_or_stale_leaves_na(self):
        for converter in (None, "stale"):
            with self.subTest(converter=converter):
                if converter == "stale":
                    with tempfile.TemporaryDirectory() as tmp:
                        path = Path(tmp) / "c.json"
                        converter_json(path, spec_version="fs1-000000000000")
                        with self.assertRaises(s1_converter.ConverterUnavailable):
                            s1_converter.load(str(path))
                    continue
                result = self.run_merge([track_a_row()], index_rows=[{"status": "SKIPPED_NO_IMAGERY"}],
                                        converter=None)
                self.assertEqual(result.loc[0, "route_reason"], "converter_missing")
                self.assertTrue(pd.isna(result.loc[0, "combined_km2"]))

    def test_excluded_decision_leaves_na(self):
        result = self.run_merge([track_a_row()], index_rows=[{"status": "SKIPPED_NO_IMAGERY"}],
                                converter="excluded")
        self.assertEqual(result.loc[0, "route_reason"], "sits_unavailable_excluded")
        self.assertTrue(pd.isna(result.loc[0, "combined_km2"]))

    def test_interim_main_needs_no_track_b_or_converter(self):
        result = self.run_merge([track_a_row(), track_a_row(event_district_id="E1::b", district="B", area_s1_km2=None)],
                                [("E1::a", {})], converter=None, routing="s1_interim")
        a, b = result.iloc[0], result.iloc[1]
        self.assertEqual((a["satellite_source"], a["combined_km2"], a["route_reason"]), ("S1", 12.0, "interim_s1_only"))
        self.assertEqual(a["routing_mode"], "s1_interim")
        self.assertEqual(a["sits_status"], "ok")          # SITS columns kept for reference
        self.assertTrue(pd.notna(a["sits_ndwi_gated_km2"]))
        self.assertTrue(pd.isna(b["combined_km2"]))
        self.assertEqual(b["route_reason"], "no_s1")
        self.assertTrue(pd.isna(a["converter_decision"]))

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

    def test_npz_without_spec_or_layout_rejected(self):
        with self.assertRaisesRegex(ValueError, "another spec"):
            self.run_merge([track_a_row()], [("E1::a", {"spec_version": None})])
        with self.assertRaisesRegex(ValueError, "layout"):
            self.run_merge([track_a_row()], [("E1::a", {"layout_version": np.array("h5-1")})])
        with self.assertRaisesRegex(ValueError, "s1_flood_km2"):
            self.run_merge([track_a_row()], [("E1::a", {"s1_flood_km2": None})])

    def test_empty_archive_is_unavailable(self):
        empty = {k: np.empty(0) for k in ("scores", "ndwi_flood", "ndwi_flood_km2", "tile_area_km2",
                                          "usable_px", "usable_km2", "s1_flood_km2", "block_id")}
        result = self.run_merge([track_a_row()], [("E1::a", empty)])
        self.assertEqual((result.loc[0, "sits_status"], result.loc[0, "sits_reason"]),
                         ("unavailable", "no_usable_pixels"))
        self.assertEqual(result.loc[0, "satellite_source"], "S1_TO_SITS")

    def test_aoi_failure_is_none(self):
        result = self.run_merge([track_a_row(aoi_match_status="failed")], [("E1::a", {})])
        row = result.iloc[0]
        self.assertTrue(pd.isna(row["combined_km2"]))
        self.assertEqual(row["satellite_source"], "NONE")
        self.assertEqual(row["route_reason"], "aoi_failed")


if __name__ == "__main__":
    unittest.main()
