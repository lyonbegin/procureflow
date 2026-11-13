#!/usr/bin/env python3
"""Diagnose a restored ChatGPT web session without exposing private data.

Only status codes, allowlisted structural boolean flags, and login-control
presence are printed. No account identity, cookies, tokens, content or URLs.
"""
import sys
import time
from playwright.sync_api import sync_playwright


def check(page):
    try:
        result = page.evaluate("""async () => {
            let state={status:0,user:false,token:false,
                       isAuthenticated:false, empty:false, meStatus:0};
            try {
                const r=await fetch('/api/auth/session',
                    {credentials:'include',cache:'no-store'});
                state.status=r.status;
                if (r.ok) {
                    const o=await r.json();
                    state.empty=!o || (typeof o==='object'
                                       && Object.keys(o).length===0);
                    state.user=Boolean(o?.user && Object.keys(o.user).length);
                    state.token=Boolean(o?.accessToken || o?.access_token);
                    state.isAuthenticated=o?.isAuthenticated===true;
                }
            } catch (e) {}
            try {
                const r=await fetch('/backend-api/me',
                    {credentials:'include',redirect:'manual'});
                state.meStatus=r.status;
            } catch(e) {}
            return state;
        }""")
        return result
    except Exception:
        return {"status":0,"user":False,"token":False,"isAuthenticated":False,"empty":False,"meStatus":0}


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9222')
        context=browser.contexts[0]
        tabs=[p for p in context.pages if not p.is_closed()]
        page=tabs[0] if tabs else context.new_page()
        try:
            page.goto('https://chatgpt.com/',wait_until='domcontentloaded',timeout=60000)
        except Exception as e:
            print("CHATGPT_NAVIGATION_ISSUE="+type(e).__name__,flush=True)
        result={}
        for i in range(8):
            result=check(page)
            if result.get("user") and result.get("token"):
                break
            if result.get("isAuthenticated") and result.get("meStatus")==200:
                break
            time.sleep(3)
        print("SESSION_HTTP_STATUS="+str(result.get("status",0)),flush=True)
        print("SESSION_IS_EMPTY="+str(result.get("empty",False)).lower(),flush=True)
        print("SESSION_USER_PRESENT="+str(result.get("user",False)).lower(),flush=True)
        print("SESSION_ACCESS_TOKEN_PRESENT="+str(result.get("token",False)).lower(),flush=True)
        print("SESSION_IS_AUTHENTICATED_FLAG="+str(result.get("isAuthenticated",False)).lower(),flush=True)
        print("CHATGPT_BACKEND_ME_HTTP_STATUS="+str(result.get("meStatus",0)),flush=True)
        try:
            login=page.get_by_role("button",name="Log in",exact=True).count()+page.get_by_role("link",name="Log in",exact=True).count()
            signup=page.get_by_role("button",name="Sign up",exact=True).count()+page.get_by_role("link",name="Sign up",exact=True).count()
            print("LOGIN_BUTTON_VISIBLE="+str(login>0).lower(),flush=True)
            print("SIGNUP_BUTTON_VISIBLE="+str(signup>0).lower(),flush=True)
        except Exception:
            print("LOGIN_UI_CHECK_UNAVAILABLE",flush=True)
        authed=bool(result.get("user") and result.get("token")) or bool(result.get("isAuthenticated") and result.get("meStatus")==200)
        if authed:
            print("PASS_CHATGPT_SESSION_AUTHENTICATED_RESTORED",flush=True)
            return 0
        print("FAIL_CHATGPT_SESSION_AUTH_NOT_VERIFIED",flush=True)
        return 2


if __name__=="__main__":
    sys.exit(main())
