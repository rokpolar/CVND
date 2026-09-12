"""Offline contract tests: paid calls are mocked."""
import argparse
import gzip
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import article_qa as qa
from district_recovery import apply_recovery
from district_keys import make_event_district_id


class QATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.args = argparse.Namespace(
            registry=self.root/"registry.csv", source=self.root/"articles.jsonl.gz",
            database=self.root/"bodies.sqlite", work=self.root/"qa",
            model=qa.MODEL, billing_project="test", maximum_tib=.25,
            execute=True, retry_failed=False)
        self.rows = [dict(event_id="E001", event_district_id="E001::puri",
                          source_record_id="new", state="Odisha", district="Puri",
                          start_date="2020-01-01", end_date="2020-01-02",
                          aoi_level="district", district_source="official",
                          district_resolution_evidence="[]")]
        self.write_registry()
        con = sqlite3.connect(self.args.database)
        con.execute("CREATE TABLE documents (url TEXT PRIMARY KEY, status TEXT, body_text TEXT, page_title TEXT, http_status INTEGER)")
        con.execute("INSERT INTO documents VALUES ('https://x/a','ok','Flooding affected Puri in Odisha.','','200')")
        con.commit()
        con.close()
        self.write_articles([dict(url="https://x/a", published_at="2020-01-02", state="Odisha", source_record_id="old")])

    def write_registry(self):
        pd.DataFrame(self.rows).to_csv(self.args.registry,index=False)

    def write_articles(self, rows):
        with gzip.open(self.args.source,"wt") as f:
            for r in rows:
                f.write(json.dumps(r)+"\n")

    def prepare(self):
        qa.prepare(self.args)
        return qa.checked(self.args)

    def valid(self, request):
        return {"decisions":[dict(event_district_id=d["event_district_id"],
              verdict="relevant",reason_code="flood_in_district",
              evidence_source="body",evidence_excerpt="Flooding affected Puri")
              for d in request["districts"]]}

    def test_reassignment_dedup_and_boundaries(self):
        row = dict(url="https://x/a", state="Odisha", source_record_id="old")
        self.write_articles([{**row,"published_at":"2020-01-15"}]*2)
        _, requests, _ = self.prepare()
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0]["day"],14)
        qa.save(self.args.work/"results.json",{requests[0]["custom_id"]:{
            **self.valid(requests[0]),"usage":{},"model":qa.MODEL}})
        qa.counts(self.args)
        a=pd.read_csv(self.args.work/"counts_14d.csv")
        b=pd.read_csv(self.args.work/"counts_30d.csv")
        self.assertEqual(a.final_article_count.iloc[0],0)
        self.assertEqual(b.final_article_count.iloc[0],1)
        self.write_articles([{**row,"published_at":"2020-01-31"}])
        _, requests, _ = self.prepare()
        self.assertEqual(requests,[])

    def test_missing_is_not_negative(self):
        self.write_articles([dict(url="https://x/missing",state="Odisha",published_at="2020-01-01")])
        _,requests,pending=self.prepare()
        self.assertFalse(requests)
        self.assertEqual(pending[0]["quality"],"missing_text")
        qa.counts(self.args)
        count=pd.read_csv(self.args.work/"counts_14d.csv")
        self.assertTrue(pd.isna(count.final_article_count.iloc[0]))

    def test_schema_ids_and_evidence(self):
        _,requests,_=self.prepare()
        good=self.valid(requests[0])
        qa.validate_response(requests[0],good)
        with self.assertRaises(ValueError):
            qa.validate_response(requests[0],{"decisions":good["decisions"]*2})
        with self.assertRaises(ValueError):
            qa.validate_response(requests[0],{"decisions":[]})
        good["decisions"][0]["evidence_excerpt"]="invented"
        with self.assertRaises(ValueError):
            qa.validate_response(requests[0],good)

    def test_estimate_cap_never_executes(self):
        self.write_articles([])
        self.prepare()
        execute=Mock()
        with self.assertRaises(ValueError):
            qa.supplement(self.args,Mock(return_value=(1024**4,"test")),execute)
        execute.assert_not_called()

    def test_complete_zero_supplement(self):
        self.write_articles([])
        self.prepare()
        def execute(sql, project, **kwargs):
            with gzip.open(kwargs["article_output"],"wt") as f: pass
            return [], {"article_rows":0}
        qa.supplement(self.args,Mock(return_value=(100,"test")),execute)
        self.prepare()
        qa.counts(self.args)
        self.assertEqual(pd.read_csv(self.args.work/"counts_14d.csv").final_article_count.iloc[0],0)

    def test_batch_resume_partial_failure(self):
        _,requests,_=self.prepare()
        client=Mock()
        client.files.create.return_value.id="file"
        client.batches.create.return_value=SimpleNamespace(id="batch",status="in_progress")
        qa.submit(self.args,client)
        qa.submit(self.args,client)
        self.assertEqual(client.batches.create.call_count,1)
        client.batches.retrieve.return_value=SimpleNamespace(id="batch",status="completed",output_file_id="out",error_file_id=None)
        body={"status":"completed","model":qa.MODEL,"usage":{"input_tokens":10},
              "output":[{"type":"message","content":[{"type":"output_text","text":json.dumps(self.valid(requests[0]))}]}]}
        client.files.content.return_value.text=json.dumps({"custom_id":requests[0]["custom_id"],"response":{"status_code":200,"body":body}})
        qa.collect(self.args,client)
        self.assertEqual(len(qa.read(self.args.work/"results.json")),1)
        qa.submit(self.args,client)
        self.assertEqual(client.batches.create.call_count,1)
        qa.counts(self.args)
        self.assertEqual(pd.read_csv(self.args.work/"counts_14d.csv").final_article_count.iloc[0],1)

    def test_stale_registry(self):
        self.prepare()
        self.rows[0]["start_date"]="2020-01-02"
        self.write_registry()
        with self.assertRaisesRegex(ValueError,"Stale"):
            qa.checked(self.args)

    def test_failed_batch_retry_and_duplicate_output(self):
        _, requests, _ = self.prepare()
        client = Mock()
        client.files.create.return_value.id = "file"
        client.batches.create.return_value = SimpleNamespace(id="batch", status="in_progress")
        qa.submit(self.args, client)
        client.batches.retrieve.return_value = SimpleNamespace(id="batch", status="expired", output_file_id=None, error_file_id=None)
        qa.collect(self.args, client)
        self.assertIn(requests[0]["custom_id"], qa.read(self.args.work/"errors.json"))
        qa.submit(self.args, client)
        self.assertEqual(client.batches.create.call_count, 1)
        self.args.retry_failed = True
        qa.submit(self.args, client)
        self.assertEqual(client.batches.create.call_count, 2)

    def test_cache_migration_requires_same_id_and_geometry(self):
        from registry_cache import compatible_rows
        old = pd.DataFrame(self.rows)
        current = old.copy()
        cache = old.assign(geometry_id="geo")
        aoi = cache.copy()
        self.assertEqual(len(compatible_rows(cache, old, current, aoi)), 1)
        aoi["geometry_id"] = "changed"
        self.assertEqual(len(compatible_rows(cache, old, current, aoi)), 0)
        current["event_district_id"] = "E001::renamed"
        self.assertEqual(len(compatible_rows(cache, old, current)), 0)

    def test_overlapping_event_candidates(self):
        self.rows.append({**self.rows[0], "event_id":"E002", "event_district_id":"E002::puri", "start_date":"2020-01-02"})
        self.write_registry()
        _, requests, _ = self.prepare()
        self.assertEqual({r["event_id"] for r in requests}, {"E001", "E002"})

    def test_duplicate_batch_rows_never_become_results(self):
        _, requests, _ = self.prepare()
        key = requests[0]["custom_id"]
        qa.save(self.args.work/"batches.json", [{
            "id":"b", "status":"in_progress", "custom_ids":[key],
            "registry_sha256":requests[0]["registry_sha256"]}])
        client = Mock()
        client.batches.retrieve.return_value = SimpleNamespace(id="b", status="completed", output_file_id="o", error_file_id=None)
        row = json.dumps({"custom_id":key, "response":{"status_code":200, "body":{}}})
        client.files.content.return_value.text = row + "\n" + row
        qa.collect(self.args, client)
        self.assertEqual(qa.read(self.args.work/"results.json"), {})
        self.assertIn("Duplicate", qa.read(self.args.work/"errors.json")[key])

    def test_lost_submission_ack_is_reconciled_without_resubmit(self):
        _, requests, _ = self.prepare()
        client = Mock()
        client.files.create.return_value.id = "file"
        client.batches.create.side_effect = TimeoutError("lost acknowledgement")
        with self.assertRaises(TimeoutError):
            qa.submit(self.args, client)
        intent = qa.read(self.args.work/"batches.json")[0]
        client.batches.list.return_value = [SimpleNamespace(
            id="accepted", status="in_progress",
            metadata={"cvnd_submission":intent["submission_key"]})]
        qa.submit(self.args, client)
        self.assertEqual(client.batches.create.call_count, 1)
        self.assertEqual(qa.read(self.args.work/"batches.json")[0]["id"], "accepted")

    def test_qa_count_join_preserves_missing_and_scope(self):
        from join_district_flood_articles import build_district_table
        _, requests, _ = self.prepare()
        registry = pd.DataFrame(self.rows)
        flood = registry.assign(flood_area_km2=1., flood_ratio=.01, aoi_area_km2=100.,
                                satellite_source="S1_TO_SITS", satellite_status="observed",
                                aoi_match_status="matched")
        cov = pd.DataFrame([dict(state="Odisha",district="Puri",total_population=100,
                     urban_population=20,rural_population=80,urban_population_share=.2,
                     census_year=2011,source="fixture",match_status="matched")])
        qa.counts(self.args)
        table,_ = build_district_table(registry,flood,pd.read_csv(self.args.work/"counts_14d.csv"),cov)
        self.assertTrue(pd.isna(table.article_count.iloc[0]))
        qa.save(self.args.work/"results.json",{requests[0]["custom_id"]:self.valid(requests[0])})
        qa.counts(self.args)
        table,_ = build_district_table(registry,flood,pd.read_csv(self.args.work/"counts_14d.csv"),cov)
        self.assertEqual(table.article_count.iloc[0],1)
        self.assertEqual(table.coverage_scope.iloc[0],qa.SCOPE)

    def test_aliases_and_multilingual_excerpt(self):
        pairs={"Badaun":"Budaun","Bara Banki":"Barabanki","Mumbai":"Mumbai City",
               "West Karbi-Anglong":"West Karbi Anglong","Ri-Bhoi":"Ri Bhoi",
               "Kanniyakumari":"Kanyakumari","Thoothukkudi":"Thoothukudi"}
        aliases=pd.read_csv(qa.ROOT/"data/raw/district_recovery_aliases.csv",keep_default_na=False).to_dict("records")
        for old,new in pairs.items():
            rows=pd.DataFrame([{**self.rows[0],"district":name,
                "event_district_id":make_event_district_id("E001",name)} for name in (old,new)])
            evidence=pd.DataFrame(columns=["event_id","state","canonical_district","source_url","evidence_note"])
            result=apply_recovery(rows,evidence,aliases)
            self.assertEqual(result.district.tolist(),[new])
            self.assertNotIn("district_resolution_confidence",result)
            self.assertIn(old.casefold(),qa.aliases_for(new,aliases))
        text="x"*3000+" पुरी में बाढ़ "+"x"*10000
        excerpt=qa.context_excerpt(text,"News",["पुरी"])
        self.assertIn("पुरी",excerpt)
        self.assertLessEqual(len(excerpt),8000)

if __name__=="__main__":
    unittest.main()
