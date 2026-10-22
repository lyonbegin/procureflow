#!/usr/bin/env python3
"""Freemoa headless collector: reuse one approved Google->Freemoa session.

Google restricts scripted sign-in on GitHub runners. Users authenticate once
in a normal visible Chrome browser; headless Chrome subsequently uses only
Freemoa cookies from GitHub Secret FREEMOA_SESSION_B64. No Google password,
no extra encryption key, and no browser-profile upload.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from tools.freemoa_google_login import (
    LOGIN_URL, import_session_secret, filter_freemoa_state,
    verify_freemoa_account
)

class LoginStop(RuntimeError):
    pass

def click_google(page):
    """Probe only: click Freemoa's official Google login control."""
    selectors=[
        page.get_by_role("link",name=re.compile("Google|구글",re.I)),
        page.get_by_role("button",name=re.compile("Google|구글",re.I)),
        page.get_by_text("Google 로그인",exact=False),
        page.get_by_text("구글 로그인",exact=False),
        page.locator("a[href*='google' i],a[onclick*='google' i],button[onclick*='google' i]"),
        page.locator("img[alt*='google' i],img[alt*='구글']")
    ]
    for candidate in selectors:
        try:
            if candidate.count() and candidate.first.is_visible():
                candidate.first.click(timeout=4500)
                return True
        except Exception:
            continue
    return False

def probe_google_entry(context):
    page=context.new_page()
    response=page.goto(LOGIN_URL,wait_until="domcontentloaded",timeout=25000)
    if not response or response.status>=400:
        raise LoginStop("freemoa_login_page_unavailable")
    if not click_google(page):
        raise LoginStop("freemoa_google_login_button_missing")
    for _ in range(25):
        for tab in context.pages:
            if urlparse(tab.url).hostname=="accounts.google.com":
                return "accounts.google.com"
        page.wait_for_timeout(300)
    raise LoginStop("google_provider_window_missing")

def verify_existing_session(context):
    page=context.new_page()
    try:
        return verify_freemoa_account(page)
    finally:
        page.close()

def run(mode,output,limit):
    status={"mode":mode,"status":"starting","authenticated":False,
            "details_parsed":0,"listing_cards":0}
    output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(channel="chrome",headless=True,
                                   args=["--no-sandbox","--disable-dev-shm-usage"])
        context=None
        try:
            if mode=="probe":
                context=browser.new_context(locale="ko-KR")
                status["google_provider_host"]=probe_google_entry(context)
                status["status"]="google_provider_reached"
                return status
            token=os.environ.get("FREEMOA_SESSION_B64","")
            if not token:
                raise LoginStop("missing_freemoa_session_secret")
            try:
                session=import_session_secret(token)
            except RuntimeError as exc:
                raise LoginStop("invalid_freemoa_session_secret") from exc
            context=browser.new_context(locale="ko-KR",storage_state=session)
            check=verify_existing_session(context)
            status["auth_probe"]=check.get("reason","")
            if not check.get("authenticated"):
                raise LoginStop("freemoa_session_expired_or_rejected")
            status["authenticated"]=True
            status["auth_method"]="freemoa_google_session_reuse"
            from tools.crawl_probe import scan
            with tempfile.TemporaryDirectory() as directory:
                temp_state=Path(directory)/"freemoa.json"
                temp_state.write_text(json.dumps(
                    filter_freemoa_state(context.storage_state()),
                    ensure_ascii=False),encoding="utf-8")
                if os.name!="nt":
                    os.chmod(temp_state,0o600)
                report=scan("freemoa","projects",output,max_records=limit,
                            storage_state=temp_state)
            status["listing_cards"]=report.get("list_cards_parsed",0)
            status["details_parsed"]=report.get("detail_records_parsed",0)
            status["projects"]=[
                {"source_id":x.get("source_id"),"title":x.get("title"),
                 "detail_verified":x.get("detail_verified",False)}
                for x in report.get("records",[])
            ]
            status["status"]=("detail_success" if status["details_parsed"]>0
                              else "authenticated_but_no_details")
            return status
        except LoginStop as exc:
            status["status"]="authentication_stopped"
            status["reason"]=str(exc)
            return status
        except Exception as exc:
            status["status"]="execution_error"
            status["reason"]=type(exc).__name__
            return status
        finally:
            if context:context.close()
            browser.close()
            # Authenticated detail descriptions are not stored as public
            # GitHub Actions artifacts. Only safe count-level diagnostics.
            raw=output/"result.json"
            if raw.exists():
                raw.unlink()
            (output/"login_status.json").write_text(
                json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=("probe","crawl"),default="crawl")
    parser.add_argument("--output",default="artifacts/freemoa-google")
    parser.add_argument("--limit",type=int,default=10)
    args=parser.parse_args()
    if not 1<=args.limit<=10:
        parser.error("--limit must be 1 to 10")
    result=run(args.mode,Path(args.output),args.limit)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result["status"] in ("google_provider_reached",
                                    "detail_success") else 1

if __name__=="__main__":
    sys.exit(main())
