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

    def test_results_from_an_older_method_do_not_count_as_finished(self):
        """Changing the method must re-run every event without anyone having to
        delete files by hand -- mixing versions in one column is exactly the
        measurement inconsistency this pipeline exists to remove."""
        with tempfile.TemporaryDirectory() as tmp:
            sfa.append_result(tmp, self._row("E001", 1.0,
                                             version=sfa.METHOD_VERSION - 1))
            sfa.append_result(tmp, self._row("E002", 2.0))
            self.assertEqual(sfa.finished_events(tmp), {"E002"})

    def test_results_without_a_version_column_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            pd.DataFrame([{"event_id": "E001", "flood_km2": 1.0}]).to_csv(
                Path(tmp) / sfa.RESULT_NAME, index=False)
            self.assertEqual(sfa.finished_events(tmp), set())

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
