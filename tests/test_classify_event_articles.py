import csv
import json
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import classify_event_articles as classifier


def write_event_sources(root: Path) -> tuple[Path, Path]:
    events = pd.DataFrame(
        [
            {
                "event_id": "E001",
                "state": "State A",
                "district": "North",
                "disaster_type": "flood",
                "start_date": "2020-01-01",
                "end_date": "2020-01-05",
                "source_record_id": "2020-0001-IND",
            },
            {
                "event_id": "E002",
                "state": "State A",
                "district": "South",
                "disaster_type": "flood",
                "start_date": "2020-01-10",
                "end_date": "2020-01-12",
                "source_record_id": "2020-0002-IND",
            },
            {
                "event_id": "E003",
                "state": "State B",
                "district": "East",
                "disaster_type": "flood",
                "start_date": "2020-01-01",
                "end_date": "2020-01-04",
                "source_record_id": "2020-0003-IND",
            },
        ]
    )
    rich = events.rename(
        columns={
            "source_record_id": "DisNo.",
            "disaster_type": "Disaster Type",
        }
    ).copy()
    rich["Disaster Subtype"] = "Flash flood"
    rich["Event Name"] = ["North flood", "South flood", "East flood"]
    rich["Location"] = ["North river", "South river", "East river"]
    rich["Origin"] = "Heavy rain"
    rich["Associated Types"] = "Landslide"
    rich["River Basin"] = ["N", "S", "E"]
    events_path = root / "events.csv"
    rich_path = root / "EM-DAT.xlsx"
    events.to_csv(events_path, index=False)
    rich.to_excel(rich_path, index=False)
    return events_path, rich_path


