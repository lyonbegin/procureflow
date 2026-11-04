"""No-network build gates for truly isolated G2B site collector."""
import os
from pathlib import Path
from unittest import TestCase,main
from unittest.mock import patch
from datetime import date

import fresh_g2b_app as app
import fresh_g2b_store as db
import fresh_g2b_site as site


class FakeLegacy:
    def __init__(self,legacy):self.legacy=legacy
    def execute(self,query):return self
    def fetchone(self):return {"legacy":self.legacy}


class SiteFirstTest(TestCase):
    def test_no_database_raises_not_falls_back_to_production(self):
        with patch.dict(os.environ,{"FRESH_DATABASE_URL":""}):
            with self.assertRaisesRegex(RuntimeError,"FRESH_DATABASE_URL_REQUIRED"):
                db.connect()

    def test_old_database_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"LEGACY_DATABASE_REJECTED"):
            db.guard(FakeLegacy("procureflow.tenders"))

    def test_empty_new_database_accepted(self):
        db.guard(FakeLegacy(None))

    def test_schema_names_only_fresh(self):
        stmts="\n".join(db.DDLS)
        self.assertIn("fresh_g2b.site_search_runs",stmts)
        self.assertIn("fresh_g2b.site_offers",stmts)
        self.assertNotIn("INSERT INTO procureflow.",stmts)
        self.assertNotIn("FROM procureflow.",stmts)

    def test_no_legacy_actual_source_in_new_app(self):
        sources="\n".join((Path(__file__).parent/p).read_text() for p in (
              "fresh_g2b_app.py","fresh_g2b_site.py","fresh_g2b_store.py"))
        self.assertNotIn("db.session(",sources)
        self.assertNotIn("save_batch(",sources)
        self.assertNotIn("collect(days=",sources)
        self.assertNotIn("procureflow.bid_results",sources)
        self.assertNotIn("229건",sources)

    def test_search_requires_ten_digit(self):
        with self.assertRaisesRegex(ValueError,"EXACT_10_REQUIRED"):
            app._validate_action("search",{"detail10":"81111599",
                 "start":"2026-10-01","end":"2026-10-20"})

    def test_search_correct_month_parameters(self):
        x=app._validate_action("search",{"detail10":"8111159901",
            "start":"2016-11-04","end":"2026-11-04","month":"2026-11","page":1})
        self.assertEqual(x["detail10"],"8111159901")
        self.assertEqual(x["month"],"2026-11")

    def test_search_rejects_out_of_period(self):
        with self.assertRaises(ValueError):
            app._validate_action("search",{"detail10":"8111159901",
               "start":"2001-01-01","end":"2026-11-04","page":1})

    def test_action_must_be_admin(self):
        with patch.dict(os.environ,{"FRESH_ADMIN_TOKEN":"private"}):
            with self.assertRaises(Exception) as e:app._verify_admin("wrong")
            self.assertEqual(e.exception.status_code,403)
            app._verify_admin("private")

    def test_bad_ids_not_accepted_for_original(self):
        with self.assertRaisesRegex(ValueError,"INVALID_BID_ID"):
            app._validate_action("detail",{"bid_no":"8digit","bid_ord":"000",
                                               "detail10":"8111159901"})

    def test_dd_and_bk_ids_supported_in_new_store(self):
        self.assertTrue(db.BID.fullmatch("R26BK01787028"))
        self.assertTrue(db.BID.fullmatch("R26DD20902086"))
        self.assertTrue(site.BID.fullmatch("R26DD20902086"))

    def test_official_attachment_hosts_allowlisted(self):
        self.assertTrue(site.official_url("https://www.g2b.go.kr/file/download?id=3"))
        self.assertFalse(site.official_url("http://www.g2b.go.kr/file"))
        self.assertFalse(site.official_url("https://example.com/evil.pdf"))
        self.assertFalse(site.official_url("https://www.g2b.go.kr.evil.test/a"))

    def test_original_detail_evidence_not_title_similarity(self):
        self.assertTrue(site.explicit_detail10(
            "사업명: 정보시스템개발\n세부품명번호 8111159901", "8111159901"))
        self.assertFalse(site.explicit_detail10("사업명 8111159901 입니다","8111159901"))
        self.assertFalse(site.explicit_detail10(
            "세부품명번호 8111159902 / 별개 8111159901","8111159901"))

    def test_original_url_checks_actual_identity(self):
        u=site.detail_url("R26BK01787028","000")
        self.assertIn("bidPbancNo=R26BK01787028",u)
        self.assertIn("bidPbancOrd=000",u)

    def test_real_official_g2b_document_identity(self):
        u=("https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do"
           "?bidPbancNo=R26BK01355326&bidPbancOrd=000&fileSeq=2"
           "&fileType=&prcmBsneSeCd=03")
        self.assertEqual(site.official_file_identity(u),
                         ("R26BK01355326","000"))
        action=app._validate_action("official-file",
                    {"url":u,"detail10":"8111159901"})
        self.assertEqual(action["bid_no"],"R26BK01355326")
        self.assertEqual(action["detail10"],"8111159901")

    def test_reject_arbitrary_document_paths_even_on_g2b(self):
        with self.assertRaises(ValueError):
            site.official_file_identity("https://www.g2b.go.kr/login?bidPbancNo=R26BK01355326")
        with self.assertRaises(ValueError):
            app._validate_action("official-file",{
                "url":"https://evil.test/pn/pnp/pnpe/UntyAtchFile/downloadFile.do",
                "detail10":"8111159901"})

    def test_rank_one_never_award(self):
        data={"bid_info":{"bidPgstCd":"개찰완료"},"etc_data":{},
              "bidders":[{"grpNm":"가상 A","onbsRnkg":"1","bdngAmt":"120000"}]}
        self.assertEqual(site.explicitly_confirmed_winner(data)["status"],
                         "not_confirmed")

    def test_single_screen_keeps_old_node_links(self):
        html=(Path(__file__).parent/"fresh_g2b.html").read_text()
        self.assertIn("section=public_nodes",html)
        self.assertIn("A01-public-win-strategy.json",html)
        self.assertIn("기존 229건 사용 안 함",html)
        self.assertIn("실제 나라장터 검색 실행",html)


if __name__=="__main__":main(verbosity=2)
