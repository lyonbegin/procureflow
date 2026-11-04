"""Build-gated smoke tests. No real G2B requests, no DB, no tokens."""
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from g2b_detail10_search import search_one_page

CODE="8111159901"
START="2016-10-24"
END="2026-10-22"

def source(items,total=None):
    return {"response":{"header":{"resultCode":"00"},
       "body":{"items":items,"totalCount":len(items) if total is None else total}}}

class ExactFilterTest(unittest.TestCase):
    def test_actual_filter_sent_before_result_pagination(self):
        calls=[]
        def get(url):
            calls.append(parse_qs(urlsplit(url).query))
            return source([
              {"bidNtceNo":"R26BK01234567","dtilPrdctClsfcNo":CODE},
              {"bidNtceNo":"R26BK01234568","prdctClsfcNo":"81111599"}])
        r=search_one_page(CODE,START,END,key="fixture-key",request_fn=get)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["dtilPrdctClsfcNo"],[CODE])
        self.assertNotIn("prdctClsfcNo",calls[0])
        self.assertEqual(calls[0]["inqryBgnDt"],["202610010000"])
        self.assertEqual(calls[0]["inqryEndDt"],["202610222359"])
        self.assertEqual(len(r["matched"]),1)
        self.assertEqual(len(r["unverified_candidates"]),1)
        self.assertEqual(r["next"],{"cursor":"2026-09","page":1})
        self.assertFalse(r["outcome_collection_executed"])
    def test_not_a_121_month_full_crawl(self):
        calls=[]
        r=search_one_page(CODE,START,END,key="fixture",
          request_fn=lambda url:(calls.append(url) or source([])))
        self.assertEqual(len(calls),1)
        self.assertFalse(r["full_history_verified"])
    def test_wrong_10digit_response_blocks(self):
        r=search_one_page(CODE,START,END,key="fixture",request_fn=lambda _:source([
          {"bidNtceNo":"R26BK01234567","dtilPrdctClsfcNo":"8111159902"}]))
        self.assertEqual(r["status"],"blocked_official_filter_not_respected")
        self.assertFalse(r["matched"])
    def test_short_page_not_claimed_complete(self):
        r=search_one_page(CODE,START,END,key="fixture",request_fn=lambda _:source([
          {"bidNtceNo":"R26BK01234567","dtilPrdctClsfcNo":CODE}],total=150))
        self.assertEqual(r["status"],"blocked_truncated_official_page")
    def test_no_key_no_request(self):
        r=search_one_page(CODE,START,END,key="",request_fn=lambda _:self.fail("called"))
        self.assertEqual(r["status"],"blocked_missing_official_api_credential")
        self.assertEqual(r["api_requests"],0)
    def test_8digit_rejected(self):
        with self.assertRaises(ValueError):
            search_one_page("81111599",START,END,key="fixture")
    def test_last_page_and_last_month(self):
        payload=[{"bidNtceNo":f"R26BK{i:08d}","dtilPrdctClsfcNo":CODE} for i in range(100)]
        r=search_one_page(CODE,START,END,key="fixture",
                          request_fn=lambda _:source(payload,total=120))
        self.assertEqual(r["next"],{"cursor":"2026-10","page":2})
        r=search_one_page(CODE,START,END,key="fixture",page=2,
                          request_fn=lambda _:source(payload[:20],total=120))
        self.assertEqual(r["next"],{"cursor":"2026-09","page":1})
        r=search_one_page(CODE,START,END,key="fixture",cursor="2016-10",
                          request_fn=lambda _:source([]))
        self.assertIsNone(r["next"])
if __name__=="__main__":
    unittest.main(verbosity=2)
