"""Offline build gate: no legacy DB, strictly verified fresh site results."""
import unittest
from pathlib import Path
from unittest.mock import patch
import fresh_g2b_store as store
import fresh_g2b_site as site
from g2b_bid_notice_site_search import search_window,request_has_filter

class FreshTest(unittest.TestCase):
    def test_legacy_schema_is_never_referenced_for_data(self):
        src=(Path(__file__).parent/"fresh_g2b_api.py").read_text()
        self.assertEqual(src.count("procureflow.tenders"),1)  # intentional safety guard only
        self.assertNotIn("bid_results",src)
        self.assertNotIn("FROM procureflow.",src)
        self.assertNotIn("g2b_search_first",src)

    def test_store_has_only_legacy_safety_guard(self):
        source=(Path(__file__).parent/"fresh_g2b_store.py").read_text()
        self.assertNotIn("FROM procureflow.",source)
        self.assertNotIn("JOIN procureflow.",source)
        self.assertIn("LEGACY_DATABASE_FORBIDDEN",source)

    def test_10digit_exact_code_not_8digit(self):
        w=search_window("8111159901","2016-11-04","2026-11-04")
        self.assertEqual(w["cursor"],"2026-11")
        with self.assertRaises(ValueError):
            search_window("81111599","2016-11-04","2026-11-04")

    def test_real_post_condition_proof(self):
        form='{"dlSrchBidPbancM":{"dtlsPrnmNo":"8111159901","dateSt":"20261101","dateEd":"20261104"}}'
        self.assertTrue(request_has_filter(form,"8111159901","2026-11-01","2026-11-04"))
        self.assertFalse(request_has_filter('{"title":"8111159901","dateSt":"20261101","dateEd":"20261104"}',
              "8111159901","2026-11-01","2026-11-04"))

    def test_bounded_site_readiness_waits_for_delayed_websquare(self):
        class Frame:
            url="https://www.g2b.go.kr/"
            def __init__(self):
                self.calls=0
            def is_detached(self):
                return False
            def evaluate(self,script):
                self.calls+=1
                return {"state":"complete","text":0,"controls":0} if self.calls<3 else (
                    {"state":"complete","text":24,"controls":3})
        class Page:
            def __init__(self):
                self.frames=[Frame()]
                self.waits=[]
            def wait_for_timeout(self,ms):
                self.waits.append(ms)
        page=Page()
        self.assertTrue(__import__("g2b_bid_notice_site_search")._wait_for_site_rendered(page,2000))
        self.assertEqual(len(page.waits),2)

    def test_empty_site_after_bounded_wait_blocks(self):
        class Frame:
            url="https://www.g2b.go.kr/"
            def is_detached(self):
                return False
            def evaluate(self,script):
                return {"state":"complete","text":0,"controls":0}
        class Page:
            frames=[Frame()]
            def wait_for_timeout(self,ms):
                pass
        self.assertFalse(__import__("g2b_bid_notice_site_search")._wait_for_site_rendered(Page(),1000))

    def test_official_date_input_is_yyyymmdd_even_when_blank(self):
        class Input:
            def __init__(self):
                self.entered=None
            def fill(self, value, timeout=None):
                self.entered=value
            def press(self, key, timeout=None):
                self.key=key
        field=Input()
        from g2b_bid_notice_site_search import _fill_date
        self.assertEqual(_fill_date(field,"2026-11-04"),"20261104")
        self.assertEqual(field.entered,"20261104")
        self.assertEqual(field.key,"Tab")

    def test_official_date_replay_preserves_10digit_and_other_fields(self):
        from g2b_bid_notice_site_search import _verified_date_replay,SearchBlocked
        from types import SimpleNamespace
        import json
        url="https://www.g2b.go.kr/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do"
        original={"dlBidPbancLstM":{"dtlsPrnmNo":"8111159901",
                  "fromBidDt":"20261006","toBidDt":"20261104",
                  "recordCountPerPage":"10","page":1}}
        req=SimpleNamespace(url=url,method="POST",post_data=json.dumps(original))
        payload=json.loads(_verified_date_replay(req,"8111159901","2026-11-01","2026-11-04"))
        row=payload["dlBidPbancLstM"]
        self.assertEqual(row["fromBidDt"],"20261101")
        self.assertEqual(row["toBidDt"],"20261104")
        self.assertEqual(row["dtlsPrnmNo"],"8111159901")
        self.assertEqual(row["recordCountPerPage"],"10")
        self.assertEqual(original["dlBidPbancLstM"]["fromBidDt"],"20261006")
        with self.assertRaises(SearchBlocked):
            _verified_date_replay(req,"8111159902","2026-11-01","2026-11-04")
        req.url="https://example.com/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do"
        with self.assertRaises(SearchBlocked):
            _verified_date_replay(req,"8111159901","2026-11-01","2026-11-04")

    def test_file_discovery_hosts_only(self):
        self.assertTrue(site._official("https://www.g2b.go.kr/file/download.do"))
        self.assertFalse(site._official("https://example.com/bad.exe"))
        self.assertFalse(site._official("http://www.g2b.go.kr/file"))
        self.assertFalse(site._official("https://www.g2b.go.kr@evil.test/file"))

    def test_opening_identity_strict(self):
        site._check("R26BK01787028","000")
        site._check("R26DD20902086","000")
        with self.assertRaises(site.SourceBlocked):site._check("R26BK01787028","notOrd")

    def test_final_winner_requires_explicit_status(self):
        self.assertIsNone(site._confirmed_name({"bid_info":{"fnlSucsfbdCorpNm":"1순위 후보"}}))
        self.assertEqual(site._confirmed_name({"bid_info":{
            "fnlSucsfbdCorpNm":"확정업체",
            "awardStatusText":"최종낙찰"}}),"확정업체")

    def test_live_search_failure_never_returns_cached_data(self):
        with patch.object(site,"run_search",return_value={
             "status":"blocked","reason":"BID_NOTICE_EXACT10_FIELD_NOT_FOUND"}):
            with self.assertRaises(site.SourceBlocked):
                site.search_one("8111159901","2016-11-04","2026-11-04")

    def test_ui_links_to_previous_node_management(self):
        html=(Path(__file__).parent/"fresh_g2b.html").read_text()
        self.assertIn("section=public_nodes",html)
        self.assertIn("api/fresh/search",html)
        self.assertIn("기존 229건",html)  # explicitly says NOT imported

    def test_fresh_only_env_var(self):
        self.assertIn("FRESH_DATABASE_URL",
            (Path(__file__).parent/"fresh_g2b_store.py").read_text())


if __name__=="__main__":unittest.main(verbosity=2)
