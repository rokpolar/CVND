import inspect
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_flood_area_table  # noqa: E402
import merge_results  # noqa: E402
import s1_converter  # noqa: E402
import satellite  # noqa: E402
from district_keys import key_from_stem  # noqa: E402
from fake_ee import FakeEE, is_unweighted, reducer_kind  # noqa: E402
from flood_spec import (H5_LAYOUT_VERSION, SPEC, SPEC_VERSION, TRACK_A_COLUMNS,  # noqa: E402
                        variant_spec)

S1_ASSET = SPEC.s1_collection
S2_ASSET = SPEC.s2_collection
ROW = {"event_district_id": "E1::a", "event_id": "E1", "source_record_id": "D1",
       "state": "Assam", "district": "A", "start_date": "2020-07-01",
       "aoi_level": "district"}
UTM = "EPSG:32644"          # FakeEE centroid (80.5, 20.5)
KM2 = 1e6


def fake_aoi(fake):
    return {"geometry": fake.Geometry.Polygon("district"), "aoi_level": "district",
            "aoi_source": SPEC.gaul_level2, "aoi_match_status": "matched",
            "geometry_id": "G1", "aoi_area_km2": 120.0}


def fixed_hist(values):
    """fixedHistogram output [[bucket_min, count], ...] for the spec buckets."""
    edges = SPEC.otsu_hist_min_db + SPEC.otsu_bucket_db * np.arange(SPEC.otsu_buckets)
    return [[float(e), float(values(e + SPEC.otsu_bucket_db / 2))] for e in edges]


AREAS = {"aoi": 100 * KM2, "eligible": 90 * KM2, "builtup": 9 * KM2, "cropland": 45 * KM2,
         "post_seen": 80 * KM2, "ndwi_flood": 4 * KM2, "ndwi_pre": 1 * KM2,
         "ndwi_during": 5 * KM2, "optical_observed": 60 * KM2, "ndwi_builtup": 0.5 * KM2,
         "s1_flood": 12 * KM2, "s1_builtup": 0.2 * KM2, "s1_on_optical": 6 * KM2,
         "s1_ndwi_both": 3 * KM2}


def reduce_handler(areas=None, hist=None):
    def reduce(node, kwargs):
        kind = reducer_kind(kwargs)
        if kind == "Reducer.fixedHistogram":
            return hist or {}
        if kind == "Reducer.sum":
            return dict(areas if areas is not None else AREAS)
        return {}
    return reduce


def run_track_a(fake, spec=SPEC, **patches):
    with patch.object(satellite, "ee", fake), \
            patch.object(satellite, "resolve_aoi", lambda row, spec=SPEC: fake_aoi(fake)):
        if "measurement_mask" in patches:
            with patch.object(satellite, "measurement_mask", patches["measurement_mask"]):
                return satellite.detect_flood_baseline(pd.Series(ROW), spec)
        return satellite.detect_flood_baseline(pd.Series(ROW), spec)


def area_reductions(fake):
    return [c.target._kwargs for c in fake.named("getInfo")
            if c.target._op == "reduceRegion" and reducer_kind(c.target._kwargs) == "Reducer.sum"]


