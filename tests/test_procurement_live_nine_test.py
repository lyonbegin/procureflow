"""No PostgreSQL or Worker: deterministic G2B N01 website-search contract."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import live_nine_test as live

class OnDemandNineStageTests(unittest.TestCase):
    def test_no_db_worker_or_scheduled_browser_dependencies_in_source(self):
        text=(ROOT/"n8n/unified/live_nine_test.py").read_text()
        self.assertNotIn("from db import",text)
        self.assertNotIn("import psycopg",text)
        self.assertNotIn("procureflow.jobs",text)
        self.assertNotIn("schedule.tick",text)
    def test_invalid_request_does_not_start_network(self):
        with patch.object(live,"_client",side_effect=AssertionError("No requests allowed")):
            with self.assertRaises(ValueError):
                live.begin("f"*48,{"bid_no":"OTHER","detail10":live.DETAIL})
    def test_nine_steps_in_order_and_zero_db_reads(self):
        fake_notice={"bid_no":live.CASE,"title":"철강·금속 인공지능전환(AX)실증센터 스마트 실증장비 모니터링 시스템용 소프트웨어 개발 용역","agency":"(재)전남테크노파크","source":live.OFFICIAL+"/","official_fields_verified":True}
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
    def test_official_original_must_contain_actual_tender_title_and_agency(self):
        actual_text="""▪수요기관 : (재)전남테크노파크
        소액 수의 전자견적서 제출 공고
        < 철강·금속 인공지능전환(AX)실증센터 스마트 실증장비
          모니터링 시스템용 소프트웨어 개발 용역 >
        1. 사업명 : 철강·금속 인공지능전환(AX)실증센터 스마트 실증장비 모니터링 시스템용 소프트웨어 개발 용역
        가. 기초금액 : 51,626,000 원, 사업기간 계약일로부터 25일 이내
        """
        with patch.object(live,"_extract",return_value=(actual_text,"hwp5_ole")):
            fields=live._official_notice_fields(b"valid raw", "application/octet-stream")
        self.assertTrue(fields["official_fields_verified"])
        self.assertIn("철강·금속",fields["title"])
        self.assertIn("소프트웨어 개발 용역",fields["title"])
        self.assertIn("전남테크노파크",fields["agency"])
        self.assertEqual(fields["budget"],"51626000")
        self.assertEqual(fields["extracted_from"],"hwp5_ole")
    def test_hwp_header_only_must_not_verify_n01(self):
        with patch.object(live,"_extract",return_value=("A"*120,"hwp5_ole")):
            with self.assertRaisesRegex(ValueError,"TITLE_OR_AGENCY"):
                live._official_notice_fields(b"arbitrary valid HWP bytes","application/octet-stream")
    def test_n01_download_only_without_title_is_source_error_not_partial(self):
        job={"run_id":"6"*32,"status":"running","mode":"on_demand_live_no_database",
             "case_bid_no":live.CASE,"completed_steps":0,"partial_steps":0,
             "steps":[],"db_reads":0,"worker_calls":0,"bid_submitted":False}
        with patch.object(live,"_client",return_value=None), \
             patch.object(live,"_once"), \
             patch.object(live,"_live_notice",return_value={
                "verified_by":"official_original_attachment","title":None,"agency":None,
                "source_file_bytes":105472}), \
             patch.object(live,"_live_attachments",return_value=([],[])), \
             patch.object(live,"_live_openings",return_value={"official_rows":0}), \
             patch.object(live,"_document",return_value=b"review"):
            live._execute(job)
        self.assertEqual(job["steps"][0]["status"],"source_error")
        self.assertIn("N01_TITLE_AND_AGENCY_REQUIRED",job["steps"][0]["output"]["error"])
        self.assertEqual(job["completed_steps"],9)
    def test_official_urls_cannot_be_redirected_elsewhere(self):
        with self.assertRaises(ValueError):
            live._fetch(None,"https://www.evil.com/official")
    def test_n01_selected_notice_and_latest_list_from_official_post(self):
        recent=[{"bid_no":"R26BK01816186","bid_ord":"000","title":"새로운 공고",
                 "agency":"최근 기관","publication":"2026/11/07 21:09"}]
        selected=[{"bid_no":live.CASE,"bid_ord":"000","title":"실제 공고명",
                   "agency":"재단법인전남테크노파크","publication":"2026/10/22 17:53",
                   "budget":"51626000","budget_source_field":"alotBgtAmt"}]
        with patch.object(live,"_g2b_list_rows",side_effect=[recent,selected]) as searched, \
             patch.object(live,"_fetch",side_effect=AssertionError("No fallback expected")):
            notice=live._live_notice(None)
        self.assertEqual(searched.call_count,2)
        self.assertEqual(searched.call_args_list[0].args[3] if len(searched.call_args_list[0].args)>3 else "", "")
        self.assertEqual(searched.call_args_list[1].args[3],live.CASE)
        self.assertEqual(notice["notice_list"],"AVAILABLE")
        self.assertTrue(notice["search_request_verified"])
        self.assertEqual(notice["latest_notice_count"],1)
        self.assertEqual(notice["latest_notice_rows"][0]["title"],"새로운 공고")
        self.assertEqual(notice["bid_no"],live.CASE)
        self.assertEqual(notice["agency"],"재단법인전남테크노파크")
        self.assertFalse(notice["exact10_category_verified"])
        self.assertEqual(notice["source"],live.G2B_BID_LIST)

    def test_n01_official_json_row_maps_actual_g2b_fields(self):
        raw=[{"bidPbancUntyNo":live.CASE,"bidPbancUntyOrd":"000",
              "bidPbancNm":"철강·금속 인공지능전환&#40;AX&#41; 실증센터 개발 용역",
              "dmstNm":"재단법인전남테크노파크",
              "pbancPstgDt":"2026/10/22 17:53&lt;br/&gt;&#40;마감&#41;",
              "prcmBsneSeCdNm":"일반용역","alotBgtAmt":"51626000",
              "pbancSttsNm":"등록공고"}]
        with patch.object(live,"_json_post",return_value=raw) as request:
            rows=live._g2b_list_rows(None,"20261022","20261108",live.CASE)
        self.assertEqual(len(rows),1)
        self.assertIn("(AX)",rows[0]["title"])
        self.assertEqual(rows[0]["publication"],"2026/10/22 17:53")
        self.assertEqual(rows[0]["budget"],"51626000")
        args=request.call_args.args
        self.assertEqual(args[1],live.G2B_BID_LIST)
        self.assertEqual(args[2]["dlBidPbancLstM"]["bidPbancNo"],live.CASE)
        self.assertEqual(args[2]["dlBidPbancLstM"]["recordCountPerPage"],"20")

    def test_n01_empty_or_unverified_g2b_listing_remains_partial_on_hwp(self):
        with patch.object(live,"_official_g2b_search",
                          side_effect=ValueError("G2B_BID_NOTICE_LIVE_SEARCH_UNVERIFIED")), \
             patch.object(live,"_fetch",return_value=(b"\xd0\xcf\x11\xe0"+"x".encode(),"application/octet-stream")), \
             patch.object(live,"_official_notice_fields",return_value={
                 "title":"공식 HWP 추출 공고명","agency":"공식 HWP 기관",
                 "official_fields_verified":True}):
            notice=live._live_notice(None)
        self.assertEqual(notice["notice_list"],"UNAVAILABLE")
        self.assertIn("HWP_CASE_ONLY",notice["warning"])
        self.assertNotIn("search_request_verified",notice)

    def test_n01_selected_notice_missing_is_not_verified(self):
        latest=[{"bid_no":"R26BK01816186","bid_ord":"000","title":"새 공고","agency":"기관"}]
        with patch.object(live,"_g2b_list_rows",side_effect=[latest,[]]):
            with self.assertRaisesRegex(ValueError,"G2B_SELECTED_NOTICE_NOT_FOUND_IN_OFFICIAL_LIST"):
                live._official_g2b_search(None)

    def test_n01_empty_recent_list_is_not_verified(self):
        with patch.object(live,"_g2b_list_rows",return_value=[]):
            with self.assertRaisesRegex(ValueError,"G2B_RECENT_BID_NOTICE_LIST_EMPTY"):
                live._official_g2b_search(None)


if __name__=="__main__":unittest.main()
