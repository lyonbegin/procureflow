"""Build-time contract tests for the official-source mobile FastAPI endpoint."""
import unittest
from contextlib import contextmanager
from datetime import datetime,timezone
from unittest.mock import patch
from fastapi import HTTPException
import fresh_mobile_api as mobile

NOTICE={
 "bid_no":"R26BM01032642","bid_ord":"000","title":"업무망 DNS시스템외 1종 유지보수",
 "agency":"한전KDN(주)","detail10":"","posted_on":None,
 "original_json":{"untyBidPbancNo":"R26BM01032642"},
 "response_sha":"c"*64,"category_verified":False,
 "first_seen":datetime(2026,11,5,9,31,tzinfo=timezone.utc)
}
REGIONAL={
 **NOTICE,"bid_no":"R26BM01032671","title":"우장산역 노후 에스컬레이터 교체공사",
 "agency":"서울교통공사",
}

class FakeConnection:
 def __init__(self,rows=None):
  self.calls=[]
  self.rows=rows if rows is not None else [REGIONAL]
 def execute(self,sql,params=None):
  self.calls.append((sql,params or []))
  self.is_count="SELECT count(*)" in sql
  return self
 def fetchone(self):
  return {"n":len(self.rows)}
 def fetchall(self):
  return self.rows

class MobileSearchTests(unittest.TestCase):
 def _search(self,**params):
  fake=FakeConnection()
  @contextmanager
  def context():
   yield fake
  with patch.object(mobile.store,"conn",context):
   result=mobile.search_notices(**params)
  return fake,result
 def test_real_notice_from_new_table(self):
  fake,out=self._search(keyword="교체",region="서울")
  self.assertEqual(out["total"],1)
  self.assertEqual(out["source"],"fresh_g2b_official_site")
  self.assertTrue(out["no_external_third_party_api"])
  self.assertEqual(out["items"][0]["bidNo"],"R26BM01032671")
  self.assertEqual(out["items"][0]["region"],"서울")
  self.assertEqual(out["items"][0]["regionBasis"],"agency_name_only")
  self.assertEqual(out["items"][0]["status"],"")
  self.assertIsNone(out["items"][0]["deadlineAt"])
  self.assertIn("n.agency",fake.calls[0][0])
  self.assertIn("n.title",fake.calls[0][0])
  self.assertIn("freshg2b.notices",fake.calls[0][0])
  self.assertNotIn("procureflow.tenders",fake.calls[0][0])
  self.assertEqual(fake.calls[0][1][0:4],["교체"]*3+["서울"])
 def test_category_title_match_explicitly_unverified(self):
  fake,out=self._search(category="it")
  self.assertIn("업종은 공고명",out["filterNotes"][1])
  self.assertIn("시스템",fake.calls[0][1])
  self.assertFalse(out["items"][0]["categoryVerified"])
 def test_deadline_filter_unknown_is_not_reported_as_soon(self):
  fake,out=self._search(deadline_soon=True)
  self.assertFalse(out["items"][0]["deadlineSoon"])
  self.assertTrue(any("마감일" in x for x in out["filterNotes"]))
  self.assertIn("regexp_replace",fake.calls[0][0])
 def test_unsupported_area_rejected(self):
  with self.assertRaisesRegex(ValueError,"지역"):
   mobile.search_notices(region="서울%")
 def test_selected_bid_detail_uses_exact_id_round(self):
  with patch.object(mobile.store,"notice_detail",return_value={"notice":NOTICE,"executions":[],"offers":[],"final_awards":[],"attachments":[]}) as fn:
   d=mobile.mobile_notice_detail("R26BM01032642","000")
  fn.assert_called_once_with("R26BM01032642","000")
  self.assertEqual(d["item"]["bidNo"],"R26BM01032642")
  self.assertEqual(d["item"]["bidSeq"],"000")
  self.assertTrue(d["item"]["originalUrl"].startswith("https://www.g2b.go.kr/"))
 def test_wrong_detail_id_fails_closed(self):
  with self.assertRaises(HTTPException) as cx:
   mobile.mobile_notice_detail("../../etc/passwd","000")
  self.assertEqual(cx.exception.status_code,400)
 def test_official_code_vs_unverified_title_heuristic(self):
  self.assertEqual(mobile.task_from_notice({"prcmBsneSeCd":"조070002"},"임대형공장 공사"),("SERVICE","official_code"))
  self.assertEqual(mobile.task_from_notice({},"서울시 신축 공사"),("CONSTRUCTION","title_keyword_unverified"))
 def test_no_date_or_amount_fabrication(self):
  item=mobile.map_notice(NOTICE)
  self.assertIsNone(item["postedAt"])
  self.assertIsNone(item["deadlineAt"])
  self.assertIsNone(item["budgetAmount"])
  self.assertEqual(item["status"],"")
if __name__=="__main__":
 unittest.main(verbosity=2)
