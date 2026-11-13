#!/usr/bin/env python3
"""One-off ChatGPT Google sign-in probe in a GitHub-hosted Chrome.

Uses ONLY existing GitHub Actions Google credentials. No remote desktop,
public tunnel, extra password, persisted cookies, or profile artifacts.
Passwords, account identifiers and session contents are never logged.
"""
import json
import os
import re
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

CDP = "http://127.0.0.1:9222"
ROOT = "https://chatgpt.com"


def state(page):
    """Observe the ChatGPT account session without printing any user data."""
    try:
        status = page.evaluate(
            """async () => {
              const r = await fetch('/api/auth/session', {credentials: 'include'});
              if (!r.ok) return {ok:false, http:r.status};
              const j = await r.json();
              return {ok:!!(j && (j.user || j.accessToken || j.access_token)),
                      http:r.status};
            }"""
        )
        return bool(status.get("ok"))
    except Exception:
        return False


def find_google_page(context, page):
    for _ in range(30):
        for tab in context.pages:
            if "accounts.google.com" in tab.url:
                return tab
        if "accounts.google.com" in page.url:
            return page
        time.sleep(1)
    return None


def attempt_google(context, page, email, password):
    page.goto(ROOT, wait_until="domcontentloaded", timeout=60000)
    if state(page):
        print("PASS_EXISTING_CHATGPT_SESSION", flush=True)
        return True

    print("CHATGPT_LOGIN_REQUIRED", flush=True)
    try:
        login = page.get_by_role("button", name=re.compile(r"^Log in$|^로그인$", re.I))
        if not login.count():
            login = page.get_by_role("link", name=re.compile(r"^Log in$|^로그인$", re.I))
        if login.count():
            login.first.click(timeout=12000)
        else:
            page.goto(ROOT + "/auth/login", wait_until="domcontentloaded", timeout=30000)
    except Exception:
        page.goto(ROOT + "/auth/login", wait_until="domcontentloaded", timeout=30000)

    for _ in range(15):
        google = page.get_by_role("button", name=re.compile(r"Google", re.I))
        if not google.count():
            google = page.get_by_text(re.compile(r"Continue with Google|Google로 계속|Google 계정", re.I))
        if google.count():
            google.first.click(timeout=10000)
            break
        time.sleep(1)
    else:
        print("BLOCKED_GOOGLE_LOGIN_BUTTON_NOT_FOUND", flush=True)
        return False

    google_page = find_google_page(context, page)
    if google_page is None:
        print("BLOCKED_GOOGLE_PROVIDER_PAGE_NOT_FOUND", flush=True)
        return False

    print("GOOGLE_PROVIDER_OPENED", flush=True)
    # Google can display account selection, emailed challenges or anti-automation.
    try:
        email_input = google_page.locator('input[type="email"]')
        if email_input.count() and email_input.first.is_visible():
            email_input.first.fill(email, timeout=15000)
            google_page.locator('#identifierNext').click(timeout=15000)
            print("GOOGLE_EMAIL_SUBMITTED", flush=True)
        elif google_page.get_by_text(email, exact=True).count():
            google_page.get_by_text(email, exact=True).first.click(timeout=12000)
            print("GOOGLE_ACCOUNT_SELECTED", flush=True)
        else:
            print("GOOGLE_ACCOUNT_SELECTION_REQUIRES_INTERACTION", flush=True)
    except (PlaywrightTimeout, Exception):
        print("GOOGLE_ACCOUNT_STAGE_BLOCKED", flush=True)

    try:
        google_page.locator('input[type="password"]').wait_for(timeout=25000)
        google_page.locator('input[type="password"]').fill(password, timeout=15000)
        google_page.locator('#passwordNext').click(timeout=15000)
        print("GOOGLE_PASSWORD_SUBMITTED", flush=True)
    except Exception:
        print("GOOGLE_PASSWORD_STAGE_NOT_AUTOMATABLE_OR_CHALLENGED", flush=True)

    # A Google approval push or 2FA can require explicit user action.
    print("WAITING_FOR_GOOGLE_APPROVAL_IF_PROMPTED", flush=True)
    for i in range(36):
        try:
            if not page.is_closed() and page.url.startswith(ROOT) and state(page):
                print("PASS_CHATGPT_GOOGLE_LOGIN_VERIFIED", flush=True)
                return True
            # Login can complete in a newly opened ChatGPT page.
            for tab in context.pages:
                if not tab.is_closed() and tab.url.startswith(ROOT) and state(tab):
                    print("PASS_CHATGPT_GOOGLE_LOGIN_VERIFIED", flush=True)
                    return True
        except Exception:
            pass
        if i in (5, 17, 29):
            print("LOGIN_STILL_PENDING_APPROVAL_OR_BLOCKED", flush=True)
        time.sleep(5)
    print("FAIL_CHATGPT_GOOGLE_LOGIN_NOT_VERIFIED", flush=True)
    return False


def main():
    email = os.environ.get("FREEMOA_GOOGLE_EMAIL", "")
    password = os.environ.get("FREEMOA_GOOGLE_PASSWORD", "")
    if not email or not password:
        print("MISSING_PREVIOUSLY_REGISTERED_GOOGLE_CREDENTIALS", flush=True)
        return 2
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP, timeout=30000)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        try:
            return 0 if attempt_google(context, page, email, password) else 1
        except Exception as exc:
            print("CHATGPT_LOGIN_PROBE_ERROR_" + type(exc).__name__, flush=True)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
