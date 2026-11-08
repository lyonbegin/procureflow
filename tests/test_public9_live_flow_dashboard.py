#!/usr/bin/env python3
"""Real deployed shared Vue Flow iframe + same-frame fullscreen modal.

Only browser-scoped API interceptions for deterministic N01-N09 transitions.
Never writes synthetic stages or completion checkpoints to Railway.
"""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE=os.environ.get("PROCUREFLOW_UI_BASE","https://procureflow-unified-studio-candidate-production.up.railway.app")
OUT=Path("artifacts/public9-live-dashboard")
OUT.mkdir(parents=True,exist_ok=True)
URL=BASE+"/admin/index.html?section=public"
TITLES=["최신 공고 수집·선정","공고·첨부 원본 다운로드","공고 공식 속성 수집","동일 세부품명 10년 공고 수집",
        "과거 개찰·낙찰 원본 수집","공급·인력 근거자료 수집","원가·가격 근거자료 수집","전체 수집자료 통합·AI 전달","AI 종합 분석·최종 평가"]
BID="R26BK01816186"
RUN="8"*32
def step(n,status,out=None):
    return {"node":"N%02d"%n,"title":TITLES[n-1],"status":status,
            "input":{"bid_no":BID},"output":out or {},
            "at":"2026-11-08T09:20:%02d+09:00"%n}
s1=step(1,"verified",{"notice_list":"AVAILABLE","bid_no":BID})
s2=step(2,"verified",{"file_count":3,"downloaded":3,
    "official_attachment_inventory_complete":True,"analysis_performed":False,
    "storage_folder":"/data/n01/bids/R26BK01816186-000/attachments",
    "manifest_path":"/data/n01/bids/R26BK01816186-000/attachment_manifest.json",
    "files":[{"file_seq":i,"original_filename":name,"saved":True,
              "file_type":name.split(".")[-1],
              "size_bytes":12345,
              "saved_path":"/data/n01/bids/R26BK01816186-000/attachments/00%d__%s"%(i,name)}
             for i,name in enumerate(["별지서식.hwp","입찰지침서.pdf","입찰공고.pdf"],1)]})
s3=step(3,"partial",{"detail10_verified":False,"detail10":None,
    "gaps":["official_10_digit_detail_class_not_verified"],
    "business_evaluation_performed":False})
s4=step(4,"partial",{"requested_detail10":None,"periods_checked":[],
    "verified_record_count":0,"gaps":["exact_10_digit_class_required_for_10_year_search"],
    "business_evaluation_performed":False})
s5=step(5,"partial",{"opening_records":[],
    "gaps":["no_exact_10_digit_historical_candidates"],
    "business_evaluation_performed":False})
s6=step(6,"partial",{"supplier_quotation_original_count":0,
    "gaps":["independent_supplier_quotation_source_not_connected"],
    "business_evaluation_performed":False})
s7=step(7,"partial",{"source_amounts":[{"field":"alotBgtAmt","raw":"123000000"}],
    "recommended_bid":None,"business_evaluation_performed":False})
s8=step(8,"partial",{"source_originals":3,"handoff_bundle":{"originals":[1,2,3]},
    "ai_analysis_performed":False,"word_draft_generated":False})
s9=step(9,"partial",{"ai_evaluation_performed":False,
    "reason":"N09_AI_API_NOT_CONFIGURED","human_review_required":True})
def state(items,active=None,done=False):
    return {"run_id":RUN,"case_bid_no":BID,"case_bid_ord":"000",
      "status":"completed_with_missing_evidence" if done else "running",
      "mode":"on_demand_live_no_database","completed_steps":len(items),
      "steps":items,"active_node":active,
      "active_title":TITLES[int(active[1:])-1] if active else None,
      "active_since":"2026-11-08T09:20:02+09:00" if active else None,
      "finished_at":"2026-11-08T09:20:22+09:00" if done else None}
phases=[state([],active="N01"),state([s1],active="N02"),
        state([s1,s2,s3],active="N04"),
        state([s1,s2,s3,s4,s5,s6,s7,s8,s9],done=True)]
