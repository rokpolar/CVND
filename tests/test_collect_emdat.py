import importlib.util
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
SPEC = importlib.util.spec_from_file_location("collect_emdat", SRC / "collect_emdat.py")
collect_emdat = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collect_emdat)


class CollectEmdatTests(unittest.TestCase):
    def test_query_contains_cvnd_defaults(self):
        query = collect_emdat.build_query(2015, 2026, ["ind"], ["nat-hyd-flo-*"], True, 500, 0)
        self.assertIn("from: 2015", query)
        self.assertIn("to: 2026", query)
        self.assertIn('iso: ["IND"]', query)
        self.assertIn('classif: ["nat-hyd-flo-*"]', query)
        self.assertIn("cursor: {limit: 500, offset: 0}", query)

    def test_portal_row_preserves_expected_schema_and_serializes_objects(self):
        converted = collect_emdat.portal_row(
            {"disno": "2024-0001-IND", "type": "Flood", "admin_units": [{"adm1": "Assam"}]}
        )
        self.assertEqual(list(converted), [heading for heading, _ in collect_emdat.PORTAL_COLUMNS])
        self.assertEqual(converted["DisNo."], "2024-0001-IND")
        self.assertEqual(converted["Disaster Type"], "Flood")
        self.assertEqual(converted["Admin Units"], '[{"adm1":"Assam"}]')
        self.assertEqual(converted["Historic"], "")

    def test_fetch_all_paginates_until_total(self):
        offsets = []

        def fetch(query):
            offset = 0 if "offset: 0" in query else 2
            offsets.append(offset)
            rows = [{"disno": "A"}, {"disno": "B"}] if offset == 0 else [{"disno": "C"}]
            return {
                "data": {
                    "api_version": "1",
                    "public_emdat": {
                        "total_available": 3,
                        "info": {"version": "2026.1", "timestamp": "now"},
                        "data": rows,
                    },
                }
            }

        rows, metadata = collect_emdat.fetch_all(
            fetch,
            from_year=2015,
            to_year=2026,
            iso_codes=["IND"],
            classifications=["nat-hyd-flo-*"],
            include_historic=True,
            page_size=2,
        )
        self.assertEqual(offsets, [0, 2])
        self.assertEqual([row["disno"] for row in rows], ["A", "B", "C"])
        self.assertEqual(metadata["dataset_version"], "2026.1")
        self.assertEqual(metadata["rows_fetched"], 3)

    def test_rejects_invalid_iso(self):
        with self.assertRaises(ValueError):
            collect_emdat.build_query(2015, 2026, ["India"], ["nat-hyd-flo-*"], True, 500, 0)


if __name__ == "__main__":
    unittest.main()