class TrackAMeasurementSpecTests(unittest.TestCase):
    def test_windows_are_spec_windows(self):
        fake = FakeEE(reduce=reduce_handler())
        run_track_a(fake)
        advances = [call.args for call in fake.named("advance")]
        self.assertIn((14, "day"), advances)
        self.assertIn((-30, "day"), advances)
        self.assertNotIn(7, [args[0] for args in advances])

    def test_masks_applied_on_s2_and_s1_paths(self):
        fake = FakeEE(reduce=reduce_handler())
        eligible = fake.Image("ELIGIBLE")
        run_track_a(fake, measurement_mask=lambda spec=SPEC: eligible)
        masked = [call.target._origins for call in fake.named("And")
                  if call.args and call.args[0] is eligible]
        self.assertTrue(any(S2_ASSET in origins for origins in masked))
        self.assertTrue(any(S1_ASSET in origins for origins in masked))

    def test_one_area_reduction_carries_every_footprint(self):
        fake = FakeEE(reduce=reduce_handler())
        row = run_track_a(fake)
        self.assertEqual(len(area_reductions(fake)), 1)
        self.assertEqual(row["area_s1_km2"], 12.0)
        self.assertEqual(row["area_s2_km2"], 4.0)
        self.assertEqual(row["grid_aoi_km2"], 100.0)
        self.assertEqual(row["eligible_km2"], 90.0)
        self.assertEqual(row["cloud_pct"], 20.0)
        self.assertAlmostEqual(row["optical_observed_frac"], 60 / 90, places=4)
        self.assertEqual(row["s1_on_optical_km2"], 6.0)
        self.assertEqual(row["s1_ndwi_both_km2"], 3.0)
        self.assertEqual(row["builtup_km2"], 9.0)
        self.assertEqual(row["grid_crs"], UTM)
        self.assertEqual(row["baseline_status"], "OK")
        self.assertEqual(row["spec_version"], SPEC_VERSION)
        self.assertTrue(set(TRACK_A_COLUMNS) <= set(row))

    def test_s2_zero_does_not_override_positive_s1(self):
        fake = FakeEE(reduce=reduce_handler({**AREAS, "ndwi_flood": 0, "ndwi_during": 0}))
        row = run_track_a(fake)
        self.assertEqual(row["area_s1_km2"], 12.0)
        self.assertEqual(row["area_s2_km2"], 0.0)
        self.assertEqual(row["baseline_status"], "OK")

    def test_reductions_use_the_district_grid_without_best_effort(self):
        fake = FakeEE(reduce=reduce_handler())
        run_track_a(fake)
        reductions = [call.target._kwargs for call in fake.named("getInfo")
                      if call.target._op == "reduceRegion"]
        self.assertEqual(len(reductions), 2)          # Otsu histogram + areas
        for kwargs in reductions:
            self.assertIs(kwargs["bestEffort"], False)
            self.assertEqual(kwargs["crs"], UTM)
            self.assertEqual(kwargs["crsTransform"], [10, 0, 500000.0, 0, -10, 2201920.0])
            self.assertNotIn("scale", kwargs)
            self.assertEqual(kwargs["maxPixels"], SPEC.max_pixels)
            # Pixels count whole: fractional mask weights must not shrink areas.
            self.assertTrue(is_unweighted(kwargs))
        self.assertTrue(fake.named("Image.pixelArea"))

    def test_otsu_fallback_flag_recorded(self):
        fake = FakeEE(reduce=reduce_handler())
        row = run_track_a(fake)
        self.assertIs(row["otsu_fallback_used"], True)
        self.assertEqual(row["otsu_threshold_db"], SPEC.otsu_fallback_db)

        hist = {"VV": fixed_hist(lambda c: np.exp(-((c + 19) ** 2)) * 50
                                 + np.exp(-((c + 11) ** 2)) * 200)}
        fake = FakeEE(reduce=reduce_handler(hist=hist))
        row = run_track_a(fake)
        self.assertIs(row["otsu_fallback_used"], False)
        self.assertTrue(SPEC.otsu_lo_db <= row["otsu_threshold_db"] <= SPEC.otsu_hi_db)

    def test_s1_orbit_filter_includes_both_passes_and_records_orbit(self):
        fake = FakeEE(reduce=reduce_handler(), orbits=("ASCENDING", "DESCENDING"))
        row = run_track_a(fake)
        self.assertIn(("orbitProperties_pass", ["ASCENDING", "DESCENDING"]),
                      [call.args for call in fake.named("Filter.inList")])
        self.assertFalse([call for call in fake.named("Filter.eq")
                          if call.args and call.args[0] == "orbitProperties_pass"])
        self.assertEqual(row["s1_orbit"], "BOTH")

    def test_no_imagery_is_missing_not_zero(self):
        fake = FakeEE(reduce=reduce_handler(), size=lambda node: 0)
        row = run_track_a(fake)
        self.assertIsNone(row["area_s1_km2"])
        self.assertIsNone(row["area_s2_km2"])
        self.assertIsNone(row["optical_observed_km2"])
        self.assertEqual(row["cloud_pct"], 100.0)
        self.assertEqual(row["baseline_status"], "NO_IMAGERY")

    def test_limit_error_splits_into_grid_rectangles(self):
        spec = replace(SPEC, reduce_split_m=1280)
        region_calls = []

        def reduce(node, kwargs):
            geometry = kwargs["geometry"]
            region_calls.append(geometry._op)
            if geometry._op == "Geometry.Polygon":
                raise Exception("Computation timed out.")
            if reducer_kind(kwargs) == "Reducer.fixedHistogram":
                return {"VV": fixed_hist(lambda c: 1.0)}
            return {"aoi": 1 * KM2, "eligible": 1 * KM2, "s1_flood": 0.5 * KM2}

        fake = FakeEE(reduce=reduce)
        row = run_track_a(fake, spec)
        # 5 x 3 tiles of 640 m, 1280 m rectangles -> 3 x 2 parts
        self.assertEqual(region_calls.count("intersection"), 12)   # histogram + areas
        self.assertEqual(row["grid_aoi_km2"], 6.0)
        self.assertEqual(row["area_s1_km2"], 3.0)
        rects = [c.args for c in fake.named("Geometry.Rectangle")]
        self.assertTrue(all(args[2] is False for args in rects))

    def test_persistent_limit_error_is_recorded_with_kind(self):
        def reduce(node, kwargs):
            raise Exception("User memory limit exceeded.")
        row = run_track_a(FakeEE(reduce=reduce))
        self.assertTrue(row["baseline_status"].startswith("ERROR"))
        self.assertEqual(row["error_kind"], "memory")

    def test_same_season_reference_and_mndwi_variants(self):
        fake = FakeEE(reduce=reduce_handler())
        run_track_a(fake, variant_spec("pre_same_season_3y"))
        self.assertEqual(len(fake.named("Filter.date")), 2 * 3)   # S2 and S1, three years
        self.assertTrue(fake.named("Filter.Or"))
        self.assertIn((-1, "year"), [c.args for c in fake.named("advance")])

        fake = FakeEE(reduce=reduce_handler())
        row = run_track_a(fake, variant_spec("mndwi"))
        self.assertIn((["B3", "B11"],), [c.args for c in fake.named("normalizedDifference")])
        self.assertNotEqual(row["spec_version"], SPEC_VERSION)

    def test_cache_row_with_stale_spec_is_discarded(self):
        self.assertTrue(satellite._cache_identity_matches({**ROW, "spec_version": SPEC_VERSION}, ROW))
        self.assertFalse(satellite._cache_identity_matches({**ROW, "spec_version": "fs1-000000000000"}, ROW))
        self.assertFalse(satellite._cache_identity_matches(dict(ROW), ROW))
        variant = satellite.spec_version(variant_spec("mndwi"))
        self.assertTrue(satellite._cache_identity_matches({**ROW, "spec_version": variant}, ROW, variant))


