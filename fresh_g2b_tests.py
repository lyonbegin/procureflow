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

    def test_actual_unified_notice_response_parses_public_rows(self):
        from g2b_bid_notice_site_search import _response_records
        body={"ErrorCode":0,"result":[
            {"untyBidPbancNo":"R26BK01787028","untyBidPbancOrd":"000",
             "bidPbancNm":"공식 테스트 공고명","oderInstUntyGrpNm":"공식 발주기관",
             "pbancPstgDt":"20261027"}]}
        rows,total=_response_records(body)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["bid_no"],"R26BK01787028")
        self.assertEqual(rows[0]["agency"],"공식 발주기관")
        self.assertEqual(rows[0]["direct_category_codes"],[])

    def test_public_filtered_candidate_must_remain_category_unverified(self):
        candidate={"bid_no":"R26BK01787028","bid_ord":"000",
            "direct_category_codes":[],"raw":{"untyBidPbancNo":"R26BK01787028"},
            "title":"공식 검색 결과","agency":"원본 기관","posted_on":"20261027"}
        fake={"status":"partial_filtered_result","search_request_verified":True,
              "matched_explicit_detail10":[],
              "pending_original_detail10_verification":[candidate]}
        with patch.object(site,"run_search",return_value=fake):
            _,_,rows=site.search_one("8111159901","2026-10-01","2026-10-31")
        self.assertEqual(len(rows),1)
        self.assertFalse(rows[0]["original_category_evidence"])
        self.assertTrue(rows[0]["official_filter_verified"])
        self.assertEqual(rows[0]["posted_on"],"2026-10-27")

    def test_server_rendered_public_notice_page_shows_real_db_items(self):
        from fresh_g2b_api import live_notices
        fake=[{"bid_no":"R26BM01022088","bid_ord":"000",
               "title":"원격교육연수 이수자 정보관리시스템 고도화",
               "agency":"조달청 대구지방조달청","category_verified":False,
               "posted_on":None}]
        with patch.object(store,"recent_notices",return_value=fake):
            page=live_notices()
        html=page.body.decode("utf-8")
        self.assertIn("신규 DB 1건",html)
        self.assertIn("R26BM01022088",html)
        self.assertIn("원격교육연수",html)
        self.assertIn("상세 분류 확인 대기",html)

    def test_unfiltered_latest_search_requires_real_date_bound_post(self):
        import json
        from g2b_bid_notice_site_search import request_has_filter
        post={"dlBidPbancLstM":{"dtlsPrnmNo":"",
              "fromBidDt":"20261005","toBidDt":"20261105"}}
        payload=json.dumps(post)
        self.assertTrue(request_has_filter(payload,"","2026-10-05","2026-11-05"))
        self.assertFalse(request_has_filter(payload,"","2026-10-04","2026-11-05"))
        self.assertFalse(request_has_filter(json.dumps({"anything":post["dlBidPbancLstM"]}),
                           "","2026-10-05","2026-11-05"))

    def test_latest_default_is_past_one_calendar_month(self):
        from fresh_g2b_api import latest_default_period
        from datetime import date
        a,b=latest_default_period()
        first,last=date.fromisoformat(a),date.fromisoformat(b)
        self.assertLessEqual((last-first).days,31)
        self.assertGreaterEqual((last-first).days,28)

    def test_latest_one_job_stops_after_first_new(self):
        import fresh_g2b_api as api
        fake={"status":"partial_filtered_result","search_request_verified":True,
              "returned_bid_ids":10,"response_sha":"hash",
              "live_search_endpoint":"/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do"}
        new={"saved":1,"checked":3,"notice":"R26BM01022088-000"}
        with patch.object(api.store,"change_job") as change, \
             patch.object(api.store,"attempt"), \
             patch.object(api.store,"save_first_unseen",return_value=new) as save, \
             patch.object(api,"search_one",return_value=({"detail10":"","start":"2026-11-01","end":"2026-11-05","page":1},fake,[{"bid_no":"R26BM01022088"}])) as search:
            api._run(999,"latest_one",{"first":"2026-10-05","last":"2026-11-05"})
        search.assert_called_once()
        save.assert_called_once()
        self.assertEqual(change.call_args.kwargs["saved"],1)

    def test_latest_transient_g2b_modal_retries_then_one_save(self):
        import fresh_g2b_api as api
        fake={"status":"partial_filtered_result","search_request_verified":True,
              "returned_bid_ids":5,"response_sha":"hash",
              "live_search_endpoint":"/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do"}
        good=({"detail10":"","start":"2026-11-01","end":"2026-11-05","page":1},
              fake,[{"bid_no":"R26BM01022088"}])
        with patch.object(api.store,"change_job") as change, \
             patch.object(api.store,"attempt"), \
             patch.object(api.store,"save_first_unseen",
                 return_value={"saved":1,"checked":2,"notice":"R26BM01022088-000"}), \
             patch.object(api,"search_one",side_effect=[
                 site.SourceBlocked("OFFICIAL_BID_SEARCH_UNVERIFIED_BID_NOTICE_10DIGIT_NOT_IN_ACTUAL_POST_REQUEST"),
                 good]) as search:
            api._run(1001,"latest_one",{"first":"2026-10-05","last":"2026-11-05"})
        self.assertEqual(search.call_count,2)
        self.assertEqual(change.call_args.kwargs["saved"],1)

    def test_native_post_click_creates_latest_job_redirect(self):
        import fresh_g2b_api as api
        from fastapi import BackgroundTasks
        background=BackgroundTasks()
        with patch.object(api,"_create_job_or_409",return_value=913) as create:
            response=api.run_next_from_browser(background)
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers.get("location"),"/run-status/913")
        self.assertEqual(len(background.tasks),1)
        self.assertEqual(create.call_args.args[0],"latest_one")
        self.assertEqual(create.call_args.args[1]["limit_new"],1)

    def test_native_status_page_shows_new_record_and_next_button(self):
        import fresh_g2b_api as api
        fake={"id":913,"kind":"latest_one","status":"completed",
              "rows_seen":10,"rows_saved":1,"error":"",
              "events":[{"status":"new_notice_saved",
                         "bid_no":"R26BM01032440","bid_ord":"000"}]}
        with patch.object(api.store,"job_detail",return_value=fake), \
             patch.object(api.store,"notice_detail",
                 return_value={"notice":{"title":"황새울보도교 보수공사"}}):
            response=api.run_status(913)
        html=response.body.decode("utf-8")
        self.assertIn("황새울보도교 보수공사",html)
        self.assertIn("action='/run-next'",html)
        self.assertIn("신규 공고 1건 저장 완료",html)

    def test_initial_html_shows_only_latest_one_saved_notice(self):
        import fresh_g2b_api as api
        item={"bid_no":"R26BM01032440","bid_ord":"000",
              "title":"황새울보도교 보수공사",
              "agency":"경기도 성남시","category_verified":False}
        with patch.object(store,"recent_notices",return_value=[item]) as getter:
            html=api.home().body.decode("utf-8")
        getter.assert_called_once_with(1)
        self.assertIn("황새울보도교 보수공사",html)
        self.assertIn("R26BM01032440",html)
        self.assertIn('id="noticeCount">1</strong>',html)

    def test_latest_ui_is_one_click_not_manual_bulk(self):
        source=(Path(__file__).parent/"fresh_g2b.html").read_text()
        self.assertIn('method="post" action="/run-next"',source)
        self.assertIn("다음 신규 공고 1건",source)
        self.assertNotIn('id="code"',source)
        self.assertNotIn('id="first"',source)

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
        self.assertIn("action=\"/run-next\"",html)
        self.assertIn("기존 229건",html)  # explicitly says NOT imported

    def test_fresh_only_env_var(self):
        self.assertIn("FRESH_DATABASE_URL",
            (Path(__file__).parent/"fresh_g2b_store.py").read_text())


if __name__=="__main__":unittest.main(verbosity=2)
