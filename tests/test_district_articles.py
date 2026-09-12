import json
import gzip
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import district_articles  # noqa: E402


class DistrictArticlesTests(unittest.TestCase):
    def setUp(self):
        self.registry = pd.DataFrame(
            [
                {
                    "event_district_id": "E1::puri",
                    "event_id": "E1",
                    "source_record_id": "2020-0001-IND",
                    "state": "Odisha",
                    "district": "Puri",
                    "start_date": "2020-01-01",
                },
                {
                    "event_district_id": "E1::cuttack",
                    "event_id": "E1",
                    "source_record_id": "2020-0001-IND",
                    "state": "Odisha",
                    "district": "Cuttack",
                    "start_date": "2020-01-01",
                },
            ]
        )

    def test_registry_expansion_keeps_parent_and_deterministic_ids(self):
        first = district_articles.prepare_district_registry(self.registry)
        second = district_articles.prepare_district_registry(self.registry)
        self.assertEqual(first["event_district_id"].tolist(), second["event_district_id"].tolist())
        self.assertEqual(set(first["event_id"]), {"E1"})
        self.assertEqual(set(first["source_record_id"]), {"2020-0001-IND"})
        self.assertEqual(set(first["event_district_id"]), {"E1::puri", "E1::cuttack"})

    def test_window_is_fixed_half_open_fourteen_days(self):
        windows = district_articles.prepare_district_windows(self.registry)
        self.assertEqual(windows[0]["query_start"].isoformat(), "2020-01-01")
        self.assertEqual(windows[0]["query_end_exclusive"].isoformat(), "2020-01-15")
        query = district_articles.build_district_query(windows)
        self.assertIn("DATE(g.published_at) < e.query_end_exclusive", query)
        self.assertIn("PARTITION BY normalized_url, state, district", query)

    def test_state_only_rows_are_not_a_district_candidate(self):
        query = district_articles.build_district_query(
            district_articles.prepare_district_windows(self.registry)
        )
        self.assertIn("district_terms", query)
        self.assertNotIn("state-only", query)
        candidate_sql = query.split("candidate_matches", 1)[1].split("deduplicated", 1)[0]
        self.assertNotIn("UNNEST(e.state)", candidate_sql)

    def test_structured_location_requires_same_state_block(self):
        self.assertTrue(
            district_articles.structured_location_matches(
                "1#Puri,Odisha,India#IN#", state="Odisha", district="Puri"
            )
        )
        self.assertFalse(
            district_articles.structured_location_matches(
                "1#Puri,Bihar,India#IN#", state="Odisha", district="Puri"
            )
        )

    def test_overlapping_events_assign_same_url_to_nearest_onset(self):
        registry = pd.DataFrame(
            [
                {
                    "event_district_id": "E1::puri",
                    "event_id": "E1",
                    "source_record_id": "D1",
                    "state": "Odisha",
                    "district": "Puri",
                    "start_date": "2020-01-01",
                },
                {
                    "event_district_id": "E2::puri",
                    "event_id": "E2",
                    "source_record_id": "D2",
                    "state": "Odisha",
                    "district": "Puri",
                    "start_date": "2020-01-10",
                },
            ]
        )
        rows = [
            {
                "event_district_id": event_id,
                "event_id": event_id.split("::")[0],
                "state": "Odisha",
                "district": "Puri",
                "district_evidence": "gkg_location",
                "locations_lower": "3#Puri, Odisha, India#IN#",
                "published_at": "2020-01-11T00:00:00Z",
                "url": "https://news.example/shared",
                "body_text": "Flood reached Puri.",
                "document_status": "ok",
            }
            for event_id in ("E1::puri", "E2::puri")
        ]
        with tempfile.TemporaryDirectory() as temp:
            payload = Path(temp) / "articles.jsonl.gz"
            with gzip.open(payload, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            manifest = Path(temp) / "manifest.json"
            district_articles.write_collection_manifest(
                manifest,
                registry,
                status=district_articles.COLLECTION_COMPLETE,
                article_payload_sha256=district_articles.file_fingerprint(payload),
            )
            counts = district_articles.build_district_counts(
                registry,
                rows,
                manifest_path=manifest,
                article_payload_path=payload,
            )
        self.assertEqual(
            int(counts.loc[counts["event_district_id"] == "E1::puri", "candidate_article_count"].iloc[0]),
            0,
        )
        self.assertEqual(
            int(counts.loc[counts["event_district_id"] == "E2::puri", "candidate_article_count"].iloc[0]),
            1,
        )

    def test_heuristic_counts_are_filtered_and_keep_zero_rows(self):
        frame = district_articles.prepare_district_registry(self.registry)
        puri_id = frame.loc[frame["district"] == "Puri", "event_district_id"].item()
        cuttack_id = frame.loc[frame["district"] == "Cuttack", "event_district_id"].item()
        rows = [
            {
                "event_district_id": puri_id,
                "event_id": "E1",
                "state": "Odisha",
                "district": "Puri",
                "published_at": "2020-01-02T00:00:00Z",
                "url": "https://news.example/puri",
                "district_evidence": "gkg_location",
                "locations_lower": "3#Puri, Odisha, India#IN#",
                "body_text": "Flood waters reached Puri homes.",
                "document_status": "ok",
            },
            # Same URL is a duplicate within the same district.
            {
                "event_district_id": puri_id,
                "event_id": "E1",
                "state": "Odisha",
                "district": "Puri",
                "published_at": "2020-01-03T00:00:00Z",
                "url": "https://news.example/puri",
                "district_evidence": "gkg_location",
                "locations_lower": "3#Puri, Odisha, India#IN#",
                "body_text": "Flood waters reached Puri homes.",
                "document_status": "ok",
            },
            # A state-only row has no valid district key and must be rejected.
        ]
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            payload = temp_root / "articles.jsonl.gz"
            with gzip.open(payload, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            manifest = temp_root / "manifest.json"
            district_articles.write_collection_manifest(
                manifest,
                frame,
                status=district_articles.COLLECTION_COMPLETE,
                article_payload_sha256=district_articles.file_fingerprint(payload),
            )
            counts = district_articles.build_district_counts(
                frame,
                rows,
                manifest_path=manifest,
                article_payload_path=payload,
            )
        puri = counts.loc[counts["event_district_id"] == puri_id].iloc[0]
        cuttack = counts.loc[counts["event_district_id"] == cuttack_id].iloc[0]
        self.assertEqual(int(puri["candidate_article_count"]), 1)
        self.assertEqual(int(puri["heuristic_pass_count"]), 1)
        self.assertEqual(int(puri["final_article_count"]), 1)
        self.assertEqual(int(cuttack["candidate_article_count"]), 0)
        self.assertEqual(cuttack["collection_status"], "complete")

    def test_failed_manifest_is_distinct_from_complete_zero(self):
        frame = district_articles.prepare_district_registry(self.registry)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            district_articles.write_collection_manifest(
                path, frame, status=district_articles.COLLECTION_FAILED
            )
            payload = json.loads(path.read_text())
            self.assertEqual(payload["collection_status"], "failed")
            counts = district_articles.build_district_counts(
                frame, [], manifest_path=path
            )
            self.assertEqual(set(counts["collection_status"]), {"failed"})

    def test_state_fallback_is_retained_but_ineligible(self):
        fallback = self.registry.iloc[:1].copy()
        fallback["district"] = "Odisha"
        fallback["district_source"] = "state_fallback"
        frame = district_articles.prepare_district_registry(fallback)
        self.assertFalse(bool(frame.iloc[0]["primary_eligible"]))
        with self.assertRaises(ValueError):
            district_articles.prepare_district_windows(fallback)

    def test_puducherry_named_district_is_eligible(self):
        district = self.registry.iloc[:1].copy()
        district['state'] = 'Puducherry'
        district['district'] = 'Puducherry'
        district['aoi_level'] = 'district'
        district['district_source'] = 'external_recovery'
        self.assertTrue(bool(district_articles.prepare_district_registry(district).iloc[0]['primary_eligible']))
        district['district_source'] = 'state_fallback'
        self.assertFalse(bool(district_articles.prepare_district_registry(district).iloc[0]['primary_eligible']))


if __name__ == "__main__":
    unittest.main()
