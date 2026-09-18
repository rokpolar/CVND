import json
import hashlib
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
import sits_measure  # noqa: E402
from district_keys import analysis_key, cache_stem  # noqa: E402
from flood_spec import (CONVERTER_RULES_VERSION, H5_LAYOUT_VERSION,  # noqa: E402
                        LEGACY_ROUTE_REASONS, LEGACY_SATELLITE_SOURCES, MEASURED_SOURCES,
                        ROUTE_REASONS, SATELLITE_SOURCES, SPEC_VERSION)
from merge_results import (Candidates, Route, s1_then_s2_route_area, legacy_route_area,  # noqa: E402
                           route_area, sits_then_track_a_route_area)

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
                         set(MEASURED_SOURCES) - {"S1", "NDWI"})

    def test_s1_then_s2_routing(self):
        for status in ("pending", "unavailable", "ok"):
            c = Candidates(True, sits_status=status, s1_km2=40.0, sits_full_km2=6, sits_gated_km2=3,
                           sits_method="ndwi-calib", eligible_km2=100.0, sits_usable_km2=90.0)
            self.assertEqual(s1_then_s2_route_area(c), Route(40.0, "S1", "s1_primary", "aoi"))
        self.assertEqual(s1_then_s2_route_area(Candidates(True, s1_km2=0.0)).combined_km2, 0.0)
        self.assertEqual(s1_then_s2_route_area(
            Candidates(True, ndwi_trackA_km2=4.0, s2_post_images=2)),
            Route(4.0, "NDWI", "s2_fallback", "aoi"))
        self.assertEqual(s1_then_s2_route_area(Candidates(True)),
                         Route(None, "NONE", "no_s1_or_s2"))
        self.assertEqual(s1_then_s2_route_area(Candidates(False, s1_km2=4.0)),
                         Route(None, "NONE", "aoi_failed"))
        for route in (s1_then_s2_route_area(Candidates(True, s1_km2=1.0)),
                      s1_then_s2_route_area(Candidates(True))):
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

    def test_sits_then_track_a_routing_table(self):
        track_a = dict(s1_km2=9.0, ndwi_trackA_km2=4.0, s2_post_images=3)
        cases = [
            ("SITS measured: gated NDWI",
             Candidates(**OK, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib", **track_a),
             Route(3, "SITS_NDWI", "sits_gate_passed", "sits_tiles")),
            ("SITS measured: restored",
             Candidates(**OK, sits_full_km2=10, sits_gated_km2=3, sits_method="ndwi-calib",
                        sits_s1_usable_km2=12, **track_a),
             Route(10, "SITS_NDWI_RESTORED", "sits_restored_by_s1", "sits_tiles")),
            ("too few usable pixels -> Track A S1",
             Candidates(True, sits_status="ok", eligible_km2=100.0, sits_usable_km2=10.0, sits_full_km2=6,
                        sits_gated_km2=1, sits_method="ndwi-calib", **track_a),
             Route(9.0, "S1", "track_a_sits_footprint_small", "aoi")),
            ("Track B found no imagery -> Track A S1, no converter needed",
             Candidates(True, sits_status="unavailable", **track_a),
             Route(9.0, "S1", "track_a_sits_unavailable", "aoi")),
            ("no imagery and no S1 -> Track A S2 NDWI",
             Candidates(True, sits_status="unavailable", ndwi_trackA_km2=4.0, s2_post_images=3),
             Route(4.0, "NDWI", "track_a_sits_unavailable", "aoi")),
            ("Track B not run yet -> Track A, not missing",
             Candidates(True, sits_status="pending", **track_a),
             Route(9.0, "S1", "track_a_sits_pending", "aoi")),
            ("observed zero S1 stays zero",
             Candidates(True, sits_status="pending", s1_km2=0.0),
             Route(0.0, "S1", "track_a_sits_pending", "aoi")),
            ("nothing measured anywhere -> missing",
             Candidates(True, sits_status="pending"), Route(None, "NONE", "no_s1_or_s2")),
            ("AOI failure", Candidates(False, sits_status="ok", **track_a), Route(None, "NONE", "aoi_failed")),
        ]
        for label, candidates, expected in cases:
            with self.subTest(label):
                route = sits_then_track_a_route_area(candidates)
                self.assertEqual(route, expected)
                self.assertIn(route.satellite_source, SATELLITE_SOURCES)
                self.assertIn(route.route_reason, ROUTE_REASONS)
                self.assertEqual(route.combined_km2 is None, route.satellite_source == "NONE")

    def test_sits_then_track_a_keeps_every_sits_route(self):
        # Wherever route_area measures with SITS, this mode returns exactly that.
        for label, candidates, expected in GOLDEN:
            if expected.satellite_source in ("SITS_NDWI", "SITS_NDWI_RESTORED"):
                with self.subTest(label):
                    self.assertEqual(sits_then_track_a_route_area(candidates), expected)

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


def registry_rows_for(track_rows, extra_keys=()):
    """A registry holding the identity of every Track A row (plus extra districts)."""
    rows = {}
    for row in track_rows:
        rows[analysis_key(row)] = {c: row.get(c) for c in ("event_district_id", "event_id",
                                                          "source_record_id", "state",
                                                          "district", "start_date")}
    for key in extra_keys:
        district = key.split("::")[-1]
        rows.setdefault(key, {**{c: IDENTITY[c] for c in ("event_id", "source_record_id",
                                                           "state", "start_date")},
                              "event_district_id": key, "district": district.upper(),
                              "aoi_match_status": "pending"})
    return list(rows.values())


def measure_archives(scores_dir, table):
    """What run_sits_inference does after writing each archive: one table row."""
    rows = []
    for path in sorted(Path(scores_dir).glob("*.npz")):
        with np.load(path, allow_pickle=False) as archive:
            rows.append(sits_measure.measurement_row(archive))
    if rows:
        sits_measure.upsert_measurements(rows, table)


class MergeHarness:
    def build_inputs(self, root, track_rows, archives=(), index_rows=(), converter="linear",
                     registry_rows=None, aoi_rows=(), measure=True):
        scores = root / "scores"
        scores.mkdir(exist_ok=True)
        for key, changes in archives:
            # Scores are only current for the H5 on disk: give each one a
            # stand-in H5 (PATCH_DIR is root) and its hash, as inference records.
            h5 = root / f"{cache_stem(key)}.h5"
            h5.write_bytes(f"fixture:{key}".encode())
            changes = dict(changes)
            changes.setdefault("patches_sha256", np.array(hashlib.sha256(h5.read_bytes()).hexdigest()))
            score_archive(scores / f"{cache_stem(key)}.npz", **changes)
        paths = {name: root / f"{name}.csv" for name in ("track", "index", "registry", "aoi", "measurements")}
        pd.DataFrame(track_rows).to_csv(paths["track"], index=False)
        if index_rows:
            pd.DataFrame([{**IDENTITY, "spec_version": SPEC_VERSION, **r}
                          for r in index_rows]).to_csv(paths["index"], index=False)
        pd.DataFrame(registry_rows if registry_rows is not None
                     else registry_rows_for(track_rows)).to_csv(paths["registry"], index=False)
        if aoi_rows:
            pd.DataFrame(list(aoi_rows)).to_csv(paths["aoi"], index=False)
        if measure:
            measure_archives(scores, paths["measurements"])
        conv = root / "conv.json"
        if converter:
            converter_json(conv, converter)
        return scores, paths, conv

    def patch_inputs(self, stack, root, scores, paths, conv, output):
        for name, value in [("SCORES_DIR", scores), ("TRACK_A_CSV", paths["track"]),
                            ("OUT_CSV", output), ("SITS_INDEX_CSV", paths["index"]),
                            ("PATCH_DIR", root), ("REGISTRY_CSV", paths["registry"]),
                            ("AOI_CSV", paths["aoi"]), ("MEASUREMENTS_CSV", paths["measurements"])]:
            stack.enter_context(patch.object(merge_results, name, str(value)))
        stack.enter_context(patch.object(s1_converter, "CONVERTER_JSON", str(conv)))


class MergeMainTests(MergeHarness, unittest.TestCase):
    def run_merge(self, track_rows, archives=(), index_rows=(), converter="linear",
                  routing="sits_primary", registry_rows=None, aoi_rows=(), recompute=False,
                  measure=True):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            scores, paths, conv = self.build_inputs(root, track_rows, archives, index_rows, converter,
                                                    registry_rows, aoi_rows, measure and not recompute)
            output = root / "combined.csv"
            self.patch_inputs(stack, root, scores, paths, conv, output)
            merge_results.main(routing, recompute_from_npz=recompute)
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

    def test_s1_then_s2_main_needs_no_track_b_or_converter(self):
        result = self.run_merge([track_a_row(), track_a_row(event_district_id="E1::b", district="B", area_s1_km2=None)],
                                [("E1::a", {})], converter=None, routing="s1_then_s2")
        a, b = result.iloc[0], result.iloc[1]
        self.assertEqual((a["satellite_source"], a["combined_km2"], a["route_reason"]),
                         ("S1", 12.0, "s1_primary"))
        self.assertEqual(a["routing_mode"], "s1_then_s2")
        self.assertEqual(a["sits_status"], "ok")          # SITS columns kept for reference
        self.assertTrue(pd.notna(a["sits_ndwi_gated_km2"]))
        self.assertEqual((b["satellite_source"], b["combined_km2"], b["route_reason"]),
                         ("NDWI", 5.0, "s2_fallback"))
        self.assertTrue(pd.isna(a["converter_decision"]))

    def test_sits_then_track_a_main_leaves_no_district_out(self):
        tracks = [track_a_row(),
                  track_a_row(event_district_id="E1::b", district="B", area_s1_km2=7.0),
                  track_a_row(event_district_id="E1::c", district="C", area_s1_km2=None)]
        result = self.run_merge(
            tracks, [("E1::a", {})], converter=None, routing="sits_then_track_a",
            index_rows=[{"status": "OK", "kept_tiles": 60},
                        {"event_district_id": "E1::c", "district": "C",
                         "status": "SKIPPED_NO_IMAGERY", "reason": "no_post_imagery"}])
        rows = result.set_index("event_district_id")
        self.assertEqual(rows.loc["E1::a", "satellite_source"], "SITS_NDWI")      # Track B measured
        self.assertAlmostEqual(rows.loc["E1::a", "combined_km2"], 25 * 800 * 90 / 1e6, places=4)
        self.assertEqual(tuple(rows.loc["E1::b", ["satellite_source", "combined_km2", "route_reason"]]),
                         ("S1", 7.0, "track_a_sits_pending"))                   # Track B not run
        self.assertEqual(tuple(rows.loc["E1::c", ["satellite_source", "combined_km2", "route_reason"]]),
                         ("NDWI", 5.0, "track_a_sits_unavailable"))             # Track B: no imagery
        self.assertEqual(rows.loc["E1::c", "sits_reason"], "no_post_imagery")
        self.assertFalse(rows["combined_km2"].isna().any())
        self.assertTrue(rows["converter_decision"].isna().all())               # no converter used

    def test_stale_track_a_rows_are_not_reused_but_keep_their_row(self):
        result = self.run_merge([track_a_row(),
                                 track_a_row(event_district_id="E1::b", district="B",
                                             spec_version="fs1-000000000000")])
        self.assertEqual(result["event_district_id"].tolist(), ["E1::a", "E1::b"])
        b = result.iloc[1]
        self.assertEqual(b["track_a_status"], "not_run")
        self.assertTrue(pd.isna(b["s1_flood_km2"]))
        self.assertTrue(pd.isna(b["combined_km2"]))

    def test_track_a_error_rows_are_recorded_not_routed(self):
        result = self.run_merge([track_a_row(baseline_status="OK"),
                                 track_a_row(event_district_id="E1::b", district="B",
                                             area_s1_km2=None, area_s2_km2=None,
                                             baseline_status="ERROR: Computation timed out.")],
                                routing="s1_then_s2", converter=None)
        self.assertEqual(result["event_district_id"].tolist(), ["E1::a", "E1::b"])
        self.assertEqual(result.loc[0, "geometry_id"], "G1")
        self.assertEqual(result["track_a_status"].tolist(), ["measured", "error"])
        self.assertEqual(result.loc[1, "satellite_source"], "NONE")
        self.assertTrue(pd.isna(result.loc[1, "combined_km2"]))

    def test_missing_track_a_is_an_error(self):
        with patch.object(merge_results, "TRACK_A_CSV", "does/not/exist.csv"):
            with self.assertRaises(FileNotFoundError):
                merge_results.main()

    def test_missing_registry_is_an_error(self):
        with patch.object(merge_results, "REGISTRY_CSV", "does/not/exist.csv"):
            with self.assertRaisesRegex(FileNotFoundError, "registry"):
                merge_results.main()

    def test_npz_without_track_a_row_is_recorded_not_fatal(self):
        # Previously a ValueError that discarded the whole merge.
        result = self.run_merge([track_a_row()], [("E1::zzz", {})], recompute=True,
                                registry_rows=registry_rows_for([track_a_row()], ["E1::zzz"]))
        self.assertEqual(result["event_district_id"].tolist(), ["E1::a", "E1::zzz"])
        self.assertEqual(result.loc[1, "track_a_status"], "not_run")

    def test_sits_measurement_without_track_a_row_still_routes(self):
        aoi = {**IDENTITY, "event_district_id": "E1::zzz", "district": "ZZZ", "aoi_level": "district",
               "aoi_source": "gb", "aoi_match_status": "matched", "aoi_area_km2": 90.0,
               "spec_version": SPEC_VERSION}
        result = self.run_merge([track_a_row()], [("E1::zzz", {"event_district_id": np.array("E1::zzz"),
                                                               "district": np.array("ZZZ")})],
                                registry_rows=registry_rows_for([track_a_row()], ["E1::zzz"]),
                                aoi_rows=[aoi])
        row = result.set_index("event_district_id").loc["E1::zzz"]
        self.assertEqual((row["track_a_status"], row["sits_measure_status"]), ("not_run", "measured"))
        self.assertEqual(row["aoi_match_status"], "matched")
        # SITS stands on its own tiles; the usable fraction needs Track A's eligible area.
        self.assertEqual(row["satellite_source"], "SITS_NDWI")
        self.assertAlmostEqual(row["combined_km2"], 25 * 800 * 90 / 1e6, places=4)

    def test_registry_without_any_input_is_a_not_run_row(self):
        result = self.run_merge([track_a_row()],
                                registry_rows=registry_rows_for([track_a_row()], ["E9::x"]))
        self.assertEqual(len(result), 2)
        row = result.set_index("event_district_id").loc["E9::x"]
        self.assertEqual((row["track_a_status"], row["track_b_patch_status"], row["sits_measure_status"]),
                         ("not_run", "not_run", "not_run"))
        self.assertEqual((row["satellite_source"], row["route_reason"]), ("NONE", "aoi_failed"))

    def test_status_columns_are_filled_on_every_row(self):
        result = self.run_merge([track_a_row(), track_a_row(event_district_id="E1::b", district="B")],
                                [("E1::a", {})],
                                index_rows=[{"status": "OK", "kept_tiles": 60},
                                            {"event_district_id": "E1::b", "district": "B",
                                             "status": "ERROR: boom"}],
                                registry_rows=registry_rows_for([track_a_row()], ["E1::b", "E1::c"]))
        self.assertEqual(len(result), 3)
        for column in ("track_a_status", "track_b_patch_status", "sits_measure_status"):
            self.assertFalse(result[column].isna().any(), column)
        by_key = result.set_index("event_district_id")
        self.assertEqual(by_key.loc["E1::a", "track_b_patch_status"], "ok")
        self.assertEqual(by_key.loc["E1::b", "track_b_patch_status"], "error")
        self.assertEqual(by_key.loc["E1::c", "track_b_patch_status"], "not_run")
        self.assertEqual(by_key["sits_measure_status"].tolist(), ["measured", "not_run", "not_run"])

    def test_incomplete_patch_download_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(merge_results, "PATCH_DIR", tmp):
            Path(tmp, f"{cache_stem('E1::a')}.h5.blocks.json").write_text("[0]")
            self.assertEqual(merge_results.track_b_patch_status("E1::a", {"status": "OK"}), "incomplete")

    def test_npz_without_spec_or_layout_rejected_on_recompute(self):
        with self.assertRaisesRegex(ValueError, "another spec"):
            self.run_merge([track_a_row()], [("E1::a", {"spec_version": None})], recompute=True)
        with self.assertRaisesRegex(ValueError, "layout"):
            self.run_merge([track_a_row()], [("E1::a", {"layout_version": np.array("h5-1")})], recompute=True)
        with self.assertRaisesRegex(ValueError, "s1_flood_km2"):
            self.run_merge([track_a_row()], [("E1::a", {"s1_flood_km2": None})], recompute=True)

    def test_stale_measurement_rows_are_ignored(self):
        for changes in ({"spec_version": np.array("fs1-000000000000")}, {"layout_version": np.array("h5-1")}):
            with self.subTest(changes=list(changes)):
                row = self.run_merge([track_a_row()], [("E1::a", changes)]).iloc[0]
                self.assertEqual((row["sits_measure_status"], row["sits_status"]), ("not_run", "pending"))

    def test_measurement_with_wrong_identity_is_dropped_not_fatal(self):
        row = self.run_merge([track_a_row()], [("E1::a", {"geometry_id": np.array("G-other")})]).iloc[0]
        self.assertEqual(row["sits_measure_status"], "not_run")
        self.assertEqual(row["route_reason"], "sits_pending")

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
