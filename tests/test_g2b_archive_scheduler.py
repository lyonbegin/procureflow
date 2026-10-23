import json
import unittest
from datetime import date,datetime,timedelta
from g2b_date_windows import window,KST
from g2b_schedule import config,next_backfill_cursor
from g2b_bid_collector import fetch_opening_listing


class WindowTests(unittest.TestCase):
    def test_explicit_historical_dates_are_stable(self):
        first,last=window(2,"2026-02-03","2026-02-04")
        self.assertEqual(first.isoformat(),"2026-02-03")
        self.assertEqual(last.isoformat(),"2026-02-04")

    def test_invalid_dates_or_future_are_rejected(self):
        with self.assertRaises(ValueError):window(2,"2026-02-05","2026-02-04")
        with self.assertRaises(ValueError):window(2,"2024-01-01","2026-01-01")
        with self.assertRaises(ValueError):window(2,"2026-02-05",None)
        with self.assertRaises(ValueError):window(2,"2029-01-01","2029-01-02")

    def test_backfill_cursor_continues_on_next_page(self):
        cfg={"start_date":"2026-07-20","page_start":5}
        nxt=next_backfill_cursor(cfg,{"has_more":True,"last_page":6})
        self.assertEqual(nxt,{"cursor_date":"2026-07-20","cursor_page":7})

    def test_completed_date_advances_backward_exact_one_day(self):
        cfg={"start_date":"2026-07-20","page_start":7}
        nxt=next_backfill_cursor(cfg,{"has_more":False,"last_page":7})
        self.assertEqual(nxt,{"cursor_date":"2026-07-19","cursor_page":1})

    def test_award_backfill_config_uses_one_fixed_day(self):
        now=datetime(2026,10,23,10,0,tzinfo=KST)
        cfg=config("award","backfill",{
          "cursor_date":"2026-10-04","cursor_page":3},now)
        self.assertEqual(cfg["start_date"],"2026-10-04")
        self.assertEqual(cfg["end_date"],"2026-10-04")
        self.assertEqual(cfg["page_start"],3)
        self.assertEqual(cfg["limit"],40)


class ListingWindowTests(unittest.TestCase):
    def test_opening_page_can_resume_historical_window(self):
        class Response:
            status=200
            def json(self):
                return {"result":{"onbsRsltClsfList":[]}}
        class Request:
            calls=[]
            def post(self,url,data,headers,timeout):
                self.calls.append(json.loads(data))
                return Response()
        class Context:
            request=Request()
        stats={}
        result=fetch_opening_listing(
            Context(),days=3,pages=2,max_results=20,
            start_date="2026-05-01",end_date="2026-05-01",
            page_start=3,stats=stats)
        self.assertEqual(result,[])
        params=Context.request.calls[0]["dlSrchOnbsRsltClsfListInM"]
        self.assertEqual(params["onbsYmdStr"],"20260501")
        self.assertEqual(params["onbsYmdEnd"],"20260501")
        self.assertEqual(params["firstIndex"],21)
        self.assertEqual(params["lastIndex"],30)
        self.assertEqual(stats["last_page"],3)
        self.assertFalse(stats["has_more"])


if __name__=="__main__":
    unittest.main()