def write_article_database(root: Path) -> Path:
    path = root / "articles.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE documents (
          url TEXT PRIMARY KEY,
          status TEXT,
          http_status INTEGER,
          final_url TEXT,
          page_title TEXT,
          canonical_url TEXT,
          extraction_method TEXT,
          extraction_confidence REAL,
          word_count INTEGER,
          candidate_count INTEGER,
          selected_attempt_url TEXT,
          fallback_used TEXT,
          attempt_count INTEGER,
          error TEXT,
          content_sha256 TEXT,
          body_text TEXT
        );
        CREATE TABLE event_articles (
          event_id TEXT,
          state TEXT,
          source_record_id TEXT,
          gkg_record_id TEXT,
          published_at TEXT,
          url TEXT,
          source_domain TEXT,
          source_lang TEXT,
          gdelt_title TEXT,
          authors TEXT,
          tone REAL,
          sharing_image TEXT
        );
        """
    )
    bodies = {
        "https://a.example/shared": ("ok", "same-hash", "Flood waters reached homes."),
        "https://b.example/same-body": ("ok", "same-hash", "Flood waters reached homes."),
        "https://c.example/hindi": ("extract_weak", "hindi-hash", "गांव में बाढ़ से घर डूब गए।"),
        "https://d.example/weather": ("ok", "weather-hash", "Heavy rain is expected."),
        "https://e.example/missing": ("http_error", None, None),
        "https://f.example/other": (
            "ok", "other-hash", "Inundation damaged another village."
        ),
        "not-a-url": ("ok", "bad-url", "flood"),
    }
    connection.executemany(
        "INSERT INTO documents(url,status,content_sha256,body_text) VALUES (?,?,?,?)",
        [(url, *values) for url, values in bodies.items()],
    )
    links = [
        ("E001", "State A", "2020-0001-IND", "2020-01-15T12:00:00Z", "https://a.example/shared"),
        ("E001", "State B", "2020-0001-IND", "2020-01-15T12:00:00Z", "https://a.example/shared"),
        ("E001", "State A", "2020-0001-IND", "2020-01-15T12:00:00Z", "https://b.example/same-body"),
        ("E001", "State A", "2020-0001-IND", "2020-01-16T12:00:00Z", "https://c.example/hindi"),
        ("E001", "State A", "2020-0001-IND", "2020-01-17T12:00:00Z", "https://d.example/weather"),
        ("E001", "State A", "2020-0001-IND", "2020-01-18T12:00:00Z", "https://e.example/missing"),
        ("E001", "State A", "2020-0001-IND", "2020-01-19T12:00:00Z", "https://f.example/other"),
        ("E001", "State A", "2020-0001-IND", "2021-01-01T12:00:00Z", "not-a-url"),
    ]
    connection.executemany(
        """
        INSERT INTO event_articles(
          event_id,state,source_record_id,published_at,url,source_domain,source_lang,
          gdelt_title,authors,tone,sharing_image
        ) VALUES (?,?,?,?,?,'example.com','en','Title','Author',0.0,NULL)
        """,
        links,
    )
    connection.commit()
    connection.close()
    return path


class KeywordTests(unittest.TestCase):
    def test_multilingual_keywords_scan_full_body_and_keep_context(self):
        body = "x" * 5_000 + " बाढ़ " + "tail" * 200
        status, excerpt, matches = classifier.classify_heuristic(
            "ok", body, "Village update"
        )
        self.assertLessEqual(len(excerpt), classifier.TEXT_CHAR_LIMIT)
        self.assertEqual(status, "keyword_match")
        self.assertIn("hin:बाढ़", matches)
        self.assertIn("Village update", excerpt)
        self.assertIn("बाढ़", excerpt)

    def test_unicode_normalization_offsets_do_not_drop_matched_context(self):
        # NFKC contracts each two-codepoint sequence to one character. The
        # keyword is beyond the raw 1,000-char lead but before normalized 1,000.
        body = ("e\u0301" * 700) + " flood damaged homes"
        status, excerpt, matches = classifier.classify_heuristic("ok", body)
        self.assertEqual(status, "keyword_match")
        self.assertIn("en:flood", matches)
        self.assertIn("flood", excerpt)
        self.assertIn("MATCHED CONTEXT", excerpt)

    def test_page_title_participates_in_keyword_filter(self):
        status, excerpt, matches = classifier.classify_heuristic(
            "ok",
            "The district administration issued a public notice.",
            "Flash flood damages several villages",
        )
        self.assertEqual(status, "keyword_match")
        self.assertIn("en:flash flood", matches)
        self.assertIn("Flash flood", excerpt)

    def test_weak_body_is_separate_from_primary_candidates(self):
        status, _excerpt, matches = classifier.classify_heuristic(
            "extract_weak", "गांव में बाढ़ से घर डूब गए।"
        )
        self.assertEqual(status, "weak_keyword_match")
        self.assertIn("hin:बाढ़", matches)

    def test_english_keywords_use_word_boundaries(self):
        status, _excerpt, matches = classifier.classify_heuristic(
            "ok", "The stadium installed new LED floodlights."
        )
        self.assertEqual(status, "keyword_absent")
        self.assertNotIn("en:flood", matches)

    def test_missing_body_and_generic_rain_are_rejected(self):
        self.assertEqual(
            classifier.classify_heuristic("http_error", "flood")[0],
            "no_body",
        )
        self.assertEqual(
            classifier.classify_heuristic("ok", "Heavy monsoon rain")[0],
            "keyword_absent",
        )


class CandidatePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.events_path, self.rich_path = write_event_sources(self.root)
        self.articles_path = write_article_database(self.root)
        self.relevance_path = self.root / "relevance.sqlite"

    def tearDown(self):
        self.tempdir.cleanup()

    def prepare(self):
        return classifier.prepare_candidates(
            self.articles_path,
            self.relevance_path,
            self.events_path,
            self.rich_path,
        )

    def test_candidate_expansion_allows_multiple_events_and_states(self):
        result = self.prepare()
        self.assertEqual(result["selected_events"], 3)
        connection = sqlite3.connect(self.relevance_path)
        try:
            event_ids = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT event_id FROM article_event_candidates
                    WHERE url='https://a.example/shared'
                    """
                )
            }
            self.assertEqual(event_ids, {"E001", "E002", "E003"})
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM article_event_candidates WHERE url='not-a-url'"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_body_hash_cache_keeps_url_level_counting(self):
        self.prepare()
        connection = classifier.connect_relevance_database(self.relevance_path)
        try:
            created = classifier.ensure_llm_requests(
                connection, classifier.configured_model(), event_ids=["E001"]
            )
            # Two different URLs have the same body hash and event profile.
            self.assertGreaterEqual(created, 2)
            shared_requests = connection.execute(
                """
                SELECT COUNT(DISTINCT request_key)
                FROM article_event_candidates
                WHERE event_id='E001' AND url IN (
                  'https://a.example/shared', 'https://b.example/same-body'
                )
                """
            ).fetchone()[0]
            self.assertEqual(shared_requests, 1)
            request_key = connection.execute(
                """
                SELECT request_key FROM article_event_candidates
                WHERE event_id='E001' AND url='https://a.example/shared'
                """
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO llm_decisions(
                  request_key,related,decision_status,decided_at_utc
                ) VALUES (?,1,'related','2020-01-01T00:00:00Z')
                """,
                (request_key,),
            )
            connection.execute(
                "UPDATE llm_requests SET status='completed' WHERE request_key=?",
                (request_key,),
            )
            connection.commit()
        finally:
            connection.close()

        counts_path = self.root / "counts.csv"
        mapping_path = self.root / "mapping.csv.gz"
        classifier.export_results(self.relevance_path, counts_path, mapping_path)
        counts = pd.read_csv(counts_path).set_index("event_id")
        self.assertEqual(counts.loc["E001", "final_article_count"], 2)

    def test_prompt_cache_separates_same_body_with_different_titles(self):
        articles = sqlite3.connect(self.articles_path)
        try:
            articles.execute(
                "UPDATE documents SET page_title='North district flood' "
                "WHERE url='https://a.example/shared'"
            )
            articles.execute(
                "UPDATE documents SET page_title='South district flood' "
                "WHERE url='https://b.example/same-body'"
            )
            articles.commit()
        finally:
            articles.close()
        self.prepare()
        connection = classifier.connect_relevance_database(self.relevance_path)
        try:
            classifier.ensure_llm_requests(
                connection, classifier.configured_model(), event_ids=["E001"]
            )
            keys = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT request_key
                    FROM article_event_candidates
                    WHERE event_id='E001' AND url IN (
                      'https://a.example/shared', 'https://b.example/same-body'
                    )
                    """
                )
            }
            self.assertEqual(len(keys), 2)
        finally:
            connection.close()

    def test_all_events_are_exported_even_when_no_candidates_exist(self):
        self.prepare()
        counts_path = self.root / "counts.csv"
        mapping_path = self.root / "mapping.csv.gz"
        classifier.export_results(self.relevance_path, counts_path, mapping_path)
        counts = pd.read_csv(counts_path)
        self.assertEqual(set(counts["event_id"]), {"E001", "E002", "E003"})

    def test_limited_run_cannot_replace_a_nonempty_database(self):
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, "limited rebuild"):
            classifier.prepare_candidates(
                self.articles_path,
                self.relevance_path,
                self.events_path,
                self.rich_path,
                limit=1,
            )

    def test_full_prepare_drops_events_removed_from_the_registry(self):
        self.prepare()
        events = pd.read_csv(self.events_path)
        events[events["event_id"] != "E003"].to_csv(self.events_path, index=False)
        result = classifier.prepare_candidates(
            self.articles_path,
            self.relevance_path,
            self.events_path,
            self.rich_path,
        )
        self.assertEqual(result["pruned_stale_event_profiles"], 1)
        connection = sqlite3.connect(self.relevance_path)
        try:
            remaining = {
                row[0]
                for row in connection.execute("SELECT event_id FROM event_profiles")
            }
            self.assertEqual(remaining, {"E001", "E002"})
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM article_event_candidates WHERE event_id='E003'"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()
        counts_path = self.root / "counts.csv"
        classifier.export_results(
            self.relevance_path, counts_path, self.root / "mapping.csv.gz"
        )
        counts = pd.read_csv(counts_path)
        self.assertEqual(set(counts["event_id"]), {"E001", "E002"})

    def test_filtered_prepare_keeps_other_event_profiles(self):
        self.prepare()
        classifier.prepare_candidates(
            self.articles_path,
            self.relevance_path,
            self.events_path,
            self.rich_path,
            event_ids=["E001"],
        )
        connection = sqlite3.connect(self.relevance_path)
        try:
            remaining = {
                row[0]
                for row in connection.execute("SELECT event_id FROM event_profiles")
            }
            self.assertEqual(remaining, {"E001", "E002", "E003"})
        finally:
            connection.close()

    def test_resume_refreshes_repaired_bodies_without_dropping_cached_keys(self):
        self.prepare()
        connection = classifier.connect_relevance_database(self.relevance_path)
        try:
            classifier.ensure_llm_requests(
                connection, classifier.configured_model(), event_ids=["E001"]
            )
            shared_key = connection.execute(
                """
                SELECT request_key FROM article_event_candidates
                WHERE event_id='E001' AND url='https://a.example/shared'
                """
            ).fetchone()[0]
            other_key = connection.execute(
                """
                SELECT request_key FROM article_event_candidates
                WHERE event_id='E001' AND url='https://f.example/other'
                """
            ).fetchone()[0]
            missing_status = connection.execute(
                """
                SELECT h.status FROM heuristic_results AS h
                WHERE h.event_id='E001' AND h.url='https://e.example/missing'
                """
            ).fetchone()[0]
            self.assertIsNotNone(shared_key)
            self.assertIsNotNone(other_key)
            self.assertEqual(missing_status, "no_body")
        finally:
            connection.close()

        articles = sqlite3.connect(self.articles_path)
        try:
            articles.execute(
                """
                UPDATE documents
                SET status='ok', content_sha256='repaired-hash',
                    body_text='Flood waters returned to the village.'
                WHERE url='https://e.example/missing'
                """
            )
            articles.execute(
                """
                UPDATE documents
                SET content_sha256='other-hash-2',
                    body_text='Floodwater damaged another village again.'
                WHERE url='https://f.example/other'
                """
            )
            articles.commit()
        finally:
            articles.close()

        classifier.prepare_candidates(
            self.articles_path,
            self.relevance_path,
            self.events_path,
            self.rich_path,
            resume=True,
        )
        connection = sqlite3.connect(self.relevance_path)
        try:
            shared_after = connection.execute(
                """
                SELECT request_key FROM article_event_candidates
                WHERE event_id='E001' AND url='https://a.example/shared'
                """
            ).fetchone()[0]
            other_after = connection.execute(
                """
                SELECT request_key FROM article_event_candidates
                WHERE event_id='E001' AND url='https://f.example/other'
                """
            ).fetchone()[0]
            repaired = connection.execute(
                """
                SELECT c.document_status, c.text_excerpt, h.status
                FROM article_event_candidates AS c
                JOIN heuristic_results AS h
                  ON h.event_id=c.event_id AND h.url=c.url
                WHERE c.event_id='E001' AND c.url='https://e.example/missing'
                """
            ).fetchone()
            self.assertEqual(shared_after, shared_key)
            self.assertIsNone(other_after)
            self.assertEqual(repaired[0], "ok")
            self.assertIn("Flood waters", repaired[1])
            self.assertEqual(repaired[2], "keyword_match")
        finally:
            connection.close()


