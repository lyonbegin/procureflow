#!/usr/bin/env python3
"""Locate REAL ChatGPT profile / Log out control without actually logging out.

This test must not revoke the saved encrypted login session. Only booleans and
test-id names are printed; account email and any private menu content are not.
"""
import re
import sys
from playwright.sync_api import sync_playwright,TimeoutError as PlaywrightTimeoutError
from w2a_account_runtime import read_browser_email

def main():
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        pages=[p for p in browser.contexts[0].pages
               if not p.is_closed() and p.url.startswith("https://chatgpt.com/")]
        if not pages or not read_browser_email(pages[0]):
            print("FAIL_NO_AUTHENTICATED_CHATGPT_PAGE")
            return 2
        page=pages[0]
        selectors=[
            ("accounts-profile-button",page.get_by_test_id("accounts-profile-button")),
            ("profile-button",page.get_by_test_id("profile-button")),
            ("profile-accessible",page.get_by_role("button",name=re.compile(
                r"Open profile menu|Profile menu|계정 메뉴|프로필 메뉴",re.I))),
        ]
        found=None
        for label,selector in selectors:
            try:
                if selector.count() and selector.first.is_visible():
                    selector.first.click(timeout=3000)
                    found=label
                    break
            except Exception:
                continue
        if not found:
            print("FAIL_NO_SUPPORTED_PROFILE_MENU_BUTTON")
            print("PROBE_ACCOUNT_PROFILE_TESTID="+str(
                page.locator('[data-testid="accounts-profile-button"]').count()))
            print("PROBE_PROFILE_TESTID="+str(
                page.locator('[data-testid="profile-button"]').count()))
            return 2
        checks=[
            ("menuitem",page.get_by_role("menuitem",name=re.compile(
                r"Log out|Sign out|로그아웃",re.I))),
            ("button",page.get_by_role("button",name=re.compile(
                r"^Log out$|^Sign out$|^로그아웃$",re.I))),
            ("text",page.get_by_text(re.compile(
                r"^Log out$|^Sign out$|^로그아웃$",re.I))),
        ]
        available=[]
        for label,sel in checks:
            try:
                if sel.count() and sel.first.is_visible():
                    available.append(label)
            except Exception:
                pass
        print("PASS_REAL_CHATGPT_PROFILE_MENU_OPEN_"+found)
        if not available:
            print("FAIL_LOGOUT_CONTROL_NOT_FOUND_AFTER_PROFILE_OPEN")
            return 2
        print("PASS_REAL_CHATGPT_LOGOUT_CONTROL_LOCATED_NO_CLICK")
        page.keyboard.press("Escape")
        return 0

if __name__=="__main__":
    sys.exit(main())
