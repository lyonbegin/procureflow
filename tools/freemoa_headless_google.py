#!/usr/bin/env python3
"""Google -> Freemoa sign-in using headless Chromium.

probe: verify the real social-login button opens Google.
crawl: reuse an encrypted Freemoa-only session, or attempt ordinary Google
username/password sign-in from protected environment variables. Google MFA,
CAPTCHA and security challenges are never bypassed.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from cryptography.fernet import Fernet, InvalidToken
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
from tools.freemoa_google_login import LOGIN_URL, filter_freemoa_state, verify_freemoa_account

class LoginStop(Exception):
    pass

def cipher():
    secret=os.environ.get("FREEMOA_SESSION_ENCRYPTION_KEY","")
    if len(secret)<24:
        raise LoginStop("missing_or_short_session_encryption_key")
    key=base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)

def restore_state(path):
    if not path.exists():return None
    try:
        value=json.loads(cipher().decrypt(path.read_bytes()))
        return filter_freemoa_state(value)
    except (InvalidToken,ValueError,UnicodeError) as err:
        raise LoginStop("encrypted_session_invalid") from err

def encrypt_state(context,path):
    data=filter_freemoa_state(context.storage_state())
    if not data["cookies"]:raise LoginStop("freemoa_session_cookies_missing")
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    tmp.write_bytes(cipher().encrypt(json.dumps(data).encode()))
    if os.name!="nt":os.chmod(tmp,0o600)
    tmp.replace(path)

def click_google(page):
    selectors=[
        page.get_by_role("link",name=re.compile("Google|구글",re.I)),
        page.get_by_role("button",name=re.compile("Google|구글",re.I)),
        page.get_by_text("Google 로그인",exact=False),
        page.get_by_text("구글 로그인",exact=False),
        page.locator("a[href*='google' i],a[onclick*='google' i],button[onclick*='google' i]"),
        page.locator("img[alt*='google' i],img[alt*='구글']")
    ]
    for selector in selectors:
        try:
            if selector.count() and selector.first.is_visible():
                selector.first.click(timeout=5000)
                return True
        except Exception:
            continue
    return False

def google_window(context,page):
    for candidate in reversed(context.pages):
        if urlparse(candidate.url).hostname=="accounts.google.com":
            return candidate
    return None

def open_google(context):
    page=context.new_page()
    response=page.goto(LOGIN_URL,wait_until="domcontentloaded",timeout=30000)
    if not response or response.status>=400:
        raise LoginStop("freemoa_login_http_error")
    if not click_google(page):
        raise LoginStop("google_button_not_found")
    for _ in range(25):
        found=google_window(context,page)
        if found:return found,page
        page.wait_for_timeout(350)
    raise LoginStop("google_provider_window_not_opened")

def fill_and_submit(page,selector,value):
    target=page.locator(selector).first
    target.wait_for(state="visible",timeout=16000)
    target.fill(value)
    target.press("Enter")

def sign_in(context):
    email=os.environ.get("FREEMOA_GOOGLE_EMAIL","")
    password=os.environ.get("FREEMOA_GOOGLE_PASSWORD","")
    if not email or not password:
        raise LoginStop("missing_google_email_or_password_secret")
    google,freemoa=open_google(context)
    try:
        fill_and_submit(google,"input[type=email]",email)
        fill_and_submit(google,"input[type=password]",password)
    except BrowserTimeout as exc:
        raise LoginStop("google_account_screen_or_verification_required") from exc
    for _ in range(70):
        active=google_window(context,freemoa)
        if active is None or active.is_closed():return
        if "/challenge/" in urlparse(active.url).path:
            raise LoginStop("google_mfa_or_approval_required")
        freemoa.wait_for_timeout(500)
    raise LoginStop("google_login_redirect_unfinished")

def verified(context):
    check_page=context.new_page()
    try:
        return verify_freemoa_account(check_page).get("authenticated") is True
    except Exception:
        return False
    finally:
        check_page.close()

def run(mode,encrypted_file,output,limit):
    result={"mode":mode,"status":"starting","authenticated":False,"detail_records":0}
    output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=None
        try:
            if mode=="probe":
                context=browser.new_context(locale="ko-KR")
                google,_=open_google(context)
                result["provider_host"]=urlparse(google.url).hostname
                result["status"]="google_provider_reached"
                return result
            restored=restore_state(encrypted_file)
            context=browser.new_context(locale="ko-KR",storage_state=restored or None)
            if restored and verified(context):
                result["auth_method"]="encrypted_session_reused"
            else:
                context.close()
                context=browser.new_context(locale="ko-KR")
                sign_in(context)
                if not verified(context):
                    raise LoginStop("freemoa_detail_api_authentication_failed")
                result["auth_method"]="headless_google_login"
                encrypt_state(context,encrypted_file)
            result["authenticated"]=True
            from tools.crawl_probe import scan
            with tempfile.TemporaryDirectory() as td:
                state_path=Path(td)/"state.json"
                state_path.write_text(json.dumps(filter_freemoa_state(context.storage_state())))
                if os.name!="nt":os.chmod(state_path,0o600)
                report=scan("freemoa","projects",output,max_records=limit,
                            storage_state=str(state_path))
            result["detail_records"]=report.get("detail_records_parsed",0)
            result["list_cards"]=report.get("list_cards_parsed",0)
            # The GitHub repo is public: never publish authenticated briefs
            # as plain JSON artifacts. Encrypt them before upload.
            plain=output/"result.json"
            if plain.exists():
                protected=output/"result.json.enc"
                protected.write_bytes(cipher().encrypt(plain.read_bytes()))
                if os.name!="nt":os.chmod(protected,0o600)
                plain.unlink()
            result["status"]="detail_success" if result["detail_records"] else "authenticated_but_no_details"
            return result
        except LoginStop as exc:
            result["status"]="authentication_stopped"
            result["reason"]=str(exc)
            return result
        except Exception as exc:
            result["status"]="execution_error"
            result["reason"]=type(exc).__name__
            return result
        finally:
            if context:context.close()
            browser.close()
            (output/"login_status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=["probe","crawl"],default="probe")
    parser.add_argument("--encrypted-session",default=".private/freemoa-session.enc")
    parser.add_argument("--output",default="artifacts/freemoa-google")
    parser.add_argument("--limit",type=int,default=10)
    args=parser.parse_args()
    status=run(args.mode,Path(args.encrypted_session),Path(args.output),args.limit)
    print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"] in ("google_provider_reached","detail_success") else 1

if __name__=="__main__":sys.exit(main())