class MeasurementGridTests(unittest.TestCase):
    def test_utm_zone(self):
        self.assertEqual(satellite.utm_epsg(85.9, 26.1), 32645)
        self.assertEqual(satellite.utm_epsg(69.8, 23.4), 32642)
        self.assertEqual(satellite.utm_epsg(80.5, -5.0), 32744)

    def test_grid_is_snapped_and_covers_the_bounds(self):
        grid = satellite.grid_from_utm_bounds(UTM, 500003.0, 2200001.0, 503197.0, 2201919.0)
        self.assertEqual((grid.x0, grid.y0), (500000.0, 2201920.0))
        self.assertEqual((grid.npx, grid.npy), (5, 3))
        self.assertGreaterEqual(grid.x0 + grid.npx * grid.tile_m, 503197.0)
        self.assertLessEqual(grid.y0 - grid.npy * grid.tile_m, 2200001.0)

    def test_tile_count_depends_on_metric_extent_not_latitude(self):
        # The old degree grid gave 17 tiles per 16-tile block at 26°N and cut
        # 51 px strips. On a metric grid the count is the extent / 640 m.
        low = satellite.grid_from_utm_bounds("EPSG:32645", 300000, 900000, 364000, 932000)
        high = satellite.grid_from_utm_bounds("EPSG:32645", 300000, 3400000, 364000, 3432000)
        self.assertEqual((low.npx, low.npy), (100, 50))
        self.assertEqual((low.npx, low.npy), (high.npx, high.npy))

    def test_blocks_are_whole_tiles_and_partition_the_grid(self):
        grid = satellite.grid_from_utm_bounds(UTM, 0, 0, 40 * 640 - 1, 20 * 640 - 1)
        B, P = satellite.SITS_BLOCK_PATCHES, SPEC.sits_patch_px
        seen = np.zeros((grid.npy * P, grid.npx * P), dtype=int)
        for bi in range(0, grid.npy, B):
            for bj in range(0, grid.npx, B):
                row, col, h, w = grid.block(bi, bj, B)
                self.assertEqual((h % P, w % P), (0, 0))
                seen[row:row + h, col:col + w] += 1
                self.assertEqual(grid.transform(col, row)[2], grid.x0 + col * 10)
        self.assertTrue((seen == 1).all())

    def test_sub_rectangles_partition_the_grid(self):
        grid = satellite.grid_from_utm_bounds(UTM, 0, 0, 7 * 640 - 1, 5 * 640 - 1)
        rects = grid.sub_rects(1280)
        area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
        self.assertEqual(area, grid.npx * grid.npy * grid.tile_m ** 2)
        for x0, y0, x1, y1 in rects:
            self.assertEqual(((x0 - grid.x0) % 10, (y1 - grid.y0) % 10), (0, 0))


class BaselineTests(unittest.TestCase):
    def test_no_onset_month_composite(self):
        for day in (1, 14, 16, 31):
            event = datetime(2019, 7, min(day, 31))
            pool_a, pool_b = satellite.baseline_pool_months(event, 3)
            self.assertNotIn((2019, 7), pool_a + pool_b)
            self.assertEqual(pool_b, [(2019, m) for m in range(1, 7)])
            for year, month in pool_a + pool_b:
                self.assertLessEqual(satellite.month_window(year, month, event)[1], "2019-07-01")

    def test_pool_a_wraps_the_year(self):
        pool_a, _ = satellite.baseline_pool_months(datetime(2020, 1, 20), 1)
        self.assertEqual(pool_a, [(2018, 12), (2019, 1), (2019, 2)])
        pool_a, _ = satellite.baseline_pool_months(datetime(2020, 12, 20), 1)
        self.assertEqual(pool_a, [(2019, 11), (2019, 12), (2020, 1)])

    def test_month_window_is_clipped_to_onset(self):
        self.assertEqual(satellite.month_window(2019, 6, datetime(2019, 6, 20)),
                         ("2019-06-01", "2019-06-20"))
        self.assertEqual(satellite.month_window(2019, 12, datetime(2020, 3, 1)),
                         ("2019-12-01", "2020-01-01"))

    def test_choose_baseline(self):
        a = [("2018-06", None, 0.9, 0.3), ("2018-07", None, 0.6, 0.1), ("2017-06", None, 0.95, 0.4),
             ("2016-07", None, 0.4, 0.0)]
        b = [("2019-03", None, 0.8, 0.05), ("2019-04", None, 0.7, 0.2)]
        chosen = satellite.choose_baseline(a, b, 4, 0.5)
        self.assertEqual([c[0] for c in chosen], ["2017-06", "2018-06", "2018-07", "2019-03"])
        self.assertIsNone(satellite.choose_baseline(a[:1], [], 4, 0.5))