idle={"status":"not_run","completed_steps":0,"steps":[]}

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul",
                            viewport={"width":1500,"height":1040})
    page=ctx.new_page()
    errors=[]
    page.on("pageerror",lambda exc:errors.append("parent "+str(exc)))
    page.on("framenavigated",lambda frame:errors.append("frame_navigated "+frame.url)
            if getattr(page,"_record_navigation",False) and "public9_embed" in frame.url else None)
    flow={"started":False,"phase":0,"post_count":0}
    def get(route):
        payload=phases[flow["phase"]] if flow["started"] else idle
        route.fulfill(status=200,content_type="application/json",
                      body=json.dumps(payload,ensure_ascii=False))
    def post(route):
        assert route.request.post_data_json=={"mode":"auto"}
        flow["started"]=True;flow["phase"]=0;flow["post_count"]+=1
        route.fulfill(status=202,content_type="application/json",
                      body=json.dumps(phases[0],ensure_ascii=False))
    page.route("**/api/procurement/public9/live-run",get)
    page.route("**/api/procurement/public9/run-all",post)
    page.goto(URL,wait_until="domcontentloaded",timeout=45000)
    iframe=page.locator("#p9-shared-studio-frame")
    iframe.wait_for(timeout=25000)
    assert iframe.count()==1,"Must embed ONE shared Studio instance"
    assert iframe.get_attribute("src").startswith("/?workflow=operations%2FPF00-public-nine-real.json"),iframe.get_attribute("src")
    assert page.locator("[data-p9=flow]").count()==0,"Obsolete duplicate 3x3 execution flow must be removed"
    inner=page.frame_locator("#p9-shared-studio-frame")
    inner.locator('.vue-flow__node[data-id="public9-01"]').wait_for(timeout=35000)
    assert inner.locator(".vue-flow__node").count()==10,"Original shared workflow 9 stages + trigger must remain"
    assert "공통 편집기" in inner.locator("body").inner_text(),"NOT the actual common Studio"
    page.screenshot(path=str(OUT/"01_shared_studio_embedded_waiting.png"),full_page=True)
    # Identity persists across parent status refreshes and full-screen toggle.
    frame=iframe.element_handle().content_frame()
    frame.evaluate("window.__iframePersistentInstance='SHARED_STUDIO_UNCHANGED'")
    main_start=page.get_by_test_id("live-nine-run-all")
    top_start=page.get_by_test_id("live-nine-run-top")
    assert main_start.count()==1 and top_start.count()==1,"Start must be above the Studio and in its toolbar"
    assert main_start.is_visible() and top_start.is_visible()
    assert top_start.is_enabled(),"New start button must be clickable"
    assert page.locator('.p9-controls').bounding_box()['y'] < iframe.bounding_box()['y'], "Start controls must precede large iframe"
    top_start.click()
    inner.locator('.vue-flow__node[data-id="public9-01"] .studio-node.is-running').wait_for(timeout=18000)
    assert flow["post_count"]==1,"Admin run button must invoke single existing pipeline"
    assert page.locator('[data-p9="counter"]').inner_text()=="진행된 단계 0 / 9"
    assert "실행 중" in inner.locator('.vue-flow__node[data-id="public9-01"] .node-footer').inner_text()
    page.screenshot(path=str(OUT/"02_n01_running_inside_original_canvas.png"),full_page=True)
    flow["phase"]=1
    page.locator('[data-public9="latest"]').click()
    inner.locator('.vue-flow__node[data-id="public9-02"] .studio-node.is-running').wait_for(timeout=18000)
    assert inner.locator('.vue-flow__node[data-id="public9-01"] .studio-node.is-success').count()==1
    assert page.locator("[data-p9=counter]").inner_text()=="진행된 단계 1 / 9"
    page.screenshot(path=str(OUT/"03_n01_n02_shared_canvas_transition.png"),full_page=True)
    flow["phase"]=2
    page.locator('[data-public9="latest"]').click()
    inner.locator('.vue-flow__node[data-id="public9-04"] .studio-node.is-running').wait_for(timeout=18000)
    inner.locator('.vue-flow__node[data-id="public9-03"] .studio-node.is-partial').wait_for(timeout=18000)
    assert page.locator(".p9-inventory-item").count()==3
    page.screenshot(path=str(OUT/"04_n03_partial_n04_running_original_canvas.png"),full_page=True)
    flow["phase"]=3
    page.locator('[data-public9="latest"]').click()
    inner.locator('.vue-flow__node[data-id="public9-05"] .studio-node.is-partial').wait_for(timeout=18000)
    assert inner.locator('.vue-flow__node[data-id="public9-07"] .studio-node.is-partial').count()==1
    assert inner.locator('.vue-flow__node[data-id="public9-09"] .studio-node.is-partial').count()==1
    assert page.locator("[data-p9=counter]").inner_text()=="진행된 단계 9 / 9"
    assert page.locator(".p9-issue-row").count()==7
    page.screenshot(path=str(OUT/"05_mixed_errors_in_original_shared_editor.png"),full_page=True)
    page.locator('[data-public9="expand"]').click()
    assert page.locator("#p9-shared-studio-panel.p9-studio-fullscreen").count()==1
    assert page.locator("#p9-shared-studio-frame").count()==1
    assert frame.evaluate("window.__iframePersistentInstance")=="SHARED_STUDIO_UNCHANGED","Fullscreen reloaded editor"
    page.screenshot(path=str(OUT/"06_fullscreen_same_shared_canvas.png"),full_page=True)
    page.locator('[data-public9="expand"]').click()
    assert page.locator("#p9-shared-studio-panel.p9-studio-fullscreen").count()==0
    assert frame.evaluate("window.__iframePersistentInstance")=="SHARED_STUDIO_UNCHANGED","Closing fullscreen reloaded editor"
    # Trigger editor selection -> parent INPUT/OUTPUT inspector.
    # Focus the real VueFlow node first. Clicking the node wrapper midpoint
    # can hit the inner toolbar, which intentionally stops propagation.
    page.evaluate("document.getElementById('p9-shared-studio-frame').contentWindow.postMessage({type:'procureflow:focus-node',node:'N05'},location.origin)")
    page.wait_for_timeout(500)
    inner.locator('.vue-flow__node[data-id="public9-05"] .node-header').click(timeout=12000)
    page.locator(".p9-inspector h3").get_by_text("N05").wait_for(timeout=15000)
    assert "no_exact_10_digit_historical_candidates" in page.locator(".p9-inspector").inner_text()
    page.locator('[data-public9="latest"]').click()
    assert frame.evaluate("window.__iframePersistentInstance")=="SHARED_STUDIO_UNCHANGED","Polling reloaded editor"
    assert len([e for e in errors if e.startswith("parent ")])==0,errors
    print("PUBLIC9_SHARED_STUDIO_IFRAME_MODAL_DESKTOP_PASS",json.dumps({
      "same_iframe":True,"studio_nodes":10,"stage_changes":"N01→N02→N04→9/9",
      "separate_flow":False,"blocked":0,"partial":7,"verified":2,
      "file_list":3,"source":"shared-n8n-studio Vue Flow","js_errors":[]},ensure_ascii=False),flush=True)
    page.set_viewport_size({"width":390,"height":844})
    page.wait_for_timeout(500)
    assert iframe.count()==1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 4"),"Mobile horizontal overflow"
    page.screenshot(path=str(OUT/"07_mobile_shared_studio_embedded.png"),full_page=True)
    print("PUBLIC9_SHARED_STUDIO_IFRAME_MODAL_MOBILE_PASS",flush=True)
    # Regression: no dispatch token must NOT hide or disable test initiation.
    # The backend must give an honest error, which must be visible above iframe.
    page2=ctx.new_page()
    disconnected={"status":"not_run","mode":"github_actions_nine_nodes",
                  "dispatch_ready":False,"completed_steps":0,"steps":[]}
    page2.route("**/api/procurement/public9/live-run",
      lambda route:route.fulfill(status=200,content_type="application/json",
          body=json.dumps(disconnected,ensure_ascii=False)))
    dispatched={"count":0}
    def reject(route):
        dispatched["count"]+=1
        route.fulfill(status=503,content_type="application/json",body=json.dumps({
            "error":"GITHUB_DISPATCH_TOKEN_NOT_CONFIGURED_NO_RAILWAY_FALLBACK"}))
    page2.route("**/api/procurement/public9/run-all",reject)
    page2.goto(URL,wait_until="domcontentloaded",timeout=45000)
    top=page2.get_by_test_id("live-nine-run-top")
    top.wait_for(state="visible",timeout=20000)
    assert top.is_enabled(),"Do not disable the start button because auth is absent"
    assert "9단계 실행 시작" in top.inner_text()
    top.click()
    page2.locator('[data-p9-start-feedback]').get_by_text(
        "PROCUREFLOW_GITHUB_DISPATCH_TOKEN",exact=False).wait_for(timeout=16000)
    assert dispatched["count"]==1,"Start MUST send one real attempt; no staged success"
    assert page2.get_by_test_id("live-nine-run-all").is_enabled()
    assert "running" not in page2.locator('[data-p9="global-status"]').get_attribute("class")
    page2.screenshot(path=str(OUT/"08_missing_auth_start_visible_error.png"),full_page=True)
    print("PUBLIC9_START_BUTTON_ALWAYS_VISIBLE_AUTH_FAILURE_HONEST_PASS",flush=True)
    ctx.close();browser.close()
