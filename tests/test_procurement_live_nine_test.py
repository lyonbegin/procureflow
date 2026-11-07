"""N01 automatic latest-first procurement selection and N02 identity handoff."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import n01_auto as auto
import live_nine_test as live

BID_A="R26BK01816186"
BID_B="R26BK01815798"
BID_C="R26BK01815502"

def notice(no=BID_A,order="000",**extras):
    return {"bid_no":no,"bid_ord":order,"title":"실제 나라장터 공고 "+no,
            "agency":"나라장터 발주기관","business_code":"03",
            "publication":"2026/11/07 21:09","source":live.G2B_BID_LIST,
            "notice_list":"AVAILABLE","official_fields_verified":True,
            "selection_reason":"newest_unprocessed",**extras}

def run_job(no=BID_A,order="000",run_id="a"*32):
    return {"run_id":run_id,"status":"running","mode":"on_demand_live_no_database",
            "case_bid_no":no,"case_bid_ord":order,
            "selected_notice":notice(no,order),"completed_steps":0,
            "partial_steps":0,"steps":[],"db_reads":0,"worker_calls":0,
            "bid_submitted":False}

class AutomaticProcurementStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        change=patch.object(auto,"LEDGER_PATH",Path(self.tmp.name)/"new_n01_journal.json")
        change.start()
        self.addCleanup(change.stop)

    def test_newest_not_seen_is_selected_without_user_or_fixed_bid(self):
        rows=[notice(BID_A),notice(BID_B)]
        with patch.object(live,"_g2b_list_rows",return_value=rows) as fetch:
            found=live._official_g2b_search(None)
        self.assertEqual(found["bid_no"],BID_A)
        self.assertTrue(found["selection_automatic"])
        self.assertEqual(found["selection_reason"],"newest_unprocessed")
        self.assertEqual(found["latest_notice_count"],2)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(fetch.call_args.kwargs["page"],1)
        self.assertEqual(found["selection_policy"],"newest_not_fully_nine_stage_verified")

    def test_incomplete_same_tender_selected_again_not_skipped(self):
        rec=run_job()
        for i,status in enumerate(["verified","verified","partial","blocked"],start=1):
            auto.record_stage(rec,i,status)
        with patch.object(live,"_g2b_list_rows",return_value=[notice(BID_A),notice(BID_B)]):
            out=live._official_g2b_search(None)
        self.assertEqual(out["bid_no"],BID_A)
        self.assertEqual(out["selection_reason"],"retry_incomplete")
        self.assertEqual(out["skipped_completed_count"],0)
        self.assertEqual(out["prior_checkpoint"]["stage_status"]["N04"],"blocked")

    def test_nine_executed_but_partials_and_blocked_never_count_as_complete(self):
        rec=run_job()
        for i in range(1,10):
            auto.record_stage(rec,i,"verified" if i in (1,2,3,8) else "partial")
        stored=auto._load()["records"][BID_A+"-000"]
        self.assertEqual(stored["state"],"incomplete")
        self.assertEqual(len(stored["stage_status"]),9)
        self.assertFalse(auto.completed(stored))
        selected=auto.select(lambda page:[notice(BID_A),notice(BID_B)])
        self.assertEqual(selected["selected"]["bid_no"],BID_A)
        self.assertEqual(selected["selection_reason"],"retry_incomplete")

    def test_only_nine_verified_stages_allow_next_notice(self):
        rec=run_job()
        for i in range(1,10):
            auto.record_stage(rec,i,"verified")
        done=auto._load()["records"][BID_A+"-000"]
        self.assertTrue(auto.completed(done))
        selected=auto.select(lambda page:[notice(BID_A),notice(BID_B)])
        self.assertEqual(selected["selected"]["bid_no"],BID_B)
        self.assertEqual(selected["skipped_fully_verified"],[BID_A+"-000"])
        self.assertEqual(selected["skipped_completed_count"],1)
        self.assertEqual(selected["selection_reason"],"newest_unprocessed")

    def test_resume_after_new_run_id_does_not_reuse_old_verified_stage_status(self):
        first=run_job(run_id="a"*32)
        for i in range(1,10):auto.record_stage(first,i,"verified" if i!=9 else "partial")
        second=run_job(run_id="b"*32)
        auto.record_stage(second,1,"verified")
        prior=auto._load()["records"][BID_A+"-000"]
        self.assertEqual(prior["attempts"],2)
        self.assertEqual(prior["stage_status"],{"N01":"verified"})
        self.assertFalse(auto.completed(prior))

    def test_when_first_twenty_are_verified_go_to_next_official_page(self):
        page1=[notice("R26BK%08d"%(1800000+i)) for i in range(20)]
        ledger={"version":1,"records":{}}
        for row in page1:
            key=row["bid_no"]+"-"+row["bid_ord"]
            ledger["records"][key]={"state":"fully_verified",
                                    "stage_status":{s:"verified" for s in auto.STAGE_IDS}}
        auto._store(ledger)
        requested=[]
        def fetch(page):
            requested.append(page)
            return page1 if page==1 else [notice(BID_C)]
        result=auto.select(fetch)
        self.assertEqual(requested,[1,2])
        self.assertEqual(result["selected"]["bid_no"],BID_C)
        self.assertEqual(result["scanned_pages"],2)
        self.assertEqual(result["skipped_completed_count"],20)

    def test_same_notice_different_revision_is_separate_checkpoint(self):
        for i in range(1,10):auto.record_stage(run_job(order="000"),i,"verified")
        selected=auto.select(lambda p:[notice(BID_A,"001"),notice(BID_A,"000")])
        self.assertEqual(selected["selected"]["bid_ord"],"001")

    def test_g2b_pagination_payload_is_real_server_side_pagination(self):
        data=live._g2b_bid_list_payload("20261101","20261108",page=2)["dlBidPbancLstM"]
        self.assertEqual((data["currentPage"],data["startIndex"],data["endIndex"]),("2",21,40))
        with patch.object(live,"_json_post",return_value=[{
            "bidPbancUntyNo":BID_C,"bidPbancUntyOrd":"001",
            "bidPbancNm":"실제 공고&#40;변경&#41;","dmstNm":"실제 기관",
            "pbancPstgDt":"2026/11/07 18:00&lt;br/&gt;&#40;2026/11/10&#41;",
            "prcmBsneSeCd":"03","prcmBsneSeCdNm":"일반용역",
            "pbancSttsNm":"변경공고","alotBgtAmt":"52000000",
        }]) as p:
            rows=live._g2b_list_rows(None,"20261101","20261108",page=2)
        self.assertEqual(rows[0]["bid_no"],BID_C)
        self.assertEqual(rows[0]["bid_ord"],"001")
        self.assertEqual(rows[0]["title"],"실제 공고(변경)")
        self.assertEqual(rows[0]["budget"],"52000000")
        self.assertEqual(rows[0]["business_code"],"03")
        self.assertEqual(p.call_args.args[2]["dlBidPbancLstM"]["currentPage"],"2")

    def test_n02_attachment_uses_n01_selected_notice_not_old_case(self):
        chosen=notice(BID_B,"001")
        received=[]
        def fetch(_,url,*args,**kwargs):
            received.append(url)
            return b"%PDF-1.4 sample","application/pdf"
        with patch.object(live,"_fetch",side_effect=fetch), \
             patch.object(live,"_extract",return_value=("본문 텍스트","pdf")):
            files,text=live._live_attachments(None,{},chosen)
        self.assertEqual(len(files),2)
        self.assertEqual(len(text),2)
        self.assertTrue(all("bidPbancNo="+BID_B in u for u in received))
        self.assertTrue(all("bidPbancOrd=001" in u for u in received))
        self.assertTrue(all("R26BK01787028" not in u for u in received))

    def test_n02_requires_actual_n01_auto_selection(self):
        with self.assertRaisesRegex(ValueError,"N02_AUTO_SELECTED_NOTICE_REQUIRED"):
            live._live_attachments(None,{},None)

    def test_nine_executor_passes_new_auto_selected_tender_to_n02(self):
        job=run_job(BID_B,run_id="c"*32)
        job.pop("selected_notice")
        chosen=notice(BID_B,"001",selection_reason="retry_incomplete")
        with patch.object(live,"_client",return_value=None), \
             patch.object(live,"_once"), \
             patch.object(live,"_live_notice",return_value=chosen), \
             patch.object(live,"_live_attachments",return_value=([{
                 "file_seq":1,"sha256":"0"*64,"bytes":120}],["입찰참가자격 소프트웨어사업자"])) as attachments, \
             patch.object(live,"_live_openings",return_value={"official_rows":1}), \
             patch.object(live,"_document",return_value=b"docx"):
            live._execute(job)
        self.assertEqual(job["case_bid_no"],BID_B)
        self.assertEqual(job["case_bid_ord"],"001")
        self.assertEqual(job["steps"][0]["status"],"verified")
        self.assertEqual(job["steps"][1]["input"]["bid_no"],BID_B)
        self.assertEqual(job["steps"][1]["input"]["bid_ord"],"001")
        self.assertEqual(attachments.call_args.args[2]["bid_no"],BID_B)
        self.assertEqual(job["status"],"completed_with_missing_evidence")
        self.assertFalse(job["completion_checkpoint"]["fully_completed"])
        chosen_again=auto.select(lambda p:[chosen,notice(BID_C)])
        self.assertEqual(chosen_again["selected"]["bid_no"],BID_B)
        self.assertEqual(chosen_again["selection_reason"],"retry_incomplete")

    def test_new_latest_arrival_does_not_starve_unfinished_prior_tender(self):
        previous=run_job(BID_A,run_id="d"*32)
        for stage in range(1,5):
            auto.record_stage(previous,stage,"verified" if stage<=2 else "blocked")
        newer=notice(BID_B)
        older=notice(BID_A)
        def read(_,start,end,bid_no="",page=1):
            return [older] if bid_no==BID_A else [newer,older]
        with patch.object(live,"_g2b_list_rows",side_effect=read) as fetch:
            chosen=live._official_g2b_search(None)
        self.assertEqual(chosen["bid_no"],BID_A)
        self.assertEqual(chosen["selection_reason"],"retry_incomplete")
        self.assertEqual(chosen["prior_checkpoint"]["stage_status"]["N04"],"blocked")
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(fetch.call_args_list[1].kwargs["bid_no"],BID_A)

    def test_unavailable_old_unfinished_tender_does_not_silently_switch_to_new(self):
        previous=run_job(BID_A,run_id="e"*32)
        auto.record_stage(previous,1,"verified")
        with patch.object(live,"_g2b_list_rows",side_effect=lambda _op,_s,_e,bid_no="",page=1:
                          [] if bid_no else [notice(BID_B)]):
            with self.assertRaisesRegex(ValueError,"N01_INCOMPLETE_NOTICE_OFFICIAL_REVALIDATION_FAILED"):
                live._official_g2b_search(None)

    def test_reject_old_fixed_notice_request_and_accept_only_auto_mode(self):
        with patch.object(live,"_client",side_effect=AssertionError("network should not be called")):
            with self.assertRaisesRegex(ValueError,"AUTOMATIC_SELECTION_ONLY"):
                live.begin("session",{"bid_no":"R26BK01787028","detail10":"8111159901"})

    def test_no_old_postgresql_worker_or_pinned_tender_in_current_n01_source(self):
        src=(ROOT/"n8n/unified/live_nine_test.py").read_text(encoding="utf-8")
        ui=(ROOT/"n8n/admin-console/public9.js").read_text(encoding="utf-8")
        self.assertNotIn("from db import",src)
        self.assertNotIn("import psycopg",src)
        self.assertNotIn('CASE="R26BK01787028"',src)
        self.assertNotIn("const CASE=",ui)
        self.assertIn("mode:'auto'",ui)

if __name__=="__main__":
    unittest.main()
