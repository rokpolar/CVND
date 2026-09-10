"""Tests for how FloodViT areas reach the severity column.

Until merge_results.py read sar_flood_area.csv, the whole SAR/FloodViT pipeline
was disconnected: severity came from the old threshold-S1 and NDWI paths, which
pick a method per event by cloud cover. Cloud cover during the monsoon tracks
rainfall, which tracks flood severity, so the measurement method was correlated
with the quantity being measured. These tests pin the wiring and the guards that
keep an unusable row out of it.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import merge_results as mr  # noqa: E402


def _csv(tmp, rows):
    p = Path(tmp) / "sar_flood_area.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)


def _row(**kw):
    base = {"event_id": "E203", "flood_km2": 3903.6, "is_control": False,
            "status": "OK", "blocks_done": 360, "blocks_total": 360,
            "method_version": 10}
    base.update(kw)
    return base


class LoadFloodVitTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_missing_file_is_not_an_error(self):
        """The file lives in the run's --state-dir (a Drive folder on Colab) and
        has to be copied in; its absence must degrade, not crash."""
        areas, ver = mr.load_floodvit(str(Path(self.tmp) / "nope.csv"))
        self.assertEqual(areas, {})
        self.assertIsNone(ver)

    def test_reads_event_areas(self):
        areas, ver = mr.load_floodvit(_csv(self.tmp, [_row()]))
        self.assertEqual(areas, {"E203": 3903.6})
        self.assertEqual(ver, 10)

    def test_controls_are_not_events(self):
        """A control is the same AOI at a no-flood date -- evidence about the
        method, not a flood to put in the study."""
        rows = [_row(), _row(event_id="E203#c-216", is_control=True,
                             flood_km2=5884.9)]
        areas, _ = mr.load_floodvit(_csv(self.tmp, rows))
        self.assertEqual(set(areas), {"E203"})

    def test_partial_runs_are_dropped(self):
        """A run that stopped early reports a smaller area for the same flood,
        which downstream cannot tell from a smaller flood."""
        rows = [_row(), _row(event_id="E104", blocks_done=200, blocks_total=360)]
        areas, _ = mr.load_floodvit(_csv(self.tmp, rows))
        self.assertEqual(set(areas), {"E203"})

    def test_skipped_events_are_dropped(self):
        rows = [_row(), _row(event_id="E001", status="SKIPPED: NO_POST_SCENE",
                             flood_km2=None)]
        areas, _ = mr.load_floodvit(_csv(self.tmp, rows))
        self.assertEqual(set(areas), {"E203"})

    def test_only_the_newest_method_version_survives(self):
        """Areas measured by different methods are not comparable -- that is why
        the version is recorded at all."""
        rows = [_row(event_id="E104", flood_km2=63.4, method_version=8),
                _row(event_id="E203", flood_km2=100.0, method_version=10)]
        areas, ver = mr.load_floodvit(_csv(self.tmp, rows))
        self.assertEqual(ver, 10)
        self.assertEqual(set(areas), {"E203"})

    def test_a_rerun_replaces_the_earlier_row(self):
        rows = [_row(flood_km2=1.0), _row(flood_km2=2.0)]
        areas, _ = mr.load_floodvit(_csv(self.tmp, rows))
        self.assertEqual(areas["E203"], 2.0)

    def test_header_only_file_is_handled(self):
        """A run that authenticated and then died leaves the header behind."""
        p = Path(self.tmp) / "empty.csv"
        pd.DataFrame(columns=list(_row())).to_csv(p, index=False)
        areas, ver = mr.load_floodvit(str(p))
        self.assertEqual(areas, {})
        self.assertIsNone(ver)

    def test_every_row_unusable_yields_nothing(self):
        rows = [_row(event_id="E001", status="SKIPPED: NO_POST_SCENE",
                     flood_km2=None)]
        areas, ver = mr.load_floodvit(_csv(self.tmp, rows))
        self.assertEqual(areas, {})
        self.assertIsNone(ver)


class OtsuBoundaryTests(unittest.TestCase):
    """Same off-by-one as satellite.py's Otsu, mirrored. w0 is a cumulative sum
    through bin i, so bin i is class 0, while callers select class 1 with
    `scores > t`. Returning the bin CENTRE put the upper half of that bin on the
    wrong side of the cut for every event."""

    def test_threshold_is_a_bin_edge_not_a_bin_centre(self):
        import numpy as np
        x = np.concatenate([np.full(200, 0.10), np.full(200, 0.90)])
        t = mr._otsu(x)
        edges = np.histogram(x, bins=64, range=(0.0, 1.0))[1]
        self.assertTrue(np.isclose(edges, t).any(),
                        f"{t} is not one of the bin edges")
        centers = (edges[:-1] + edges[1:]) / 2
        self.assertFalse(np.isclose(centers, t).any(),
                         f"{t} is a bin centre -- the bug is back")

    def test_the_cut_separates_the_two_modes(self):
        import numpy as np
        x = np.concatenate([np.full(200, 0.10), np.full(200, 0.90)])
        t = mr._otsu(x)
        self.assertGreater(t, 0.10)
        self.assertLess(t, 0.90)

    def test_every_low_bin_is_at_or_below_the_threshold(self):
        """The invariant for `scores > t`: nothing Otsu assigned to class 0 may
        end up above the cut."""
        import numpy as np
        x = np.concatenate([np.full(100, 0.05), np.full(20, 0.30),
                            np.full(100, 0.80)])
        t = mr._otsu(x)
        self.assertLessEqual(0.30, t)    # the middle mode stays in class 0

    def test_empty_input_falls_back(self):
        import numpy as np
        self.assertEqual(mr._otsu(np.array([])), 0.5)


class SourceSummaryTests(unittest.TestCase):
    def test_mixed_methods_are_called_out(self):
        out = pd.DataFrame({"combined_source":
                            ["FloodViT"] * 180 + ["NDWI(no-S1)"] * 20})
        msg = mr.summarise_sources(out)
        self.assertIn("20 event(s) are not measured by FloodViT", msg)
        self.assertIn("cloud cover", msg)

    def test_all_floodvit_raises_no_warning(self):
        out = pd.DataFrame({"combined_source": ["FloodViT"] * 200})
        self.assertNotIn("WARNING", mr.summarise_sources(out))

    def test_unmeasured_events_do_not_count_as_mixing(self):
        """'none' is a missing measurement, not a second method."""
        out = pd.DataFrame({"combined_source": ["FloodViT"] * 190 + ["none"] * 10})
        self.assertNotIn("WARNING", mr.summarise_sources(out))

    def test_no_floodvit_at_all_is_reported(self):
        out = pd.DataFrame({"combined_source": ["S1(cloud)"] * 50})
        self.assertIn("no event is measured by FloodViT",
                      mr.summarise_sources(out))


if __name__ == "__main__":
    unittest.main()
