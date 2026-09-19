"""Track A / Track B / merge are stored apart, and the merge is re-runnable.

The merge must be a pure function of the Track A table and the Track B
measurement table: no score archive, nothing written upstream, one row per
registry district, and a second routing into a second file.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_flood_area_table  # noqa: E402
import merge_results  # noqa: E402
import sits_measure  # noqa: E402
from district_keys import cache_stem  # noqa: E402
from flood_spec import COMBINED_COLUMNS, SPEC_VERSION  # noqa: E402
from test_merge_routing import (IDENTITY, MergeHarness, registry_rows_for,  # noqa: E402
                                score_archive, track_a_row)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else None


class ReMergeTests(MergeHarness, unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tracks = [track_a_row(), track_a_row(event_district_id="E1::b", district="B", area_s1_km2=4.0)]
        self.registry = registry_rows_for(self.tracks, ["E1::c"])
        self.scores, self.paths, self.conv = self.build_inputs(
            self.root, self.tracks, [("E1::a", {})],
            index_rows=[{"status": "OK", "kept_tiles": 60},
                        {"event_district_id": "E1::b", "district": "B", "status": "SKIPPED_NO_IMAGERY"}],
            registry_rows=self.registry)

    def tearDown(self):
        self._tmp.cleanup()

    def merge(self, routing, output, recompute=False):
        with ExitStack() as stack:
            self.patch_inputs(stack, self.root, self.scores, self.paths, self.conv, self.root / "default.csv")
            merge_results.main(routing, output=output, recompute_from_npz=recompute)
        return pd.read_csv(output)

    def upstream(self):
        files = [*self.paths.values(), self.conv, *sorted(self.scores.glob("*")),
                 *sorted(self.root.glob("*.h5"))]
        return {str(path): digest(path) for path in files}

    def test_two_routings_from_the_tables_alone(self):
        before = self.upstream()
        shutil.rmtree(self.scores)            # no NPZ at all
        sits = self.merge("sits_primary", self.root / "combined.sits.csv")
        s1 = self.merge("s1_then_s2", self.root / "combined.s1.csv")

        self.assertNotEqual(digest(self.root / "combined.sits.csv"), digest(self.root / "combined.s1.csv"))
        self.assertFalse((self.root / "default.csv").exists())
        after = {path: value for path, value in self.upstream().items() if "scores" not in path}
        self.assertEqual(after, {p: v for p, v in before.items() if "scores" not in p})

        for frame in (sits, s1):
            self.assertEqual(len(frame), len(self.registry))
            self.assertEqual(list(frame.columns), list(COMBINED_COLUMNS))
        self.assertEqual(sits.set_index("event_district_id").loc["E1::a", "satellite_source"], "SITS_NDWI")
        self.assertEqual(s1.set_index("event_district_id").loc["E1::a", "satellite_source"], "S1")
        self.assertEqual(sits.set_index("event_district_id").loc["E1::b", "satellite_source"], "S1_TO_SITS")

    def test_table_merge_equals_archive_recompute(self):
        for routing in ("sits_primary", "s1_then_s2", "sits_then_track_a"):
            with self.subTest(routing=routing):
                table = self.merge(routing, self.root / f"table.{routing}.csv")
                archive = self.merge(routing, self.root / f"npz.{routing}.csv", recompute=True)
                pd.testing.assert_frame_equal(table, archive)

    def test_merge_opens_no_upstream_file_for_writing(self):
        protected = {os.path.normcase(os.path.abspath(p)) for p in self.upstream()}
        real_open = open

        def guarded(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and any(flag in mode for flag in "wax+"):
                if os.path.normcase(os.path.abspath(file)) in protected:
                    raise AssertionError(f"merge opened upstream {file} with mode {mode}")
            return real_open(file, mode, *args, **kwargs)

        import builtins
        with patch.object(builtins, "open", guarded):
            self.merge("sits_primary", self.root / "guarded.csv")


class MeasurementTableTests(unittest.TestCase):
    def test_row_round_trips_to_the_same_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{cache_stem('E1::a')}.npz"
            score_archive(path)
            table = Path(tmp) / "m.csv"
            with np.load(path) as archive:
                expected = sits_measure.sits_candidates(archive)
                sits_measure.upsert_measurements([sits_measure.measurement_row(archive)], table)
            stored = sits_measure.load_measurements(table)["E1::a"]
            self.assertEqual(sits_measure.candidates_from_row(stored), expected)
            self.assertEqual(int(stored["n_tiles"]), 60)
            self.assertEqual(list(pd.read_csv(table).columns), list(sits_measure.MEASUREMENT_COLUMNS))

    def test_upsert_replaces_one_district_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "m.csv"
            rows = []
            for key in ("E1::a", "E1::b", "E1::c"):
                path = Path(tmp) / f"{cache_stem(key)}.npz"
                score_archive(path, event_district_id=np.array(key))
                with np.load(path) as archive:
                    rows.append(sits_measure.measurement_row(archive))
            sits_measure.upsert_measurements(rows, table)
            before = pd.read_csv(table, dtype=str)

            rerun = dict(rows[1], patches_sha256="p-rerun", sits_ndwi_full_km2=9.0)
            sits_measure.upsert_measurements([rerun], table)
            after = pd.read_csv(table, dtype=str)

            self.assertEqual(after["event_district_id"].tolist(), ["E1::a", "E1::b", "E1::c"])
            pd.testing.assert_frame_equal(after.iloc[[0, 2]].reset_index(drop=True),
                                          before.iloc[[0, 2]].reset_index(drop=True))
            self.assertEqual(after.loc[1, "patches_sha256"], "p-rerun")
            self.assertEqual(float(after.loc[1, "sits_ndwi_full_km2"]), 9.0)

    def test_unusable_district_is_still_a_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "e.npz"
            empty = {k: np.empty(0) for k in ("scores", "ndwi_flood", "ndwi_flood_km2", "tile_area_km2",
                                              "usable_px", "usable_km2", "s1_flood_km2", "block_id")}
            score_archive(path, **empty)
            with np.load(path) as archive:
                row = sits_measure.measurement_row(archive)
            self.assertEqual((row["sits_method"], row["n_tiles"]), ("", 0))
            self.assertEqual(sits_measure.candidates_from_row(row), {})


class FloodAreaGuardTests(unittest.TestCase):
    REGISTRY = {"event_district_id": "E1::a", "event_id": "E1", "source_record_id": "D1",
                "state": "Assam", "district": "A", "start_date": "2020-07-01"}

    def combined(self, **changes):
        row = {**IDENTITY, "aoi_level": "district", "aoi_match_status": "matched", "aoi_area_km2": 100.0,
               "combined_km2": 3.0, "satellite_source": "SITS_NDWI", "route_reason": "sits_gate_passed",
               "eligible_km2": 30.0, "spec_version": SPEC_VERSION}
        row.update(changes)
        return pd.DataFrame([row])

    def test_header_only_merge_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pd.DataFrame(columns=list(COMBINED_COLUMNS)).to_csv(root / "combined.csv", index=False)
            pd.DataFrame([self.REGISTRY]).to_csv(root / "registry.csv", index=False)
            done = subprocess.run([sys.executable, str(ROOT / "src" / "build_flood_area_table.py"),
                                   "--input", str(root / "combined.csv"), "--registry", str(root / "registry.csv"),
                                   "--output", str(root / "area.csv")], capture_output=True, text=True)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("no rows", done.stderr)
            self.assertFalse((root / "area.csv").exists())

    def test_measured_area_is_not_demoted_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry, output, aoi = root / "registry.csv", root / "area.csv", root / "aoi.csv"
            pd.DataFrame([self.REGISTRY]).to_csv(registry, index=False)
            pd.DataFrame([{**self.REGISTRY, "aoi_match_status": "matched", "aoi_area_km2": 100.0,
                           "geometry_id": "G1", "spec_version": SPEC_VERSION}]).to_csv(aoi, index=False)
            self.combined().to_csv(root / "good.csv", index=False)
            self.combined(combined_km2=None, satellite_source="NONE",
                          route_reason="sits_pending").to_csv(root / "bad.csv", index=False)
            real_path = build_flood_area_table.data_path
            with patch.object(build_flood_area_table, "data_path",
                              lambda key: aoi if key == "district_aoi" else real_path(key)):
                build_flood_area_table.main(str(root / "good.csv"), str(registry), str(output))
                self.assertEqual(pd.read_csv(output).loc[0, "satellite_status"], "observed")
                baseline = digest(output)
                with self.assertRaisesRegex(ValueError, "allow-demotion"):
                    build_flood_area_table.main(str(root / "bad.csv"), str(registry), str(output))
                self.assertEqual(digest(output), baseline)
                build_flood_area_table.main(str(root / "bad.csv"), str(registry), str(output),
                                            allow_demotion=True)
                self.assertNotEqual(digest(output), baseline)


@unittest.skipUnless(shutil.which("bash"), "run_pipeline.sh needs bash")
class PipelineGuardTests(unittest.TestCase):
    def run_script(self, **env):
        environment = {**os.environ, "PYTHON": sys.executable, "DRY_RUN": "1", **env}
        for name in ("SKIP_GEE", "SATELLITE_TRACK", "SATELLITE_ROUTING"):
            if name not in env:
                environment.pop(name, None)
        # The resolved path, not "bash": on Windows CreateProcess searches System32
        # first and would start WSL bash, which does not inherit this environment.
        return subprocess.run([shutil.which("bash"), str(ROOT / "scripts" / "run_pipeline.sh"), "--dry-run"],
                              capture_output=True, text=True, env=environment, cwd=ROOT, timeout=120)

    def test_non_production_routing_is_refused(self):
        done = self.run_script(SKIP_GEE="0", SATELLITE_TRACK="A", SATELLITE_ROUTING="sits_primary")
        self.assertEqual(done.returncode, 2)
        self.assertIn("requires s1_then_s2", done.stderr)
        self.assertNotIn(">>>", done.stdout)

    def test_track_b_is_refused_by_production_pipeline(self):
        done = self.run_script(SKIP_GEE="1", SATELLITE_TRACK="both", SATELLITE_ROUTING="sits_primary")
        self.assertEqual(done.returncode, 2)
        self.assertIn("Track A only", done.stderr)

    def test_defaults_only_run_track_a_s1_then_s2(self):
        done = self.run_script()
        self.assertNotIn("needs Track B", done.stderr)
        self.assertNotIn("needs cached Track B", done.stderr)
        self.assertIn("SATELLITE_TRACK=A SATELLITE_ROUTING=s1_then_s2", done.stdout)
        self.assertIn("ARTICLE_PIPELINE_MODE=frozen", done.stdout)
        self.assertIn("SKIP_GEE=0", done.stdout)
        self.assertIn("S2/SITS: Track A only", done.stdout)
        self.assertIn("src/merge_results.py --routing s1_then_s2", done.stdout)
        self.assertNotIn('src/satellite.py --track B', done.stdout)
        self.assertLess(done.stdout.index('--sensor s1'), done.stdout.index('--sensor s2'))

    def test_frozen_mode_refuses_stale_qa_without_article_writes(self):
        done = self.run_script(SKIP_GEE="1", ARTICLE_PIPELINE_MODE="frozen",
                               LLM_QA_MODEL="deliberately-stale-model")
        self.assertEqual(done.returncode, 1)
        self.assertIn("requires validated llm_complete", done.stderr)
        self.assertNotIn("district_articles.py --execute", done.stdout)
        self.assertNotIn("article_qa.py adopt-existing", done.stdout)
        self.assertNotIn("article_qa.py run-batches", done.stdout)

    def test_banner_states_s2(self):
        done = self.run_script(SKIP_GEE="1", SATELLITE_TRACK="A", SATELLITE_ROUTING="s1_then_s2")
        self.assertIn("S2/SITS: Track A only", done.stdout)


if __name__ == "__main__":
    unittest.main()
