#!/usr/bin/env python3
"""Safe on-runner validation of a restored ChatGPT web session.

Read the authenticated session endpoint from the real Chrome tab. Print only
status flags: never print account identity, token, cookies or page text.
"""
import os
import sys
import time
from playwright.sync_api import sync_playwright


def check(page):
    try:
        result = page.evaluate("""async () => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 12000);
            try {
                const r = await fetch('/api/auth/session',
                    {credentials:'include', cache:'no-store', signal:controller.signal});
                if (!r.ok) return {ok:false, status:r.status};
                const body = await r.json();
                return {
                    ok: Boolean(body && typeof body === 'object'
                         && body.user && (body.accessToken || body.access_token)),
                    status:r.status
                };
            } catch(e) {
                return {ok:false, status:0};
            } finally { clearTimeout(timer); }
        }""")
        return bool(result.get("ok", False)), int(result.get("status", 0))
    except Exception:
        return False, 0


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9222')
        context = browser.contexts[0]
        tabs = [p for p in context.pages if not p.is_closed()]
        page = tabs[0] if tabs else context.new_page()
        try:
            page.goto('https://chatgpt.com/', wait_until='domcontentloaded', timeout=60000)
        except Exception as ex:
            print("CHATGPT_NAVIGATION_PROBLEM=" + type(ex).__name__, flush=True)
        ok, status = False, 0
        for n in range(12):
            ok, status = check(page)
            if ok:
                break
            time.sleep(3)
            if n in (3, 7):
                try:
                    page.reload(wait_until='domcontentloaded', timeout=30000)
                except Exception:
                    pass
        print("CHATGPT_SESSION_HTTP_STATUS=" + str(status), flush=True)
        if ok:
            print("PASS_CHATGPT_SESSION_AUTHENTICATED_RESTORED", flush=True)
            return 0
        print("FAIL_CHATGPT_SESSION_AUTH_NOT_VERIFIED", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