class LlmContractTests(unittest.TestCase):
    def test_production_model_and_reasoning_are_fixed(self):
        self.assertEqual(classifier.configured_model(), "gpt-5.6-luna")
        request = classifier.build_batch_request(
            "cvnd_test",
            classifier.configured_model(),
            {
                "event_id": "E001",
                "source_record_id": "2020-0001-IND",
                "state": "State A",
                "district": "North",
                "start_date": "2020-01-01",
                "end_date": "2020-01-05",
                "disaster_type": "Flood",
                "disaster_subtype": "Flash flood",
                "event_name": "",
                "official_location": "North river",
                "origin": "Heavy rain",
                "associated_types": "",
                "river_basin": "N",
            },
            "Flood waters reached homes.",
        )
        body = request["body"]
        self.assertEqual(body["model"], "gpt-5.6-luna")
        self.assertEqual(body["reasoning"], {"effort": "none"})
        self.assertEqual(body["text"]["format"], classifier.RESPONSE_SCHEMA)
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(request["url"], "/v1/responses")

    def test_batch_custom_id_is_the_64_character_request_key(self):
        profile = {
            "event_id": "E001",
            "source_record_id": "2020-0001-IND",
            "state": "State A",
            "district": "North",
            "start_date": "2020-01-01",
            "end_date": "2020-01-05",
            "disaster_type": "Flood",
            "disaster_subtype": "Flash flood",
            "event_name": "",
            "official_location": "North river",
            "origin": "Heavy rain",
            "associated_types": "",
            "river_basin": "N",
        }
        request_key = classifier.request_key_for(
            profile, "Flood waters reached homes.", classifier.configured_model()
        )
        self.assertEqual(len(request_key), 64)
        self.assertEqual(classifier.batch_custom_id(request_key), request_key)
        with self.assertRaisesRegex(ValueError, "64 characters"):
            classifier.batch_custom_id("x" * 65)

    def test_model_is_hardcoded_and_missing_value_fails(self):
        with mock.patch.object(classifier, "OPENAI_EVENT_FILTER_MODEL", ""):
            with self.assertRaisesRegex(RuntimeError, "is empty"):
                classifier.configured_model()
        submit_actions = classifier.build_parser()._subparsers._group_actions[0].choices[
            "submit"
        ]._actions
        option_strings = {
            flag for action in submit_actions for flag in action.option_strings
        }
        self.assertNotIn("--model", option_strings)

    def test_structured_output_and_ambiguous_output(self):
        related, status = classifier.extract_related(
            {
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": json.dumps({"related": True})}
                        ]
                    }
                ]
            }
        )
        self.assertEqual((related, status), (True, "parsed"))
        self.assertEqual(
            classifier.extract_related({"output_text": "maybe"}),
            (False, "ambiguous_no"),
        )

    def test_batch_chunks_respect_request_count_limit(self):
        rows = [
            {"custom_id": f"id-{index}", "request_json": "{}"}
            for index in range(5)
        ]
        chunks = list(classifier.chunk_requests(rows, 1_000, max_requests=2))
        self.assertEqual([len(chunk) for chunk in chunks], [2, 2, 1])

    def test_submit_cli_uses_a_conservative_default_wave(self):
        args = classifier.build_parser().parse_args(["submit", "--production"])
        self.assertEqual(args.limit, classifier.DEFAULT_SUBMIT_REQUEST_LIMIT)


