"""Tests for the income group derivation.

`income_group` was a hand-written string with no source and it did not track
income. The paper regresses log_ratio on it to ask whether poorer states get less
coverage, so a label that is not income makes that contrast meaningless -- and it
failed silently, because "Low" is a perfectly plausible value for any state.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import state_income as si  # noqa: E402


class DerivationTests(unittest.TestCase):
    def test_groups_are_monotone_in_income(self):
        """The property the hand-written labels broke: no state may sit in a
        lower group than a poorer one."""
        gsdp = si.load_gsdp()
        groups = si.income_groups(gsdp)
        rank = {"Low": 0, "Middle": 1, "High": 2}
        ordered = sorted(gsdp, key=lambda s: gsdp[s])
        seen = [rank[groups[s]] for s in ordered]
        self.assertEqual(seen, sorted(seen))

    def test_tertiles_split_the_states_evenly(self):
        counts = pd.Series(si.income_groups()).value_counts()
        self.assertEqual(set(counts.index), set(si.GROUPS))
        self.assertLessEqual(counts.max() - counts.min(), 2)

    def test_equal_incomes_share_a_group(self):
        """Assam, Rajasthan and Tripura all sit at 95,000. Cutting on rank rather
        than on value would have separated them arbitrarily."""
        gsdp = si.load_gsdp()
        groups = si.income_groups(gsdp)
        by_value = {}
        for state, v in gsdp.items():
            by_value.setdefault(v, []).append(state)
        for v, states in by_value.items():
            if len(states) > 1:
                self.assertEqual(len({groups[s] for s in states}), 1,
                                 msg=f"{states} share GSDP {v}")

    def test_the_known_mislabels_are_corrected(self):
        groups = si.income_groups()
        self.assertEqual(groups["Sikkim"], "High")          # 3rd highest, was Low
        self.assertEqual(groups["Kerala"], "High")          # 7th, was Middle
        self.assertEqual(groups["Bihar"], "Low")            # lowest, was Low
        for state in ("Himachal Pradesh", "Uttarakhand", "Arunachal Pradesh",
                      "Mizoram"):
            self.assertNotEqual(groups[state], "Low", msg=state)

    def test_missing_covariates_degrade_rather_than_crash(self):
        self.assertEqual(si.income_groups({}), {})
        self.assertEqual(si.load_gsdp(Path("does-not-exist.csv")), {})


class ApplyTests(unittest.TestCase):
    def test_unknown_states_get_their_own_category(self):
        """A NaN would get no dummy from get_dummies and so be absorbed into the
        reference group, silently counting as the baseline income level."""
        df = pd.DataFrame({"state": ["Bihar", "Atlantis"],
                           "income_group": ["Low", "Middle"]})
        out = si.apply_income_group(df, verbose=False)
        self.assertEqual(out.loc[1, "income_group"], si.UNKNOWN)
        self.assertNotIn(si.UNKNOWN, si.GROUPS)

    def test_the_original_frame_is_not_mutated(self):
        df = pd.DataFrame({"state": ["Sikkim"], "income_group": ["Low"]})
        si.apply_income_group(df, verbose=False)
        self.assertEqual(df.loc[0, "income_group"], "Low")

    def test_real_events_are_reassigned(self):
        """A third of the sample moves group, so this is not a cosmetic fix."""
        ev = pd.read_csv(ROOT / "data" / "raw" / "events.csv")
        out = si.apply_income_group(ev, verbose=False)
        moved = (out["income_group"] != ev["income_group"]).sum()
        self.assertGreater(moved, 0.2 * len(ev))

    def test_unknown_survives_the_plotting_categories(self):
        """visualize.py builds a pd.Categorical from INCOME_ORDER, and a value
        outside those categories becomes NaN -- so a group missing from the list
        drops out of every figure silently."""
        sys.path.insert(0, str(ROOT / "src"))
        from cvnd_config import COLORS_INCOME, INCOME_ORDER
        self.assertIn(si.UNKNOWN, INCOME_ORDER)
        self.assertIn(si.UNKNOWN, COLORS_INCOME)
        for g in si.GROUPS:
            self.assertIn(g, INCOME_ORDER, msg=g)
            self.assertIn(g, COLORS_INCOME, msg=g)

    def test_both_consumers_use_the_shared_derivation(self):
        """Two call sites reading the same column must not disagree."""
        for name in ("compute_expected_coverage.py", "compute_mss.py"):
            src = (ROOT / "src" / name).read_text(encoding="utf-8")
            self.assertIn("state_income.apply_income_group", src, msg=name)


if __name__ == "__main__":
    unittest.main()
