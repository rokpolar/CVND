import sys
import unittest
from pathlib import Path

import pandas as pd


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from build_emdat_events import build_state_events, load_official_workbook  # noqa: E402
from cvnd_layout import data_path  # noqa: E402


class BuildEmdatEventsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base, _ = load_official_workbook(data_path("emdat_base"))
        cls.full, cls.registry = build_state_events(cls.base)

    def test_all_official_records_are_covered_without_duplicate_state_pairs(self):
        self.assertEqual(len(self.base), 75)
        self.assertEqual(self.full["source_record_id"].nunique(), len(self.base))
        self.assertFalse(self.full.duplicated(["source_record_id", "state"]).any())
        self.assertTrue((self.registry["event_source"] == "emdat_official_state").all())
        self.assertTrue((self.registry["aoi_level"] == "state").all())

    def test_every_original_column_is_preserved_on_each_state_row(self):
        original_columns = list(self.base.columns)
        source = self.base.set_index(self.base["DisNo."].astype(str))
        for _, row in self.full.iterrows():
            expected = source.loc[row["source_record_id"]]
            for column in original_columns:
                actual_value = row[column]
                expected_value = expected[column]
                same = (pd.isna(actual_value) and pd.isna(expected_value)) or actual_value == expected_value
                self.assertTrue(same, f"{row['source_record_id']} changed {column}")

    def test_multistate_event_is_not_merged_or_seeded(self):
        states = set(
            self.full.loc[self.full["source_record_id"] == "2020-0304-IND", "state"]
        )
        self.assertEqual(len(states), 12)
        self.assertIn("Assam", states)
        self.assertIn("West Bengal", states)

    def test_non_indian_kashmir_units_are_excluded(self):
        states = self.full.loc[
            self.full["source_record_id"] == "2020-0249-IND", "state"
        ].tolist()
        self.assertEqual(states, ["Jammu and Kashmir"])


if __name__ == "__main__":
    unittest.main()
