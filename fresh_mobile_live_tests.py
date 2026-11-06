"""Source-only live official search tests. No DB reads, no fabricated matches."""
import unittest,json,time
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import Response
from g2b_bid_notice_site_search import _verified_live_filter_replay,SearchBlocked
import fresh_mobile_live as mobile

class LiveOfficialTests(unittest.TestCase):
 def test_replays_user_filters_in_real_observed_public_post(self):
  request=SimpleNamespace(
   url="https://www.g2b.go.kr/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do",
   method="POST",post_data=json.dumps({"dlBidPbancLstM":{
     "dtlsPrnmNo":"","fromBidDt":"20261101","toBidDt":"20261106",
     "bidPbancNm":"","odnLmtLgdngNm":"","odnLmtLgdngCd":"","dtlsPrnmNm":"",
     "prcmBsneSeCd":"0000 조070001 조070002 조070003",
     "currentPage":"","recordCountPerPage":"10","startIndex":1,"endIndex":10}}))
  posted=_verified_live_filter_replay(request,"","2026-11-01","2026-11-06",
      keyword="정보시스템",region="서울특별시",category="정보시스템",
      task_type="SERVICE",page=2,size=10,region_code="11")
  q=json.loads(posted)["dlBidPbancLstM"]
  self.assertEqual(q["bidPbancNm"],"정보시스템")
  self.assertEqual(q["odnLmtLgdngNm"],"서울특별시")
  self.assertEqual(q["odnLmtLgdngCd"],"11")
  self.assertEqual(q["dtlsPrnmNm"],"정보시스템")
  self.assertEqual(q["prcmBsneSeCd"],"조070003")
  self.assertEqual(q["currentPage"],"2")
  self.assertEqual(q["startIndex"],11)
  self.assertEqual(q["endIndex"],20)
 def test_source_filter_verification_fails_closed_without_origin_field(self):
  request=SimpleNamespace(
   url="https://www.g2b.go.kr/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do",
   method="POST",post_data=json.dumps({"dlBidPbancLstM":{
     "dtlsPrnmNo":"","fromBidDt":"20261101","toBidDt":"20261106",
     "bidPbancNm":"","currentPage":"","recordCountPerPage":"10","startIndex":1,"endIndex":10}}))
  with self.assertRaisesRegex(SearchBlocked,"FIELD_NOT_OBSERVED"):
   _verified_live_filter_replay(request,"","2026-11-01","2026-11-06",region="서울특별시")
 def test_start_job_queues_fresh_runner_without_db(self):
  id_holder=[]
  class MockExec:
   def submit(self,fn,id_,params):
    id_holder.append(id_)
  with patch.object(mobile,"EXECUTOR",MockExec()):
   reply=mobile.start_live_search(Response(),keyword="시스템",region="서울",category="",
     task_type="",sort="latest",page=1,size=10,deadline_soon=False,include_closed=False)
  self.assertEqual(reply["status"],"queued")
  self.assertEqual(reply["source"],"g2b_live_official_site")
  self.assertEqual(reply["db_reads"],0)
  self.assertEqual(mobile.JOBS[id_holder[0]]["params"]["region"],"서울")
  del mobile.JOBS[id_holder[0]]
 def test_live_job_returns_actual_new_request_result(self):
  job_id="c"*32
  mobile.JOBS[job_id]={"status":"queued","created_at":time.time(),"params":{},"result":None,"error":None}
  raw={"bid_no":"R26BM01032671","bid_ord":"000","title":"우장산역 노후 에스컬레이터 교체공사",
       "agency":"서울교통공사","raw":{"untyBidPbancNo":"R26BM01032671"},"direct_category_codes":[],"posted_on":"20261105"}
  doc={"status":"partial_filtered_result","search_request_verified":True,"live_filter_verified":True,
       "matched_explicit_detail10":[],"pending_original_detail10_verification":[raw],
       "official_total":1,"returned_bid_ids":1,"live_search_endpoint":"/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do",
       "request_window":{"start":"2026-11-01","end":"2026-11-06"},"response_sha":"z"*64,
       "live_filters":{"keyword":"우장산역","region_restriction":"서울특별시"},"next_page":None}
  params=mobile.clean_filters(keyword="우장산역",region="서울")
  with patch.object(mobile,"run_search",return_value=doc) as call:
   mobile._work(job_id,params)
  result=mobile.live_search_job(job_id)
  self.assertEqual(result["status"],"completed")
  self.assertEqual(result["items"][0]["bidNo"],"R26BM01032671")
  self.assertEqual(result["db_reads"],0)
  self.assertTrue(result["live_search_verified"])
  self.assertEqual(call.call_args.kwargs["keyword"],"우장산역")
  self.assertEqual(call.call_args.kwargs["region"],"서울특별시")
  del mobile.JOBS[job_id]
 def test_blocked_live_search_does_not_fallback_to_database(self):
  job_id="d"*32
  mobile.JOBS[job_id]={"status":"queued","created_at":time.time(),"params":{},"result":None,"error":None}
  params=mobile.clean_filters(keyword="시스템")
  with patch.object(mobile,"run_search",return_value={"status":"blocked","reason":"OFFICIAL_POST_UNVERIFIED"}):
   mobile._work(job_id,params)
  result=mobile.live_search_job(job_id)
  self.assertEqual(result["status"],"blocked")
  self.assertEqual(result["items"],[])
  self.assertFalse(result["live_search_verified"])
  self.assertEqual(result["db_reads"],0)
  del mobile.JOBS[job_id]
 def test_region_requires_real_dropdown_option_code(self):
  from g2b_bid_notice_site_search import _verified_live_filter_replay,SearchBlocked
  req=SimpleNamespace(url="https://www.g2b.go.kr/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do",
   method="POST",post_data=json.dumps({"dlBidPbancLstM":{
    "dtlsPrnmNo":"","fromBidDt":"20261101","toBidDt":"20261106",
    "bidPbancNm":"","odnLmtLgdngNm":"","odnLmtLgdngCd":"",
    "dtlsPrnmNm":"","prcmBsneSeCd":"",
    "currentPage":"","recordCountPerPage":"10","startIndex":1,"endIndex":10}}))
  with self.assertRaisesRegex(SearchBlocked,"REGION_CODE_NOT_VERIFIED"):
   _verified_live_filter_replay(req,"","2026-11-01","2026-11-06",region="서울특별시")
  body=_verified_live_filter_replay(req,"","2026-11-01","2026-11-06",
    region="서울특별시",region_code="A_REAL_UI_OPTION_CODE")
  self.assertEqual(json.loads(body)["dlBidPbancLstM"]["odnLmtLgdngCd"],"A_REAL_UI_OPTION_CODE")
 def test_invalid_region_and_task_rejected(self):
  with self.assertRaisesRegex(ValueError,"UNSUPPORTED_REGION"):
   mobile.clean_filters(region="SOMEWHERE")
  with self.assertRaisesRegex(ValueError,"UNSUPPORTED_TASK"):
   mobile.clean_filters(task_type="INVALID")
if __name__=="__main__":unittest.main(verbosity=2)
