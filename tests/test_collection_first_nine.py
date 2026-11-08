"""N01–N08 collect-only, N09 first and only business evaluation.

Static tests use mock official HTTPS responses solely to validate field
provenance, exact 10-digit matching, year windows and no fabricated output.
Live official endpoint checks are separate workflow jobs.
"""
import hashlib,json,os,sys,unittest
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import collect_only_stages as c
import n09_final_ai as ai
import github_node_worker as worker
BID="R26BK01816186"
NOTICE={"bid_no":BID,"bid_ord":"000","title":"예제 공고",
        "agency":"예제 기관","budget":"123000000","publication":"20261108"}
CODE="8111159900"
ROW={"bidPbancUntyNo":BID,"bidPbancUntyOrd":"000",
     "dtlsPrnmNo":CODE,"dtlsPrnmNm":"정보시스템개발서비스",
     "bidPbancNm":"예제 공고","pbancPstgDt":"20261108",
     "dmstNm":"예제 기관","alotBgtAmt":"123000000"}
class Live:
    @staticmethod
    def _g2b_bid_list_payload(start,end,bid="",page=1):
        return {"dlBidPbancLstM":{"start":start,"end":end,"bidPbancNo":bid,"currentPage":page}}
    @staticmethod
    def _now():
        return datetime(2026,11,8)
