"""Read-only browser UAT on actual Railway deployment.

No privileged session and NO production writes. Screenshots/JSON evidence
are saved as CI artifacts. Authentication-required cases are BLOCKED, not PASSED.
Run: python scripts/flow_real_user_browser_uat.py
Requires: pip install playwright; python -m playwright install chromium
"""
import json
import os
import pathlib
import traceback
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

BASE = os.getenv("PROCUREFLOW_LIVE_URL", "https://procureflow-api-production.up.railway.app/flow")
OUT = pathlib.Path(os.getenv("PROCUREFLOW_UAT_OUTPUT", "uat-results"))
OUT.mkdir(parents=True, exist_ok=True)
results = {}
errors = []
def result(case, status, detail, screen=None):
    results[case] = {"status": status, "detail": str(detail)[:1200],
                     "screenshot": str(screen) if screen else None}
    print(f"{case} {status}: {detail}", flush=True)
def shot(page, name):
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True, timeout=20000)
    return path

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width":1440,"height":900}, device_scale_factor=1)
    page.on("pageerror", lambda e: errors.append(str(e)[:1000]))
    page.on("console", lambda message: errors.append("console: "+message.text[:1000]) if message.type == "error" else None)
    try:
        response = page.goto(BASE, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2400)
        status = response.status if response else -1
        has_topbar = page.locator(".flow-workspace-topbar").count() > 0
        has_canvas = page.locator(".flow-workspace-canvas").count() > 0
        screenshot = shot(page, "01-live-flow-1440")
        result("U01","PASS" if status==200 and has_topbar and has_canvas else "FAIL",
               f"HTTP={status}, header={has_topbar}, canvas={has_canvas}, title={page.title()}", screenshot)
        if has_canvas:
            stage = page.locator(".flow-workspace-stage").bounding_box()
            view_h = page.viewport_size["height"]
            fraction = (stage["height"]/view_h) if stage else 0
            legacy = page.locator(".side-rail").count()
            result("U02","PASS" if fraction>.75 and not legacy else "FAIL",
                   f"stage_height={stage['height'] if stage else 'none'}, viewport={view_h}, fraction={fraction:.2f}, old_sidebar_count={legacy}")
        else:
            result("U02","FAIL","Workflow workspace canvas not loaded")
        button=page.get_by_role("button",name="편집·디버그")
        if button.count():
            button.click(timeout=10000)
            page.wait_for_timeout(1200)
        is_editor=page.locator(".dag-studio").count()>0
        new_button=page.get_by_role("button",name="새 워크플로").count()>0
        result("U03","PASS" if is_editor and new_button else "FAIL",
               f"editor_open={is_editor}, new_workflow_button={new_button}",shot(page,"03-edit-designer"))
        if is_editor:
            no_submit_controls=page.get_by_text("입찰 제출",exact=True).count()==0
            result("U23","PASS" if no_submit_controls else "FAIL",
                   "Unauthorized browser; did not attempt to create production workflows, submit bids or upload files.")
            # Test unprivileged admin boundary via harmless read-only route, no write calls.
            auth_requests=[]
            def auth_watch(request):
                if "/workflow/designs" in request.url:
                    auth_requests.append((request.method,request.url.split("?")[0]))
            page.on("request",auth_watch)
            box=page.locator(".dag-panel-scroll input[type=password]")
            if box.count():
                box.fill("invalid-uat-token-NO-WRITE")
                page.wait_for_timeout(900)
                result("U23","PASS",f"Token input is type=password; design read attempted={auth_requests}; no write attempted")
            # Search functionality and preview buttons; not a DB write
            search=page.locator(".dag-palette input[type=search]")
            if search.count():
                search.fill("50")
                page.wait_for_timeout(300)
                visible=page.locator(".dag-palette-items button").count()
                result("U06","PASS" if visible>0 else "FAIL",f"Search '50' yields {visible} palette options")
            else:
                result("U06","FAIL","Function library search input missing")
            result("U04","BLOCKED","Authentication required for actual workflow creation; did not mutate production")
            for case in ["U05","U07","U08","U09","U10","U11","U12","U17","U18","U19","U20","U21","U24"]:
                result(case,"BLOCKED","Requires authenticated sandbox or authenticated browser; real production mutation not attempted")
            shot(page,"03-designer-after-search")
        else:
            result("U06","FAIL","Designer not accessible; cannot search 104 functions")
            result("U23","NOT_RUN","Designer not loaded")
        if is_editor:
            # Check mobile viewport on existing page without refreshing token into persistent storage
            page.set_viewport_size({"width":390,"height":844})
            page.wait_for_timeout(500)
            mobile = shot(page,"22-mobile-390")
            body_width=page.evaluate("document.body.scrollWidth")
            result("U22","PASS" if body_width<=420 else "FAIL",
                   f"Viewport width=390, document.scrollWidth={body_width}; manual visual usability review still required",mobile)
        # These require administrator token; never turn static presence into a pass.
        for case in ["U13","U14","U15","U16"]:
            result(case,"BLOCKED","Actual upload/API test requires authorized browser token; not attempted")
    except Exception as exc:
        errors.append(traceback.format_exc()[-3500:])
        result("U01","FAIL",type(exc).__name__+": "+str(exc))
    finally:
        browser.close()
for i in range(1,25):
    results.setdefault(f"U{i:02}":{"status":"NOT_RUN","detail":"Browser step not reached","screenshot":None})
output={"url":BASE,"timestamp_utc":datetime.now(timezone.utc).isoformat(),
        "browser":"Chromium headed=false",
        "tests":results,"browser_errors":errors[:35],
        "summary":{status:sum(r["status"]==status for r in results.values())
                   for status in ["PASS","FAIL","BLOCKED","NOT_RUN"]},
        "warning":"PASS proves only observed browser operations, not authenticated DAG or Worker execution"}
(OUT/"uat_report.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
(OUT/"browser_errors.txt").write_text("\n".join(errors),encoding="utf-8")
print("UAT_SUMMARY",json.dumps(output["summary"],ensure_ascii=False),flush=True)
# Fail CI on confirmed browser failures, but don't pretend BLOCKED tasks are completed.
raise SystemExit(1 if output["summary"]["FAIL"] else 0)
