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
TITLES=["공고 직접 조회","첨부 원본 다운로드","자격·원문 조건","개찰 원본 조회",
        "경쟁 정보 분석","수행·원가 근거","가격전략 검증","Word 검토 초안","독립 최종 검증"]
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
s3=step(3,"partial",{"analysis_performed":False,"downloaded_files":3})
s4=step(4,"partial",{"source_query_verified":True,"bid_no":BID,"bid_ord":"000",
                      "matching_selected_notice":0})
s5=step(5,"blocked",{"status":"HOLD_ORIGINAL_10DIGIT_MATCH_UNVERIFIED"})
s6=step(6,"blocked",{"status":"MISSING_COMPANY_COST_EVIDENCE"})
s7=step(7,"blocked",{"status":"NO_PRICE_RECOMMENDATION"})
s8=step(8,"partial",{"draft_only":True})
s9=step(9,"partial",{"blocked_steps":3,"partial_steps":4})
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
    page.get_by_test_id("live-nine-run-all").click()
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
    inner.locator('.vue-flow__node[data-id="public9-05"] .studio-node.is-blocked').wait_for(timeout=18000)
    assert inner.locator('.vue-flow__node[data-id="public9-07"] .studio-node.is-blocked').count()==1
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
    assert "HOLD_ORIGINAL_10DIGIT_MATCH_UNVERIFIED" in page.locator(".p9-inspector").inner_text()
    page.locator('[data-public9="latest"]').click()
    assert frame.evaluate("window.__iframePersistentInstance")=="SHARED_STUDIO_UNCHANGED","Polling reloaded editor"
    assert len([e for e in errors if e.startswith("parent ")])==0,errors
    print("PUBLIC9_SHARED_STUDIO_IFRAME_MODAL_DESKTOP_PASS",json.dumps({
      "same_iframe":True,"studio_nodes":10,"stage_changes":"N01→N02→N04→9/9",
      "separate_flow":False,"blocked":3,"partial":4,"verified":2,
      "file_list":3,"source":"shared-n8n-studio Vue Flow","js_errors":[]},ensure_ascii=False),flush=True)
    page.set_viewport_size({"width":390,"height":844})
    page.wait_for_timeout(500)
    assert iframe.count()==1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 4"),"Mobile horizontal overflow"
    page.screenshot(path=str(OUT/"07_mobile_shared_studio_embedded.png"),full_page=True)
    print("PUBLIC9_SHARED_STUDIO_IFRAME_MODAL_MOBILE_PASS",flush=True)
    ctx.close();browser.close()
