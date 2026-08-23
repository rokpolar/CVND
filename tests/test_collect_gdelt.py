import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(args.maximum_tib_billed, 2.0)
        self.assertEqual(args.article_output.name, "gdelt_bq.articles.jsonl.gz")
        self.assertEqual(args.article_metadata_profile, "basic")
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

    def test_article_query_returns_urls_and_gkg_metadata(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events, pre_days=0, post_days=93, include_district=True
        )
        sql = collect_gdelt.build_query(
            windows,
            languages=("en", "hin"),
            result_level="articles",
            article_metadata_profile="rich",
        )
        self.assertIn("GKGRECORDID AS gkg_record_id", sql)
        self.assertIn("SourceCommonName", sql)
        self.assertIn("AS title", sql)
        self.assertIn("AS authors", sql)
        self.assertIn("AS tone", sql)
        self.assertIn("SharingImage", sql)
        self.assertIn("FROM assigned\nORDER BY event_id, published_at", sql)
        self.assertNotIn("language_stats AS", sql)

    def test_basic_article_profile_avoids_extra_gkg_columns(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events, pre_days=0, post_days=93, include_district=True
        )
        sql = collect_gdelt.build_query(windows, result_level="articles")
        self.assertIn("NET.REG_DOMAIN(DocumentIdentifier)", sql)
        self.assertIn("CAST(NULL AS STRING) AS title", sql)
        self.assertNotIn("GKGRECORDID AS", sql)
        self.assertNotIn("REGEXP_EXTRACT(Extras", sql)

    def test_article_rows_are_aggregated_locally_for_mss(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events, pre_days=0, post_days=93, include_district=True
        )
        accumulator = collect_gdelt.ArticleSummaryAccumulator(windows)
        base = {
            "event_id": "E001",
            "state": "Odisha",
            "source_record_id": "2020-0001-IND",
            "gkg_record_id": "record-1",
            "url": "https://example.com/1",
            "source_domain": "example.com",
            "source_lang": "en",
        }
        accumulator.add({**base, "published_at": "2020-06-10T01:00:00+00:00"})
        accumulator.add(
            {
                **base,
                "gkg_record_id": "record-2",
                "url": "https://example.com/2",
                "published_at": "2020-06-11T02:00:00+00:00",
            }
        )
        rows = accumulator.finish()
        event_one = next(row for row in rows if row["event_id"] == "E001")
        event_two = next(row for row in rows if row["event_id"] == "E002")
        self.assertEqual(event_one["article_count"], 2)
        self.assertEqual(event_one["coverage_days"], 2)
        self.assertEqual(event_two["article_count"], 0)

    def test_partition_ranges_merge_overlapping_windows_only(self):
        windows = collect_gdelt.prepare_event_windows(
            self.events, pre_days=0, post_days=93, include_district=True
        )
        self.assertEqual(
            collect_gdelt.coalesce_query_ranges(windows),
            [(pd.Timestamp("2020-06-10").date(), pd.Timestamp("2020-09-16").date())],
        )

    def test_execute_writes_single_article_and_summary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.csv"
            sql_path = root / "query.sql"
            article_path = root / "articles.jsonl.gz"
            output_path = root / "gdelt.json"
            metadata_path = root / "gdelt.meta.json"
            self.events.to_csv(events_path, index=False)

            summary_rows = [
                {
                    "event_id": row.event_id,
                    "state": row.state,
                    "source_record_id": row.source_record_id,
                    "source_lang": "und",
                    "article_count": 0,
                    "first_article_date": None,
                    "last_article_date": None,
                    "coverage_days": 0,
                    "coverage_days_threshold_1": 0,
                }
                for row in self.events.itertuples()
            ]

            def fake_execute(sql, project, *, article_output, windows, maximum_bytes_billed):
                article_output.write_bytes(b"test")
                return summary_rows, {
                    "job_id": "job-1",
                    "billing_project": project,
                    "total_bytes_processed": 123,
                    "cache_hit": False,
                    "article_rows": 0,
                }

            with patch.object(
                collect_gdelt, "execute_article_query", side_effect=fake_execute
            ):
                result = collect_gdelt.main(
                    [
                        "--events", str(events_path),
                        "--sql-output", str(sql_path),
                        "--article-output", str(article_path),
                        "--output", str(output_path),
                        "--metadata", str(metadata_path),
                        "--billing-project", "test-project",
                        "--execute",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertTrue(article_path.exists())
            self.assertEqual(len(json.loads(output_path.read_text())), 2)
            metadata = json.loads(metadata_path.read_text())
            self.assertEqual(metadata["collection_mode"], "article_metadata")
            self.assertEqual(metadata["job_id"], "job-1")

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
