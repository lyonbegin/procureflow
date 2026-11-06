#!/usr/bin/env python3
"""Live Chromium E2E: only isolated browser cookie / fictional fixture actions.

Never triggers G2B collection or actual bid. Fail closed when any UI or
read-only API assertion fails. Store screenshots and JSON trace in artifact.
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import json, traceback, sys, time

BASE="https://procureflow-unified-studio-candidate-production.up.railway.app"
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
    def read_only_live_api():
        path="/api/procurement/public9/stage1?q=&status=all&limit=30&offset=0&selected_bid_no=R26BK01787028"
        r=context.request.get(BASE+path,timeout=35000)
        result=r.json()
        require(r.status==200,f"Read-only PostgreSQL stage1 returned HTTP {r.status}: {str(result)[:350]}")
        require(result.get("source")=="actual_procureflow_postgresql_g2b_notices","PostgreSQL source provenance missing")
        require(result.get("crawler_executed") is False and result.get("worker_executed") is False,"Read-only stage1 must never launch worker")
        require(len(result.get("nodes",[]))==3,"Expected three read-only stage1 node inspections")
        return {"http":r.status,"source":result.get("source"),"node_count":len(result["nodes"])}
    record("read_only_real_postgres_stage1",read_only_live_api)
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
        page.wait_for_timeout(1200)
        page.reload(wait_until="domcontentloaded")
        page.locator('[data-stock-flow="scenarios/S01.json"]').wait_for(timeout=20000)
        require(page.locator(".vue-flow__node").count()==after,"Browser-specific SQLite save/reload lost newly created node")
        page.screenshot(path=str(OUT/"03_saved_draft.png"),full_page=True)
        return {"before":before,"after":after,"saved_session_only":True}
    record("node_add_and_sqlite_reopen",safe_node_controls)
    def run_fixture_python():
        page.locator('[data-stock-flow="operations/A01-public-win-strategy.json"]').click(timeout=20000)
        page.locator('.vue-flow__node[data-id="public-N01"]').wait_for(timeout=20000)
        page.locator('.vue-flow__node[data-id="public-N01"]').click(force=True,timeout=15000)
        page.get_by_test_id("execute-node01").wait_for(timeout=15000)
        page.get_by_test_id("execute-node01").click(timeout=25000)
        page.get_by_test_id("node01-result").wait_for(timeout=25000)
        result=page.get_by_test_id("node01-result").inner_text()
        require("SUCCESS" in result, "Fixture Python N01 did not succeed: "+result[:350])
        out=page.get_by_test_id("node01-output").inner_text()
        require("fictional_test_fixture" in out,"Fixture provenance not found; abort")
        page.screenshot(path=str(OUT/"04_python_fixture_node.png"),full_page=True)
        return {"status":"SUCCESS","evidence":"fictional_test_fixture"}
    record("A01_mock_python_N01_and_SQLite",run_fixture_python)
    record("javascript_runtime_errors",lambda: (require(not errors,f"JavaScript page exceptions: {errors[:5]}"),{"page_errors":[]})[1])
    (OUT/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf8")
    context.close()
    browser.close()
print("LIVE_UI_SUMMARY",json.dumps({"passed":sum(x["status"]=="PASS" for x in results),"failed":sum(x["status"]=="FAIL" for x in results)},ensure_ascii=False),flush=True)
sys.exit(1 if any(x["status"]=="FAIL" for x in results) else 0)
