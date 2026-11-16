#!/usr/bin/env python3
"""Confirm TWO different genuine ChatGPT HTTPS sessions on isolated Chrome CDP.

No email, token, cookie, profile path, personal data, or page text is logged.
"""
import sys
import time
from playwright.sync_api import sync_playwright
from w2a_account_runtime import read_browser_email,CHATGPT_HOME


def get_email(pw,port:int):
    browser=pw.chromium.connect_over_cdp(
        f"http://127.0.0.1:{port}",timeout=20000)
    if not browser.contexts:
        return None
    pages=[p for p in browser.contexts[0].pages
           if not p.is_closed() and p.url.startswith(CHATGPT_HOME)]
    if not pages:
        return None
    for page in pages:
        try:
            result=read_browser_email(page)
            if result:
                return result
        except Exception:
            pass
    return None


def verify_two():
    with sync_playwright() as pw:
        for i in range(12):
            try:
                a=get_email(pw,9222)
                b=get_email(pw,9223)
                if a and b and a!=b:
                    print("PASS_TWO_DISTINCT_LIVE_CHATGPT_BROWSER_SESSIONS",flush=True)
                    return 0
                if a and b and a==b:
                    print("FAIL_TWO_CHROME_PROFILES_HAVE_SAME_CHATGPT_ACCOUNT",flush=True)
                    return 2
            except Exception:
                pass
            time.sleep(2)
    print("FAIL_TWO_REAL_CHATGPT_SESSIONS_NOT_VERIFIED",flush=True)
    return 2


if __name__=="__main__":
    sys.exit(verify_two())
