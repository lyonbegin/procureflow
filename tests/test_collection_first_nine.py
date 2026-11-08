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
        self.assertEqual(status,"verified")  # N03 collected official metadata.
        self.assertIsNone(out["detail10"])
        self.assertFalse(out["detail10_verified"])
        self.assertIsNone(out["class8"])
        self.assertIn("official_8_digit_item_class_not_in_listing",out["gaps"])
    def test_n03_accepts_official_8_digit_item_code_without_detail10(self):
        official=dict(ROW)
        official.pop("dtlsPrnmNo")
        official["prdlstClsfNo"]="81111599"
        status,out=c.n03_metadata(None,NOTICE,lambda *_:[official],
                                  Live,date(2026,11,8))
        self.assertEqual(status,"verified")
        self.assertEqual(out["class8"],"81111599")
        self.assertEqual(out["class8_source_field"],"prdlstClsfNo")
        self.assertIsNone(out["detail10"])
        self.assertFalse(out["business_evaluation_performed"])

    def test_n03_searches_beyond_first_year_window(self):
        seen=[]
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            seen.append((q["start"],q["end"],q["currentPage"]))
            if q["start"]=="20241108":
                return [ROW]
            return []
        status,out=c.n03_metadata(None,NOTICE,post,Live,date(2026,11,8))
        self.assertEqual(status,"verified")
        self.assertEqual(out["detail10"],CODE)
        self.assertGreater(len(seen),1)
        self.assertEqual(out["query_windows_checked"][0]["start"],"20251108")
        self.assertEqual(out["query_windows_checked"][1]["start"],"20241108")
        self.assertFalse(out["business_evaluation_performed"])

    def test_n04_actual_8_digit_item_matches_official_records(self):
        seen=[]
        official={**ROW,"prdlstClsfNo":"81111599","bidPbancUntyNo":"R25BK01816186"}
        official.pop("dtlsPrnmNo")
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            seen.append(dict(q))
            if q["start"]=="20161108":
                return [official,{**official,"bidPbancUntyNo":"R26BK00000000",
                                  "prdlstClsfNo":"12345678"}]
            return []
        status,out=c.n04_history(None,NOTICE,{"class8":"81111599","class8_verified":True},
                                 post,Live,date(2026,11,8))
        self.assertEqual(out["query_mode"],"official_item8")
        self.assertEqual(out["periods_requested"],len(list(c._periods(date(2026,11,8)))))
        self.assertGreaterEqual(len(seen),10)
        self.assertEqual(out["records"][0]["class8"],"81111599")
        self.assertEqual(out["verified_record_count"],1)
        self.assertEqual(out["unverified_classification_count"],1)
        self.assertEqual(status,"partial")
        self.assertEqual(seen[0]["prdlstClsfNo"],"81111599")
        self.assertFalse(out["business_evaluation_performed"])

    def test_n04_without_item_code_collects_labeled_agency_candidates(self):
        seen=[]
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            seen.append(dict(q))
            if q["start"]=="20251108":
                return [{**ROW,"bidPbancUntyNo":"R25BK01816186"}]
            return []
        status,out=c.n04_history(None,NOTICE,{"detail10":None},post,Live,date(2026,11,8))
        self.assertEqual(out["query_mode"],"official_agency_name")
        self.assertEqual(out["candidate_record_count"],1)
        self.assertEqual(out["verified_record_count"],0)
        self.assertEqual(out["records"][0]["match_basis"],"official_agency_name")
        self.assertFalse(out["records"][0]["official_classification_confirmed"])
        self.assertEqual(status,"partial")
        self.assertTrue(seen)
        self.assertFalse(out["business_evaluation_performed"])

    def test_n04_uses_longest_real_title_subject_not_unique_location_prefix(self):
        notice={**NOTICE,"title":"해운대 특별정비예정 11구역 행정용역컨설팅(PM) 입찰공고"}
        mode,fields,term=c._history_query(notice,{})
        self.assertEqual(mode,"official_title_keyword")
        self.assertEqual(term,"컨설팅")
        self.assertEqual(fields["bidPbancNm"],term)

    def test_n04_does_not_treat_business_category_as_item_code(self):
        self.assertEqual(c._history_query(
            {"bid_no":BID,"bid_ord":"000","business_code":"조070001",
             "title":"검사용역프로젝트","agency":"테스트기관"},{} )[0],"official_title_keyword")

    def test_n04_three_year_initial_window_and_fifty_unique(self):
        seen=[]
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            seen.append((q["start"],int(q["currentPage"])))
            if q["start"]!="20231108":return []
            start=(int(q["currentPage"])-1)*20
            return [{**ROW,"bidPbancUntyNo":f"R25BK{i:08d}"}
                    for i in range(start+1,min(start+21,51))]
        status,out=c.n04_history(None,NOTICE,{"detail10":CODE,"detail10_verified":True},
                                 post,Live,date(2026,11,8))
        self.assertEqual(status,"verified")
        self.assertEqual(out["initial_years"],3)
        self.assertEqual(out["years_searched"],3)
        self.assertEqual(len(out["periods_checked"]),3)
        self.assertEqual(out["candidate_record_count"],50)
        self.assertTrue(out["target_reached"])
        self.assertEqual(out["periods_checked"][0]["from"],"20251108")
        self.assertEqual(out["periods_checked"][2]["from"],"20231108")
        self.assertEqual(out["periods_checked"][2]["pages_checked"],3)
        self.assertEqual(out["periods_checked"][2]["cumulative_records"],50)
        self.assertFalse(out["business_evaluation_performed"])

    def test_n04_extends_one_year_at_a_time_until_fifty(self):
        year_starts=("20251108","20241108","20231108","20221108")
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            n=year_starts.index(q["start"]) if q["start"] in year_starts else 9
            if n==9 or int(q["currentPage"])>1:return []
            count=20 if n==3 else 10
            return [{**ROW,"bidPbancUntyNo":f"R25BK{n*100+i:08d}"}
                    for i in range(1,count+1)]
        status,out=c.n04_history(None,NOTICE,{"detail10":CODE,"detail10_verified":True},
                                 post,Live,date(2026,11,8))
        self.assertEqual(status,"verified")
        self.assertEqual(out["candidate_record_count"],50)
        self.assertTrue(out["target_reached"])
        self.assertEqual(out["years_expanded"],4)
        self.assertEqual(out["years_searched"],4)
        self.assertEqual(out["periods_checked"][3]["from"],"20221108")
        self.assertEqual(out["periods_checked"][3]["to"],"20231107")
        self.assertEqual(out["periods_checked"][3]["cumulative_records"],50)

    def test_n04_fifty_official_title_candidates_collected_without_ai_judgment(self):
        # A title-derived collection is allowed, but the category remains unknown.
        title="정보시스템개발서비스 관련 용역"
        notice={**NOTICE,"title":title}
        query=c._history_query(notice,{})[2]
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            if q["start"]!="20231108":return []
            page=int(q["currentPage"])
            start=(page-1)*20
            return [{**ROW,"bidPbancUntyNo":f"R25BK{i:08d}",
                     "bidPbancNm":title}
                    for i in range(start+1,min(start+21,51))]
        state,out=c.n04_history(None,notice,{},post,Live,date(2026,11,8))
        self.assertTrue(query in title)
        self.assertEqual(state,"verified")
        self.assertEqual(out["candidate_record_count"],50)
        self.assertTrue(out["collection_target_complete"])
        self.assertEqual(out["verified_record_count"],0)
        self.assertTrue(all(not x["official_classification_confirmed"] for x in out["records"]))
        self.assertIn("historical_candidates_unclassified_final_ai_review",out["gaps"])
        self.assertFalse(out["business_evaluation_performed"])

    def test_n04_ten_year_max_and_deduplicated_count(self):
        seen=[]
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            seen.append(q["start"])
            # Even ten repeated responses count as a single historical notice.
            return [{**ROW,"bidPbancUntyNo":"R25BK12345678"}]
        state,out=c.n04_history(None,NOTICE,{"detail10":CODE,"detail10_verified":True},
                                post,Live,date(2026,11,8))
        self.assertEqual(state,"partial")
        self.assertEqual(out["years_searched"],10)
        self.assertEqual(len(seen),10)
        self.assertEqual(out["candidate_record_count"],1)
        self.assertFalse(out["target_reached"])
        self.assertIn("historical_target_not_reached:1/50",out["gaps"])
        self.assertIn("historical_max_years_exhausted",out["gaps"])
        self.assertEqual(out["periods_checked"][-1]["from"],"20161108")

    def test_n04_fifty_candidates_target_succeeds_with_nonexhaustive_page_gap(self):
        def post(opener,url,payload,headers):
            q=payload["dlBidPbancLstM"]
            age=int(q["start"][:4])
            p=int(q["currentPage"])
            return [{**ROW,"bidPbancUntyNo":f"R25BK{(age-2000)*10000+p*100+i:08d}"}
                    for i in range(20)]
        state,out=c.n04_history(None,NOTICE,{"detail10":CODE,"detail10_verified":True},
                                post,Live,date(2026,11,8),max_pages=3)
        self.assertEqual(state,"verified")
        self.assertTrue(out["target_reached"])
        self.assertEqual(out["candidate_record_count"],50)
        self.assertTrue(out["collection_target_complete"])
        self.assertFalse(out["all_history_complete"])
        self.assertTrue(any(g.startswith("history_period_page_limit:")
                            for g in out["gaps"]))
        self.assertEqual(out["years_searched"],3)

    def test_n04_page_limit_not_misreported_as_full_scan(self):
        def post(opener,url,payload,headers):
            return [{**ROW,"bidPbancUntyNo":f"R25BK{i:08d}"} for i in range(20)]
        status,out=c.n04_history(None,NOTICE,{"detail10":CODE,"detail10_verified":True},
                                 post,Live,date(2026,11,8),max_pages=1)
        self.assertEqual(status,"partial")
        self.assertFalse(out["all_history_complete"])
        self.assertTrue(any(x.startswith("history_period_page_limit:") for x in out["gaps"]))

    def test_n05_capacity_at_least_fifty(self):
        self.assertGreaterEqual(c.MAX_OPENING_LOOKUPS,50)

    def test_n05_exact_list_row_fills_official_detail_request(self):
        hist={"records":[{"bid_no":BID,"bid_ord":"000","detail10":None,
                         "query_period":{"from":"20250101","to":"20251231"}}]}
        official={"bidPbancNo":BID,"bidPbancOrd":"000",
                  "bidClsfNo":"7","bidPrgrsOrd":"002",
                  "prcmBsneSeCd":"조070003","bidPgstCd":"공식상태코드"}
        observed=[]
        def post(opener,url,payload,headers):
            if url==c.OPENING_LIST:
                self.assertEqual(payload["dlSrchOnbsRsltClsfListInM"]["bidPbancNo"],BID)
                return {"onbsRsltClsfList":[official]}
            if url==c.OPENING_DETAIL:
                q=payload["dlSrchOnbsRsltBidInM"]
                observed.append(dict(q))
                return {"successBidInfo":[{"onbsRnkg":"1","grpNm":"테스트업체",
                                          "bdngAmt":"111000000","bdrt":"87.745"}],
                        "bidInfo":{}}
            raise AssertionError("UNEXPECTED_OFFICIAL_ENDPOINT")
        state,out=c.n05_openings(None,hist,post,date(2026,11,8))
        self.assertEqual(state,"verified")
        self.assertEqual(out["checked"],1)
        self.assertEqual(len(out["opening_records"]),1)
        self.assertEqual(out["opening_records"][0]["bid_no"],BID)
        self.assertEqual(out["opening_records"][0]["official_fields"]["bidClsfNo"],"7")
        self.assertEqual(observed[0]["bidClsfNo"],"7")
        self.assertEqual(observed[0]["bidPrgrsOrd"],"002")
        self.assertEqual(observed[0]["prcmBsneSeCd"],"조070003")
        self.assertEqual(observed[0]["bidPgstCd"],"공식상태코드")
        self.assertEqual(out["observed_bidder_row_count"],1)
        self.assertFalse(out["business_evaluation_performed"])
        self.assertNotIn("competitor_ranking",out)

    def test_n05_missing_official_detail_keys_never_forges_status(self):
        hist={"records":[{"bid_no":BID,"bid_ord":"000",
                          "query_period":{"from":"20250101","to":"20251231"}}]}
        calls=[]
        def post(opener,url,payload,headers):
            calls.append(url)
            if url==c.OPENING_LIST:
                return {"onbsRsltClsfList":[{"bidPbancNo":BID,"bidPbancOrd":"000"}]}
            raise AssertionError("MUST_NOT_SEND_FABRICATED_DETAIL_PARAMETERS")
        state,out=c.n05_openings(None,hist,post,date(2026,11,8))
        self.assertEqual(state,"partial")
        self.assertEqual(calls,[c.OPENING_LIST])
        self.assertEqual(out["checked"],1)
        self.assertTrue(any("official_opening_detail_keys_missing" in x
                            for x in out["gaps"]))
        self.assertEqual(out["observed_bidder_row_count"],0)

    def test_n05_distinguishes_official_http_422_from_unpublished(self):
        from urllib.error import HTTPError
        hist={"records":[{"bid_no":BID,"bid_ord":"000",
                         "query_period":{"from":"20250101","to":"20251231"}}]}
        official={"bidPbancNo":BID,"bidPbancOrd":"000",
                  "bidClsfNo":"0","bidPrgrsOrd":"000",
                  "prcmBsneSeCd":"조070003","bidPgstCd":"공식코드"}
        def post(opener,url,payload,headers):
            if url==c.OPENING_LIST:return {"onbsRsltClsfList":[official]}
            raise HTTPError(url,422,"Unprocessable Entity",None,None)
        state,out=c.n05_openings(None,hist,post,date(2026,11,8))
        self.assertEqual(state,"partial")
        self.assertEqual(out["per_notice"][0]["status"],"partial")
        self.assertTrue(any("official_http_422" in x for x in out["gaps"]))
        self.assertEqual(out["not_published_count"],0)
        self.assertEqual(out["opening_records"][0]["bid_no"],BID)
        self.assertEqual(out["observed_bidder_row_count"],0)

    def test_n05_http_422_body_distinguishes_explicit_unpublished(self):
        from urllib.error import HTTPError
        from io import BytesIO
        published=HTTPError(c.OPENING_DETAIL,422,"Unprocessable Entity",None,
                            BytesIO(json.dumps({
                               "ErrorMsg":"개찰결과 데이터가 존재하지 않습니다"}).encode("utf-8")))
        ambiguous=HTTPError(c.OPENING_DETAIL,422,"Unprocessable Entity",None,
                            BytesIO(b'{"ErrorMsg":"Unknown request parameter"}'))
        self.assertEqual(c._n05_error(published),
                         "official_422_no_published_opening_detail")
        self.assertEqual(c._n05_error(ambiguous),
                         "official_http_422_unclassified")

    def test_n05_pages_official_list_and_rejects_unrelated_rows(self):
        hist={"records":[{"bid_no":BID,"bid_ord":"000",
                         "query_period":{"from":"20250101","to":"20251231"}}]}
        official={"bidPbancNo":BID,"bidPbancOrd":"000",
                  "bidClsfNo":"1","bidPrgrsOrd":"001",
                  "prcmBsneSeCd":"조070003","bidPgstCd":"공식코드"}
        def post(opener,url,payload,headers):
            if url==c.OPENING_LIST:
                start=payload["dlSrchOnbsRsltClsfListInM"]["firstIndex"]
                if start==1:
                    return {"onbsRsltClsfList":[{
                        "bidPbancNo":"R25BK00000001","bidPbancOrd":"000"}
                        for _ in range(10)]}
                return {"onbsRsltClsfList":[official]}
            return {"successBidInfo":[{"bdngAmt":"1000000"}],"bidInfo":{}}
        state,out=c.n05_openings(None,hist,post,date(2026,11,8))
        self.assertEqual(state,"verified")
        self.assertEqual(out["opening_list_pages"],2)
        self.assertEqual(out["unrelated_response_rows"],10)
        self.assertEqual(len(out["opening_records"]),1)
        self.assertEqual(out["observed_bidder_row_count"],1)

    def test_n05_unpublished_is_not_bidders_collected(self):
        history={"records":[{"bid_no":BID,"bid_ord":"000",
                             "query_period":{"from":"20250101","to":"20251231"}}]}
        def post(opener,url,payload,headers):
            self.assertEqual(url,c.OPENING_LIST)
            return {"onbsRsltClsfList":[]}
        state,out=c.n05_openings(None,history,post,date(2026,11,8))
        self.assertEqual(state,"partial")
        self.assertEqual(out["not_published_count"],1)
        self.assertEqual(out["checked"],1)
        self.assertEqual(out["observed_bidder_row_count"],0)

    def test_n05_handles_fifty_historical_candidates(self):
        history={"records":[{"bid_no":f"R25BK{i:08d}","bid_ord":"000",
                              "query_period":{"from":"20250101","to":"20251231"}}
                             for i in range(1,51)]}
        def post(opener,url,payload,headers):
            self.assertEqual(url,c.OPENING_LIST)
            return {"onbsRsltClsfList":[]}
        state,out=c.n05_openings(None,history,post,date(2026,11,8))
        self.assertEqual(state,"partial")
        self.assertEqual(out["attempted"],50)
        self.assertEqual(out["checked"],50)
        self.assertEqual(out["not_published_count"],50)
        self.assertEqual(len(out["per_notice"]),50)
        self.assertFalse(out["business_evaluation_performed"])

    def test_n06_company_history_preserves_all_observed_bid_and_award_source_rows(self):
        history={"records":[{"bid_no":"R25BK00000001","bid_ord":"000",
            "class8":"81111599","detail10":None,"official_fields":{"bidPbancNm":"사업A"}}]}
        opening={"opening_records":[{"bid_no":"R25BK00000001","bid_ord":"000",
                  "official_fields":{"scsbdAmt":"137000000","bidQntty":"4"}}],
                 "bidder_detail_records":[{
                    "bid_no":"R25BK00000001","bid_ord":"000","source":c.OPENING_DETAIL,
                    "bid_info_fields":{"fnlSucsfbdCorpNm":"가업체","scsbdAmt":"137000000"},
                    "source_page_sha256":["ab"*32],
                    "bidClsfNo":"0","bidPrgrsOrd":"000",
                    "bidders":[
                        {"bzmnRegNo":"1234567890","grpNm":"가업체",
                         "bdngAmt":"138000000","bdrt":"89.1","onbsRnkg":"1"},
                        {"bzmnRegNo":"2234567890","grpNm":"나업체",
                         "bdngAmt":"139000000","bdrt":"88.2","onbsRnkg":"2"},
                        {"bzmnRegNo":"1234567890","grpNm":"가업체",
                         "bdngAmt":"140000000","bdrt":"88.0","onbsRnkg":"3"}]}]}
        s6,n6=c.n06_supply_catalog(NOTICE,{"files":[]},history,opening)
        self.assertEqual(s6,"verified")
        self.assertEqual(n6["company_count"],2)
        self.assertEqual(n6["bid_history_record_count"],3)
        self.assertEqual([x["bid_amount"] for x in n6["bid_history_records"]],
                         ["138000000","139000000","140000000"])
        self.assertEqual([x["bid_rate"] for x in n6["bid_history_records"]],
                         ["89.1","88.2","88.0"])
        company=next(x for x in n6["company_records"]
                     if x["registration_number"]=="1234567890")
        self.assertEqual(company["bid_record_indexes"],[0,2])
        self.assertEqual(n6["bid_history_records"][2]["source_detail_index"],0)
        self.assertEqual(n6["bid_history_records"][2]["source_bidder_index"],2)
        self.assertEqual(len(n6["award_result_source_records"]),1)
        self.assertFalse(n6["award_result_source_records"][0]["final_award_verified"])
        self.assertFalse(n6["all_time_company_history_verified"])
        self.assertFalse(n6["business_evaluation_performed"])

    def test_n07_groups_item_prices_and_quantities_not_company_summaries(self):
        history={"records":[{"bid_no":"R25BK00000001","bid_ord":"000",
            "class8":"81111599","detail10":None,"official_fields":{
               "bidPbancNm":"정보시스템 관련 사업","bidQntty":"4"}}]}
        opening={"opening_records":[{"bid_no":"R25BK00000001","bid_ord":"000",
                  "official_fields":{"scsbdAmt":"137000000","bidQntty":"4"}}],
                 "bidder_detail_records":[{"bid_no":"R25BK00000001","bid_ord":"000",
                   "source":c.OPENING_DETAIL,
                   "bidders":[{"bzmnRegNo":"1234567890","grpNm":"가업체",
                         "bdngAmt":"138000000","bdrt":"89.1"}]}]}
        s7,n7=c.n07_price_sources(NOTICE,{"official_fields":{}},
                                     history,opening,{})
        self.assertEqual(s7,"verified")
        self.assertEqual(n7["classification_group_count"],1)
        self.assertEqual(n7["classification_groups"][0]["class8"],"81111599")
        self.assertTrue(any(x["raw"]=="137000000" and x["field"]=="scsbdAmt"
                            for x in n7["source_amounts"]))
        self.assertTrue(any(x["raw"]=="138000000" and x["field"]=="bdngAmt"
                            for x in n7["source_amounts"]))
        self.assertTrue(any(x["raw"]=="4" and x["field"]=="bidQntty"
                            for x in n7["price_quantity_records"]))
        self.assertEqual(n7["awarded_price_records_verified"],0)
        self.assertIsNone(n7["recommended_bid"])
        self.assertFalse(n7["business_evaluation_performed"])

    def test_n08_handoff_contains_both_company_and_commodity_original_evidence(self):
        history={"records":[{"bid_no":"R25BK00000001","bid_ord":"000",
              "class8":"81111599","official_fields":{"bidPbancNm":"사업"}}]}
        opening={"opening_records":[{"bid_no":"R25BK00000001","bid_ord":"000",
                  "official_fields":{"scsbdAmt":"137000000"}}],
                 "bidder_detail_records":[{"bid_no":"R25BK00000001","bid_ord":"000",
                   "source":c.OPENING_DETAIL,
                   "bidders":[{"bzmnRegNo":"1234567890","grpNm":"가업체",
                         "bdngAmt":"138000000"}]}]}
        _,n6=c.n06_supply_catalog(NOTICE,{"files":[]},history,opening)
        _,n7=c.n07_price_sources(NOTICE,{},history,opening,n6)
        previous={"N02":{"files":[{"file_seq":1,"sha256":"a"*64,
                          "size_bytes":123,"source":"official"}]},
                  "N04":history,"N05":opening,"N06":n6,"N07":n7}
        state,out=c.n08_handoff(NOTICE,previous)
        self.assertEqual(state,"verified")
        bundle=out["handoff_bundle"]
        self.assertEqual(bundle["bidder_detail_records"][0]["bidders"][0]
                         ["bdngAmt"],"138000000")
        self.assertEqual(bundle["company_bid_history_records"][0]["bid_amount"],
                         "138000000")
        self.assertTrue(any(x["field"]=="scsbdAmt" for x in bundle["source_amount_fields"]))
        self.assertEqual(len(bundle["company_records"]),1)
        self.assertFalse(out["business_evaluation_performed"])

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
