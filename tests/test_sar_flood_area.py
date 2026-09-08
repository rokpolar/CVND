"""Resume-state tests for the streaming SAR pipeline. No torch, no Earth Engine.

The whole design rests on state being portable and crash-safe: a Colab session
dies at its quota, and the run has to continue from another account or from the
local machine with nothing but the state directory carried across.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sar_flood_area as sfa  # noqa: E402


class ProgressTests(unittest.TestCase):
    def test_missing_progress_starts_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = sfa.load_progress(tmp, "E001")
            self.assertEqual(s["done_blocks"], [])
            self.assertEqual(s["patches"], 0)
            self.assertEqual(s["counts"]["flood_px"], 0)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"done_blocks": [0, 3], "counts": {"no_water_px": 5,
                     "permanent_water_px": 2, "flood_px": 7},
                     "patches": 4, "valid_px": 99, "failed_blocks": [9],
                     "total_blocks": 20,
                     "method_version": sfa.METHOD_VERSION}
            sfa.save_progress(tmp, "E001", state)
            self.assertEqual(sfa.load_progress(tmp, "E001"), state)

    def test_progress_from_an_older_method_is_discarded(self):
        """A terrain gate or a scale change makes old counts incomparable, so
        stale state must be dropped rather than resumed on top of."""
        with tempfile.TemporaryDirectory() as tmp:
            sfa.save_progress(tmp, "E001", {
                "done_blocks": [0, 1, 2], "counts": {"no_water_px": 0,
                "permanent_water_px": 0, "flood_px": 999}, "patches": 3,
                "valid_px": 9, "failed_blocks": [], "total_blocks": 3,
                "method_version": sfa.METHOD_VERSION - 1})
            s = sfa.load_progress(tmp, "E001")
            self.assertEqual(s["done_blocks"], [])
            self.assertEqual(s["counts"]["flood_px"], 0)
            self.assertEqual(s["method_version"], sfa.METHOD_VERSION)

    def test_save_is_atomic(self):
        """Written after every block; a half-written file on a killed session
        would lose the whole event, so the write goes through a temp file."""
        with tempfile.TemporaryDirectory() as tmp:
            sfa.save_progress(tmp, "E001", sfa._fresh_state())
            leftovers = list((Path(tmp) / sfa.PROGRESS_DIR).glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_corrupt_progress_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = sfa.progress_path(tmp, "E001")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{ not json")
            s = sfa.load_progress(tmp, "E001")
            self.assertEqual(s["done_blocks"], [])

    def test_legacy_progress_gains_new_fields(self):
        """State written by an earlier version must still load."""
        with tempfile.TemporaryDirectory() as tmp:
            p = sfa.progress_path(tmp, "E001")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"done_blocks": [1],
                                     "counts": sfa._zero_counts(), "patches": 3,
                                     "method_version": sfa.METHOD_VERSION}))
            s = sfa.load_progress(tmp, "E001")
            self.assertEqual(s["failed_blocks"], [])
            self.assertIsNone(s["total_blocks"])


class CompletenessTests(unittest.TestCase):
    """An event counts as finished only when every block was classified.

    Without the check, a session killed mid-download leaves the blocks it reached
    marked done, the next run finds nothing left to do, and a partial area is
    written as final. Sikkim was once recorded complete with 0 km2 observed.
    """

    def test_result_carries_both_block_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, {"event_id": "E203", "flood_km2": 5.0,
                                    "blocks_done": 364, "blocks_total": 364,
                                    "is_control": False,
                                    "method_version": sfa.METHOD_VERSION})
            df = pd.read_csv(Path(tmp) / sfa.RESULT_NAME)
            self.assertEqual(df.loc[0, "blocks_done"], df.loc[0, "blocks_total"])

    def test_partial_progress_is_not_a_result(self):
        """Progress alone must never make an event look finished -- only a row in
        the results file does, and that row is written after the check."""
        with tempfile.TemporaryDirectory() as tmp:
            state = sfa._fresh_state()
            state["done_blocks"] = list(range(71))
            state["total_blocks"] = 364
            sfa.save_progress(tmp, "E203", state)
            self.assertEqual(sfa.finished_events(tmp), set())


class ResetTests(unittest.TestCase):
    @staticmethod
    def _seed(tmp, ev, km2=1.0):
        sfa.save_progress(tmp, ev, sfa._fresh_state())
        sfa.append_result(tmp, {"event_id": ev, "flood_km2": km2,
                                "is_control": "#ctrl" in ev,
                                "method_version": sfa.METHOD_VERSION})

    def test_resets_only_the_named_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, "E104")
            self._seed(tmp, "E203")
            sfa.reset_summary(tmp, ["E104"])
            self.assertFalse(sfa.progress_path(tmp, "E104").exists())
            self.assertTrue(sfa.progress_path(tmp, "E203").exists())
            self.assertEqual(sfa.finished_events(tmp), {"E203"})

    def test_can_reset_a_control_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, "E104")
            self._seed(tmp, "E104#ctrl-365d")
            sfa.reset_summary(tmp, ["E104#ctrl-365d"])
            self.assertEqual(sfa.finished_events(tmp), {"E104"})

    def test_all_clears_progress_and_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed(tmp, "E104")
            self._seed(tmp, "E203")
            sfa.reset_summary(tmp, ["all"])
            self.assertEqual(sfa.finished_events(tmp), set())
            self.assertEqual(
                list((Path(tmp) / sfa.PROGRESS_DIR).glob("*.json")), [])

    def test_reports_when_there_was_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("nothing to delete", sfa.reset_summary(tmp, ["E999"]))


class ControlRunTests(unittest.TestCase):
    """A control run measures the same AOI at a non-flood date. It must never be
    mistaken for the real event, or a baseline would end up in the severity model."""

    def test_control_id_is_distinct(self):
        cid = sfa.control_id("E104", -365)
        self.assertNotEqual(cid, "E104")
        self.assertIn("E104", cid)

    def test_control_id_encodes_the_offset(self):
        self.assertNotEqual(sfa.control_id("E104", -365),
                            sfa.control_id("E104", -730))

    def test_shift_date_keeps_the_season(self):
        """A year back, not six months: SAR backscatter is seasonal, so a control
        from a different season would differ for reasons other than flooding."""
        self.assertEqual(sfa.shift_date("2020-05-24", -365), "2019-05-25")

    def test_control_and_event_coexist_in_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, {"event_id": "E104", "flood_km2": 63.4,
                                    "is_control": False,
                                    "method_version": sfa.METHOD_VERSION})
            sfa.append_result(tmp, {"event_id": sfa.control_id("E104", -365),
                                    "flood_km2": 2.1, "is_control": True,
                                    "method_version": sfa.METHOD_VERSION})
            df = pd.read_csv(Path(tmp) / sfa.RESULT_NAME)
            self.assertEqual(len(df), 2)
            self.assertEqual(len(df[~df["is_control"]]), 1)


class ResultTests(unittest.TestCase):
    @staticmethod
    def _row(ev, km2, version=None):
        return {"event_id": ev, "state": "Assam", "flood_km2": km2,
                "status": "OK",
                "method_version": sfa.METHOD_VERSION if version is None else version}

    def test_append_and_sort(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, self._row("E002", 10.0))
            sfa.append_result(tmp, self._row("E001", 20.0))
            df = pd.read_csv(Path(tmp) / sfa.RESULT_NAME)
            self.assertEqual(list(df["event_id"]), ["E001", "E002"])

    def test_rerun_replaces_rather_than_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, self._row("E001", 10.0))
            sfa.append_result(tmp, self._row("E001", 99.0))
            df = pd.read_csv(Path(tmp) / sfa.RESULT_NAME)
            self.assertEqual(len(df), 1)
            self.assertEqual(df.loc[0, "flood_km2"], 99.0)

    def test_finished_events_drives_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sfa.finished_events(tmp), set())
            sfa.append_result(tmp, self._row("E001", 1.0))
            self.assertEqual(sfa.finished_events(tmp), {"E001"})

    def test_an_older_version_still_counts_as_finished(self):
        """A version bump must not silently restart a long run. Re-measuring is
        --force; the mismatch is reported, not acted on."""
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, self._row("E001", 1.0,
                                             version=sfa.METHOD_VERSION - 1))
            sfa.append_result(tmp, self._row("E002", 2.0))
            self.assertEqual(sfa.finished_events(tmp), {"E001", "E002"})

    def test_mixed_versions_are_reported(self):
        """Areas measured by different methods are not comparable, so a run has
        to say when its results file holds more than one."""
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, self._row("E001", 1.0,
                                             version=sfa.METHOD_VERSION - 1))
            sfa.append_result(tmp, self._row("E002", 2.0))
            stale = sfa.stale_versions(tmp)
            self.assertEqual(stale, {sfa.METHOD_VERSION - 1: ["E001"]})

    def test_no_warning_when_versions_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, self._row("E002", 2.0))
            self.assertEqual(sfa.stale_versions(tmp), {})

    def test_results_without_a_version_column_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            pd.DataFrame([{"event_id": "E001", "flood_km2": 1.0}]).to_csv(
                Path(tmp) / sfa.RESULT_NAME, index=False)
            self.assertEqual(sfa.finished_events(tmp), {"E001"})
            self.assertIn("(no version recorded)", sfa.stale_versions(tmp))

    def test_reset_clears_both_progress_and_result(self):
        """--force must drop both: a leftover result row marks the event finished
        again, and leftover progress resumes on top of the counts being thrown away."""
        with tempfile.TemporaryDirectory() as tmp:
            sfa.save_progress(tmp, "E001", sfa._fresh_state())
            sfa.append_result(tmp, self._row("E001", 1.0))
            sfa.append_result(tmp, self._row("E002", 2.0))

            sfa.reset_event(tmp, "E001")

            self.assertFalse(sfa.progress_path(tmp, "E001").exists())
            self.assertEqual(sfa.finished_events(tmp), {"E002"})
            self.assertTrue(sfa.progress_path(tmp, "E002").exists() is False)

    def test_drop_result_keeps_progress(self):
        """--redo: the blocks are still good, only the result is wrong. Deleting
        an hour of classified blocks to rewrite one row is pure loss."""
        with tempfile.TemporaryDirectory() as tmp:
            sfa.save_progress(tmp, "E203", sfa._fresh_state())
            sfa.append_result(tmp, self._row("E203", 5.0))
            self.assertTrue(sfa.drop_result(tmp, "E203"))
            self.assertTrue(sfa.progress_path(tmp, "E203").exists())
            self.assertEqual(sfa.finished_events(tmp), set())

    def test_drop_result_reports_when_there_was_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(sfa.drop_result(tmp, "E999"))

    def test_reset_drops_progress_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfa.save_progress(tmp, "E203", sfa._fresh_state())
            sfa.append_result(tmp, self._row("E203", 5.0))
            sfa.reset_event(tmp, "E203")
            self.assertFalse(sfa.progress_path(tmp, "E203").exists())

    def test_reset_on_unknown_event_is_harmless(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, self._row("E002", 2.0))
            sfa.reset_event(tmp, "E999")
            self.assertEqual(sfa.finished_events(tmp), {"E002"})

    def test_state_dir_is_self_contained(self):
        """Everything needed to resume must sit under state-dir -- that is what
        gets copied to Drive or to the other machine."""
        with tempfile.TemporaryDirectory() as tmp:
            sfa.save_progress(tmp, "E001", sfa._fresh_state())
            sfa.append_result(tmp, self._row("E002", 3.0))
            names = {p.name for p in Path(tmp).rglob("*") if p.is_file()}
            self.assertEqual(names, {"E001.json", sfa.RESULT_NAME})


if __name__ == "__main__":
    unittest.main()
