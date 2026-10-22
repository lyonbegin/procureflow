"""Tests for exact Kmong Enterprise link and content extraction contracts."""
import unittest

from kmong_enterprise_collector import detail_id, listing_url, parse_fields, DETAIL_RE

class KmongEnterpriseTests(unittest.TestCase):
    def test_live_observed_project_route(self):
        self.assertEqual(detail_id("https://kmong.com/enterprise/requests/227244"),"227244")
        self.assertEqual(detail_id("https://www.kmong.com/enterprise/requests/227244?test=1"),"227244")
    def test_reject_unrelated_urls(self):
        for url in [
            "https://evil.example/enterprise/requests/227244",
            "http://kmong.com/enterprise/requests/227244",
            "https://kmong.com/enterprise/requests/",
            "https://kmong.com/enterprise/requests?category_list=6",
            "https://kmong.com/category/6",
        ]:
            self.assertIsNone(detail_id(url),url)
    def test_filters_are_source_native(self):
        self.assertEqual(listing_url(1),"https://kmong.com/enterprise/requests?category_list=6&page=1&q=&sort=created_at")
        with self.assertRaises(ValueError):listing_url(0)
    def test_fields_do_not_infer_fake_budget(self):
        sample="예산\n22,000,000원\n진행 방식\n외주\n프로젝트 기간\n102일\nPython React AI 자연어 검색 DB 데이터"
        meta=parse_fields(sample)
        self.assertEqual(meta["budget_krw"],22000000)
        self.assertEqual(meta["work_format"],"외주")
        self.assertEqual(meta["duration_days"],102)
        self.assertIn("ai",meta["tags"])
        self.assertIn("development",meta["tags"])
        self.assertIsNone(parse_fields("예산은 추후 협의") .get("budget_krw"))
    def test_card_route_regex(self):
        self.assertTrue(DETAIL_RE.fullmatch("/enterprise/requests/227244"))
        self.assertFalse(DETAIL_RE.fullmatch("/enterprise/requests/227244/edit"))

if __name__ == "__main__":
    unittest.main()
