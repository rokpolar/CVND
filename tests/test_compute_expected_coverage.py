"""Tests for the coverage regression's residuals, ranking and dispersion.

These are quiet failures: every one of them produced a plausible number. The
Pearson residual used a dispersion of 1.0 regardless of what was estimated, the
"integer" rank truncated ties, and an assertion about a data property aborted the
whole run. Nothing raised, so nothing was noticed.
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = (ROOT / "src" / "compute_expected_coverage.py").read_text(encoding="utf-8")


def _statsmodels():
    try:
        import statsmodels.api as sm
        return sm
    except ImportError:
        return None


class PearsonResidualTests(unittest.TestCase):
    """GLM with family=NegativeBinomial(alpha=a) reports result.scale as exactly
    1.0, so `mu + result.scale * mu**2` assumed alpha=1 whatever fit_negbin
    estimated. statsmodels' own resid_pearson uses the family variance."""

    def test_glm_scale_is_one_and_is_not_the_dispersion(self):
        sm = _statsmodels()
        if sm is None:
            self.skipTest("statsmodels not installed")
        y, X, alpha = self._fit_data(sm)
        r = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
        self.assertEqual(r.scale, 1.0)
        self.assertNotAlmostEqual(alpha, 1.0, places=2)

    def test_resid_pearson_matches_the_alpha_correct_formula(self):
        sm = _statsmodels()
        if sm is None:
            self.skipTest("statsmodels not installed")
        y, X, alpha = self._fit_data(sm)
        r = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
        mu = np.clip(np.asarray(r.fittedvalues, float), 1e-8, None)
        correct = (y - mu) / np.sqrt(mu + alpha * mu ** 2 + 1e-12)
        old = (y - mu) / np.sqrt(mu + r.scale * mu ** 2 + 1e-12)
        np.testing.assert_allclose(r.resid_pearson, correct, atol=1e-8)
        # and the version that was in the code is materially different
        self.assertGreater(np.abs(old - r.resid_pearson).max(), 0.1)

    def test_code_uses_resid_pearson(self):
        self.assertIn("result.resid_pearson", SRC)
        self.assertNotIn("result.scale * mu ** 2", SRC)

    @staticmethod
    def _fit_data(sm):
        rng = np.random.default_rng(0)
        x = rng.normal(size=300)
        mu = np.exp(1.0 + 0.5 * x)
        y = rng.negative_binomial(1 / 0.7, 1 / (1 + 0.7 * mu)).astype(float)
        X = sm.add_constant(np.c_[x])
        nb = sm.NegativeBinomial(y, X).fit(disp=False, maxiter=200)
        return y, X, float(nb.params[-1])


class RankTests(unittest.TestCase):
    def test_average_rank_truncation_loses_ranks(self):
        """The bug being guarded: 1.5 and 1.5 both truncate to 1, and rank 2
        never appears, so the column stops being a ranking."""
        s = pd.Series([-1.0, -1.0, 0.5])
        bad = s.rank(method="average").astype(int)
        self.assertEqual(sorted(bad), [1, 1, 3])

    def test_min_rank_is_already_integral(self):
        s = pd.Series([-1.0, -1.0, 0.5])
        good = s.rank(method="min").astype(int)
        np.testing.assert_array_equal(good.to_numpy(), [1, 1, 3])
        np.testing.assert_allclose(s.rank(method="min").to_numpy(),
                                   good.to_numpy())

    def test_code_uses_min_not_average(self):
        i = SRC.index("rank_undercovered")
        window = SRC[i:i + 300]
        self.assertIn('method="min"', window)
        self.assertNotIn('method="average"', window)


class TierAssertionTests(unittest.TestCase):
    def test_the_lowest_tertile_need_not_be_all_negative(self):
        """Whether the bottom third of log_ratio is entirely below zero depends
        on the data, not on the code, so it cannot be an assertion."""
        import importlib
        cec = importlib.import_module("compute_expected_coverage")
        resid = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])   # nothing under-covered
        tiers = cec.severity_tier_tertile(resid)
        low = resid[tiers == "low"]
        self.assertTrue(len(low) > 0)
        self.assertTrue((low >= 0).all())

    def test_the_check_no_longer_aborts_the_run(self):
        i = SRC.index("severity_tier\"] == \"low\"")
        self.assertNotIn("raise AssertionError", SRC[i:i + 600])


class DispersionReportingTests(unittest.TestCase):
    def test_alpha_reaches_the_output(self):
        """Every standard error depends on it, but it lived in a local and never
        appeared in any artifact, so the regression could not be reproduced."""
        self.assertIn("fitted.nb_alpha = alpha", SRC)
        self.assertIn('out["nb_alpha"]', SRC)


