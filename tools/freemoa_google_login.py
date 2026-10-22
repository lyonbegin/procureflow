#!/usr/bin/env python3
"""One-time *interactive* Google sign-in to Freemoa.

Run locally in a visible Chrome browser. User approves Google's consent/MFA;
the tool does not accept or capture passwords. Only freemoa.net browser
session state is exported, never Google cookies. No remote upload.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://www.freemoa.net/m0/s02"
PROJECTS_URL = "https://www.freemoa.net/m4/s41?page=1"
DETAIL_PATH = "/m4a/s41v"

def _freemoa_host(host: str) -> bool:
    return host == "freemoa.net" or host.endswith(".freemoa.net")

def filter_freemoa_state(state: dict) -> dict:
    """Keep only Freemoa-origin data in a local bearer-session export."""
    return {
        "cookies": [c for c in state.get("cookies", [])
                    if _freemoa_host(str(c.get("domain", "")).lstrip("."))],
        "origins": [o for o in state.get("origins", [])
                    if _freemoa_host(urlparse(o.get("origin", "")).hostname or "")],
    }

def save_private_state(context, path: Path) -> int:
    contents = filter_freemoa_state(context.storage_state())
    if not contents["cookies"]:
        raise RuntimeError("No Freemoa session cookies found; Google login has not finished.")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(contents, ensure_ascii=False), encoding="utf-8")
    if os.name != "nt":
        os.chmod(temp, 0o600)
    temp.replace(path)
    return len(contents["cookies"])

def verify_freemoa_account(page) -> dict:
    """Check a real detailed project AJAX response, not a login-page redirect."""
    page.goto(PROJECTS_URL, wait_until="commit", timeout=25000)
    page.wait_for_selector("#projectListNew .projTitle[data-pno]", timeout=25000)
    with page.expect_response(lambda r: DETAIL_PATH in urlparse(r.url).path,
                              timeout=18000) as pending:
        page.locator("#projectListNew .projTitle[data-pno]").first.click()
    original = pending.value.request
    # Chrome may release a response body too early. Fetch using same-origin
    # authenticated browser cookies and the request's actual POST parameters.
    result = page.evaluate("""async request => {
        const headers = {"X-Requested-With":"XMLHttpRequest"};
        if(request.contentType) headers["Content-Type"]=request.contentType;
        const response = await fetch(request.url,{
            method:request.method,
            body:request.method==="GET"?undefined:request.body,
            credentials:"same-origin",
            headers
        });
        return {http_status:response.status,text:await response.text()};
    }""", {
        "url": original.url,
        "method": original.method,
        "body": original.post_data,
        "contentType": original.headers.get("content-type", "")
    })
    response = json.loads(result["text"])
    error = response.get("ERROR", {})
    if error and (error.get("NO") == -1 or "로그인" in str(error.get("MSG", ""))):
        return {"authenticated":False,"reason":"프리모아가 로그인 필요라고 응답"}
    data = response.get("DATA")
    success = result["http_status"] == 200 and data not in (None, "", [], {})
    return {
        "authenticated":success,
        "http_status":result["http_status"],
        "has_project_detail":success,
        "reason":"프로젝트 상세 데이터 확보" if success else "로그인 또는 프로젝트 상세 접근 권한을 확인할 수 없음",
    }

def main():
    parser = argparse.ArgumentParser(description="Interactive Freemoa Google login")
    parser.add_argument("--data-dir", default=str(Path.home()/".procureflow"/"freemoa"))
    args = parser.parse_args()
    home = Path(args.data_dir).expanduser().resolve()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    profile = home/"chrome-profile"
    state_path = home/"freemoa.state.json"

    print("Chrome opens Freemoa's real login page. Choose 'Google 로그인'.")
    print("Complete Google account selection and verification yourself in Chrome.")
    print("Never provide your Google password, one-time code or cookie file in chat.")
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",
            headless=False,
            locale="ko-KR",
            args=["--no-sandbox"],
        )
        try:
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            input("After the Google sign-in is completed in Chrome, press Enter here to validate: ")
            check = verify_freemoa_account(page)
            print(json.dumps(check,ensure_ascii=False))
            if not check["authenticated"]:
                print("Freemoa detail access has not been authenticated. No state file was saved.")
                return 2
            count = save_private_state(browser, state_path)
            print(f"Authenticated Freemoa session saved locally: {state_path}")
            print(f"Saved {count} freemoa.net session cookies. Google cookies excluded.")
            print("This is a sensitive session file. Do not commit or upload it.")
            return 0
        finally:
            browser.close()

if __name__ == "__main__":
    sys.exit(main())
