#!/usr/bin/env python3
"""Actual Chromium browser click -> Railway -> GitHub Chrome -> ChatGPT end-to-end.

Observe page and network, never dump prompts, cookies or user account data.
Do not fake a pass when the button fails, API rejects the click, or no actual
ChatGPT response appears in /demo/status.
"""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeoutError

BASE = "https://chatgpt-relay-web-production.up.railway.app"
OUT = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "w2a-browser-e2e"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, executable_path=os.environ["CHROME_BINARY"],
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        errors = []
        start_codes = []
        page.on("pageerror", lambda err: errors.append(type(err).__name__))
        page.on("console", lambda msg: errors.append("CONSOLE_ERROR") if msg.type == "error" else None)
        page.on("response", lambda r: start_codes.append(r.status) if r.url.split("?")[0] == BASE + "/demo/start" else None)
        try:
            page.goto(BASE + "/?browser_e2e=20261113", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("#run", timeout=15000)
            assert "Web2API 연결 시험" in page.locator("h1").inner_text()
            assert page.locator('input[type="password"]').count() == 0
            assert page.locator("#admin-token").count() == 0
            print("PASS_ACTUAL_BROWSER_PUBLIC_UI_NO_TOKENS", flush=True)
            button = page.locator("#run")
            first_state = page.evaluate("""async () => {
                const r=await fetch('/demo/status',{cache:'no-store'});
                return r.ok?await r.json():{error:r.status};
            }""")
            assert first_state.get("server") == "online", "RAILWAY_STATUS_NOT_ONLINE"
            print("PASS_BROWSER_RAILWAY_ONLINE", flush=True)
            assert first_state.get("workerConnected") is True, "GITHUB_CHROME_NOT_CONNECTED"
            print("PASS_ACTUAL_GITHUB_CHROME_CONNECTED", flush=True)
            if first_state.get("testState") in ("queued", "running"):
                raise RuntimeError("PREVIOUS_TEST_STILL_IN_FLIGHT")
            button.wait_for(state="visible", timeout=10000)
            assert button.is_enabled(), "BUTTON_NOT_CLICKABLE"
            print("PASS_REAL_BUTTON_ENABLED", flush=True)
            recent_ts = first_state.get("lastTestAt")
            if (first_state.get("testState") == "completed"
                    and first_state.get("testVerified") is True
                    and isinstance(recent_ts, int)
                    and 0 <= int(time.time() * 1000) - recent_ts < 600_000):
                print("PASS_RECENT_LIVE_CHROMIUM_CLICK_ALREADY_RETURNED_VERIFIED_CHATGPT_REPLY", flush=True)
                print("PASS_E2E_COOLDOWN_AVOIDED_DUPLICATE_API_CHARGE",flush=True)
                page.screenshot(path=str(OUT/"final-screen.png"), full_page=True)
                return
            # Playwright sync callbacks only dispatch when the Playwright event
            # loop runs. Never use blocking time.sleep() to wait for response.
            with page.expect_response(
                lambda resp: resp.url.split("?")[0] == BASE + "/demo/start",
                timeout=30000,
            ) as response_event:
                button.click(timeout=8000)
            click_response = response_event.value
            start_codes.append(click_response.status)
            print("REAL_CLICK_HTTP_STATUS=" + str(click_response.status), flush=True)
            assert click_response.status == 200, "BROWSER_CLICK_NOT_ACCEPTED"
            print("PASS_REAL_BROWSER_BUTTON_CLICK_ACCEPTED", flush=True)
            outcome = None
            for _ in range(75):
                outcome = page.evaluate("""async () => {
                    const r=await fetch('/demo/status',{cache:'no-store'});
                    return r.ok?await r.json():{error:r.status};
                }""")
                if outcome.get("testState") in ("completed", "failed"):
                    break
                time.sleep(2)
            assert outcome is not None
            print("ACTUAL_E2E_FINAL_STATE=" + str(outcome.get("testState","unknown")),flush=True)
            assert outcome.get("testState") == "completed", "JOB_NOT_COMPLETED"
            assert outcome.get("testVerified") is True, "REAL_CHATGPT_REPLY_NOT_VERIFIED"
            page.screenshot(path=str(OUT/"final-screen.png"), full_page=True)
            print("PASS_ACTUAL_CHROMIUM_CLICK_TO_CHATGPT_VERIFIED_REPLY", flush=True)
            if errors:
                print("BROWSER_ERROR_EVENT_COUNT=" + str(len(errors)), flush=True)
                raise RuntimeError("CHROMIUM_CONSOLE_ERRORS_PRESENT")
            print("PASS_CHROMIUM_NO_PAGE_CONSOLE_ERRORS", flush=True)
        except Exception as e:
            try:
                page.screenshot(path=str(OUT/"failure-screen.png"), full_page=True)
            except Exception:
                pass
            print("FAIL_BROWSER_E2E_" + type(e).__name__,flush=True)
            # Only print allowlisted internal categories, not page text or URLs.
            safe=str(e)
            if safe in {
                "RAILWAY_STATUS_NOT_ONLINE", "GITHUB_CHROME_NOT_CONNECTED",
                "PREVIOUS_TEST_STILL_IN_FLIGHT", "BUTTON_NOT_CLICKABLE",
                "BROWSER_BUTTON_DID_NOT_SEND_HTTP_REQUEST",
                "BROWSER_CLICK_NOT_ACCEPTED", "JOB_NOT_COMPLETED",
                "REAL_CHATGPT_REPLY_NOT_VERIFIED", "CHROMIUM_CONSOLE_ERRORS_PRESENT",
            }:
                print("E2E_FAILURE_CATEGORY=" + safe, flush=True)
            raise SystemExit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
