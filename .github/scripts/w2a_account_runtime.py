#!/usr/bin/env python3
"""Actual Chrome session account gate, separate from OIDC worker authentication.

The email used here comes ONLY from ChatGPT's authenticated HTTPS session in
the Chrome context. Never trust account-id strings, the HITEL web page,
Web2API output, profile labels, or a cached 'last account' marker as login proof.
Passwords, cookies, session tokens and email addresses are never logged.

Sign-in with a different identity may need explicit Google/MFA interaction.
A missing interactive sign-in is a failure, not an invitation to send under a
different account. The current ChatGPT logout is UI-driven (not cookie deletion).
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

CHATGPT_HOME = "https://chatgpt.com/"
SIGNIN = "https://chatgpt.com/auth/login"
EMAIL = re.compile(r"^[^@\s]{1,100}@[^@\s]{1,180}$")


class AccountGateError(ValueError):
    pass


def canonical_email(value) -> str:
    if not isinstance(value, str) or len(value) > 254:
        raise AccountGateError("ACCOUNT_EMAIL_INVALID")
    email = value.strip().casefold()
    if not EMAIL.fullmatch(email):
        raise AccountGateError("ACCOUNT_EMAIL_INVALID")
    return email


# Whitelist the fields returned from the actual ChatGPT session response.
# Never return the token, session IDs, name, scopes, or unfiltered payload.
SESSION_JS = """async () => {
    try {
        const res = await fetch('/api/auth/session', {
            credentials:'include', cache:'no-store'
        });
        if (!res.ok) return {status:res.status, authenticated:false, email:null};
        const body = await res.json();
        const user = body?.user;
        const email = typeof user?.email === 'string' ? user.email : null;
        const authenticated = Boolean(
            email &&
            ((body?.accessToken || body?.access_token) ||
             body?.isAuthenticated === true)
        );
        return {status:res.status, authenticated, email:authenticated ? email:null};
    } catch (_e) {return {status:0, authenticated:false, email:null};}
}"""


def extract_verified_email(session: dict) -> Optional[str]:
    if not isinstance(session, dict) or session.get("status") != 200:
        return None
    if session.get("authenticated") is not True:
        return None
    try:
        return canonical_email(session.get("email"))
    except AccountGateError:
        return None


def read_browser_email(page) -> Optional[str]:
    return extract_verified_email(page.evaluate(SESSION_JS))


def confirmed_signed_out(state: dict) -> bool:
    # Network faults (status=0) are NEVER treated as proof of sign-out.
    return bool(isinstance(state, dict) and state.get("status") in (200,401)
                and state.get("authenticated") is False
                and extract_verified_email(state) is None)


def _real_logout(page) -> None:
    """Click ChatGPT's visible profile-menu logout and verify session ended."""
    # Exact data-testid used by current web; accessibility names are fallback.
    # Refuse blind coordinate clicks or direct cookie editing.
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    menus = [
        page.get_by_test_id("accounts-profile-button"),
        page.get_by_test_id("profile-button"),
        page.get_by_role("button", name=re.compile(
            r"Open profile menu|Profile menu|계정 메뉴|프로필 메뉴", re.I)),
    ]
    opened = False
    for control in menus:
        try:
            if control.count() and control.first.is_visible():
                control.first.click(timeout=3000)
                opened = True
                break
        except (PlaywrightTimeoutError, Exception):
            continue
    if not opened:
        raise AccountGateError("ACCOUNT_LOGOUT_UI_UNAVAILABLE")

    # ChatGPT animates its profile menu; wait for the contents to mount.
    page.wait_for_timeout(1200)
    actions = [
        page.get_by_role("menuitem", name=re.compile(r"Log out|Sign out|로그아웃", re.I)),
        page.get_by_role("button", name=re.compile(r"^Log out$|^Sign out$|^로그아웃$", re.I)),
        page.get_by_text(re.compile(r"^Log out$|^Sign out$|^로그아웃$", re.I)),
    ]
    clicked = False
    for action in actions:
        try:
            if action.count() and action.first.is_visible():
                action.first.click(timeout=4000)
                clicked = True
                break
        except (PlaywrightTimeoutError, Exception):
            continue
    if not clicked:
        raise AccountGateError("ACCOUNT_LOGOUT_UI_UNAVAILABLE")
    consecutively_signed_out = 0
    for _ in range(12):
        try:
            snapshot = page.evaluate(SESSION_JS)
            if confirmed_signed_out(snapshot):
                consecutively_signed_out += 1
                if consecutively_signed_out >= 2:
                    return
            else:
                consecutively_signed_out = 0
        except Exception:
            consecutively_signed_out = 0
        time.sleep(1)
    raise AccountGateError("ACCOUNT_LOGOUT_NOT_VERIFIED")


