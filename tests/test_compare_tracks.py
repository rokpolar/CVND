import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import compare_tracks as ct  # noqa: E402
import merge_results  # noqa: E402
import s1_converter  # noqa: E402
import satellite  # noqa: E402
from district_keys import cache_stem  # noqa: E402
from flood_spec import (CONVERTER_RULES, CONVERTER_RULES_VERSION, H5_LAYOUT_VERSION,  # noqa: E402
                        SPEC, SPEC_VERSION)

RULES = replace(CONVERTER_RULES, bootstrap_reps=300)


def pairs_frame(n=48, states=8, seed=0, s1=None, target=None, both=None, builtup_c=None,
                builtup=None):
    """Paired districts with independent nuisance covariates."""
    rng = np.random.default_rng(seed)
    s1 = rng.lognormal(2.0, 1.0, n) if s1 is None else s1
    target = s1 if target is None else target
    frame = pd.DataFrame({
        'event_district_id': [f'E{i}::d' for i in range(n)],
        'state': [f'S{i % states}' for i in range(n)],
        'identity_ok': True,
        's1_c_km2': s1, 'ndwi_c_km2': np.maximum(target, 1.0), 'route_c_km2': target,
        'both_c_km2': np.minimum(s1, target) * 0.9 if both is None else both,
        'usable_km2': 500.0,
        'builtup_frac_c': rng.uniform(0, 0.3, n) if builtup_c is None else builtup_c,
        'cropland_frac_c': rng.uniform(0.2, 0.8, n),
        's1_post_images': rng.integers(1, 6, n).astype(float),
        'orbit_ascending': (rng.uniform(size=n) < 0.3).astype(float),
        'orbit_descending': (rng.uniform(size=n) < 0.3).astype(float),
        'recent_2022': (rng.uniform(size=n) < 0.2).astype(float),
        'cloud_pct': rng.uniform(0, 90, n),
        'otsu_fallback': (rng.uniform(size=n) < 0.1).astype(float),
        'builtup_frac': rng.uniform(0, 0.3, n) if builtup is None else builtup,
        'cropland_frac': rng.uniform(0.2, 0.8, n),
    })
    return frame


class StatisticsTests(unittest.TestCase):
    def test_deming_recovers_line_with_errors_in_both(self):
        rng = np.random.default_rng(1)
        truth = rng.uniform(0, 5, 4000)
        x = truth + rng.normal(0, 0.3, truth.size)
        y = 0.4 + 0.8 * truth + rng.normal(0, 0.3, truth.size)
        slope, intercept = ct.deming(x, y)
        self.assertAlmostEqual(slope, 0.8, delta=0.03)
        self.assertAlmostEqual(intercept, 0.4, delta=0.1)
        ols = np.polyfit(x, y, 1)[0]
        self.assertLess(ols, slope)     # OLS is attenuated; Deming is not

    def test_tost_equivalence(self):
        rng = np.random.default_rng(2)
        groups = np.repeat(np.arange(8), 6)
        near = ct.tost_log_ratio(rng.normal(0.02, 0.1, 48), groups, np.log(1.2), 0.05, 400, 1)
        far = ct.tost_log_ratio(rng.normal(0.6, 0.1, 48), groups, np.log(1.2), 0.05, 400, 1)
        self.assertTrue(near['equivalent'])
        self.assertFalse(far['equivalent'])
        self.assertLess(far['ci_low'], far['median'])

    def test_heterogeneity_detects_builtup_shift(self):
        rng = np.random.default_rng(3)
        frame = pairs_frame(seed=3)
        groups = frame['state'].to_numpy()
        cols = list(ct.HETEROGENEITY_COVARIATES)
        flat = ct.wald_heterogeneity(rng.normal(0, 0.1, len(frame)), frame[cols], groups, 20)
        shifted = ct.wald_heterogeneity(3 * frame['builtup_frac_c'] + rng.normal(0, 0.05, len(frame)),
                                        frame[cols], groups, 20)
        self.assertEqual(flat['cov_type'], 'HC3_F')
        self.assertGreater(flat['p'], 0.10)
        self.assertLess(shifted['p'], 0.01)
        self.assertGreater(shifted['coefficients']['builtup_frac_c'], 2)

    def test_heterogeneity_untestable_design(self):
        frame = pairs_frame(n=4)
        out = ct.wald_heterogeneity(np.zeros(4), frame[list(ct.HETEROGENEITY_COVARIATES)],
                                    frame['state'], 20)
        self.assertIsNone(out['p'])

    def test_pixel_agreement(self):
        out = ct.pixel_agreement(s1=10.0, ndwi=8.0, both=6.0, usable=100.0)
        self.assertAlmostEqual(out['iou'], 0.5)
        self.assertAlmostEqual(out['omission'], 0.25)
        self.assertAlmostEqual(out['commission'], 0.4)
        po, pe = 0.94, (0.1 * 0.08 + 0.9 * 0.92)
        self.assertAlmostEqual(out['kappa'], (po - pe) / (1 - pe))

    def test_agreement_measures(self):
        x = np.array([1.0, 2.0, 4.0, 8.0])
        self.assertAlmostEqual(ct.lin_ccc(x, x), 1.0)
        self.assertLess(ct.lin_ccc(x, 2 * x), 1.0)
        ba = ct.bland_altman_log(2 * x, x, 0.0)
        self.assertAlmostEqual(ba['bias'], np.log(2))
        self.assertAlmostEqual(ba['sd'], 0.0)