class FakeFiles:
    def __init__(self):
        self.uploads = []
        self.downloads = {}

    def create(self, *, file, purpose):
        self.uploads.append((file.read(), purpose))
        return SimpleNamespace(id=f"input-{len(self.uploads)}")

    def content(self, file_id):
        return io.BytesIO(self.downloads[file_id])


class FakeBatches:
    def __init__(self):
        self.jobs = {}

    def create(self, *, input_file_id, endpoint, completion_window, metadata):
        batch_id = f"batch-{len(self.jobs) + 1}"
        job = SimpleNamespace(
            id=batch_id,
            status="validating",
            input_file_id=input_file_id,
            output_file_id=None,
            error_file_id=None,
            request_counts={},
            errors=None,
        )
        self.jobs[batch_id] = job
        return job

    def retrieve(self, batch_id):
        return self.jobs[batch_id]


class FakeOpenAI:
    def __init__(self):
        self.files = FakeFiles()
        self.batches = FakeBatches()


class PilotWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        events, rich = write_event_sources(self.root)
        articles = write_article_database(self.root)
        self.database = self.root / "relevance.sqlite"
        classifier.prepare_candidates(articles, self.database, events, rich)
        self.manifest = self.root / "pilot.csv"
        self.api = FakeOpenAI()
        self.model_patch = mock.patch.object(
            classifier, "OPENAI_EVENT_FILTER_MODEL", "fixed-test-model"
        )
        self.model_patch.start()

    def tearDown(self):
        self.model_patch.stop()
        self.tempdir.cleanup()

    def create_pilot(self):
        return classifier.create_pilot_manifest(
            self.database,
            self.manifest,
            size=4,
            negative_share=0.25,
            seed=7,
            max_per_domain=0,
        )

    def test_stratified_pilot_manifest_submits_only_selected_requests(self):
        created = self.create_pilot()
        self.assertEqual(created["sample_count"], 4)
        with self.manifest.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(
            Counter(row["sample_role"] for row in rows),
            Counter({"heuristic_positive": 3, "heuristic_negative_control": 1}),
        )
        submitted = classifier.submit_batches(
            self.database,
            self.root / "batches",
            pilot_manifest=self.manifest,
            client=self.api,
        )
        submitted_lines = [
            json.loads(line)
            for upload, _purpose in self.api.files.uploads
            for line in upload.splitlines()
        ]
        self.assertEqual(
            {line["custom_id"] for line in submitted_lines},
            {row["request_key"] for row in rows},
        )
        self.assertEqual(submitted["submission_scope"], "pilot")
        connection = sqlite3.connect(self.database)
        try:
            scope, pilot_id = connection.execute(
                "SELECT submission_scope,pilot_id FROM batch_jobs"
            ).fetchone()
            self.assertEqual(scope, "pilot")
            self.assertEqual(pilot_id, created["pilot_id"])
        finally:
            connection.close()

    def test_human_evaluation_creates_a_production_gate(self):
        self.create_pilot()
        connection = classifier.connect_relevance_database(self.database)
        try:
            _metadata, rows = classifier.read_pilot_artifacts(
                connection, self.manifest, "fixed-test-model"
            )
            classifier.ensure_llm_requests(
                connection,
                "fixed-test-model",
                candidate_pairs=[(row["event_id"], row["url"]) for row in rows],
                include_negative_controls=True,
            )
            for row in rows:
                related = int(row["sample_role"] == "heuristic_positive")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO llm_decisions(
                      request_key,related,decision_status,decided_at_utc
                    ) VALUES (?,?,'parsed','2026-01-01T00:00:00Z')
                    """,
                    (row["request_key"], related),
                )
                connection.execute(
                    "UPDATE llm_requests SET status='completed' WHERE request_key=?",
                    (row["request_key"],),
                )
            connection.commit()
        finally:
            connection.close()

        with self.manifest.open(encoding="utf-8", newline="") as handle:
            labeled = list(csv.DictReader(handle))
        for row in labeled:
            row["human_related"] = int(
                row["sample_role"] == "heuristic_positive"
            )
        with self.manifest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=classifier.PILOT_MANIFEST_FIELDS)
            writer.writeheader()
            writer.writerows(labeled)

        report_path = self.root / "pilot-evaluation.json"
        report = classifier.evaluate_pilot(
            self.database,
            self.manifest,
            report_path,
            self.root / "pilot-evaluated.csv",
            min_labels=4,
            min_human_positives=1,
            min_negative_controls=1,
            min_overlap_labels=0,
            min_accuracy=1.0,
            min_precision=1.0,
            min_recall=1.0,
            min_overlap_accuracy=0.0,
            max_heuristic_false_negative_rate=0.0,
        )
        self.assertTrue(report["passed"])

        submitted = classifier.submit_batches(
            self.database,
            self.root / "production-batches",
            production=True,
            gate_report=report_path,
            limit=1,
            client=self.api,
        )
        self.assertEqual(submitted["submission_scope"], "production")

    def test_production_submission_rejects_a_missing_gate(self):
        with self.assertRaisesRegex(ValueError, "requires --gate-report"):
            classifier.submit_batches(
                self.database,
                self.root / "batches",
                production=True,
                client=self.api,
            )


class BatchLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        events, rich = write_event_sources(self.root)
        articles = write_article_database(self.root)
        self.database = self.root / "relevance.sqlite"
        classifier.prepare_candidates(articles, self.database, events, rich)
        self.api = FakeOpenAI()
        self.model_patch = mock.patch.object(
            classifier, "OPENAI_EVENT_FILTER_MODEL", "fixed-test-model"
        )
        self.model_patch.start()

    def tearDown(self):
        self.model_patch.stop()
        self.tempdir.cleanup()

    def test_submit_and_collect_are_order_independent(self):
        submitted = classifier.submit_batches(
            self.database,
            self.root / "batches",
            event_ids=["E001"],
            client=self.api,
            enforce_gate=False,
        )
        self.assertEqual(submitted["submitted_batches"], 1)
        self.assertEqual(self.api.files.uploads[0][1], "batch")
        self.assertEqual(
            json.loads(self.api.files.uploads[0][0].splitlines()[0])["url"],
            "/v1/responses",
        )
        first_body = json.loads(self.api.files.uploads[0][0].splitlines()[0])["body"]
        self.assertEqual(first_body["reasoning"], {"effort": "none"})

        connection = sqlite3.connect(self.database)
        request_rows = list(
            connection.execute(
                "SELECT custom_id, request_key FROM llm_requests WHERE event_id='E001'"
            )
        )
        custom_ids = [row[0] for row in request_rows]
        for custom_id, request_key in request_rows:
            self.assertEqual(custom_id, request_key)
            self.assertEqual(len(custom_id), 64)
        connection.close()
        lines = [
            json.dumps(
                {
                    "custom_id": custom_id,
                    "response": {
                        "status_code": 200,
                        "body": {
                            "id": f"response-{index}",
                            "output_text": json.dumps({"related": True}),
                        },
                    },
                    "error": None,
                }
            )
            for index, custom_id in enumerate(reversed(custom_ids), start=1)
        ]
        self.api.files.downloads["output-1"] = ("\n".join(lines) + "\n").encode()
        job = self.api.batches.jobs[submitted["batch_ids"][0]]
        job.status = "completed"
        job.output_file_id = "output-1"
        job.request_counts = {"completed": len(lines), "failed": 0, "total": len(lines)}

        collected = classifier.collect_batches(
            self.database, self.root / "batches", client=self.api
        )
        self.assertEqual(collected["decisions"], len(lines))
        counts_path = self.root / "counts.csv"
        classifier.export_results(
            self.database, counts_path, self.root / "mapping.csv.gz"
        )
        counts = pd.read_csv(counts_path).set_index("event_id")
        # Three E001 URLs pass keywords; two same-body URLs share one API call.
        self.assertEqual(counts.loc["E001", "final_article_count"], 3)
        self.assertEqual(counts.loc["E001", "unique_llm_request_count"], 2)

    def test_expired_requests_can_be_requeued_without_decisions(self):
        submitted = classifier.submit_batches(
            self.database,
            self.root / "batches",
            event_ids=["E001"],
            client=self.api,
            enforce_gate=False,
        )
        self.api.batches.jobs[submitted["batch_ids"][0]].status = "expired"
        classifier.status_batches(self.database, client=self.api)
        connection = classifier.connect_relevance_database(self.database)
        try:
            self.assertGreater(
                connection.execute(
                    "SELECT COUNT(*) FROM llm_requests WHERE status='expired'"
                ).fetchone()[0],
                0,
            )
            classifier.ensure_llm_requests(
                connection,
                "fixed-test-model",
                event_ids=["E001"],
                retry_failed=True,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM llm_requests WHERE status='expired'"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_expired_batch_preserves_partial_completed_output(self):
        submitted = classifier.submit_batches(
            self.database,
            self.root / "batches",
            event_ids=["E001"],
            client=self.api,
            enforce_gate=False,
        )
        batch_id = submitted["batch_ids"][0]
        connection = sqlite3.connect(self.database)
        custom_id = connection.execute(
            "SELECT custom_id FROM llm_requests WHERE batch_id=? ORDER BY custom_id LIMIT 1",
            (batch_id,),
        ).fetchone()[0]
        connection.close()
        self.api.files.downloads["partial-output"] = (
            json.dumps(
                {
                    "custom_id": custom_id,
                    "response": {
                        "status_code": 200,
                        "body": {
                            "id": "response-partial",
                            "output_text": json.dumps({"related": True}),
                        },
                    },
                    "error": None,
                }
            )
            + "\n"
        ).encode()
        job = self.api.batches.jobs[batch_id]
        job.status = "expired"
        job.output_file_id = "partial-output"
        job.request_counts = {"completed": 1, "failed": 0, "total": 2}

        collected = classifier.collect_batches(
            self.database, self.root / "batches", client=self.api
        )
        self.assertEqual(collected["decisions"], 1)
        self.assertGreater(collected["failed"], 0)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM llm_decisions WHERE related=1"
                ).fetchone()[0],
                1,
            )
            self.assertGreater(
                connection.execute(
                    "SELECT COUNT(*) FROM llm_requests WHERE status='failed'"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_active_or_uncollected_batch_blocks_another_wave(self):
        classifier.submit_batches(
            self.database,
            self.root / "batches",
            event_ids=["E001"],
            limit=1,
            client=self.api,
            enforce_gate=False,
        )
        with self.assertRaisesRegex(RuntimeError, "Run status and collect"):
            classifier.submit_batches(
                self.database,
                self.root / "batches",
                event_ids=["E001"],
                limit=1,
                client=self.api,
                enforce_gate=False,
            )

    def test_error_file_does_not_overwrite_a_collected_decision(self):
        submitted = classifier.submit_batches(
            self.database,
            self.root / "batches",
            event_ids=["E001"],
            limit=1,
            client=self.api,
            enforce_gate=False,
        )
        batch_id = submitted["batch_ids"][0]
        connection = sqlite3.connect(self.database)
        custom_id = connection.execute(
            "SELECT custom_id FROM llm_requests WHERE batch_id=?",
            (batch_id,),
        ).fetchone()[0]
        connection.close()
        success_line = json.dumps(
            {
                "custom_id": custom_id,
                "response": {
                    "status_code": 200,
                    "body": {
                        "id": "response-ok",
                        "output_text": json.dumps({"related": True}),
                    },
                },
                "error": None,
            }
        )
        error_line = json.dumps(
            {
                "custom_id": custom_id,
                "response": None,
                "error": {"code": "server_error", "message": "duplicate error row"},
            }
        )
        self.api.files.downloads["output-ok"] = (success_line + "\n").encode()
        self.api.files.downloads["error-dup"] = (error_line + "\n").encode()
        job = self.api.batches.jobs[batch_id]
        job.status = "completed"
        job.output_file_id = "output-ok"
        job.error_file_id = "error-dup"

        collected = classifier.collect_batches(
            self.database, self.root / "batches", client=self.api
        )
        self.assertEqual(collected["decisions"], 1)
        self.assertEqual(collected["related"], 1)
        connection = sqlite3.connect(self.database)
        try:
            status, related = connection.execute(
                """
                SELECT r.status, d.related
                FROM llm_requests AS r
                JOIN llm_decisions AS d ON d.request_key=r.request_key
                WHERE r.custom_id=?
                """,
                (custom_id,),
            ).fetchone()
            self.assertEqual(status, "completed")
            self.assertEqual(related, 1)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