def ensure_requested_account(
    requested_email: str,
    *,
    read: Callable[[], Optional[str]],
    logout: Callable[[], None],
    open_login: Callable[[], None],
    login_wait_seconds: float = 12.0,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """A equals A => reuse; A versus B => logout then B sign-in; B missing => login.

    No automatic retries of a possibly already-sent message. This function is
    executed before invoking Web2API and reads actual session state each time.
    """
    expected = canonical_email(requested_email)
    current = read()
    if current is not None:
        current = canonical_email(current)
    if current == expected:
        return expected
    if current:
        logout()
        # A UI click or cookie clear is insufficient proof: re-read session.
        if read() is not None:
            raise AccountGateError("ACCOUNT_LOGOUT_NOT_VERIFIED")
    open_login()
    deadline = time.monotonic() + max(0.0, login_wait_seconds)
    while True:
        observed = read()
        if observed is not None:
            observed = canonical_email(observed)
            if observed == expected:
                return expected
            # Wrong SSO account: do NOT send, do NOT blindly log out again.
            raise AccountGateError("ACCOUNT_LOGIN_WRONG_IDENTITY")
        if time.monotonic() >= deadline:
            raise AccountGateError("ACCOUNT_INTERACTIVE_LOGIN_REQUIRED")
        sleep(min(2.0, max(0.01, deadline-time.monotonic())))


def actual_chrome_account(
    expected_email: str,
    *,
    wait_seconds: float = 12.0,
) -> str:
    """Use live Chrome CDP in the GitHub runner, never the caller's browser."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        if not browser.contexts:
            raise AccountGateError("CHROME_CONTEXT_MISSING")
        context = browser.contexts[0]
        pages = [p for p in context.pages if not p.is_closed()
                 and p.url.startswith("https://chatgpt.com/")]
        page = pages[0] if pages else context.new_page()
        if not page.url.startswith(CHATGPT_HOME):
            page.goto(CHATGPT_HOME, wait_until="domcontentloaded", timeout=30000)

        def start_login() -> None:
            page.goto(SIGNIN, wait_until="domcontentloaded", timeout=30000)

        return ensure_requested_account(
            expected_email, read=lambda:read_browser_email(page),
            logout=lambda:_real_logout(page), open_login=start_login,
            login_wait_seconds=wait_seconds,
        )


def find_verified_cdp_port(expected_email: str) -> int:
    """Find account A or B by the REAL live session, never an account label.

    Read only: never log out a different authenticated account to satisfy a
    job. The independent Chrome profiles use 9222 and 9223.
    """
    expected = canonical_email(expected_email)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for port in (9222, 9223):
            try:
                browser = pw.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}", timeout=10000)
                if not browser.contexts:
                    continue
                for page in browser.contexts[0].pages:
                    if page.is_closed() or not page.url.startswith(CHATGPT_HOME):
                        continue
                    if read_browser_email(page) == expected:
                        return port
            except Exception:
                continue
    raise AccountGateError("ACCOUNT_INTERACTIVE_LOGIN_REQUIRED")


def verify_same_session(expected_email: str, *, cdp_port: int = 9222) -> bool:
    """Independent read of the selected Chrome profile immediately around send."""
    if cdp_port not in (9222, 9223):
        return False
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(
            f"http://127.0.0.1:{cdp_port}")
        if not browser.contexts:
            return False
        for page in browser.contexts[0].pages:
            if page.is_closed() or not page.url.startswith(CHATGPT_HOME):
                continue
            try:
                return read_browser_email(page) == canonical_email(expected_email)
            except Exception:
                return False
    return False
