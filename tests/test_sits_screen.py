"""Track B screen: Track B's decisions per district without downloading.

The screen must reach the decision Track B plus the merge would reach: the
same B1-B3 checks, the same retained tiles, the same usable-pixel area. The
equivalence test runs one synthetic block through Track B's own code
(_tiles_from_block -> usable_pixels) and through the screen's arithmetic.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_sits_inference  # noqa: E402
import satellite  # noqa: E402
import sits_screen  # noqa: E402
from fake_ee import FakeEE  # noqa: E402
from flood_spec import SPEC, SPEC_VERSION  # noqa: E402
from test_district_satellite import ROW, aux_block, fake_aoi, timestep_block  # noqa: E402

P = SPEC.sits_patch_px
KEEP = SPEC.sits_keep_valid


def groups(per_tile: dict, key="mean") -> dict:
    return {"groups": [{"tile": tile, key: value} for tile, value in per_tile.items()]}


class RuleTests(unittest.TestCase):
    def test_every_timestep_separately(self):
        by_time = {"0": groups({1: 1.0, 2: 0.9, 3: 0.69}),
                   "1": groups({1: 0.7, 2: 0.5, 3: 1.0})}
        self.assertEqual(sits_screen.retained_tile_ids(by_time, 2, KEEP), {1})
        self.assertEqual(sits_screen.retained_tile_ids({}, 2, KEEP), set())
        # The download pre-screen shares the rule.
        self.assertTrue(satellite._screen_groups_have_tile(by_time, 2, KEEP))
        self.assertFalse(satellite._screen_groups_have_tile({"0": groups({3: 0.1})}, 1, KEEP))

    def test_usable_counts_only_on_retained_tiles(self):
        block = {"0": groups({1: 1.0, 2: 0.2}), "usable": groups({1: 3e6, 2: 9e6}, "sum"),
                 "eligible": {"eligible": 20e6}}
        other = {"0": groups({5: 0.8}), "usable": groups({5: 1e6}, "sum"),
                 "eligible": {"eligible": 5e6}}
        self.assertEqual(sits_screen.summarize_blocks([block, other], 1, KEEP),
                         {"kept_tiles": 2, "usable_km2": 4.0, "eligible_km2": 25.0})

    def test_decision_follows_track_b_then_merge_order(self):
        decide = sits_screen.screen_decision
        self.assertEqual(decide(0, 0, False), ("track_a_expected", "no_post_imagery", None))
        self.assertEqual(decide(3, 0, False), ("track_a_expected", "no_pre_imagery", None))
        self.assertEqual(decide(3, 5, False), ("track_a_expected", "no_clear_baseline", None))
        self.assertEqual(decide(3, 5, True, 0, 0.0, 90.0), ("track_a_expected", "no_retained_tiles", None))
        self.assertEqual(decide(3, 5, True, 12, 0.0, 90.0), ("track_a_expected", "no_usable_pixels", 0.0))
        self.assertEqual(decide(3, 5, True, 12, 35.9, 90.0)[:2], ("track_a_expected", "usable_below_min"))
        self.assertEqual(decide(3, 5, True, 12, 36.0, 90.0), ("sits_expected", "ok", 0.4))
        # The merge keeps SITS when it has no eligible area to divide by.
        self.assertEqual(decide(3, 5, True, 12, 1.0, None), ("sits_expected", "ok", None))


class EquivalenceWithTrackBTests(unittest.TestCase):
    """One 2x2-tile block through Track B's code and through the screen."""

    def setUp(self):
        H = W = 2 * P
        self.arrs = [timestep_block(H, W) for _ in range(5)]
        # tile (0,0): clear everywhere
        # tile (0,1): 40% cloud in timestep 2 only -> dropped
        self.arrs[2]["valid"][: int(0.4 * P), P:] = 0
        # tile (1,0): 20% cloud per timestep, at different places -> kept,
        # but fewer pixels are clear in *every* timestep
        for t in range(5):
            rows = slice(P + t * 10, P + t * 10 + int(0.2 * P))
            self.arrs[t]["valid"][rows, :P] = 0
        # tile (1,1): 35% cloud in timestep 0 -> dropped
        self.arrs[0]["valid"][P:P + int(0.35 * P), P:] = 0
        aux = aux_block(H, W)
        aux["area"] = 99.5
        aux["eligible"][:5, :] = 0                      # permanent water / steep strip
        aux["inside"][:, :3] = 0                        # outside the district
        aux["ndwi_pre"][10:14, 10:14] = satellite.NDWI_NODATA
        aux["ndwi_post"][P + 40:P + 44, 3:9] = satellite.NDWI_NODATA
        self.aux = aux

    def track_b(self):
        tiles = satellite._tiles_from_block(self.arrs, self.aux)
        usable = run_sits_inference.usable_pixels(np.stack(tiles["ndwi_ref"]), np.stack(tiles["mask"]),
                                                  satellite.NDWI_NODATA)
        usable_m2 = sum(float(n) * float(a) for n, a in zip(usable.sum(axis=(1, 2)), tiles["pixel_area_m2"]))
        return {r * 2 + c for r, c in tiles["rc"]}, usable_m2 / 1e6

    def screen(self):
        """The screen's reductions, evaluated with numpy on the same pixels."""
        rows, cols = np.indices(self.aux.shape)
        tile = (rows // P) * 2 + cols // P
        valid = [a["valid"].astype(bool) for a in self.arrs]
        eligible = self.aux["eligible"].astype(bool) & self.aux["inside"].astype(bool)
        observed = ((self.aux["ndwi_pre"] != satellite.NDWI_NODATA)
                    & (self.aux["ndwi_post"] != satellite.NDWI_NODATA))
        usable = eligible & np.logical_and.reduce(valid) & observed
        area = self.aux["area"].astype(float)
        stats = {str(t): groups({i: float(v[tile == i].mean()) for i in range(4)})
                 for t, v in enumerate(valid)}
        stats["usable"] = groups({i: float((usable * area)[tile == i].sum()) for i in range(4)}, "sum")
        stats["eligible"] = {"eligible": float((eligible * area).sum())}
        return sits_screen.summarize_blocks([stats], len(valid), KEEP)

    def test_same_tiles_and_usable_area_as_track_b(self):
        kept, usable_km2 = self.track_b()
        screen = self.screen()
        self.assertEqual(kept, {0, 2})
        self.assertEqual(screen["kept_tiles"], len(kept))
        self.assertAlmostEqual(screen["usable_km2"], usable_km2, places=9)
        self.assertGreater(usable_km2, 0)

    def test_eligible_area_is_track_as_block_sum(self):
        eligible_m2 = satellite.block_stats(self.aux, -15.0)[1]
        self.assertAlmostEqual(self.screen()["eligible_km2"], eligible_m2 / 1e6, places=9)


class ScreenDistrictTests(unittest.TestCase):
    """screen_sits_patch on the fake Earth Engine client: decisions, no download."""

    BASELINE = [(f"2019-0{m}", None, 0.9, 0.1) for m in range(1, 5)]

    def run_screen(self, size=2, baseline=True, block_stats=None):
        fake = FakeEE(size=lambda node: size)
        base = [(tag, fake.Image(f"t{i}"), c, w) for i, (tag, _, c, w) in enumerate(self.BASELINE)]
        forbidden = AssertionError("the screen must not download pixels")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(satellite, "ee", fake), \
                patch.object(satellite, "SITS_OUTPUT_DIR", tmp), \
                patch.object(satellite, "resolve_aoi", lambda row, spec=SPEC: fake_aoi(fake)), \
                patch.object(satellite, "_pick_baseline", lambda *a, **k: base if baseline else None) as pick, \
                patch.object(satellite, "_aoi_blocks", lambda region, grid, b=None: ([(0, 0, 0), (1, 0, 16)], 2)), \
                patch.object(satellite, "_screen_block_stats",
                             side_effect=block_stats or (lambda *a, **k: {})) as stats, \
                patch.object(satellite, "_fetch_npy", side_effect=forbidden), \
                patch.object(satellite, "_download_block", side_effect=forbidden), \
                patch.object(satellite, "_download_block_arrays", side_effect=forbidden):
            row = satellite.screen_sits_patch(pd.Series(ROW))
            self.assertEqual(list(Path(tmp).iterdir()), [])          # no H5, no checkpoint
        return row, stats

    def test_no_post_imagery_stops_before_baseline(self):
        row, stats = self.run_screen(size=0)
        self.assertEqual((row["screen_result"], row["screen_reason"]), ("track_a_expected", "no_post_imagery"))
        stats.assert_not_called()

    def test_no_clear_baseline(self):
        row, stats = self.run_screen(baseline=False)
        self.assertEqual(row["screen_reason"], "no_clear_baseline")
        stats.assert_not_called()

    def test_block_reductions_decide(self):
        good = {str(t): groups({7: 1.0}) for t in range(5)}
        good.update(usable=groups({7: 36e6}, "sum"), eligible={"eligible": 90e6})
        row, stats = self.run_screen(block_stats=lambda *a, **k: good)
        self.assertEqual(stats.call_count, 2)                            # one request per AOI block
        self.assertEqual((row["screen_result"], row["screen_reason"]), ("sits_expected", "ok"))
        self.assertEqual((row["kept_tiles"], row["blocks"]), (2, 2))
        self.assertAlmostEqual(row["usable_frac"], 72 / 180)
        self.assertEqual((row["geometry_id"], row["spec_version"]), ("G1", SPEC_VERSION))
        self.assertEqual(row["baseline_months"], "2019-01|2019-02|2019-03|2019-04")

        cloudy = dict(good, usable=groups({7: 10e6}, "sum"))
        row, _ = self.run_screen(block_stats=lambda *a, **k: cloudy)
        self.assertEqual((row["screen_result"], row["screen_reason"]), ("track_a_expected", "usable_below_min"))


class ScreenRunTests(unittest.TestCase):
    def events(self, **changes):
        return pd.DataFrame([{**ROW, **changes}, {**ROW, "event_district_id": "E1::b", "district": "B"}])

    def fake_screen(self, calls, fail=()):
        def screen(row, spec=SPEC):
            calls.append(row["event_district_id"])
            if row["event_district_id"] in fail:
                raise RuntimeError("EE timeout")
            return {**{c: row.get(c) for c in sits_screen.IDENTITY_COLUMNS},
                    "screen_result": "sits_expected", "screen_reason": "ok", "kept_tiles": 3,
                    "spec_version": SPEC_VERSION, "screen_version": sits_screen.SCREEN_VERSION}
        return screen

    def test_resumes_retries_errors_and_rescreens_changed_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.csv"
            calls = []
            with patch.object(satellite, "screen_sits_patch", self.fake_screen(calls, fail={"E1::b"})):
                satellite.run_track_b_screen(self.events(), path=path)
            self.assertEqual(calls, ["E1::a", "E1::b"])
            rows = sits_screen.load_screen(path)
            self.assertEqual(rows["E1::b"]["screen_result"], "error")

            calls.clear()
            with patch.object(satellite, "screen_sits_patch", self.fake_screen(calls)):
                satellite.run_track_b_screen(self.events(), path=path)
            self.assertEqual(calls, ["E1::b"])                               # only the error row
            calls.clear()
            with patch.object(satellite, "screen_sits_patch", self.fake_screen(calls)):
                satellite.run_track_b_screen(self.events(start_date="2020-07-02"), path=path)
            self.assertEqual(calls, ["E1::a"])                               # registry row changed
            self.assertEqual(len(pd.read_csv(path)), 2)                      # upsert, no duplicates


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "src" / "satellite.py"), *args],
                              capture_output=True, text=True, cwd=ROOT, timeout=300)

    def test_screen_only_needs_track_b_on_earth_engine(self):
        done = self.run_cli("--track", "A", "--screen-only")
        self.assertEqual(done.returncode, 2)
        self.assertIn("--screen-only screens Track B", done.stderr)
        done = self.run_cli("--track", "B", "--screen-only", "--backend", "cdse-local")
        self.assertEqual(done.returncode, 2)
        self.assertIn("use --backend gee", done.stderr)


if __name__ == "__main__":
    unittest.main()
