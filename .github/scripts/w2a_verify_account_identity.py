#!/usr/bin/env python3
"""Read-only live real ChatGPT account verification on temporary GitHub Chrome.

Never prints email or any session credential. Does not send a message, modify
the session or invoke sign-out. Checks the same-account fast path directly
against the actual ChatGPT HTTPS session rather than cached profile labels.
"""
import sys
from playwright.sync_api import sync_playwright
from w2a_account_runtime import (
    actual_chrome_account, read_browser_email, verify_same_session,
)

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        if not browser.contexts:
            print("FAIL_LIVE_BROWSER_CONTEXT_MISSING")
            return 2
        pages = [p for p in browser.contexts[0].pages
                 if not p.is_closed() and p.url.startswith("https://chatgpt.com/")]
        if not pages:
            print("FAIL_LIVE_CHATGPT_PAGE_MISSING")
            return 2
        email=read_browser_email(pages[0])
        if not email:
            print("FAIL_LIVE_VERIFIED_EMAIL_NOT_AVAILABLE")
            return 2
    # The expected value is obtained from the *actual* signed-in ChatGPT
    # session in this isolated test, never a user-supplied identity.
    # This is an invariant test, NOT proof of account A/B switching.
    if actual_chrome_account(email, wait_seconds=0) != email:
        print("FAIL_LIVE_SAME_ACCOUNT_REUSE")
        return 2
    if not verify_same_session(email):
        print("FAIL_LIVE_BROWSER_ACCOUNT_RECHECK")
        return 2
    print("PASS_REAL_CHATGPT_ACCOUNT_EMAIL_READ_AND_MATCH")
    print("PASS_SAME_ACCOUNT_WITHOUT_LOGOUT")
    print("PASS_SECOND_BROWSER_SESSION_IDENTITY_RECHECK")
    return 0

if __name__=="__main__":
    sys.exit(main())