class OverlappingEventTests(unittest.TestCase):
    """EM-DAT holds several records per state whose windows overlap. Severity is
    measured over each event's own window, so both cover the overlap, while
    collect_gdelt gives every article in the overlap to the lower event_id. The
    longer event then carries flood area from a period whose coverage went to its
    twin. 19 pairs, 37 of the 204 events."""

    @staticmethod
    def _frame(rows):
        df = pd.DataFrame(rows)
        df["onset_date"] = pd.to_datetime(df["start_date"])
        return df

    def test_nested_windows_in_one_state_are_flagged(self):
        import importlib
        cec = importlib.import_module("compute_expected_coverage")
        df = self._frame([
            {"event_id": "E043", "state": "Gujarat",
             "start_date": "2017-06-01", "end_date": "2017-06-30"},
            {"event_id": "E044", "state": "Gujarat",
             "start_date": "2017-06-01", "end_date": "2017-08-31"},
        ])
        self.assertEqual(cec.report_overlapping_events(df), [("E043", "E044")])

    def test_the_same_dates_in_different_states_are_not_a_clash(self):
        """One EM-DAT disaster split across states is the normal case -- 168 of
        the 204 events share a date range with another. Each has its own AOI and
        its own articles."""
        import importlib
        cec = importlib.import_module("compute_expected_coverage")
        df = self._frame([
            {"event_id": "E107", "state": "Assam",
             "start_date": "2020-06-01", "end_date": "2020-08-16"},
            {"event_id": "E108", "state": "Bihar",
             "start_date": "2020-06-01", "end_date": "2020-08-16"},
        ])
        self.assertEqual(cec.report_overlapping_events(df), [])

    def test_disjoint_windows_in_one_state_are_not_a_clash(self):
        import importlib
        cec = importlib.import_module("compute_expected_coverage")
        df = self._frame([
            {"event_id": "E001", "state": "Bihar",
             "start_date": "2019-07-01", "end_date": "2019-07-10"},
            {"event_id": "E002", "state": "Bihar",
             "start_date": "2019-08-01", "end_date": "2019-08-10"},
        ])
        self.assertEqual(cec.report_overlapping_events(df), [])

    def test_a_missing_end_date_is_treated_as_a_single_day(self):
        import importlib
        cec = importlib.import_module("compute_expected_coverage")
        df = self._frame([
            {"event_id": "E001", "state": "Bihar",
             "start_date": "2019-07-01", "end_date": None},
            {"event_id": "E002", "state": "Bihar",
             "start_date": "2019-07-05", "end_date": "2019-07-09"},
        ])
        self.assertEqual(cec.report_overlapping_events(df), [])

    def test_the_real_registry_has_the_expected_clashes(self):
        import importlib
        cec = importlib.import_module("compute_expected_coverage")
        ev = pd.read_csv(ROOT / "data" / "raw" / "events.csv")
        ev["onset_date"] = pd.to_datetime(ev["start_date"])
        pairs = cec.report_overlapping_events(ev)
        self.assertIn(("E043", "E044"), pairs)
        self.assertGreaterEqual(len(pairs), 15)


class ReportFidelityTests(unittest.TestCase):
    def test_the_report_reflects_whether_deaths_are_a_covariate(self):
        """`include_deaths` was accepted and never read, so the report stated
        'Option C: log1p(deaths) as a covariate' even when deaths were not in the
        model -- one artifact describing two different specifications."""
        i = SRC.index("| Deaths handling |")
        self.assertIn("include_deaths", SRC[i:i + 400])

    def test_the_report_records_the_dispersion(self):
        self.assertIn("NB2 dispersion", SRC)

    def test_income_breakdowns_do_not_drop_unseen_groups(self):
        """A fixed reindex(["High","Middle","Low"]) silently dropped any other
        category -- and state_income labels states with no per-capita GSDP
        'Unknown', so those events would vanish from the report."""
        self.assertNotIn('reindex(["High", "Middle", "Low"])', SRC)
        self.assertIn("order = [g for g in", SRC)


class DropReportingTests(unittest.TestCase):
    def test_zero_article_events_are_not_dropped_upstream(self):
        """compute_mss fills total_articles with 0 for every registered event, so
        a zero-coverage event arrives as 0 and not as NaN -- the dropna is about
        missing SEVERITY, which is a different and real selection problem."""
        mss = (ROOT / "src" / "compute_mss.py").read_text(encoding="utf-8")
        self.assertIn('df["total_articles"] = df["total_articles"].fillna(0)', mss)

    def test_drops_are_reported_per_column_and_year(self):
        self.assertIn("missing\"", SRC.replace("'", '"'))
        self.assertIn("dropped by onset year", SRC)


if __name__ == "__main__":
    unittest.main()
