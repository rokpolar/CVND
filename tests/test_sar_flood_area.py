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

    def test_repeat_cycle_constant(self):
        """Sentinel-1 revisits the same relative orbit every 12 days. A control
        offset off that cycle lands on other orbits, so it measures different
        ground from a different look angle -- measured on Bihar, a -365 day
        control drew blocks from {158,12,19,85} while the event used
        {121,158,12,19}."""
        self.assertEqual(sfa.S1_REPEAT_DAYS, 12)

    def test_useful_offsets_are_on_cycle(self):
        for days in (-360, -216, -12, -720):
            self.assertEqual(days % sfa.S1_REPEAT_DAYS, 0, days)

    def test_the_offsets_already_used_were_off_cycle(self):
        for days in (-365, -214):
            self.assertNotEqual(days % sfa.S1_REPEAT_DAYS, 0, days)

    def test_shift_date_keeps_the_season(self):
        """A year back, not six months: SAR backscatter is seasonal, so a control
        from a different season would differ for reasons other than flooding."""
        self.assertEqual(sfa.shift_date("2020-05-24", -360), "2019-05-30")

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
            # The per-patch counts are part of the resumable state too: without
            # them an event and its control cannot be compared over shared
            # ground after the session that measured them is gone.
            sfa.append_patch_counts(tmp, "E001", [(0, 0, 0, 1, 0, 100)])
            names = {p.name for p in Path(tmp).rglob("*") if p.is_file()}
            self.assertEqual(names,
                             {"E001.json", "E001.csv", sfa.RESULT_NAME})
            self.assertTrue(sfa.patch_counts_path(tmp, "E001").exists())


class PeakCountTests(unittest.TestCase):
    """Half the 204 events outlast 14 days, and up to v9 only the first pass
    after onset was read -- the start of a flood, not its peak. Severe floods
    last longer, so that under-measured exactly the largest events."""

    @staticmethod
    def _pred(rows):
        import numpy as np
        return np.array(rows)

    def test_the_largest_flood_across_passes_wins(self):
        import numpy as np
        valid = np.ones((1, 2, 2), dtype=bool)
        early = self._pred([[[2, 0], [0, 0]]])      # 1 flood pixel
        peak = self._pred([[[2, 2], [2, 0]]])       # 3 flood pixels
        late = self._pred([[[2, 0], [0, 0]]])
        flood, _ = sfa.peak_counts([early, peak, late], valid)
        self.assertEqual(int(flood[0]), 3)

    def test_a_single_pass_behaves_like_before(self):
        import numpy as np
        valid = np.ones((1, 2, 2), dtype=bool)
        flood, _ = sfa.peak_counts([self._pred([[[2, 2], [0, 0]]])], valid)
        self.assertEqual(int(flood[0]), 2)

    def test_the_peak_is_taken_per_patch_not_per_block(self):
        """Different patches flood at different times; a block-level max would
        credit the whole block with one patch's worst moment."""
        import numpy as np
        valid = np.ones((2, 2, 2), dtype=bool)
        first = np.array([[[2, 2], [2, 2]], [[0, 0], [0, 0]]])   # patch 0 peaks
        second = np.array([[[0, 0], [0, 0]], [[2, 2], [2, 0]]])  # patch 1 peaks
        flood, _ = sfa.peak_counts([first, second], valid)
        self.assertEqual([int(flood[0]), int(flood[1])], [4, 3])

    def test_masked_pixels_never_count_as_flood(self):
        """Steep ground and no-data still get a class from the model."""
        import numpy as np
        valid = np.array([[[True, False], [False, False]]])
        flood, _ = sfa.peak_counts([self._pred([[[2, 2], [2, 2]]])], valid)
        self.assertEqual(int(flood[0]), 1)

    def test_permanent_water_is_tracked_separately(self):
        import numpy as np
        valid = np.ones((1, 2, 2), dtype=bool)
        flood, perm = sfa.peak_counts([self._pred([[[1, 1], [2, 0]]])], valid)
        self.assertEqual(int(flood[0]), 1)
        self.assertEqual(int(perm[0]), 2)

    def test_it_is_a_peak_not_a_union(self):
        """A union would add up each pass's false positives; the peak does not."""
        import numpy as np
        valid = np.ones((1, 2, 2), dtype=bool)
        a = self._pred([[[2, 0], [0, 0]]])
        b = self._pred([[[0, 2], [0, 0]]])
        flood, _ = sfa.peak_counts([a, b], valid)
        self.assertEqual(int(flood[0]), 1)      # union would be 2

    def test_no_passes_yields_zeros_not_a_crash(self):
        import numpy as np
        flood, perm = sfa.peak_counts([], np.ones((3, 2, 2), dtype=bool))
        self.assertEqual(list(flood), [0, 0, 0])
        self.assertEqual(list(perm), [0, 0, 0])

    def test_a_generator_of_predictions_is_accepted(self):
        """The caller passes a generator so only one pass is held in memory."""
        import numpy as np
        valid = np.ones((1, 2, 2), dtype=bool)
        gen = (self._pred([[[2, 0], [0, 0]]]) for _ in range(2))
        flood, _ = sfa.peak_counts(gen, valid)
        self.assertEqual(int(flood[0]), 1)

    def test_the_input_predictions_are_not_mutated(self):
        import numpy as np
        valid = np.array([[[True, False], [True, True]]])
        pred = self._pred([[[2, 2], [2, 2]]])
        before = pred.copy()
        sfa.peak_counts([pred], valid)
        np.testing.assert_array_equal(pred, before)