class CollectFirstTests(unittest.TestCase):
    def test_n03_only_official_metadata_no_document_analysis(self):
        seen=[]
        def post(opener,url,payload,headers):
            seen.append((url,payload));return [ROW]
        status,out=c.n03_metadata(None,NOTICE,post,Live,date(2026,11,8))
        self.assertEqual(status,"verified")
        self.assertEqual(out["detail10"],CODE)
        self.assertEqual(out["detail10_source_field"],"dtlsPrnmNo")
        self.assertTrue(out["detail10_verified"])
        self.assertFalse(out["business_evaluation_performed"])
        self.assertNotIn("company_eligibility",out)
        self.assertNotIn("qualification_rules",out)
        self.assertEqual(seen[0][0],c.BID_LIST)
        self.assertEqual(seen[0][1]["dlBidPbancLstM"]["bidPbancNo"],BID)
    def test_n03_missing_class_is_gap_not_synthetic_guess(self):
        status,out=c.n03_metadata(None,NOTICE,lambda *_:[{k:v for k,v in ROW.items() if k!="dtlsPrnmNo"}],
                                  Live,date(2026,11,8))
        self.assertEqual(status,"partial")
        self.assertIsNone(out["detail10"])
        self.assertFalse(out["detail10_verified"])
        self.assertIn("official_10_digit_detail_class_not_verified",out["gaps"])
    def test_n03_searches_beyond_first_year_window(self):
        seen=[]
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            seen.append((q["start"],q["end"],q["currentPage"]))
            if q["start"]=="20251108":
                return [ROW]
            return []
        status,out=c.n03_metadata(None,NOTICE,post,Live,date(2026,11,8))
        self.assertEqual(status,"verified")
        self.assertEqual(out["detail10"],CODE)
        self.assertGreater(len(seen),1)
        self.assertEqual(out["query_windows_checked"][0]["start"],"20261108")
        self.assertEqual(out["query_windows_checked"][1]["start"],"20251108")
        self.assertFalse(out["business_evaluation_performed"])

    def test_n04_ten_year_history_only_exact_code(self):
        seen=[]
        def post(opener,url,payload,headers):
            query=payload["dlBidPbancLstM"];seen.append(dict(query))
            if query["start"]=="20161108":
                return [ROW,{"bidPbancUntyNo":"R26BK00000000",
                             "bidPbancUntyOrd":"000","dtlsPrnmNo":"1234567890"}]
            return []
        status,out=c.n04_history(None,NOTICE,{"detail10":CODE,"detail10_verified":True},
                                 post,Live,date(2026,11,8))
        self.assertEqual(out["periods_requested"],len(list(c._periods(date(2026,11,8)))))
        self.assertEqual(len(out["periods_checked"]),len(seen))
        self.assertGreaterEqual(len(seen),10)
        self.assertEqual(out["records"][0]["detail10"],CODE)
        self.assertEqual(out["verified_record_count"],1)
        self.assertEqual(out["unverified_classification_count"],1)
        self.assertEqual(status,"partial") # foreign classification explicitly flagged
        self.assertFalse(out["business_evaluation_performed"])
        self.assertEqual(seen[0]["dtlsPrnmNo"],CODE)
    def test_n04_without_detail10_does_not_make_unfiltered_lookup(self):
        def forbidden(*args):raise AssertionError("NO_UNFILTERED_HISTORICAL_QUERY_ALLOWED")
        status,out=c.n04_history(None,NOTICE,{"detail10":None},forbidden,Live,date(2026,11,8))
        self.assertEqual(status,"partial")
        self.assertEqual(out["records"],[])
        self.assertIn("exact_10_digit_class_required_for_10_year_search",out["gaps"])
    def test_n05_only_connected_official_bids_no_competitor_prediction(self):
        hist={"records":[{"bid_no":BID,"bid_ord":"000","detail10":CODE,
                         "query_period":{"from":"20260101","to":"20261231"}}]}
        def post(opener,url,payload,headers):
            self.assertEqual(payload["dlSrchOnbsRsltClsfListInM"]["bidPbancNo"],BID)
            return {"onbsRsltClsfList":[{"bidPbancNo":BID,"bidPbancOrd":"000",
                                         "onbsYmd":"20261108","scsbdAmt":"111000000"}]}
        status,out=c.n05_openings(None,hist,post,date(2026,11,8))
        self.assertEqual(status,"partial")
        self.assertEqual(len(out["opening_records"]),1)
        self.assertEqual(out["opening_records"][0]["bid_no"],BID)
        self.assertFalse(out["full_bidder_participation_records_verified"])
        self.assertFalse(out["business_evaluation_performed"])
        self.assertNotIn("competitor_ranking",out)
    def test_n06_n07_only_catalog_existing_sources(self):
        hist={"records":[{"bid_no":BID}]}
        n02={"files":[{"file_seq":1,"original_filename":"원본.hwp",
                       "sha256":"a"*64,"source":"https://www.g2b.go.kr",
                       "size_bytes":400}]}
        s6,o6=c.n06_supply_catalog(NOTICE,n02,hist,{"opening_records":[]})
        s7,o7=c.n07_price_sources(NOTICE,
            {"official_fields":{"alotBgtAmt":"123000000"}},
            hist,{"opening_records":[]},o6)
        self.assertEqual((s6,s7),("partial","partial"))
        self.assertTrue(o6["gaps"])
        self.assertFalse(o6["business_evaluation_performed"])
        self.assertFalse(o7["business_evaluation_performed"])
        self.assertIsNone(o7["recommended_bid"])
        self.assertEqual(o7["source_amounts"][0]["field"],"alotBgtAmt")
    def test_n08_combines_sources_not_word_or_ai(self):
        prev={"N01":NOTICE,"N02":{"file_count":1,"files":[
            {"file_seq":1,"original_filename":"원본.hwp","sha256":"a"*64,
             "size_bytes":5,"source":"official"}]},
            "N03":{"detail10":CODE,"gaps":[]},
            "N04":{"records":[],"gaps":["history_not_yet_available"]}}
        state,out=c.n08_handoff(NOTICE,prev)
        self.assertEqual(state,"verified")
        self.assertTrue(out["handoff_assembled"])
        self.assertTrue(out["upstream_collection_incomplete"])
        self.assertIn("N04:history_not_yet_available",out["collection_gaps"])
        self.assertEqual(out["source_originals"],1)
        self.assertEqual(out["handoff_bundle"]["exact_detail10"],CODE)
        self.assertFalse(out["ai_analysis_performed"])
        self.assertFalse(out["word_draft_generated"])
        self.assertFalse(out["business_evaluation_performed"])
    def test_n09_no_api_config_never_claims_evaluation_or_reads_originals(self):
        prev={"N08":{"handoff_bundle":{"originals":[],"collection_gaps":["missing_history"]}},
              "N02":{"files":[]}}
        with patch.dict(os.environ,{"OPENAI_API_KEY":"",
                                 "PROCUREFLOW_AI_MODEL":"","PROCUREFLOW_AI_ENABLED":"0"}):
            status,out=ai.evaluate(prev,lambda *_:(_ for _ in ()).throw(
                AssertionError("N09_MUST_NOT_READ_WITHOUT_API_CONFIG")),
                lambda *_:None)
        self.assertEqual(status,"not_executed")
        self.assertFalse(out["ai_evaluation_performed"])
        self.assertEqual(out["reason"],"N09_AI_API_NOT_CONFIGURED")
        self.assertFalse(out["bid_submitted"])
    def test_n09_api_mock_is_only_business_evaluation_and_is_human_review(self):
        raw=b"%PDF-1.4 original bytes mock"
        digest=hashlib.sha256(raw).hexdigest()
        item={"file_seq":1,"size_bytes":len(raw),"sha256":digest,
              "original_filename":"지침서.pdf","source":"official"}
        prev={"N02":{"files":[item]},"N08":{"handoff_bundle":{
            "originals":[item],"collection_gaps":["missing_competitor_details"]}}}
        report="실제 공고 증빙에 따라 적격 여부는 미확인입니다. " * 9
        calls=[]
        def fake(body,key):
            calls.append(body)
            return {"status":"completed","id":"resp_mock","output":[
                {"type":"message","content":[{"type":"output_text","text":report}]}]}
        with patch.dict(os.environ,{"OPENAI_API_KEY":"test-not-a-real-key",
                                 "PROCUREFLOW_AI_MODEL":"test-model",
                                 "PROCUREFLOW_AI_ENABLED":"1"}):
            state,out=ai.evaluate(prev,lambda f:raw,lambda r,c:("원본 텍스트","pdf"),fake)
        self.assertEqual(state,"partial") # collection gaps remain
        self.assertTrue(out["ai_evaluation_performed"])
        self.assertTrue(out["human_review_required"])
        self.assertFalse(out["bid_submitted"])
        self.assertFalse(out["final_bid_approval"])
        self.assertEqual(len(calls),1)
        self.assertFalse(calls[0]["store"])
    def test_worker_n03_calls_official_metadata_not_hwp_parser(self):
        context={"run_id":"a"*32,"selected_notice":NOTICE,
                 "outputs":{"N02":{"files":[{"file_seq":1}]}}}
        with patch("live_nine_test._client",return_value=None),\
             patch("live_nine_test._once"),\
             patch("live_nine_test._json_post",return_value=[ROW]),\
             patch("live_nine_test._extract",side_effect=AssertionError("EARLY_ORIGINAL_PARSING")):
            status,inp,out=worker.execute("N03",context)
        self.assertEqual(status,"verified")
        self.assertFalse(out["business_evaluation_performed"])
    def test_graph_has_nine_retained_nodes_no_hardcoded_auction(self):
        doc=json.loads((ROOT/"n8n/strategy-workflows/PF00-public-nine-real.json").read_text())
        nodes={n["id"]:n for n in doc["nodes"]}
        for i in range(1,10):
            n=nodes[f"public9-{i:02d}"]
            self.assertEqual(n["type"],"n8n-nodes-base.code")
            self.assertNotIn("R26BK01787028",json.dumps(n,ensure_ascii=False))
        self.assertEqual(len(nodes),10)
        self.assertIn("AI",nodes["public9-09"]["name"])
    def test_worker_does_not_import_ai_in_middle_stages(self):
        source=(ROOT/"n8n/unified/github_node_worker.py").read_text()
        between=source[source.index('    if stage=="N03":'):source.index('    if stage=="N09":')]
        self.assertNotIn("n09_final_ai",between)
        self.assertNotIn("extract_requirements(",between)
        self.assertNotIn("live._document(",between)
        self.assertNotIn("company_eligibility",between)

if __name__=="__main__":unittest.main()