class DecisionTests(unittest.TestCase):
    def test_insufficient_sample(self):
        out = ct.converter_decision(pairs_frame(n=20), RULES)
        self.assertEqual(out['decision'], 'insufficient')
        out = ct.converter_decision(pairs_frame(n=40, states=3), RULES)
        self.assertEqual(out['decision'], 'insufficient')

    def test_identity_when_sensors_agree(self):
        # A homogeneous draw; ~10% of draws reject homogeneity at p < 0.10 by design.
        rng = np.random.default_rng(5)
        s1 = rng.lognormal(2.0, 1.0, 48)
        frame = pairs_frame(s1=s1, target=s1 * np.exp(rng.normal(0, 0.05, 48)), seed=5)
        out = ct.converter_decision(frame, RULES)
        self.assertEqual(out['decision'], 'identity', out.get('reason'))
        self.assertEqual(out['model'], {'type': 'identity'})

    def test_linear_when_offset_is_homogeneous(self):
        rng = np.random.default_rng(5)
        s1 = rng.lognormal(2.0, 1.0, 48)
        target = 0.5 * s1 * np.exp(rng.normal(0, 0.05, 48))
        out = ct.converter_decision(pairs_frame(s1=s1, target=target, seed=5), RULES)
        self.assertEqual(out['decision'], 'linear', out.get('reason'))
        model = out['model']
        self.assertAlmostEqual(model['slope'], 1.0, delta=0.1)
        self.assertAlmostEqual(s1_converter.convert(model, 20.0), 10.0, delta=1.5)
        self.assertLess(out['cv']['median_abs_log_error'], 0.1)

    def test_stratified_when_builtup_shifts_the_ratio(self):
        rng = np.random.default_rng(6)
        s1 = rng.lognormal(2.0, 1.0, 48)
        builtup = rng.uniform(0, 0.3, 48)
        target = s1 * np.exp(-3 * builtup + rng.normal(0, 0.03, 48))
        out = ct.converter_decision(pairs_frame(s1=s1, target=target, builtup_c=builtup,
                                                builtup=builtup, seed=6), RULES)
        self.assertEqual(out['decision'], 'stratified', out.get('reason'))
        self.assertIn('heterogeneous', out['reason'])
        coef = out['model']['coef']
        self.assertAlmostEqual(coef['builtup_frac'], -3.0, delta=0.5)

    def test_excluded_when_no_converter_predicts(self):
        rng = np.random.default_rng(7)
        s1 = rng.lognormal(2.0, 1.0, 48)
        builtup_c = rng.uniform(0, 0.3, 48)
        target = s1 * np.exp(-4 * builtup_c + rng.normal(0, 1.0, 48))
        out = ct.converter_decision(pairs_frame(s1=s1, target=target, builtup_c=builtup_c, seed=7), RULES)
        self.assertEqual(out['decision'], 'excluded', out.get('reason'))
        self.assertNotIn('model', out)

    def test_identity_failures_leave_the_sample(self):
        frame = pairs_frame()
        frame.loc[:30, 'identity_ok'] = False
        self.assertEqual(ct.converter_decision(frame, RULES)['decision'], 'insufficient')


