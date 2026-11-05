#!/usr/bin/env python3
"""REAL Chromium UI click + official fresh DB end-to-end proof.

This does NOT use an HTTP POST shortcut to imitate clicking. Playwright
opens the public page and clicks the actual visible button once.
"""
import json
import os
import re
import time
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.getenv("FRESH_TEST_BASE", "https://fresh-g2b-site-center-production.up.railway.app")
OUT = Path("browser-evidence")
OUT.mkdir(exist_ok=True)
report = {"base": BASE, "browser": "chromium", "click_count": 0, "status": "starting"}
page_errors = []
console_errors = []

def audit(name, **data):
    report.update(data)
    print("BROWSER_E2E", name, json.dumps(data, ensure_ascii=False), flush=True)

def save_report():
    (OUT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

def get_json(context, path):
    resp = context.request.get(BASE + path, timeout=35000, fail_on_status_code=True)
    return resp.json()

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            ignore_https_errors=False,
        )
        page = context.new_page()
        page.on("pageerror", lambda err: page_errors.append(str(err)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        before = get_json(context, "/health")["new_db_notices"]
        report["db_before"] = before
        main_response = page.goto(BASE + "/", wait_until="domcontentloaded", timeout=45000)
        assert main_response and main_response.status == 200, "Main page did not return HTTP 200"
        page.locator("#searchButton").wait_for(state="visible", timeout=15000)
        button = page.locator("#searchButton")
        label = button.inner_text().strip()
        assert "다음 신규 공고 1건 가져오기" in label, f"Wrong button: {label!r}"
        assert page.locator('form#searchForm[method="post"][action="/run-next"]').count() == 1, "Form not a native POST"
        assert button.is_enabled(), "Button is disabled before clicking"
        page.screenshot(path=str(OUT / "01-before-click.png"), full_page=True)
        audit("main_page_loaded", button_label=label, db_before=before, main_title=page.title())

        # Actual browser click: do not substitute request.post() or a fabricated job.
        with page.expect_navigation(url=re.compile(r".*/run-status/\d+$"), timeout=35000):
            button.click(timeout=20000)
        report["click_count"] = 1
        job_url = page.url
        job_id = int(job_url.rsplit("/", 1)[-1])
        audit("clicked_and_redirected", job_id=job_id, job_url=job_url)
        assert job_id > 0, "No real job id after browser click"
        page.locator("body").wait_for(state="visible", timeout=15000)
        page.screenshot(path=str(OUT / "02-job-started.png"), full_page=True)

        deadline = time.monotonic() + 245
        job = None
        while time.monotonic() < deadline:
            job = get_json(context, "/api/fresh/jobs/" + str(job_id))
            if job["status"] in ("completed", "blocked", "error"):
                break
            page.wait_for_timeout(4000)
        assert job and job["status"] in ("completed", "blocked", "error"), "Timeout: no terminal job"
        report.update({"job_id": job_id, "job_status": job["status"],
                       "rows_seen": job["rows_seen"], "rows_saved": job["rows_saved"],
                       "job_error": job.get("error", "")})
        page.goto(job_url, wait_until="domcontentloaded", timeout=35000)
        page.screenshot(path=str(OUT / "03-final-job-screen.png"), full_page=True)
        status_text = page.locator("body").inner_text()
        assert f"#{job_id}" in status_text, "Result page omits actual job id"
        assert "다음 신규 공고 1건 가져오기" in status_text, "Next run button not shown"
        after = get_json(context, "/health")["new_db_notices"]
        report["db_after"] = after
        audit("job_terminal", status=job["status"], seen=job["rows_seen"],
              saved=job["rows_saved"], error=job.get("error",""), db_after=after)

        assert job["status"] == "completed", f"Official G2B search failed: {job.get('error', '')}"
        assert job["rows_saved"] in (0,1), "One-click test saved > 1 notice"
        assert after-before == job["rows_saved"], "DB delta != job saved count"
        if job["rows_saved"] == 1:
            assert "신규 공고 1건 저장 완료" in status_text, "Job success UI not visible"
            event = next((e for e in job.get("events",[]) if e.get("status")=="new_notice_saved"), None)
            assert event is not None, "No recorded real new notice event"
            no,ord_ = event["bid_no"],event["bid_ord"]
            report["new_bid_no"] = no
            report["new_bid_ord"] = ord_
            detail = get_json(context, "/api/fresh/notices/" + no + "/" + ord_)
            title = detail["notice"]["title"]
            assert title in status_text, f"New notice title not visible on result page: {title}"
            report["new_title"] = title
            # Verify return to the main page actually displays newest notice
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=35000)
            page.locator("#noticeList .item").first.wait_for(state="visible", timeout=25000)
            visible = page.locator("#noticeList .item").first.inner_text()
            page.screenshot(path=str(OUT / "04-main-after-save.png"), full_page=True)
            assert no in visible and title in visible, "Main page did not refresh to newly saved notice"
            audit("main_list_verified", bid=no, title=title)
        else:
            assert "새 공고가 없습니다" in status_text, "No-new case not explained visibly"
            audit("no_new_notice", message="Official search completed; all checked notices existed")

        # Page errors are evidence. Fail on genuine client-side crashes that
        # would prevent user actions, but log all console errors for debugging.
        report["page_errors"] = page_errors
        report["console_errors"] = console_errors[-20:]
        assert not page_errors, "Browser JavaScript errors: " + repr(page_errors)
        report["status"] = "passed"
        audit("PASS", job_id=job_id, db_before=before, db_after=after,
              new_bid_no=report.get("new_bid_no"), new_title=report.get("new_title"),
              browser_errors=len(page_errors))
        browser.close()
except Exception as exc:
    report["status"] = "failed"
    report["failure"] = repr(exc)
    report["traceback"] = traceback.format_exc()[-6000:]
    print("BROWSER_E2E_FAILED", report["traceback"], flush=True)
    raise
finally:
    save_report()