class TrackBPreparationTests(unittest.TestCase):
    def _prepare(self, fake, tmp, baseline=True):
        base = [(f"2019-0{m}", fake.Image(f"t{m}"), 0.9, 0.1) for m in range(1, 5)]
        with patch.object(satellite, "ee", fake), \
                patch.object(satellite, "SITS_OUTPUT_DIR", tmp), \
                patch.object(satellite, "resolve_aoi", lambda row, spec=SPEC: fake_aoi(fake)), \
                patch.object(satellite, "_pick_baseline", lambda *a, **k: base if baseline else None), \
                patch.object(satellite, "otsu_backscatter_threshold", lambda *a, **k: (-16.5, False, 0.8)), \
                patch.object(satellite, "_tile_region", lambda *a, **k: (0, 0)):
            return satellite.prepare_sits_patch(pd.Series(ROW))

    def test_prepare_sits_patch_writes_layout_and_grid(self):
        fake = FakeEE()
        with tempfile.TemporaryDirectory() as tmp:
            res = self._prepare(fake, tmp)
            self.assertEqual((res["status"], res["reason"], res["complete"]),
                             ("OK", "no_retained_tiles", True))
            self.assertEqual(key_from_stem(Path(res["path"]).stem), "E1::a")
            self.assertFalse(Path(res["path"] + ".blocks.json").exists())
            with h5py.File(res["path"], "r") as hdf:
                attrs = hdf["meta"].attrs
                self.assertEqual(attrs["spec_version"], SPEC_VERSION)
                self.assertEqual(attrs["layout_version"], H5_LAYOUT_VERSION)
                self.assertEqual(attrs["crs"], UTM)
                self.assertEqual(attrs["s1_threshold_db"], -16.5)
                self.assertEqual(hdf["pre"].dtype, np.uint16)
                self.assertEqual(hdf["pre"].compression, "gzip")
                for name in satellite.TILE_DATASETS + ("block_stats",):
                    self.assertIn(name, hdf)
            grid = satellite.grid_from_utm_bounds(UTM, *[500003.0, 2200001.0, 503197.0, 2201919.0])
            self.assertTrue(satellite._h5_identity_matches(res["path"], ROW, grid))
            self.assertFalse(satellite._h5_identity_matches(res["path"], ROW, grid._replace(x0=0.0)))
        advances = [call.args for call in fake.named("advance")]
        self.assertIn((14, "day"), advances)
        self.assertIn((-30, "day"), advances)
        self.assertTrue(fake.named("qualityMosaic"))           # t5 = the wettest scene

    def test_skip_reasons_are_data_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self._prepare(FakeEE(size=lambda node: 0), tmp)
            self.assertEqual((res["status"], res["reason"]), ("SKIPPED_NO_IMAGERY", "no_post_imagery"))
            res = self._prepare(FakeEE(), tmp, baseline=False)
            self.assertEqual(res["reason"], "no_clear_baseline")

    def test_t5_median_under_median_composite(self):
        fake = FakeEE()
        with patch.object(satellite, "ee", fake):
            satellite.t5_composite(fake.ImageCollection(S2_ASSET), replace(SPEC, post_composite="median"))
        self.assertFalse(fake.named("qualityMosaic"))
        self.assertTrue(fake.named("median"))


def timestep_block(h, w, value=1000, valid=1):
    dtype = np.dtype([("B4", "i2"), ("B3", "i2"), ("B2", "i2"), ("B8", "i2"), ("valid", "u1")])
    block = np.zeros((h, w), dtype=dtype)
    for band in ("B4", "B3", "B2", "B8"):
        block[band] = value
    block["valid"] = valid
    return block


def aux_block(h, w):
    dtype = np.dtype([("eligible", "u1"), ("inside", "u1"), ("area", "f4"), ("ndwi_pre", "i2"),
                      ("ndwi_post", "i2"), ("s1_pre", "i2"), ("s1_post", "i2"), ("landcover", "u1")])
    aux = np.zeros((h, w), dtype=dtype)
    aux["eligible"] = 1
    aux["inside"] = 1
    aux["area"] = 100.0
    aux["ndwi_pre"] = -500
    aux["ndwi_post"] = 800
    aux["s1_pre"] = -1000
    aux["s1_post"] = -2000
    aux["landcover"] = 40
    return aux


