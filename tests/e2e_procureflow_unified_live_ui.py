#!/usr/bin/env python3
"""Live Chromium E2E: only isolated browser cookie / fictional fixture actions.

The explicit user click triggers bounded, live G2B collection but no bid. Fail closed when any UI or
read-only API assertion fails. Store screenshots and JSON trace in artifact.
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import json, traceback, sys, time, os

BASE=os.environ.get("PROCUREFLOW_UI_BASE","https://procureflow-unified-studio-candidate-production.up.railway.app")
OUT=Path("artifacts/unified-live-ui")
OUT.mkdir(parents=True, exist_ok=True)
results=[]
def record(name, fn):
    start=time.monotonic()
    try:
        detail=fn() or {}
        results.append(dict(test=name,status="PASS",seconds=round(time.monotonic()-start,2),detail=detail))
        print("PASS",name,detail,flush=True)
    except Exception as exc:
        results.append(dict(test=name,status="FAIL",seconds=round(time.monotonic()-start,2),error=str(exc),traceback=traceback.format_exc()[-2500:]))
        print("FAIL",name,str(exc),flush=True)
        try:page.screenshot(path=str(OUT / (name.replace(" ","_")+".png")),full_page=True)
        except Exception:pass
def require(condition,message):
    if not condition:raise AssertionError(message)
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True,args=["--no-sandbox"])
    context=browser.new_context(viewport={"width":1600,"height":1000},locale="ko-KR")
    page=context.new_page()
    errors=[]
    page.on("pageerror",lambda exc:errors.append(str(exc)[:350]))
    def test_actual_graph():
        page.goto(BASE+"/?workflow=operations%2FPF00-public-nine-real.json",wait_until="domcontentloaded",timeout=45000)
        selected=page.locator('[data-stock-flow="operations/PF00-public-nine-real.json"]')
        selected.wait_for(timeout=25000)
        require("active" in (selected.get_attribute("class") or ""), "Real 9-stage graph URL did not select the requested workflow")
        page.locator('.vue-flow__node[data-id="public9-01"]').wait_for(timeout=20000)
        require(page.locator(".vue-flow__node").count()==10,"Expected original nine business nodes + trigger")
        require("공통 편집기" in page.locator("body").inner_text(),"Shared Studio project branding absent")
        page.screenshot(path=str(OUT/"01_real_9_stage.png"),full_page=True)
        return {"node_count":page.locator(".vue-flow__node").count(),"selected":"PF00-public-nine-real"}
    record("actual_9_node_url",test_actual_graph)
    def scenario_mock():
        page.locator('[data-stock-flow="scenarios/S01.json"]').click(timeout=20000)
        page.get_by_role("button",name="활동 기록").click()
        page.get_by_test_id("mock-prepare").click(timeout=20000)
        page.get_by_test_id("mock-next").click(timeout=15000)
        page.get_by_test_id("mock-run-all").click(timeout=15000)
        progress=page.get_by_test_id("mock-progress").inner_text(timeout=15000)
        require("completed" in progress.lower(),f"Mock S01 not complete: {progress}")
        page.screenshot(path=str(OUT/"02_fixture_run.png"),full_page=True)
        return {"progress":progress[-200:],"mode":"fixture_only"}
    record("scenario_S01_interactive_mock",scenario_mock)
    def safe_node_controls():
        page.get_by_role("button",name="설정",exact=True).click()
        before=page.locator(".vue-flow__node").count()
        page.locator('[data-node-kind="code"]').first.click(timeout=15000)
        page.wait_for_timeout(700)
        after=page.locator(".vue-flow__node").count()
        require(after==before+1,f"Adding code node did not increment count {before} -> {after}")
        # Use isolated browser sid; never edit an existing production workflow.
        workflow_input=page.get_by_label("워크플로 이름")
        workflow_input.fill("UI E2E S01 안전 테스트")
        workflow_input.press("Tab")
        page.get_by_role("button",name="서버 저장").click(timeout=15000)
        page.wait_for_function("() => document.querySelector('.bottom-status')?.textContent?.includes('서버 DB 저장 성공')",timeout=25000)
        persisted=context.request.get(BASE+"/api/studio/workflows/scenarios/S01.json",timeout=20000).json()
        server_nodes=len(persisted.get("workflow",{}).get("nodes",[]))
        require(server_nodes==after,f"SQLite persisted {server_nodes} nodes, expected {after}; server save regression")
        page.reload(wait_until="domcontentloaded")
        page.locator('[data-stock-flow="scenarios/S01.json"]').wait_for(timeout=20000)
        page.wait_for_function("(count) => document.querySelectorAll('.vue-flow__node').length === count",arg=after,timeout=30000)
        require(page.locator(".vue-flow__node").count()==after,"VueFlow reload failed to render persisted node")
        page.screenshot(path=str(OUT/"03_saved_draft.png"),full_page=True)
        return {"before":before,"after":after,"saved_session_only":True}
    record("node_add_and_sqlite_reopen",safe_node_controls)
    def run_fixture_python():
        with page.expect_response(lambda response: "/api/studio/workflows/operations/A01-public-win-strategy.json/versions" in response.url, timeout=30000):
            page.locator('[data-stock-flow="operations/A01-public-win-strategy.json"]').click(timeout=20000)
        page.locator('.vue-flow__node[data-id="public-N01"]').wait_for(timeout=20000)
        page.locator('.vue-flow__node[data-id="public-N01"]').click(force=True,timeout=15000)
        page.get_by_test_id("execute-node01").wait_for(timeout=18000)
        page.get_by_test_id("execute-node01").click(timeout=25000)
        page.get_by_test_id("node01-result").wait_for(timeout=25000)
        result=page.get_by_test_id("node01-result").inner_text()
        require("SUCCESS" in result, "Fixture Python N01 did not succeed: "+result[:350])
        out=page.get_by_test_id("node01-output").inner_text()
        require("fictional_test_fixture" in out,"Fixture provenance not found; abort")
        page.screenshot(path=str(OUT/"04_python_fixture_node.png"),full_page=True)
        return {"status":"SUCCESS","evidence":"fictional_test_fixture"}
    record("A01_mock_python_N01_and_SQLite",run_fixture_python)
    def test_live_nine_no_worker_no_database():
        page.goto(BASE+"/admin/index.html?section=public",wait_until="domcontentloaded",timeout=45000)
        button=page.get_by_test_id("live-nine-run-all")
        button.wait_for(timeout=20000)
        require(page.locator("#p9-token").count()==0,"Token prompt unexpectedly present")
        require("전체 순차 실행" in button.inner_text(),"One-click 9-stage button missing")
        # Never run official G2B collection automatically on git push/PR CI.
        # One-shot external test requires an explicit manual workflow input.
        if os.environ.get("PROCUREFLOW_ENABLE_ONE_SHOT_OFFICIAL_FETCH")!="1":
            page.screenshot(path=str(OUT/"05_live_button_no_auto_collection.png"),full_page=True)
            return {"live_button":True,"no_admin_token":True,
                    "official_fetch":"NOT_INVOKED_IN_AUTOMATIC_CI",
                    "worker_calls":0}
        seen=[]
        def track_request(req):
            if "/api/g2b/public/" in req.url:
                seen.append(req.url)
        page.on("request",track_request)
        button.click(timeout=20000)
        page.wait_for_function("() => document.body.innerText.includes('진행 9/9 단계')",timeout=140000)
        response=context.request.get(BASE+"/api/procurement/public9/live-run",timeout=30000)
        require(response.status==200,"Live-run endpoint HTTP "+str(response.status))
        result=response.json()
        require(result.get("mode")=="on_demand_live_no_database","Wrong execution mode")
        require(len(result.get("steps",[]))==9,"Nine sequential stages not recorded")
        require([x["node"] for x in result["steps"]]==["N%02d"%x for x in range(1,10)],"Wrong stage order")
        require(result.get("db_reads")==0 and result.get("worker_calls")==0 and result.get("bid_submitted") is False,
                "Unexpected DB, Worker or bidding side effect")
        require(not seen,"Browser made legacy database requests during live tender test: "+str(seen[:3]))
        status={s["node"]:s["status"] for s in result["steps"]}
        n01=next(x for x in result["steps"] if x["node"]=="N01")
        n02=next(x for x in result["steps"] if x["node"]=="N02")
        n04=next(x for x in result["steps"] if x["node"]=="N04")
        print("LIVE_OFFICIAL_STAGE_DIAGNOSTICS",json.dumps({
          "N01":n01["output"],
          "N02_downloaded":n02["output"].get("downloaded"),
          "N02_files":n02["output"].get("files",[]),
          "N04":n04["output"]},ensure_ascii=False)[:5000],flush=True)
        page.screenshot(path=str(OUT/"05_real_live_g2b_nine.png"),full_page=True)
        # A successful nine-stage orchestration is not automatically proof that
        # the official site returned data; report exact source errors separately.
        return {"status":result["status"],"stages":status,
                "official_verified_count":sum(x["status"]=="verified" for x in result["steps"]),
                "no_token":True,"db_reads":0,"worker_calls":0}
    record("on_demand_live_9_steps_no_worker",test_live_nine_no_worker_no_database)
    record("javascript_runtime_errors",lambda: (require(not errors,f"JavaScript page exceptions: {errors[:5]}"),{"page_errors":[]})[1])
    (OUT/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf8")
    context.close()
    browser.close()
print("LIVE_UI_SUMMARY",json.dumps({"passed":sum(x["status"]=="PASS" for x in results),"failed":sum(x["status"]=="FAIL" for x in results)},ensure_ascii=False),flush=True)
sys.exit(1 if any(x["status"]=="FAIL" for x in results) else 0)
