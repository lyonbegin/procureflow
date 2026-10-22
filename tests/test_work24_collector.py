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
    def test_no_automatic_bidding_or_pii_getters(self):
        import inspect
        from work24_collector import collect
        source=inspect.getsource(collect)
        self.assertNotIn("submit_application",source)
        self.assertNotIn("login(",source)
if __name__=="__main__":unittest.main()