def archive(n=3):
    area = np.full(n, SPEC.sits_patch_pixels * 100.0 / 1e6)
    return {
        'scores': np.array([0.9, 0.1, 0.8][:n], dtype=np.float32),
        'ndwi_flood': np.array([400, 0, 200][:n]),
        'ndwi_flood_km2': np.array([400, 0, 200][:n]) * 1e-4,
        'tile_area_km2': area, 'usable_px': np.full(n, 4000), 'usable_km2': np.full(n, 0.4),
        's1_flood': np.array([300, 100, 200][:n]), 's1_flood_km2': np.array([300, 100, 200][:n]) * 1e-4,
        'both_flood': np.array([250, 0, 150][:n]), 'builtup_px': np.full(n, 400),
        'cropland_px': np.full(n, 2000), 'ndwi_flood_builtup': np.zeros(n), 's1_flood_builtup': np.zeros(n),
    }


TRACK_A = {'event_district_id': 'E1::a', 'event_id': 'E1', 'state': 'Assam', 'district': 'A',
           'start_date': '2020-07-01', 'area_s2_km2': 10.0, 'area_s1_km2': 20.0,
           'otsu_threshold_db': -15.0, 'eligible_km2': 30.0, 'grid_aoi_km2': 40.0,
           'builtup_km2': 3.0, 'cropland_km2': 12.0, 's1_orbit': 'BOTH', 's1_post_images': 3,
           'cloud_pct': 30.0, 'otsu_fallback_used': False}


class PairTests(unittest.TestCase):
    def h5(self, **changes):
        base = {'h5_status': 'ok', 'n_blocks': 2, 'duplicate_blocks': 0, 'n_tiles': 3,
                'duplicate_tiles': 0, 'blocks_aoi_km2': 40.0, 'blocks_ndwi_km2': 10.05,
                'blocks_s1_km2': 20.0, 'threshold_b_db': -15.0}
        base.update(changes)
        return base

    def test_identity_and_paired_areas(self):
        row = ct.district_pair(pd.Series(TRACK_A), archive(), self.h5())
        self.assertTrue(row['identity_ok'])
        self.assertAlmostEqual(row['identity_rel_err'], 0.005)
        self.assertTrue(row['threshold_match'])
        self.assertAlmostEqual(row['ndwi_c_km2'], 0.06)
        self.assertAlmostEqual(row['s1_c_km2'], 0.06)
        self.assertAlmostEqual(row['both_c_km2'], 0.04)
        self.assertAlmostEqual(row['usable_km2'], 3 * 4000 * 1e-4)
        self.assertAlmostEqual(row['builtup_frac_c'], 0.1)
        self.assertAlmostEqual(row['builtup_frac'], 0.1)
        self.assertAlmostEqual(row['iou_c'], 0.04 / 0.08)

    def test_identity_fails_on_bugs(self):
        for changes in ({'blocks_ndwi_km2': 12.0}, {'duplicate_tiles': 4}, {'duplicate_blocks': 1},
                        {'h5_status': 'missing', 'blocks_ndwi_km2': None}):
            with self.subTest(changes=changes):
                self.assertFalse(ct.district_pair(pd.Series(TRACK_A), archive(), self.h5(**changes))['identity_ok'])

    def test_h5_summary_counts_duplicates(self):
        grid = satellite.grid_from_utm_bounds('EPSG:32645', 0, 0, 1279, 639)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.h5'
            with h5py.File(path, 'w') as f:
                satellite._create_h5(f, TRACK_A, {'geometry_id': 'G1'}, grid, SPEC, -15.0, False)
                satellite._append_h5(f, {'coords': np.array([[0, 0, 1, 1], [0, 64, 1, 1], [0, 0, 1, 1]], float),
                                          'pixel_area_m2': np.full(3, 100.0, np.float32),
                                          'block_stats': np.array([[0, 1e6, 1e6, 1e6, 5e5, 2e5],
                                                                   [1, 1e6, 1e6, 1e6, 5e5, 2e5]])})
            out = ct.h5_summary(path)
        self.assertEqual(out['duplicate_tiles'], 1)
        self.assertEqual(out['duplicate_blocks'], 0)
        self.assertAlmostEqual(out['blocks_ndwi_km2'], 1.0)
        self.assertEqual(out['threshold_b_db'], -15.0)
        self.assertEqual(ct.h5_summary(Path('nope.h5'))['h5_status'], 'missing')


