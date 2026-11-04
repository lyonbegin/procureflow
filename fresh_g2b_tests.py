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
