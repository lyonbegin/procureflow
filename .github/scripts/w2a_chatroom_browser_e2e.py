#!/usr/bin/env python3
"""Actual deployed Railway Chromium navigation/room/file UX verification.

No access to private user records, no bearer credentials, no arbitrary
ChatGPT prompts. Tests an isolated fresh browser session and room.
"""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE="https://chatgpt-relay-web-production.up.railway.app"
# Live retest after favicon asset fix, November 16, 2026.
OUT=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"hitel-chatroom-browser"
OUT.mkdir(parents=True,exist_ok=True)

def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,
            executable_path=os.environ["CHROME_BINARY"],
            args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(viewport={"width":1280,"height":850},
                                 ignore_https_errors=False)
        page=ctx.new_page()
        errors=[]
        page.on("pageerror",lambda err:errors.append("PAGE_SCRIPT_EXCEPTION"))
        def on_console(msg):
            if msg.type!="error":
                return
            txt=msg.text.lower()
            if "favicon" in txt:
                category="FAVICON"
            elif "content security policy" in txt or "csp" in txt:
                category="CONTENT_SECURITY_POLICY"
            elif "failed to load resource" in txt:
                category="RESOURCE_REQUEST"
            elif "not found" in txt:
                category="MISSING_RESOURCE"
            else:
                category="OTHER_CONSOLE_ERROR"
            errors.append(category)
        page.on("console",on_console)
        try:
            page.goto(BASE+"?chat-room-e2e=1",wait_until="domcontentloaded",timeout=60000)
            expect(page.locator("#new-room")).to_be_visible(timeout=15000)
            expect(page.locator("#room-list")).to_be_visible()
            expect(page.locator("#file-input")).to_have_count(1)
            assert page.locator("#admin-token").count()==0
            assert page.locator("#user-api-key").count()==0
            print("PASS_REAL_CHATROOM_BROWSER_UI_AND_NO_TOKEN_FIELDS",flush=True)

            page.locator("#new-room").click()
            page.locator("#room-name").fill("E2E 브라우저 시험방")
            page.locator("#room-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_have_text("E2E 브라우저 시험방",timeout=12000)
            print("PASS_CHROME_CLICK_CREATES_REAL_PERSISTENT_ROOM",flush=True)

            rooms=page.evaluate("""async()=>{
              const r=await fetch('/web/api/rooms',{cache:'no-store'});
              return await r.json();
            }""")["rooms"]
            room=next(x for x in rooms if x["title"]=="E2E 브라우저 시험방")
            rid=room["id"]
            page.reload(wait_until="domcontentloaded")
            expect(page.locator("#room-list")).to_contain_text("E2E 브라우저 시험방",timeout=12000)
            page.locator("#room-list .room-btn").filter(has_text="E2E 브라우저 시험방").click()
            expect(page.locator("#room-title")).to_have_text("E2E 브라우저 시험방")
            print("PASS_BROWSER_ROOM_PERSISTS_ACROSS_RELOAD",flush=True)

            page.locator("#toggle-files").click()
            expect(page.locator("#file-panel")).to_have_class("file-panel open")
            page.locator("#file-input").set_input_files({
                "name":"readme-demo.txt",
                "mimeType":"text/plain",
                "buffer":b"WEB2API_FILE_OPEN_VERIFIED_20261116\n",
            })
            expect(page.locator("#file-list")).to_contain_text("readme-demo.txt",timeout=15000)
            page.locator("#file-list button").filter(has_text="열기").click()
            expect(page.locator("#preview-content")).to_contain_text(
                "WEB2API_FILE_OPEN_VERIFIED_20261116",timeout=15000)
            page.locator("#close-preview").click()
            print("PASS_ACTUAL_BROWSER_UPLOAD_OPEN_AND_PREVIEW_FILE",flush=True)

            isolated=browser.new_context()
            other=isolated.new_page()
            other.goto(BASE,wait_until="domcontentloaded",timeout=30000)
            other.wait_for_function(
                "() => document.querySelector('#notice') && "
                "!document.querySelector('#notice').textContent.includes('준비하고')",
                timeout=10000)
            private_code=other.evaluate("""async id=>{
               const r=await fetch('/web/api/rooms/'+id,{cache:'no-store'});
               return r.status;
            }""",rid)
            assert private_code==404,"CROSS_BROWSER_ROOM_ACCESS_NOT_BLOCKED"
            print("PASS_REAL_BROWSER_PRIVATE_SESSION_ROOM_ISOLATION",flush=True)
            isolated.close()

            page.locator("#rename-room").click()
            page.locator("#room-name").fill("수정된 브라우저 시험방")
            page.locator("#room-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_have_text("수정된 브라우저 시험방",timeout=10000)
            print("PASS_BROWSER_ROOM_RENAME",flush=True)
            page.screenshot(path=str(OUT/"chatroom-success.png"),full_page=True)
            print("BROWSER_SAFE_ERROR_CATEGORIES="+",".join(sorted(set(errors))) if errors else "BROWSER_SAFE_ERROR_CATEGORIES=none",flush=True)
            assert not errors,"BROWSER_SCRIPT_CONSOLE_ERRORS"
            print("PASS_BROWSER_NO_JAVASCRIPT_RUNTIME_ERRORS",flush=True)
        except Exception as exc:
            try:page.screenshot(path=str(OUT/"chatroom-failure.png"),full_page=True)
            except Exception:pass
            print("FAIL_REAL_BROWSER_CHATROOM_"+type(exc).__name__,flush=True)
            raise
        finally:
            browser.close()

if __name__=="__main__":
    main()
