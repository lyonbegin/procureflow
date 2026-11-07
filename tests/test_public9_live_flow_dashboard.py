#!/usr/bin/env python3
"""Playwright browser assertions for the REAL deployed public9 dashboard UI.

Mocks only this browser session's status API responses to deterministically
reproduce intermediate states. Never modifies server-side production records.
"""
import json,os,time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE=os.environ.get("PROCUREFLOW_UI_BASE","https://procureflow-unified-studio-candidate-production.up.railway.app")
OUT=Path("artifacts/public9-live-dashboard")
OUT.mkdir(parents=True,exist_ok=True)
URL=BASE+"/admin/index.html?section=public"
TITLES=["공고 직접 조회","첨부 원본 다운로드","자격·원문 조건","개찰 원본 조회",
 "경쟁 정보 분석","수행·원가 근거","가격전략 검증","Word 검토 초안","독립 최종 검증"]
RUN_ID="9"*32
BID="R26BK01816186"
def step(n,status,output=None):
    return {"node":"N%02d"%n,"title":TITLES[n-1],"status":status,
            "input":{"bid_no":BID,"stage":n},"output":output or {},
            "at":"2026-11-08T08:20:%02d+09:00"%n}
s1=step(1,"verified",{"notice_list":"AVAILABLE","bid_no":BID})
s2=step(2,"verified",{"downloaded":2,"text_extracted_files":2})
s3=step(3,"partial",{"company_eligibility":"NOT_VERIFIED_NO_COMPANY_ORIGINAL"})
s4=step(4,"partial",{"exact_detail10_verified":False})
s5=step(5,"blocked",{"status":"HOLD_ORIGINAL_10DIGIT_MATCH_UNVERIFIED"})
s6=step(6,"blocked",{"status":"MISSING_COMPANY_COST_EVIDENCE"})
s7=step(7,"blocked",{"status":"NO_PRICE_RECOMMENDATION"})
s8=step(8,"partial",{"draft_only":True})
s9=step(9,"partial",{"blocked_steps":3,"source_errors":0})
def state(items,active=None,finished=False):
    return {"run_id":RUN_ID,"case_bid_no":BID,"case_bid_ord":"000",
        "mode":"on_demand_live_no_database",
        "status":"completed_with_missing_evidence" if finished else "running",
        "completed_steps":len(items),"steps":items,"active_node":active,
        "active_title":TITLES[int(active[1:])-1] if active else "",
        "active_since":"2026-11-08T08:20:02+09:00" if active else None,
        "finished_at":"2026-11-08T08:20:14+09:00" if finished else None}
phases=[
 state([],active="N01"),
 state([s1],active="N02"),
 state([s1,s2,s3],active="N04"),
 state([s1,s2,s3,s4,s5,s6,s7,s8,s9],finished=True),
]
not_run={"status":"not_run","completed_steps":0,"steps":[]}
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
    ctx=browser.new_context(viewport={"width":1480,"height":1000},locale="ko-KR",timezone_id="Asia/Seoul")
    page=ctx.new_page()
    errors=[]
    page.on("pageerror",lambda e:errors.append(str(e)))
    control={"started":False,"polls":0}
    def route_get(route):
        if not control["started"]:
            payload=not_run
        else:
            pos=min(control["polls"],len(phases)-1)
            payload=phases[pos]
            control["polls"]+=1
        route.fulfill(status=200,content_type="application/json",body=json.dumps(payload,ensure_ascii=False))
    def route_post(route):
        assert route.request.post_data_json=={"mode":"auto"}
        control["started"]=True
        control["polls"]=0
        route.fulfill(status=202,content_type="application/json",body=json.dumps(phases[0],ensure_ascii=False))
    page.route("**/api/procurement/public9/live-run",route_get)
    page.route("**/api/procurement/public9/run-all",route_post)
    page.goto(URL,wait_until="domcontentloaded",timeout=45000)
    page.locator('[data-p9="flow"]').wait_for(timeout=24000)
    assert page.locator("[data-p9-node]").count()==9,"All 9 nodes must appear simultaneously"
    assert page.locator("[data-p9-state='N01']").inner_text()=="대기"
    assert page.locator('[data-p9="counter"]').inner_text()=="진행된 단계 0 / 9"
    page.screenshot(path=str(OUT/"01_waiting.png"),full_page=True)
    page.get_by_test_id("live-nine-run-all").click()
    page.wait_for_function("() => document.querySelector('[data-p9-node=N01]')?.classList.contains('p9-running')",timeout=15000)
    assert page.locator("[data-p9='headline']").inner_text().startswith("N01"),"Current node must be visible"
    page.screenshot(path=str(OUT/"02_running_n01.png"),full_page=True)
    page.wait_for_function("() => document.querySelector('[data-p9-node=N02]')?.classList.contains('p9-running')",timeout=18000)
    assert page.locator("[data-p9-state='N01']").inner_text()=="검증 완료"
    assert page.locator('[data-p9="counter"]').inner_text()=="진행된 단계 1 / 9"
    page.screenshot(path=str(OUT/"03_transition_n01_n02.png"),full_page=True)
    page.wait_for_function("() => document.querySelector('[data-p9-node=N04]')?.classList.contains('p9-running')",timeout=18000)
    assert page.locator("[data-p9-state='N03']").inner_text()=="부분 확인"
    assert page.locator(".p9-issue-list").get_by_text("N03").count()>0
    page.screenshot(path=str(OUT/"04_partial_n03_running_n04.png"),full_page=True)
    page.wait_for_function("() => document.querySelector('[data-p9=counter]')?.textContent?.includes('9 / 9')",timeout=18000)
    assert page.locator("[data-p9='global-status']").inner_text()=="증빙 미완료"
    assert page.locator("[data-p9-state='N05']").inner_text()=="차단"
    assert page.locator("[data-p9-state='N07']").inner_text()=="차단"
    assert page.locator("[data-p9-state='N09']").inner_text()=="부분 확인"
    assert page.locator(".p9-issue-row").count()==7
    assert page.locator(".p9-issue-list").get_by_text("HOLD_ORIGINAL_10DIGIT_MATCH_UNVERIFIED").count()>0
    assert page.locator("[data-p9='counter']").inner_text()=="진행된 단계 9 / 9"
    page.screenshot(path=str(OUT/"05_complete_with_blocked_stages.png"),full_page=True)
    page.locator('[data-public9="node"][data-index="4"]').first.click()
    assert page.locator(".p9-inspector h3").inner_text().startswith("노드 상세 · N05")
    assert "HOLD_ORIGINAL_10DIGIT_MATCH_UNVERIFIED" in page.locator(".p9-inspector").inner_text()
    page.locator('[data-public9="follow"]').click()
    assert page.locator('[data-public9="follow"]').get_attribute("aria-pressed")=="true"
    assert not errors,"Unexpected JavaScript exceptions: "+repr(errors)
    print("PUBLIC9_REAL_DEPLOYED_UI_DESKTOP_PASS",json.dumps({
      "nodes":9,"progress":"9/9","verified":2,"partial":4,"blocked":3,
      "in_progress_transition":"N01→N02→N04",
      "issue_count":7,"node_inspector":"N05","errors":errors},ensure_ascii=False),flush=True)
    page.set_viewport_size({"width":390,"height":844})
    page.wait_for_timeout(400)
    assert page.locator("[data-p9-node]").count()==9
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 3"),"Mobile horizontal overflow"
    page.screenshot(path=str(OUT/"06_mobile_live_flow.png"),full_page=True)
    print("PUBLIC9_REAL_DEPLOYED_UI_MOBILE_PASS",flush=True)
    ctx.close();browser.close()
