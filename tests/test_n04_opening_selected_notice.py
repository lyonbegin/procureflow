"""N04 exact notice G2B opening lookup: never associate unrelated history."""
from datetime import datetime
from pathlib import Path
import sys,unittest
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import n04_opening as n04
def fixed():return datetime(2026,11,8,10,0,tzinfo=ZoneInfo("Asia/Seoul"))
NO={"bid_no":"R26BK01816186","bid_ord":"000"}
HIST={"bid_no":"R26BK01787028","bid_ord":"000"}
class Tests(unittest.TestCase):
 def test_exact_selected_notice_request_and_zero_result(self):
  seen=[]
  def post(opener,url,payload,headers):
   seen.append((url,payload,headers))
   return {"onbsRsltClsfList":[]}
  out=n04.lookup(None,NO,post,fixed)
  self.assertEqual(len(seen),1)
  self.assertEqual(seen[0][0],n04.OPENINGS)
  params=seen[0][1]["dlSrchOnbsRsltClsfListInM"]
  self.assertEqual(params["bidPbancNo"],NO["bid_no"])
  self.assertEqual(params["bidPbancOrd"],"000")
  self.assertEqual(params["onbsYmdEnd"],"20261108")
  self.assertEqual(out["official_rows"],0)
  self.assertEqual(out["query_result"],"no_matching_rows_in_window")
  self.assertTrue(out["source_query_verified"])
  self.assertFalse(out["exact_detail10_verified"])
  self.assertFalse(out["selected_notice_opening_original_detail_verified"])
  self.assertFalse(out["complete_ten_year_history"])
 def test_exact_matching_historical_notice(self):
  row={"bidPbancNo":HIST["bid_no"],"bidPbancOrd":"000",
       "bidPbancNm":"철강&#40;AX&#41; 시스템", "prcmBsneSeCd":"03",
       "unknown_personal_data":"SHOULD_NOT_EXPOSE"}
  out=n04.lookup(None,HIST,lambda *_:{"onbsRsltClsfList":[row]},fixed)
  self.assertEqual(out["matching_selected_notice"],1)
  self.assertEqual(out["records"][0]["bidPbancNm"],"철강(AX) 시스템")
  self.assertNotIn("unknown_personal_data",out["records"][0])
  self.assertEqual(out["original_award_winner"],None)
 def test_unrelated_result_must_fail_closed(self):
  wrong={"bidPbancNo":"R26BK00000000","bidPbancOrd":"000"}
  with self.assertRaisesRegex(ValueError,"N04_UNRELATED_OFFICIAL_OPENING_ROW"):
   n04.lookup(None,NO,lambda *_:{"onbsRsltClsfList":[wrong]},fixed)
 def test_wrong_revision_must_fail_closed(self):
  wrong={"bidPbancNo":NO["bid_no"],"bidPbancOrd":"001"}
  with self.assertRaisesRegex(ValueError,"N04_UNRELATED_OFFICIAL_OPENING_ROW"):
   n04.lookup(None,NO,lambda *_:{"onbsRsltClsfList":[wrong]},fixed)
 def test_missing_selected_notice_and_broken_source(self):
  with self.assertRaisesRegex(ValueError,"N04_SELECTED_NOTICE_REQUIRED"):
   n04.lookup(None,None,lambda *_:{},fixed)
  with self.assertRaisesRegex(ValueError,"N04_OFFICIAL_OPENING_LIST_SCHEMA_INVALID"):
   n04.lookup(None,NO,lambda *_:{"onbsRsltClsfList":{}},fixed)
if __name__=="__main__":unittest.main()