class SharedGroundTests(unittest.TestCase):
    """An event and its control do not observe the same land. Over Bihar the
    event saw 61,229 km2 and the control 80,692 km2 -- a 24% difference in the
    denominator against a gap of about one percentage point in the quantity being
    measured, so subtracting the two fractions said nothing. The difference is
    not whole blocks (the orbit assignment matched) but which patches cleared
    SAR_KEEP_VALID, so the comparison has to be per patch."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    @staticmethod
    def _rows(spec):
        """spec: {(patch_row, patch_col): (flood_px, valid_px)}"""
        return [(0, r, c, f, 0, v) for (r, c), (f, v) in spec.items()]

    def _write(self, event_id, spec):
        sfa.append_patch_counts(self.tmp, event_id, self._rows(spec))
        return sfa.load_patch_counts(self.tmp, event_id)

    def test_only_patches_both_kept_are_compared(self):
        ev = self._write("E203", {(0, 0): (100, 1000), (0, 1): (900, 1000)})
        ct = self._write("E203#c-216", {(0, 0): (50, 1000), (1, 0): (900, 1000)})
        e_frac, c_frac, shared_km2, e_only, c_only = sfa.shared_ground(ev, ct)
        self.assertAlmostEqual(e_frac, 0.1)     # (0,1) is the event's alone
        self.assertAlmostEqual(c_frac, 0.05)    # (1,0) is the control's alone
        self.assertGreater(e_only, 0)
        self.assertGreater(c_only, 0)

    def test_the_common_ground_is_the_smaller_validity(self):
        """Validity differs inside a shared patch too, so the denominator is the
        lesser of the two counts -- taking either alone credits one run with
        ground the other never saw."""
        ev = self._write("E203", {(0, 0): (400, 1000)})
        ct = self._write("E203#c-216", {(0, 0): (100, 400)})
        e_frac, c_frac, shared_km2, _, _ = sfa.shared_ground(ev, ct)
        self.assertAlmostEqual(shared_km2, 400 * (10 / 1000) ** 2)
        self.assertAlmostEqual(e_frac, 1.0)     # flood capped at common validity
        self.assertAlmostEqual(c_frac, 0.25)

    def test_no_overlap_returns_nothing(self):
        ev = self._write("E203", {(0, 0): (10, 100)})
        ct = self._write("E203#c-216", {(5, 5): (10, 100)})
        self.assertIsNone(sfa.shared_ground(ev, ct))

    def test_a_missing_side_returns_nothing(self):
        ev = self._write("E203", {(0, 0): (10, 100)})
        self.assertIsNone(sfa.shared_ground(ev, None))
        self.assertIsNone(sfa.shared_ground(None, ev))

    def test_absent_file_loads_as_none(self):
        self.assertIsNone(sfa.load_patch_counts(self.tmp, "E999"))

    def test_a_reappended_block_does_not_double_count(self):
        """A block re-run after an interrupted save appends its patches twice."""
        sfa.append_patch_counts(self.tmp, "E203", self._rows({(0, 0): (10, 100)}))
        sfa.append_patch_counts(self.tmp, "E203", self._rows({(0, 0): (20, 100)}))
        df = sfa.load_patch_counts(self.tmp, "E203")
        self.assertEqual(len(df), 1)
        self.assertEqual(int(df["flood_px"].iloc[0]), 20)   # the later run wins

    def test_reset_clears_the_patch_file(self):
        """It is append-only: left behind, the next run stacks new counts on the
        ones --force was meant to discard."""
        sfa.append_patch_counts(self.tmp, "E203", self._rows({(0, 0): (10, 100)}))
        sfa.save_progress(self.tmp, "E203", sfa._fresh_state())
        sfa.reset_event(self.tmp, "E203")
        self.assertIsNone(sfa.load_patch_counts(self.tmp, "E203"))

    def test_a_version_change_clears_the_patch_file(self):
        stale = sfa._fresh_state()
        stale["method_version"] = sfa.METHOD_VERSION - 1
        sfa.save_progress(self.tmp, "E203", stale)
        sfa.append_patch_counts(self.tmp, "E203", self._rows({(0, 0): (10, 100)}))
        sfa.load_progress(self.tmp, "E203")
        self.assertIsNone(sfa.load_patch_counts(self.tmp, "E203"))

    def test_the_comparison_uses_shared_ground_when_the_files_exist(self):
        """And says so, so a row computed over two different denominators is
        never read as evidence about the model."""
        import io
        from contextlib import redirect_stdout
        cid = sfa.control_id("E203", -216)
        self._write("E203", {(0, 0): (100, 1000), (0, 1): (900, 1000)})
        self._write(cid, {(0, 0): (50, 1000)})
        df = pd.DataFrame([
            {"event_id": "E203", "state": "Bihar", "is_control": False,
             "flood_frac_observed": 0.5},
            {"event_id": cid, "state": "Bihar", "is_control": True,
             "flood_frac_observed": 0.05},
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            sfa._print_control_comparison(df, self.tmp)
        out = buf.getvalue()
        self.assertIn("shared", out)
        self.assertNotIn("each own", out)

    def test_the_comparison_warns_when_patch_files_are_missing(self):
        import io
        from contextlib import redirect_stdout
        cid = sfa.control_id("E203", -216)
        df = pd.DataFrame([
            {"event_id": "E203", "state": "Bihar", "is_control": False,
             "flood_frac_observed": 0.06375},
            {"event_id": cid, "state": "Bihar", "is_control": True,
             "flood_frac_observed": 0.07293},
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            sfa._print_control_comparison(df, self.tmp)
        out = buf.getvalue()
        self.assertIn("each own", out)
        self.assertIn("not evidence either way", out)

    def test_redo_keeps_the_patch_file(self):
        """--redo rewrites the result row from blocks that are still good, so the
        per-patch counts behind them must survive."""
        sfa.append_patch_counts(self.tmp, "E203", self._rows({(0, 0): (10, 100)}))
        sfa.save_progress(self.tmp, "E203", sfa._fresh_state())
        sfa.append_result(self.tmp, {"event_id": "E203", "flood_km2": 1.0,
                                     "status": "OK",
                                     "method_version": sfa.METHOD_VERSION})
        sfa.drop_result(self.tmp, "E203")
        self.assertIsNotNone(sfa.load_patch_counts(self.tmp, "E203"))


if __name__ == "__main__":
    unittest.main()
