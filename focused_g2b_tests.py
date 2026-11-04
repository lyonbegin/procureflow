"""No-network regression gates for the isolated single-purpose management page."""
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

import focused_g2b as app

BID="R26BK01787028"
CODE="8111159901"


class FakeCursor:
    def __init__(self,items):self.items=items
    def fetchall(self):return self.items
    def fetchone(self):return self.items[0] if self.items else None


class FakeDB:
    def __init__(self,codes=None,matched=None,outcomes=None):
        self.codes=codes if codes is not None else [{
          "code":CODE,"source_uri":"https://www.g2b.go.kr/source/original",
          "source_field":"dtilPrdctClsfcNo","evidence_level":"official_direct","bid_ord":"000"}]
        self.matched=matched if matched is not None else [{
          "bid_no":"R21BK00000001","bid_ord":"000",
          "title":"과거 용역 입찰","agency":"다른 발주기관",
          "published":"2021-10-15","source_uri":"https://www.g2b.go.kr/original"}]
        self.outcomes=outcomes if outcomes is not None else [
          {"result_kind":"opening","company":"A업체","amount":"90000000",
           "rate":"88.5","rank":"1","participation_count":"3","result_status":"개찰",
           "last_seen":date(2021,10,16)},
          {"result_kind":"award","company":"B업체","amount":"91000000",
           "rate":"90.1","rank":"","participation_count":"3","result_status":"자료 미확정",
           "last_seen":date(2021,10,17)}]
        self.sql=[]
    def execute(self,sql,args=()):
        self.sql.append((sql,args))
        if "FROM procureflow.tenders" in sql and "WHERE source='g2b' AND external_id=%s" in sql:
            return FakeCursor([{"bid_no":BID,"title":"선택 입찰","agency":"기관",
              "category":"정보화","notice_date":"2026-10-22","deadline":"2026-10-29",
              "status":"closed","source_url":"https://www.g2b.go.kr/original",
              "last_seen":date(2026,10,22)}])
        if "FROM procureflow.g2b_notice_categories" in sql and "bid_no=%s" in sql and "ORDER BY created_at DESC LIMIT 20" in sql:
            return FakeCursor(self.codes)
        if "FROM matches" in sql:
            return FakeCursor(self.matched)
        if "FROM procureflow.bid_results" in sql:
            return FakeCursor(self.outcomes)
        if "FROM procureflow.tenders t" in sql:
            return FakeCursor([])
        raise AssertionError("Unexpected SQL "+sql[:110])


class PageTest(unittest.TestCase):
    def test_ui_one_page_and_existing_node_manager_links(self):
        content=(Path(__file__).parent/"focused_g2b.html").read_text()
        self.assertIn("section=public_nodes",content)
        self.assertIn("A01-public-win-strategy.json",content)
        self.assertIn("동일 세부종목 과거 입찰·개찰·낙찰 분석",content)
        self.assertIn("data-bid",content)
        self.assertNotIn("가상 공고 A",content)

    def test_selected_original_exact10(self):
        s=app.select_case(FakeDB(),BID)
        self.assertTrue(s["source_verified"])
        self.assertEqual(s["original_detail10"],CODE)

    def test_missing_original_cannot_create_fake_category(self):
        self.assertFalse(app.select_case(FakeDB(codes=[]),BID)["source_verified"])

    def test_multiple_original_codes_is_not_automatically_chosen(self):
        d=FakeDB(codes=[{"code":CODE},{"code":"8111159902"}])
        r=app.select_case(d,BID)
        self.assertFalse(r["source_verified"])
        self.assertIsNone(r["original_detail10"])

    def test_category_query_requires_proven_ten_not_eight_or_agency(self):
        d=FakeDB()
        r=app._history(d,BID,CODE,"2016-10-22","2026-10-22",0,20)
        sql,args=next((q,a) for q,a in d.sql if "FROM matches" in q)
        self.assertIn("c.code_type='detail10'",sql)
        self.assertIn("c.evidence_level='official_direct'",sql)
        self.assertIn("c.code=%s",sql)
        self.assertNotIn("classification8",sql)
        self.assertNotIn("h.agency ILIKE",sql)
        self.assertEqual(args[0],CODE)
        self.assertEqual(r["matching_notice_count_in_verified_db"],1)
        self.assertFalse(r["complete_10yr_website_search"])

    def test_opening_and_award_provenance_separate(self):
        r=app._history(FakeDB(),BID,CODE,"2016-10-22","2026-10-22",0,20)
        item=r["items"][0]
        self.assertEqual(item["opening_records"][0]["company"],"A업체")
        self.assertEqual(item["award_records"][0]["company"],"B업체")
        self.assertNotIn("winner_confirmed",item)

    def test_search_date_is_selected_publication_minus_10yr(self):
        d=FakeDB()
        @contextmanager
        def db():yield d
        with patch.object(app,"readonly",db):
            result=app.history(BID,offset=0,limit=20)
        self.assertEqual(result["filter"]["start"],"2016-10-22")
        self.assertEqual(result["filter"]["end"],"2026-10-22")
        self.assertEqual(result["filter"]["agency"],"ALL_AGENCIES")

    def test_history_hold_without_original_evidence(self):
        d=FakeDB(codes=[])
        @contextmanager
        def db():yield d
        with patch.object(app,"readonly",db):
            result=app.history(BID,offset=0,limit=20)
        self.assertEqual(result["status"],"HOLD")
        self.assertEqual(result["items"],[])

    def test_official_site_search_requires_verified_code(self):
        d=FakeDB(codes=[])
        @contextmanager
        def db():yield d
        with patch.object(app,"readonly",db):
            with patch.object(app,"run_search",side_effect=AssertionError("website called")):
                result=app.official_search(BID,month=None,page=1)
        self.assertEqual(result["status"],"HOLD")

    def test_actual_site_search_one_month_and_fail_closed(self):
        d=FakeDB()
        args=[]
        @contextmanager
        def db():yield d
        def site(*a,**kw):
            args.append((a,kw))
            return {"status":"blocked","reason":"BID_NOTICE_EXACT10_FIELD_NOT_FOUND",
                "search_request_verified":False,
                "matched_explicit_detail10":[]}
        with patch.object(app,"readonly",db),patch.object(app,"run_search",side_effect=site):
            result=app.official_search(BID,month=None,page=1)
        self.assertEqual(len(args),1)
        self.assertEqual(args[0][0][0],CODE)
        self.assertFalse(result["website_search_verified"])
        self.assertEqual(result["official_verified_rows_only"],[])

    def test_real_site_page_cursor_valid_and_bounded(self):
        from g2b_bid_notice_site_search import search_window
        w=search_window(CODE,"2016-10-22","2026-10-22")
        self.assertEqual((w["start"],w["end"]),("2026-10-01","2026-10-22"))
        self.assertEqual(w["previous_month"],"2026-09")
        with self.assertRaises(ValueError):
            search_window("81111599","2016-10-22","2026-10-22")

    def test_no_database_dsn_is_explicit_blocker(self):
        with patch.dict("os.environ",{"DATABASE_URL":""}):
            with self.assertRaisesRegex(Exception,"POSTGRESQL_READONLY_CONNECTION_NOT_CONFIGURED"):
                with app.readonly():pass


if __name__=="__main__":unittest.main(verbosity=2)
