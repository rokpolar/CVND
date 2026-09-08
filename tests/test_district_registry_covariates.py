import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from build_district_covariates import build_district_covariates, parse_census_table  # noqa: E402
from build_emdat_events import build_event_districts, build_state_events  # noqa: E402
from district_keys import make_event_district_id, normalize_name, normalize_state_name  # noqa: E402


class DistrictRegistryTests(unittest.TestCase):
    def _base(self):
        return pd.DataFrame(
            [
                {
                    "DisNo.": "2020-0001-IND",
                    "Start Year": 2020,
                    "Start Month": 1,
                    "Start Day": 2,
                    "End Year": 2020,
                    "End Month": 1,
                    "End Day": 3,
                    "GADM Admin Units": (
                        '[{"gid_2":"IND.4.7_1","name_1":"Assam","name_2":"Dhemaji"},'
                        '{"gid_2":"IND.4.8_1","name_1":"Assam","name_2":"Dhubri"}]'
                    ),
                    "Admin Units": "[]",
                    "Location": "Dhemaji, Dhubri (Assam)",
                },
                {
                    "DisNo.": "2020-0002-IND",
                    "Start Year": 2020,
                    "Start Month": 2,
                    "Start Day": 1,
                    "End Year": 2020,
                    "End Month": 2,
                    "End Day": 1,
                    "GADM Admin Units": '[{"gid_1":"IND.4_1","name_1":"Assam"}]',
                    "Admin Units": "[]",
                    "Location": "Assam state",
                },
            ]
        )

    def test_all_structured_districts_and_missing_rows_are_retained(self):
        base = self._base()
        _full, state_registry = build_state_events(base)
        first = build_event_districts(base, state_registry)
        second = build_event_districts(base, state_registry)
        self.assertEqual(first["event_district_id"].tolist(), second["event_district_id"].tolist())
        self.assertEqual(set(first.loc[first.source_record_id == "2020-0001-IND", "district"]), {"Dhemaji", "Dhubri"})
        missing = first.loc[first.source_record_id == "2020-0002-IND"].iloc[0]
        self.assertEqual(missing["district"], "district_missing")
        self.assertEqual(missing["aoi_match_status"], "unresolved")

    def test_name_normalization_is_conservative_and_id_is_injective(self):
        self.assertEqual(normalize_name("  HéLLo   World "), "héllo world")
        self.assertEqual(normalize_state_name("ASSAM"), "Assam")
        self.assertNotEqual(make_event_district_id("E1", "A B"), make_event_district_id("E1", "A_B"))


class DistrictCovariateTests(unittest.TestCase):
    def test_official_long_layout_and_share(self):
        source = pd.DataFrame(
            [
                {"State": "Bihar", "District": "Araria", "District Code": "001", "Residence": "Total", "Population - Persons": "1,000"},
                {"State": "Bihar", "District": "Araria", "District Code": "001", "Residence": "Urban", "Population - Persons": 400},
                {"State": "Bihar", "District": "Araria", "District Code": "001", "Residence": "Rural", "Population - Persons": 600},
            ]
        )
        result = parse_census_table(source)
        self.assertEqual(result.loc[0, "census_district_code"], "001")
        self.assertEqual(result.loc[0, "urban_population_share"], 0.4)
        self.assertEqual(result.loc[0, "census_year"], 2011)

    def test_official_pca_sd_code_layout(self):
        source = pd.DataFrame(
            [
                {"State": 18, "District": 301, "Level": "DISTRICT", "Name": "Dhubri", "TRU": "Total", "TOT_P": 1000},
                {"State": 18, "District": 301, "Level": "DISTRICT", "Name": "Dhubri", "TRU": "Urban", "TOT_P": 400},
                {"State": 18, "District": 301, "Level": "DISTRICT", "Name": "Dhubri", "TRU": "Rural", "TOT_P": 600},
                {"State": 18, "District": 0, "Level": "STATE", "Name": "ASSAM", "TRU": "Total", "TOT_P": 1000},
            ]
        )
        result = parse_census_table(source)
        self.assertEqual(result.loc[0, "state"], "Assam")
        self.assertEqual(result.loc[0, "district"], "Dhubri")
        self.assertEqual(result.loc[0, "census_district_code"], "301")
        self.assertEqual(result.loc[0, "urban_population_share"], 0.4)

    def test_missing_input_fails_clearly(self):
        missing = Path(tempfile.gettempdir()) / "definitely_missing_census_input.xlsx"
        with self.assertRaises(FileNotFoundError) as ctx:
            build_district_covariates(missing)
        self.assertIn("official Census of India 2011", str(ctx.exception))

    def test_explicit_crosswalk_projects_registry_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            census = pd.DataFrame([{"state": "Odisha", "district": "Puri", "total_population": 1000, "urban_population": 400, "rural_population": 600}])
            census_path = root / "census.csv"
            census.to_csv(census_path, index=False)
            events = pd.DataFrame([{"event_district_id": "E1::pury", "event_id": "E1", "state": "Orissa", "district": "Pury"}])
            events_path = root / "events.csv"
            events.to_csv(events_path, index=False)
            crosswalk = root / "crosswalk.csv"
            pd.DataFrame([{"registry_state": "Orissa", "registry_district": "Pury", "census_state": "Odisha", "census_district": "Puri", "notes": "verified"}]).to_csv(crosswalk, index=False)
            result = build_district_covariates(census_path, events_path=events_path, crosswalk_path=crosswalk)
            self.assertEqual(result.loc[0, "match_status"], "matched_crosswalk")
            self.assertEqual(result.loc[0, "urban_population_share"], 0.4)


if __name__ == "__main__":
    unittest.main()