class MainTests(unittest.TestCase):
    def test_main_writes_decision_consumed_by_merge(self):
        identity = {k: TRACK_A[k] for k in ('event_district_id', 'event_id', 'state', 'district', 'start_date')}
        identity.update(source_record_id='D1', geometry_id='G1')
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            (root / 'scores').mkdir()
            track = root / 'track.csv'
            pd.DataFrame([{**TRACK_A, **identity, 'aoi_match_status': 'matched', 'aoi_level': 'district',
                           'spec_version': SPEC_VERSION}]).to_csv(track, index=False)
            payload = {**archive(), **{k: np.array(v) for k, v in identity.items()},
                       'model_id': np.array('m'), 'weights_sha256': np.array('w'),
                       'patches_sha256': np.array('p'), 'spec_version': np.array(SPEC_VERSION),
                       'layout_version': np.array(H5_LAYOUT_VERSION), 'block_id': np.zeros(3)}
            np.savez(root / 'scores' / f"{cache_stem('E1::a')}.npz", **payload)
            outputs = {'AGREEMENT_CSV': root / 'agree.csv', 'SUMMARY_JSON': root / 'summary.json'}
            for name, value in [('SCORES_DIR', root / 'scores'), ('TRACK_A_CSV', track),
                                ('PATCH_DIR', root), ('SITS_INDEX_CSV', root / 'index.csv')]:
                stack.enter_context(patch.object(merge_results, name, str(value)))
            for name, value in outputs.items():
                stack.enter_context(patch.object(ct, name, str(value)))
            stack.enter_context(patch.object(s1_converter, 'CONVERTER_JSON', str(root / 'conv.json')))
            self.assertEqual(ct.main(), 0)
            converter = s1_converter.load()
            self.assertEqual(converter['decision'], 'insufficient')
            self.assertEqual(converter['rules_version'], CONVERTER_RULES_VERSION)
            summary = json.loads(outputs['SUMMARY_JSON'].read_text())
            self.assertEqual(summary['identity']['checked'], 0)   # no H5 on disk
            self.assertEqual(summary['identity']['unchecked'], 1)
            pairs = pd.read_csv(outputs['AGREEMENT_CSV'])
            self.assertEqual(pairs.loc[0, 'h5_status'], 'missing')


class ConverterArtifactTests(unittest.TestCase):
    def test_convert_models(self):
        self.assertEqual(s1_converter.convert({'type': 'identity'}, 4.0), 4.0)
        deming = {'type': 'deming_loglog', 'offset_km2': 0.1, 'slope': 1.0, 'intercept': 0.0}
        self.assertAlmostEqual(s1_converter.convert(deming, 4.0), 4.0)
        self.assertAlmostEqual(s1_converter.convert(deming, 0.0), 0.0)
        strata = {'type': 'ols_loglog_strata', 'offset_km2': 0.1,
                  'coef': {'const': 0.0, 'log_s1': 1.0, 'builtup_frac': -1.0, 'cropland_frac': 0.0}}
        self.assertAlmostEqual(s1_converter.convert(strata, 9.9, 0.5, 0.2), 10 * np.exp(-0.5) - 0.1)
        self.assertIsNone(s1_converter.convert(strata, 9.9))
        self.assertIsNone(s1_converter.convert(deming, None))

    def test_validation(self):
        good = {'decision': 'linear', 'spec_version': SPEC_VERSION, 'rules_version': CONVERTER_RULES_VERSION,
                'model': {'type': 'deming_loglog'}}
        s1_converter.validate(good)
        for bad in ({'decision': 'maybe'}, {'spec_version': 'fs1-x'}, {'rules_version': 'cr1-x'},
                    {'model': {'type': 'spline'}}):
            with self.subTest(bad=bad), self.assertRaises(s1_converter.ConverterUnavailable):
                s1_converter.validate({**good, **bad})
        s1_converter.validate({**good, 'decision': 'excluded', 'model': None})


if __name__ == '__main__':
    unittest.main()
