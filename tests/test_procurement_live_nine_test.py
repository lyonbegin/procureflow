"""No PostgreSQL, no Worker, no Chrome: deterministic live G2B orchestrator contract."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import live_nine_test as live

class OnDemandNineStageTests(unittest.TestCase):
    def test_no_db_worker_or_browser_dependencies_in_source(self):
        text=(ROOT/"n8n/unified/live_nine_test.py").read_text()
        self.assertNotIn("from db import",text)
        self.assertNotIn("import psycopg",text)
        self.assertNotIn("sync_playwright",text)
        self.assertNotIn("chromium.launch",text)
        self.assertNotIn("procureflow.jobs",text)
        self.assertNotIn("schedule.tick",text)
    def test_invalid_request_does_not_start_network(self):
        with patch.object(live,"_client",side_effect=AssertionError("No requests allowed")):
            with self.assertRaises(ValueError):
                live.begin("f"*48,{"bid_no":"OTHER","detail10":live.DETAIL})
    def test_nine_steps_in_order_and_zero_db_reads(self):
        fake_notice={"bid_no":live.CASE,"title":"원본 공고 TEST","agency":"공식기관","source":live.NURI_LIST}
        fake_docs=[{"file_seq":1,"bytes":100,"sha256":"0"*64,"source":live.ATTACH}]
        fake_history={"official_rows":3,"sample":[],"source":live.OPENINGS,"exact_detail10_verified":False}
        job={"run_id":"9"*32,"status":"running","mode":"on_demand_live_no_database",
             "case_bid_no":live.CASE,"completed_steps":0,"partial_steps":0,"steps":[],
             "db_reads":0,"worker_calls":0,"bid_submitted":False}
        with patch.object(live,"_client",return_value=None), \
             patch.object(live,"_once"), \
             patch.object(live,"_live_notice",return_value=fake_notice) as notice, \
             patch.object(live,"_live_attachments",return_value=(fake_docs,["소프트웨어사업자 직접생산확인"])) as docs, \
             patch.object(live,"_live_openings",return_value=fake_history) as opening, \
             patch.object(live,"_document",return_value=b"fake document for deterministic test") as draft:
            live._execute(job)
        self.assertEqual(job["completed_steps"],9)
        self.assertEqual([x["node"] for x in job["steps"]],
                         ["N%02d"%i for i in range(1,10)])
        self.assertEqual(job["status"],"completed_with_missing_evidence")
        self.assertEqual(job["db_reads"],0)
        self.assertEqual(job["worker_calls"],0)
        self.assertFalse(job["bid_submitted"])
        self.assertEqual(job["steps"][3]["status"],"partial")  # exact10 not verified
        self.assertEqual(job["steps"][4]["status"],"blocked")  # no false bid competitor rank
        self.assertEqual(job["steps"][6]["status"],"blocked")  # missing company cost
        self.assertEqual(job["steps"][7]["output"]["draft_generated"],True)
        notice.assert_called_once();docs.assert_called_once();opening.assert_called_once()
        draft.assert_called_once()
    def test_n01_and_n02_failure_must_still_reach_n09(self):
        """Real site timeout or bad documents must not freeze the run at N01."""
        job={"run_id":"8"*32,"status":"running","mode":"on_demand_live_no_database",
             "case_bid_no":live.CASE,"completed_steps":0,"partial_steps":0,
             "steps":[],"db_reads":0,"worker_calls":0,"bid_submitted":False}
        with patch.object(live,"_client",return_value=None), \
             patch.object(live,"_once"), \
             patch.object(live,"_live_notice",side_effect=TimeoutError("NURI_TIMEOUT")), \
             patch.object(live,"_live_attachments",side_effect=TimeoutError("FILE_TIMEOUT")), \
             patch.object(live,"_live_openings",side_effect=TimeoutError("OPENING_TIMEOUT")), \
             patch.object(live,"_document",side_effect=ValueError("DOCX_FAILED")):
            live._execute(job)
        self.assertEqual(job["completed_steps"],9)
        self.assertEqual([s["node"] for s in job["steps"]],
                         ["N%02d"%i for i in range(1,10)])
        self.assertEqual(job["steps"][0]["status"],"source_error")
        self.assertEqual(job["steps"][1]["status"],"source_error")
        self.assertEqual(job["steps"][2]["status"],"blocked")
        self.assertEqual(job["steps"][3]["status"],"source_error")
        self.assertEqual(job["steps"][7]["status"],"source_error")
        self.assertEqual(job["steps"][8]["status"],"partial")
        self.assertEqual(job["status"],"completed_with_missing_evidence")
        self.assertIsNone(job["active_node"])
        self.assertFalse(job["bid_submitted"])
    def test_fatal_unexpected_error_marks_remaining_nodes_and_releases_runner(self):
        job={"run_id":"7"*32,"status":"running","mode":"on_demand_live_no_database",
             "case_bid_no":live.CASE,"completed_steps":0,"partial_steps":0,
             "steps":[],"db_reads":0,"worker_calls":0,"bid_submitted":False}
        with patch.object(live,"_client",side_effect=RuntimeError("SESSION_START_FAILED")):
            live._execute(job)
        self.assertEqual(job["completed_steps"],9)
        self.assertEqual(job["status"],"failed")
        self.assertEqual(job["steps"][0]["status"],"source_error")
        self.assertTrue(all(x["status"]=="not_executed" for x in job["steps"][1:]))
        self.assertIn("finished_at",job)
    def test_official_urls_cannot_be_redirected_elsewhere(self):
        with self.assertRaises(ValueError):
            live._fetch(None,"https://www.evil.com/official")
if __name__=="__main__":unittest.main()
