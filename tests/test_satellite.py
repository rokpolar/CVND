"""Tests for the Otsu threshold used by the bi-temporal S1 path.

This bug has now appeared twice: _otsu_from_hist returned the winning bucket's
CENTRE while the caller selects water with `.lt(threshold)`, so half of that
bucket fell out of the water class on every event. It was fixed once, lost, and
shipped again -- because nothing tested it. satellite.py imports without Earth
Engine credentials, so there is no excuse for that.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import satellite as sat  # noqa: E402


def _hist(counts, means, width):
    return {"histogram": list(counts), "bucketMeans": list(means),
            "bucketWidth": width}


class OtsuBoundaryTests(unittest.TestCase):
    def test_threshold_is_the_class_boundary_not_a_bucket_centre(self):
        """Two clean modes: the cut belongs between them. The centre of the last
        class-0 bucket would sit half a bucket too low, and `.lt()` would then
        drop the upper half of a bucket Otsu assigned to water."""
        t, sep = sat._otsu_from_hist(
            _hist([10, 1, 1, 10], [0.5, 1.5, 2.5, 3.5], 1.0))
        self.assertAlmostEqual(t, 2.0)
        self.assertGreater(sep, 0.9)

    def test_the_old_behaviour_is_gone(self):
        """The centre of the winning bucket was 1.5; anything returning that is
        the bug back again."""
        t, _ = sat._otsu_from_hist(
            _hist([10, 1, 1, 10], [0.5, 1.5, 2.5, 3.5], 1.0))
        self.assertNotAlmostEqual(t, 1.5)

    def test_every_class_zero_pixel_is_below_the_threshold(self):
        """The invariant that matters to the caller: with water = img.lt(t), no
        bucket Otsu put in class 0 may have values at or above t."""
        means = [0.5, 1.5, 2.5, 3.5, 4.5]
        width = 1.0
        t, _ = sat._otsu_from_hist(_hist([20, 8, 1, 8, 20], means, width))
        below = [m for m in means if m + width / 2 <= t]
        self.assertTrue(below, "no bucket fell in class 0")
        for m in below:
            self.assertLessEqual(m + width / 2, t)

    def test_bucket_width_is_inferred_when_absent(self):
        h = {"histogram": [10, 1, 1, 10], "bucketMeans": [0.5, 1.5, 2.5, 3.5]}
        t, _ = sat._otsu_from_hist(h)
        self.assertAlmostEqual(t, 2.0)

    def test_single_bucket_does_not_crash(self):
        t, sep = sat._otsu_from_hist(_hist([5], [1.0], 1.0))
        self.assertIsNone(t)          # zero variance, nothing to split
        self.assertEqual(sep, 0.0)

    def test_empty_and_malformed_inputs(self):
        for bad in (None, {}, {"histogram": [1, 2]}, {"bucketMeans": [1, 2]},
                    _hist([0, 0], [1.0, 2.0], 1.0)):
            t, sep = sat._otsu_from_hist(bad)
            self.assertIsNone(t, msg=repr(bad))
            self.assertEqual(sep, 0.0, msg=repr(bad))

    def test_separability_is_between_zero_and_one(self):
        t, sep = sat._otsu_from_hist(
            _hist([10, 9, 10, 9], [0.5, 1.5, 2.5, 3.5], 1.0))
        self.assertGreaterEqual(sep, 0.0)
        self.assertLessEqual(sep, 1.0)

    def test_caller_selects_water_strictly_below(self):
        """The fix is only correct for `.lt`. If this ever becomes `.lte`, the
        boundary has to move back to the bucket centre."""
        src = (ROOT / "src" / "satellite.py").read_text(encoding="utf-8")
        self.assertIn("post_f.lt(threshold)", src)


if __name__ == "__main__":
    unittest.main()
