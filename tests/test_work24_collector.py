"""Work24 source-native URL, dedupe, provider and classification regressions."""
import unittest
from work24_collector import detail_ref, normalize_detail_url, classify, LIST_PATH, DETAIL_PATH

class Work24ContractTests(unittest.TestCase):
    def test_actual_public_work24_detail(self):
        u="https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=K120612610220037&infoTypeCd=VALIDATION&infoTypeGroup=tb_workinfoworknet"
        ref=detail_ref(u)
        self.assertEqual(ref["source_id"],"VALIDATION:K120612610220037")
        self.assertEqual(normalize_detail_url(u),u)
    def test_real_private_provider_listing(self):
        u="https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?infoTypeCd=CJK&wantedAuthNo=51610082&infoTypeGroup=tb_workinfogubun"
        self.assertEqual(detail_ref(u)["source_id"],"CJK:51610082")
        self.assertIn("infoTypeCd=CJK",normalize_detail_url(u))
    def test_denies_non_work24_hosts(self):
        for u in ("https://evil.com"+DETAIL_PATH+"?wantedAuthNo=51610082&infoTypeCd=CJK",
                  "http://www.work24.go.kr"+DETAIL_PATH+"?wantedAuthNo=51610082&infoTypeCd=CJK",
                  "https://www.work24.go.kr"+LIST_PATH,
                  "https://www.work24.go.kr"+DETAIL_PATH+"?wantedAuthNo=hi&infoTypeCd=CJK"):
            self.assertIsNone(detail_ref(u),u)
    def test_provider_id_disambiguates_dedupe(self):
        base="https://www.work24.go.kr"+DETAIL_PATH+"?wantedAuthNo=12345678&infoTypeCd="
        self.assertNotEqual(detail_ref(base+"CJK")["source_id"],detail_ref(base+"VALIDATION")["source_id"])
    def test_original_job_role_mapping(self):
        self.assertEqual(classify("병원 환경미화원 모집"),"cleaning")
        self.assertEqual(classify("아파트 경비 보안 관리"),"security")
        self.assertEqual(classify("통근버스 운전기사"),"transport")
        self.assertEqual(classify("ERP 시스템 개발자"),"development")
        self.assertEqual(classify("사무보조 채용"),"administration")
    def test_job_search_uses_actual_work24_detail_route(self):
        import inspect
        from work24_collector import search_keyword, DEFAULT_QUERIES, SEARCH_URL
        self.assertEqual(SEARCH_URL,"https://www.work24.go.kr/wk/a/b/1200/retriveDtlEmpSrchList.do")
        self.assertIn("미화",DEFAULT_QUERIES)
        self.assertIn("경비",DEFAULT_QUERIES)
        source=inspect.getsource(search_keyword)
        self.assertIn("srchWrd",source)
        self.assertIn("btnSearch",source)
        self.assertIn("fnSearch",source)
        self.assertNotIn("/cm/main.do",source)
    def test_search_sectors_are_separate_from_procurement(self):
        from work24_collector import collect
        import inspect
        code=inspect.getsource(collect)
        self.assertIn("search_keyword",code)
        self.assertIn("queries",code)
    def test_dashboard_uses_existing_fastapi_for_web_and_analysis(self):
        from pathlib import Path
        from main import app
        routes={r.path for r in app.routes if hasattr(r,"path")}
        self.assertIn("/",routes)
        self.assertIn("/api/analysis/summary",routes)
        self.assertIn("/api/market/collect",routes)
        html=(Path(__file__).resolve().parents[1]/"static"/"index.html").read_text(encoding="utf-8")
        self.assertIn("id=\"analysisSummary\"",html)
        self.assertIn("async function loadAnalysis()",html)
        self.assertIn("loadAnalysis()",html)
        self.assertIn("관리자 키",html)
        self.assertNotIn("고용24·당근·숨고·크몽은 현재 수집 대상에서 제외합니다.",html)

    def test_http_200_work24_error_page_is_rejected(self):
        from work24_collector import read_detail, normalize_detail_url
        raw_url=("https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do"
                 "?wantedAuthNo=20261019051059&infoTypeCd=CLE"
                 "&infoTypeGroup=tb_workinfogubun")
        class Response:
            status=200
        class Body:
            def inner_text(self,timeout=None):
                return "고용24 죄송합니다. 요청하신 페이지에 일시적인 문제가 발생했습니다."
        class Page:
            url=normalize_detail_url(raw_url)
            def goto(self,*a,**kw):return Response()
            def wait_for_timeout(self,*a,**kw):return None
            def locator(self,*a,**kw):return Body()
        with self.assertRaisesRegex(RuntimeError,"work24_server_error_page"):
            read_detail(Page(),{"url":raw_url,"source_id":"CLE:20261019051059"})

    def test_keyword_filter_is_verified_not_assumed(self):
        import inspect
        from work24_collector import search_keyword,collect
        src=inspect.getsource(search_keyword)
        self.assertIn("srcKeyword",src)
        self.assertIn("search_keyword_not_verified",src)
        self.assertIn("search_keyword_mismatch",src)
        detail=inspect.getsource(collect)
        self.assertIn('result["discovered"]',detail)
        self.assertIn('result["examined"]+=1',detail)
        self.assertIn('if result["saved"]>=limit:break',detail)

    def test_g2b_bid_result_collection_contract(self):
        from g2b_bid_collector import parse_response, normalize_item, OPERATIONS
        self.assertIn(("service","award"), OPERATIONS)
        payload={"response":{"header":{"resultCode":"00"},
           "body":{"totalCount":1,"items":{"item":[{
             "bidNtceNo":"R26BK00965123","bidNtceNm":"용역",
             "sucsfbidAmt":"1000000","fnlSucsfbdCorpNm":"법인"}]}}}}
        records,total=parse_response(payload)
        self.assertEqual(total,1)
        row=normalize_item(records[0],"service","award",
                           OPERATIONS[("service","award")],0)
        self.assertEqual(row["bid_ntce_no"],"R26BK00965123")
        self.assertEqual(row["amount"],"1000000")

    def test_no_automatic_bidding_or_pii_getters(self):
        import inspect
        from work24_collector import collect
        source=inspect.getsource(collect)
        self.assertNotIn("submit_application",source)
        self.assertNotIn("login(",source)
if __name__=="__main__":unittest.main()