class TileTests(unittest.TestCase):
    def test_tiles_keep_measurement_layers(self):
        P = SPEC.sits_patch_px
        arrs = [timestep_block(P, 2 * P) for _ in range(5)]
        for a in arrs:
            a["valid"][: P // 2, P:] = 0          # second tile only 50% clear
        arrs[2]["valid"][0, 0] = 0                # one pixel cloudy in one timestep
        arrs[0]["B4"][3, 3] = -7                  # negative DN is clipped for uint16
        aux = aux_block(P, 2 * P)
        aux["eligible"][1, 1] = 0
        aux["inside"][2, 2] = 0
        tiles = satellite._tiles_from_block(arrs, aux)
        self.assertEqual(tiles["rc"], [(0, 0)])
        mask = tiles["mask"][0]
        self.assertEqual(mask[0, 0], 1 | 4)       # eligible, inside, not valid in every timestep
        self.assertEqual(mask[1, 1], 2 | 4)       # valid everywhere, not eligible
        self.assertEqual(mask[2, 2], 1 | 2)       # outside the AOI
        self.assertEqual(mask[5, 5], 7)
        self.assertEqual(tiles["pre"][0].dtype, np.uint16)
        self.assertEqual(tiles["pre"][0][0, 0, 3, 3], 0)
        np.testing.assert_array_equal(tiles["ndwi_ref"][0][:, 5, 5], [-500, 800])
        np.testing.assert_array_equal(tiles["s1_ref"][0][:, 5, 5], [-1000, -2000])
        self.assertEqual(tiles["landcover"][0][5, 5], 40)
        self.assertAlmostEqual(float(tiles["pixel_area_m2"][0]), 100.0, places=3)
        self.assertEqual(tiles["pre"][0].shape, (SPEC.sits_n_pre, 4, P, P))

    def test_block_shape_mismatch_is_an_error(self):
        P = SPEC.sits_patch_px
        with self.assertRaisesRegex(ValueError, "differ in shape"):
            satellite._tiles_from_block([timestep_block(P, P)] * 5, aux_block(P, 2 * P))

    def test_block_stats_follow_track_a_definitions(self):
        aux = aux_block(4, 4)
        aux["inside"][0] = 0                      # 4 px outside the AOI
        aux["eligible"][1, 0] = 0
        aux["ndwi_pre"][2, 0] = satellite.NDWI_NODATA
        aux["s1_post"][3, 0] = -500               # not dark after
        stats = satellite.block_stats(aux, -15.0)
        aoi, eligible, observed, ndwi, s1 = stats
        self.assertEqual(aoi, 12 * 100.0)
        self.assertEqual(eligible, 11 * 100.0)
        self.assertEqual(observed, 10 * 100.0)
        self.assertEqual(ndwi, 10 * 100.0)
        self.assertEqual(s1, 10 * 100.0)          # (3,0) not dark; outside/ineligible excluded
        self.assertTrue(np.isnan(satellite.block_stats(aux, None)[4]))

    def test_fetch_checks_the_block_shape(self):
        buffer = io.BytesIO()
        np.save(buffer, np.zeros((64, 64), dtype=[("a", "u1")]))

        class Response:
            content = buffer.getvalue()
            def raise_for_status(self): pass

        class Image:
            def getDownloadURL(self, params):
                self.params = params
                return "url"

        grid = satellite.grid_from_utm_bounds(UTM, 0, 0, 1279, 1279)
        image = Image()
        with patch.object(satellite.requests, "get", lambda *a, **k: Response()):
            satellite._fetch_npy(image, grid, 0, 0, 64, 64)
            self.assertEqual(image.params["dimensions"], "64x64")
            self.assertEqual(image.params["crs"], UTM)
            with self.assertRaisesRegex(ValueError, "expected"):
                satellite._fetch_npy(image, grid, 0, 0, 128, 64)


class ResumeTests(unittest.TestCase):
    """C2: an interruption after a block's append must not duplicate its tiles."""

    def _grid(self):
        # 20 x 1 tiles -> two blocks (16 + 4 tiles)
        return satellite.grid_from_utm_bounds(UTM, 0, 0, 20 * 640 - 1, 639)

    def _run(self, path, grid, done, fail_on_dump=None):
        fake = FakeEE(aggregate=lambda node: [0, 1])

        def download(image, grid_, row, col, h, w):
            return timestep_block(h, w, value=100 + col // 64)

        def fetch(image, grid_, row, col, h, w):
            return aux_block(h, w)

        calls = {"n": 0}
        real_dump = json.dump

        def dump(obj, handle):
            calls["n"] += 1
            if fail_on_dump is not None and calls["n"] == fail_on_dump:
                raise KeyboardInterrupt("interrupted after append")
            real_dump(obj, handle)

        ckpt = str(path) + ".blocks.json"
        with patch.object(satellite, "ee", fake), \
                patch.object(satellite, "_download_block", download), \
                patch.object(satellite, "_fetch_npy", fetch), \
                patch.object(satellite.json, "dump", dump), \
                h5py.File(path, "a" if done else "w") as f:
            if done:
                satellite.truncate_to_done(f, done)
            else:
                satellite._create_h5(f, ROW, {"geometry_id": "G1"}, grid, SPEC, -15.0, False)
            n, failed = satellite._tile_region([object()] * 5, object(), fake.Geometry.Polygon("r"),
                                               grid, f, set(done), ckpt, -15.0)
        return n

    def test_interrupted_append_is_not_duplicated(self):
        grid = self._grid()
        with tempfile.TemporaryDirectory() as tmp:
            clean = self._run(Path(tmp) / "clean.h5", grid, set())
            self.assertEqual(clean, 20)
            path = Path(tmp) / "broken.h5"
            with self.assertRaises(KeyboardInterrupt):
                self._run(path, grid, set(), fail_on_dump=2)   # block 1 appended, not recorded
            with h5py.File(path, "r") as f:
                self.assertEqual(f["block_id"].shape[0], 20)    # orphan tiles are in the file
            done = set(json.loads(Path(str(path) + ".blocks.json").read_text()))
            self.assertEqual(done, {0})
            resumed = self._run(path, grid, done)
            self.assertEqual(resumed, clean)
            with h5py.File(path, "r") as f:
                ids = f["block_id"][:]
                self.assertEqual(sorted(set(ids)), [0, 1])
                self.assertEqual(len(ids), len(set(map(tuple, f["coords"][:, :2]))))
                self.assertEqual(sorted(f["block_stats"][:, 0]), [0.0, 1.0])

    def test_truncate_rejects_out_of_order_blocks(self):
        with tempfile.TemporaryDirectory() as tmp, h5py.File(Path(tmp) / "x.h5", "w") as f:
            grid = self._grid()
            satellite._create_h5(f, ROW, {"geometry_id": "G1"}, grid, SPEC, None, False)
            for name in satellite.TILE_DATASETS:
                shape = (3,) + f[name].shape[1:]
                f[name].resize(shape[0], axis=0)
            f["block_id"][:] = [5, 7, 5]
            with self.assertRaisesRegex(ValueError, "rebuild"):
                satellite.truncate_to_done(f, {5})
            f["block_id"][:] = [5, 5, 7]
            self.assertEqual(satellite.truncate_to_done(f, {5}), 1)
            self.assertEqual(f["pre"].shape[0], 2)


class AoiTableTests(unittest.TestCase):
    def test_parallel_resolution_keeps_order_and_failures(self):
        import time
        import event_aoi_area

        class Sat:
            @staticmethod
            def resolve_aoi(row):
                time.sleep(0.02 * (3 - int(row["district"][-1])))   # later rows finish first
                if row["district"] == "d2":
                    raise ValueError("district AOI match failed")
                return {"geometry": None, "aoi_level": "district", "aoi_source": SPEC.gaul_level2,
                        "aoi_match_status": "matched", "geometry_id": row["district"],
                        "aoi_area_km2": 10.0}

        events = pd.DataFrame([{**ROW, "event_district_id": f"E1::d{i}", "district": f"d{i}"}
                               for i in range(4)])
        result = event_aoi_area.resolve_rows(events, Sat, workers=4)
        self.assertEqual(result["event_district_id"].tolist(), [f"E1::d{i}" for i in range(4)])
        self.assertEqual(result["aoi_match_status"].tolist(), ["matched", "matched", "failed", "matched"])
        self.assertIn("match failed", result.loc[2, "aoi_error"])
        self.assertTrue((result["spec_version"] == SPEC_VERSION).all())


class DeadCodeTests(unittest.TestCase):
    def test_no_raw_string_dead_code(self):
        source = inspect.getsource(satellite)
        self.assertNotIn("_OLD_", source)
        self.assertNotIn("r'''", source)
        self.assertNotIn("state AOI", source)
        self.assertNotIn("GAUL/2015/level1", source)
        self.assertFalse(hasattr(satellite, "otsu_threshold"))
        self.assertFalse(hasattr(satellite, "get_masks"))
        self.assertFalse(hasattr(satellite, "tile_grid"))


class DistrictSatelliteTests(unittest.TestCase):
    def test_every_registry_state_maps_to_a_gaul_adm1(self):
        registry = SRC.parent / "data" / "intermediate" / "event_districts.csv"
        if not registry.exists():
            self.skipTest("registry not present")
        states = set(pd.read_csv(registry)["state"].dropna())
        unmapped = {s for s in states
                    if satellite.GAUL_STATE_ALIASES.get(s, s) not in satellite.GAUL_2015_INDIA_ADM1
                    and s not in satellite.GAUL_UNAVAILABLE_STATES}
        self.assertEqual(unmapped, set())
        self.assertEqual(satellite.GAUL_STATE_ALIASES["Telangana"], "Andhra Pradesh")

    def test_unavailable_state_and_state_rows_fail_before_querying(self):
        class NoEE:
            def FeatureCollection(self, asset):
                raise AssertionError("queried GAUL")
        with patch.object(satellite, "ee", NoEE()):
            with self.assertRaisesRegex(ValueError, "no district units"):
                satellite._feature_collection_for_aoi({"event_district_id": "E1::k", "state": "Jammu and Kashmir",
                                                       "district": "Kishtwar"})
            with self.assertRaisesRegex(ValueError, "only district AOIs"):
                satellite._feature_collection_for_aoi({"event_district_id": None, "state": "Assam",
                                                       "district": "A", "aoi_level": "state"})

    def test_gaul_level2_unique_match(self):
        class Number:
            def __init__(self, value): self.value = value
            def getInfo(self): return self.value

        class Collection:
            def __init__(self, count=1, features=None):
                self.count = count
                self.features = features or []
            def filter(self, _): return self
            def size(self): return Number(self.count)
            def getInfo(self): return {"features": self.features}

        class FilterClass:
            @staticmethod
            def eq(*args): return args

        class FakeGaul:
            Filter = FilterClass
            def FeatureCollection(self, asset):
                self.asset = asset
                if "level1" in asset:
                    raise AssertionError("district AOI unexpectedly used GAUL level1")
                return Collection(count=1)

        row = {"event_district_id": "E1__a", "state": "Assam", "district": "A",
               "aoi_level": "district"}
        with patch.object(satellite, "ee", FakeGaul()):
            collection = satellite._feature_collection_for_aoi(row)
        self.assertEqual(collection.size().getInfo(), 1)

    def test_gaul_level2_missing_or_ambiguous_fails_without_state_fallback(self):
        class Number:
            def __init__(self, value): self.value = value
            def getInfo(self): return self.value

        class Collection:
            def __init__(self, count, features): self.count, self.features = count, features
            def filter(self, _): return self
            def size(self): return Number(self.count)
            def getInfo(self): return {"features": self.features}

        class FilterClass:
            @staticmethod
            def eq(*args): return args

        class FakeGaul:
            Filter = FilterClass
            def __init__(self, count, features): self.count, self.features = count, features
            def FeatureCollection(self, asset):
                if "level1" in asset:
                    raise AssertionError("district AOI unexpectedly used GAUL level1")
                return Collection(self.count, self.features)

        row = {"event_district_id": "E1__a", "state": "Assam", "district": "A",
               "aoi_level": "district"}
        for count, features in [(0, []), (2, [{"properties": {"ADM2_NAME": "A"}},
                                               {"properties": {"ADM2_NAME": "A"}}])]:
            with self.subTest(count=count), patch.object(satellite, "ee", FakeGaul(count, features)):
                with self.assertRaises(ValueError):
                    satellite._feature_collection_for_aoi(row)

    def test_district_key_forces_level2_even_when_name_equals_state(self):
        row = {"event_id": "E1", "event_district_id": "E1__assam",
               "state": "Assam", "district": "Assam", "aoi_level": "state"}
        self.assertTrue(satellite._is_district_row(row))

    def test_unicode_name_normalization_is_conservative(self):
        self.assertEqual(satellite._normalized_name("São José"), "são josé")
        self.assertNotEqual(satellite._normalized_name("São José"), satellite._normalized_name("Sao Jose"))

    def test_null_reduce_region_is_missing_but_zero_is_observed(self):
        self.assertIsNone(satellite._area_value_km2({}, "flood"))
        self.assertIsNone(satellite._area_value_km2({"flood": None}, "flood"))
        self.assertEqual(satellite._area_value_km2({"flood": 0}, "flood"), 0.0)
        self.assertEqual(satellite._area_value_km2({"flood": 2_000_000}, "flood"), 2.0)

    def test_area_table_keeps_zero_and_missing_distinct(self):
        registry = pd.DataFrame([
            {"event_district_id": "E1__a", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "A", "start_date": "2020-01-01"},
            {"event_district_id": "E1__b", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "B", "start_date": "2020-01-01"},
        ])
        combined = pd.DataFrame([
            {"event_district_id": "E1__a", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "A", "start_date": "2020-01-01",
             "combined_km2": 0.0, "aoi_area_km2": 10.0, "aoi_match_status": "matched",
             "satellite_source": "SITS_NDWI", "spec_version": SPEC_VERSION},
            {"event_district_id": "E1__b", "event_id": "E1", "source_record_id": "D1",
             "state": "Assam", "district": "B", "start_date": "2020-01-01",
             "combined_km2": None, "aoi_area_km2": None,
             "aoi_match_status": "matched", "satellite_source": "NONE",
             "spec_version": SPEC_VERSION},
        ])
        aoi = pd.DataFrame([
            {"event_district_id": "E1__a", "aoi_area_km2": 10.0, "aoi_match_status": "matched",
             "spec_version": SPEC_VERSION},
            {"event_district_id": "E1__b", "aoi_area_km2": 12.0, "aoi_match_status": "matched",
             "spec_version": SPEC_VERSION},
        ])
        result = build_flood_area_table.build_flood_area_table(combined, registry, aoi)
        self.assertEqual(result.loc[0, "flood_area_km2"], 0.0)
        self.assertEqual(result.loc[0, "analysis_observation_status"], "observed_zero")
        self.assertTrue(pd.isna(result.loc[1, "flood_area_km2"]))
        self.assertEqual(result.loc[1, "satellite_status"], "missing")

    def test_failed_aoi_cannot_emit_numeric_area(self):
        registry = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "state": "Assam",
            "district": "A", "start_date": "2020-01-01",
        }])
        combined = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "source_record_id": "D1", "state": "Assam",
            "district": "A", "start_date": "2020-01-01", "combined_km2": 4.0,
            "aoi_area_km2": 12.0, "aoi_match_status": "matched", "satellite_source": "S1_TO_SITS",
            "spec_version": SPEC_VERSION,
        }])
        aoi = pd.DataFrame([{
            "event_district_id": "E1__a", "aoi_area_km2": None,
            "aoi_match_status": "failed", "spec_version": SPEC_VERSION,
        }])
        result = build_flood_area_table.build_flood_area_table(combined, registry, aoi)
        self.assertTrue(pd.isna(result.loc[0, "flood_area_km2"]))
        self.assertTrue(pd.isna(result.loc[0, "flood_ratio"]))
        self.assertEqual(result.loc[0, "satellite_status"], "failed_aoi")
        # A failed AOI clears the flood observation, not an existing AOI area.
        self.assertEqual(result.loc[0, "aoi_area_km2"], 12.0)

    def _one_district(self, **combined):
        registry = pd.DataFrame([{
            "event_district_id": "E1::a", "event_id": "E1", "source_record_id": "D1",
            "state": "Assam", "district": "A", "start_date": "2020-01-01",
        }])
        row = {"event_district_id": "E1::a", "event_id": "E1", "source_record_id": "D1",
               "state": "Assam", "district": "A", "start_date": "2020-01-01",
               "combined_km2": 3.0, "aoi_area_km2": 99.0, "aoi_match_status": "matched",
               "satellite_source": "S1_TO_SITS", "route_reason": "sits_unavailable_converted",
               "eligible_km2": 10.0, "sits_status": "unavailable", "converter_decision": "linear",
               "legacy_combined_km2": 5.0, "legacy_satellite_source": "S1",
               "spec_version": SPEC_VERSION}
        row.update(combined)
        aoi = pd.DataFrame([{"event_district_id": "E1::a", "aoi_area_km2": 12.0,
                             "aoi_match_status": "matched", "spec_version": SPEC_VERSION}])
        return build_flood_area_table.build_flood_area_table(pd.DataFrame([row]), registry, aoi)

    def test_area_table_rejects_stale_spec_version(self):
        with self.assertRaisesRegex(ValueError, "another spec"):
            self._one_district(spec_version="fs1-000000000000")
        with self.assertRaisesRegex(ValueError, "spec_version"):
            build_flood_area_table.build_flood_area_table(
                self._one_district().drop(columns=["spec_version"]).assign(combined_km2=1.0),
                self._one_district()[["event_district_id", "event_id", "source_record_id",
                                      "state", "district", "start_date"]])

    def test_ratio_computed_once_from_aoi_artifact(self):
        result = self._one_district()
        self.assertEqual(result.loc[0, "aoi_area_km2"], 12.0)
        self.assertEqual(result.loc[0, "flood_ratio"], 0.25)
        self.assertEqual(result.loc[0, "flood_ratio_eligible"], 0.3)
        self.assertEqual(result.loc[0, "legacy_flood_area_km2"], 5.0)
        self.assertEqual(result.loc[0, "sits_status"], "unavailable")
        self.assertEqual(list(result.columns), list(build_flood_area_table.FLOOD_AREA_COLUMNS))

    def test_satellite_source_passthrough_and_status_vocab(self):
        result = self._one_district(combined_km2=None, satellite_source="NONE",
                                    route_reason="sits_pending")
        self.assertEqual(result.loc[0, "satellite_status"], "missing")
        self.assertEqual(result.loc[0, "route_reason"], "sits_pending")
        result = self._one_district(combined_km2=0.0)
        self.assertEqual(result.loc[0, "satellite_source"], "S1_TO_SITS")
        self.assertEqual(result.loc[0, "satellite_status"], "observed")
        self.assertEqual(result.loc[0, "analysis_observation_status"], "observed_zero")
        self.assertEqual(result.loc[0, "spec_version"], SPEC_VERSION)
        # A numeric area without a measured source is not an observation.
        result = self._one_district(satellite_source="NONE")
        self.assertTrue(pd.isna(result.loc[0, "flood_area_km2"]))
        self.assertEqual(result.loc[0, "satellite_status"], "missing")
        # The interim routing's S1 label is a measured source.
        result = self._one_district(satellite_source="S1", route_reason="interim_s1_only")
        self.assertEqual(result.loc[0, "flood_area_km2"], 3.0)
        # NDWI was a legacy-only label.
        result = self._one_district(satellite_source="NDWI")
        self.assertTrue(pd.isna(result.loc[0, "flood_area_km2"]))

    def test_state_combined_schema_cannot_feed_district_table(self):
        registry = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "state": "Assam",
            "district": "A", "start_date": "2020-01-01",
        }])
        combined = pd.DataFrame([{
            "event_id": "E1", "state": "Assam", "district": "A",
            "start_date": "2020-01-01", "combined_km2": 4.0,
        }])
        with self.assertRaises(ValueError):
            build_flood_area_table.build_flood_area_table(combined, registry)

    def test_identity_mismatch_is_rejected(self):
        registry = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "state": "Assam",
            "district": "A", "start_date": "2020-01-01",
        }])
        combined = pd.DataFrame([{
            "event_district_id": "E1__a", "event_id": "E1", "source_record_id": "D1", "state": "Bihar",
            "district": "A", "start_date": "2020-01-01", "combined_km2": 4.0,
            "aoi_match_status": "matched", "satellite_source": "S1_TO_SITS",
            "spec_version": SPEC_VERSION,
        }])
        with self.assertRaisesRegex(ValueError, "stale satellite identity"):
            build_flood_area_table.build_flood_area_table(combined, registry)

    def test_district_merge_ignores_parent_event_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scores = root / "scores"
            scores.mkdir()
            np.savez(scores / "E1.npz", scores=np.array([0.1]), ndwi_flood=np.array([0]))
            track = root / "track.csv"
            output = root / "combined.csv"
            # The only cache is keyed by parent event_id. A district row must
            # remain missing instead of inheriting this state observation.
            pd.DataFrame([{"event_id": "E1", "area_s1_km2": 25.0,
                           "area_s2_km2": None, "s2_post_images": 0, "cloud_pct": 100.0,
                           "event_district_id": "E1__a", "aoi_match_status": "matched",
                           "aoi_area_km2": 50.0, "state": "Assam", "district": "A",
                           "spec_version": SPEC_VERSION}]).to_csv(track, index=False)
            with (patch.object(merge_results, "SCORES_DIR", str(scores)),
                  patch.object(merge_results, "PATCH_DIR", str(root)),
                  patch.object(merge_results, "SITS_INDEX_CSV", str(root / "index.csv")),
                  patch.object(s1_converter, "CONVERTER_JSON", str(root / "conv.json")),
                  patch.object(merge_results, "TRACK_A_CSV", str(track)),
                  patch.object(merge_results, "OUT_CSV", str(output))):
                merge_results.main()
            result = pd.read_csv(output)
            self.assertNotIn("E1", set(result["event_district_id"].dropna()))
            self.assertEqual(result.loc[0, "event_district_id"], "E1__a")
            # Default interim routing: the district's own Track A S1, never the parent cache.
            self.assertEqual(result.loc[0, "combined_km2"], 25.0)
            self.assertEqual(result.loc[0, "route_reason"], "interim_s1_only")
            self.assertEqual(result.loc[0, "sits_status"], "pending")
            self.assertEqual(result.loc[0, "legacy_combined_km2"], 25.0)
            self.assertEqual(result.loc[0, "legacy_route_reason"], "no_optical_s1")
            self.assertEqual(result.loc[0, "spec_version"], SPEC_VERSION)


if __name__ == "__main__":
    unittest.main()
