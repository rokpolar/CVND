import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import collect_gdelt  # noqa: E402


class CollectGdeltTests(unittest.TestCase):
    def setUp(self):
        self.events = pd.DataFrame(
            [
                {
                    "event_id": "E001",
                    "state": "Odisha",
                    "district": "Puri",
                    "start_date": "2020-06-10",
                    "source_record_id": "2020-0001-IND",
                    "event_source": "emdat_official_state",
                },
                {
                    "event_id": "E002",
                    "state": "Odisha",
                    "district": "Odisha",
                    "start_date": "2020-06-15",
                    "source_record_id": "2020-0002-IND",
                    "event_source": "emdat_official_state",
                },
            ]
        )

    def test_windows_use_fixed_onset_period_and_auditable_terms(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events, pre_days=0, post_days=93, include_district=True
        )
        self.assertEqual(windows[0]["query_start"].isoformat(), "2020-06-10")
        self.assertEqual(windows[0]["query_end"].isoformat(), "2020-09-11")
        self.assertEqual(windows[0]["location_terms"], ["odisha", "orissa", "puri"])

    def test_cli_default_uses_onset_plus_93_days(self):
        args = collect_gdelt.parse_args([])
        self.assertEqual(args.pre_days, 0)
        self.assertEqual(args.post_days, 93)
        self.assertEqual(args.max_batch_tib, 0.95)
        self.assertEqual(
            collect_gdelt._csv_values(args.languages),
            collect_gdelt.INDIA_MEDIA_LANGUAGES,
        )
        self.assertEqual(len(collect_gdelt.INDIA_MEDIA_LANGUAGES), 16)
        self.assertIn("ara", collect_gdelt.INDIA_MEDIA_LANGUAGES)
        self.assertIn("pus", collect_gdelt.INDIA_MEDIA_LANGUAGES)
        self.assertNotIn("asm", collect_gdelt.INDIA_MEDIA_LANGUAGES)
        self.assertNotIn("san", collect_gdelt.INDIA_MEDIA_LANGUAGES)

    def test_all_language_override_removes_source_language_filter(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events.iloc[:1], pre_days=0, post_days=93, include_district=True
        )
        sql = collect_gdelt.build_query(
            windows, languages=collect_gdelt._csv_values("all")
        )
        self.assertNotIn("WHERE source_lang IN UNNEST", sql)

    def test_query_filters_and_prevents_overlapping_state_double_count(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events, pre_days=0, post_days=93, include_district=True
        )
        sql = collect_gdelt.build_query(
            windows,
            topic_profile="strict",
            languages=("en", "hin"),
            exclude_domains=("example.com",),
        )
        self.assertIn("`gdelt-bq.gdeltv2.gkg_partitioned`", sql)
        self.assertIn("_PARTITIONTIME >=", sql)
        self.assertNotIn("Extras", sql)
        self.assertIn("NATURAL_DISASTER_FLOOD", sql)
        self.assertIn("NATURAL_DISASTER_FLOODWATER", sql)
        self.assertIn("NATURAL_DISASTER_FLOODED_AREAS", sql)
        self.assertIn("NATURAL_DISASTER_FLOOD_WARNING", sql)
        self.assertNotIn("NATURAL_DISASTER_MONSOON", sql)
        self.assertIn("UPPER(SPLIT(location_ref, '#')[SAFE_OFFSET(2)]) = 'IN'", sql)
        self.assertIn("FROM UNNEST(SPLIT(g.locations_lower, ';')) AS location_ref", sql)
        self.assertIn("WHERE TRIM(location_part) = term", sql)
        self.assertIn("SPLIT(theme_ref, ',')[SAFE_OFFSET(0)] IN UNNEST", sql)
        self.assertIn("TRIM(DocumentIdentifier) AS normalized_url", sql)
        self.assertNotIn("REGEXP_REPLACE(DocumentIdentifier", sql)
        self.assertIn("PARTITION BY normalized_url, state", sql)
        self.assertIn("JOIN gkg AS g", sql)
        self.assertNotIn("\n  JOIN g\n", sql)
        self.assertIn(
            "ON DATE(g.published_at) BETWEEN e.query_start AND e.query_end\n"
            "  WHERE (",
            sql,
        )
        self.assertIn("ORDER BY onset_distance, onset_date, event_id, published_at, url", sql)
        self.assertIn("source_lang IN UNNEST(['en', 'hin'])", sql)
        self.assertIn("NOT IN UNNEST(['example.com'])", sql)

    def test_broad_profile_adds_rain_and_monsoon(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events.iloc[:1], pre_days=3, post_days=21, include_district=False
        )
        sql = collect_gdelt.build_query(
            windows, topic_profile="broad", title_fallback=True
        )
        self.assertIn("NATURAL_DISASTER_HEAVY_RAIN", sql)
        self.assertIn("NATURAL_DISASTER_MONSOON", sql)
        self.assertIn("NATURAL_DISASTER_MONSOON_RAIN", sql)
        self.assertIn("NATURAL_DISASTER_TORRENTIAL_RAINFALL", sql)
        self.assertNotIn("'puri'", sql)
        self.assertIn("REGEXP_EXTRACT(Extras", sql)

    def test_partition_ranges_merge_overlapping_windows_only(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events, pre_days=0, post_days=93, include_district=True
        )
        self.assertEqual(
            collect_gdelt.coalesce_query_ranges(windows),
            [(pd.Timestamp("2020-06-10").date(), pd.Timestamp("2020-09-16").date())],
        )

    def test_batch_plan_keeps_overlapping_same_state_events_together(self):
        events = pd.concat(
            [
                self.events,
                pd.DataFrame(
                    [
                        {
                            "event_id": "E003",
                            "state": "Assam",
                            "district": "Assam",
                            "start_date": "2021-06-01",
                            "source_record_id": "2021-0001-IND",
                            "event_source": "emdat_official_state",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        windows = collect_gdelt.prepare_event_windows(
            events, pre_days=0, post_days=93, include_district=True
        )

        batches = collect_gdelt.plan_query_batches(
            windows,
            max_bytes=100,
            estimate_windows=lambda candidate: 45 * len(candidate),
        )

        self.assertEqual(len(batches), 2)
        self.assertEqual(
            [row["event_id"] for row in batches[0]["windows"]],
            ["E001", "E002"],
        )
        self.assertEqual(
            [row["event_id"] for row in batches[1]["windows"]],
            ["E003"],
        )
        self.assertTrue(all(batch["estimated_bytes"] <= 100 for batch in batches))

    def test_batch_plan_rejects_indivisible_group_over_limit(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events, pre_days=0, post_days=93, include_district=True
        )
        with self.assertRaisesRegex(ValueError, "indivisible"):
            collect_gdelt.plan_query_batches(
                windows,
                max_bytes=100,
                estimate_windows=lambda candidate: 60 * len(candidate),
            )

    def test_merge_batches_writes_primary_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.csv"
            batch_dir = root / "batches"
            output_path = root / "gdelt.json"
            metadata_path = root / "gdelt.meta.json"
            batch_dir.mkdir()
            self.events.to_csv(events_path, index=False)

            batches = []
            for index, event_id in enumerate(("E001", "E002"), start=1):
                batch_id = f"B{index:03d}"
                output_name = f"{batch_id}.json"
                row = {
                    "event_id": event_id,
                    "state": "Odisha",
                    "source_record_id": f"2020-000{index}-IND",
                    "source_lang": "und",
                    "article_count": 0,
                    "first_article_date": None,
                    "last_article_date": None,
                    "coverage_days": 0,
                }
                (batch_dir / output_name).write_text(
                    json.dumps([row]), encoding="utf-8"
                )
                batches.append(
                    {
                        "batch_id": batch_id,
                        "event_ids": [event_id],
                        "output_file": output_name,
                        "metadata_file": f"{batch_id}.meta.json",
                    }
                )
            manifest = {
                "version": 1,
                "events_sha256": hashlib.sha256(events_path.read_bytes()).hexdigest(),
                "query_options": {},
                "batches": batches,
            }
            (batch_dir / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            result = collect_gdelt.main(
                [
                    "--events",
                    str(events_path),
                    "--batch-dir",
                    str(batch_dir),
                    "--output",
                    str(output_path),
                    "--metadata",
                    str(metadata_path),
                    "--merge-batches",
                ]
            )

            self.assertEqual(result, 0)
            self.assertEqual(len(json.loads(output_path.read_text())), 2)
            self.assertEqual(
                json.loads(metadata_path.read_text())["collection_mode"],
                "merged_batches",
            )

    def test_validation_requires_every_event_including_zero_results(self):
        rows = [
            {
                "event_id": "E001",
                "state": "Odisha",
                "source_record_id": "2020-0001-IND",
                "source_lang": "und",
                "article_count": 0,
                "first_article_date": None,
                "last_article_date": None,
                "coverage_days": 0,
            }
        ]
        collect_gdelt.validate_output(rows, {"E001"})
        with self.assertRaises(ValueError):
            collect_gdelt.validate_output(rows, {"E001", "E002"})


if __name__ == "__main__":
    unittest.main()
