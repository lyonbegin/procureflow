#!/usr/bin/env python3
"""Prove the restored Chrome belongs to the SELECTED encrypted account slot.

A GitHub Actions artifact is NOT proof that an authenticated session survives
a new runner. Validate ChatGPT's current live /api/auth/session and compare
the email to our independently AES-GCM encrypted account registry.

No email, tokens, cookies, messages, or profile content are printed or
written to Actions logs. Fails closed if expired or mismatched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

from playwright.sync_api import sync_playwright
from w2a_account_runtime import canonical_email, read_browser_email
from w2a_profile_crypto import decrypt


def main() -> int:
    root = Path(os.environ["RUNNER_TEMP"]) / "w2a-check"
    raw_slot = os.environ.get("HITEL_ACCOUNT_SLOT", "1")
    if not raw_slot.isascii() or not raw_slot.isdecimal() or raw_slot.startswith("0"):
        raise SystemExit("FAIL_ACCOUNT_SLOT_INVALID")
    slot = int(raw_slot)
    if not 1 <= slot <= 100:
        raise SystemExit("FAIL_ACCOUNT_SLOT_OUT_OF_RANGE")

    registry_encrypted = root / "download" / "registry.bin"
    profile_encrypted = root / "download" / f"account-{slot:04d}.bin"
    if not registry_encrypted.is_file() or not profile_encrypted.is_file():
        raise SystemExit("FAIL_SELECTED_ENCRYPTED_ACCOUNT_NOT_SAVED")

    staging = root / "verified-registry"
    staging.mkdir(parents=True, exist_ok=True, mode=0o700)
    decrypt(str(registry_encrypted), str(staging))
    source = staging / "chrome-profile" / "registry.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    source.unlink(missing_ok=True)
    accounts = data.get("accounts")
    if data.get("version") != 1 or not isinstance(accounts, list):
        raise SystemExit("FAIL_ENCRYPTED_REGISTRY_INVALID")
    selected = next((x for x in accounts
                     if isinstance(x, dict) and x.get("id") == slot), None)
    if selected is None:
        raise SystemExit("FAIL_ACCOUNT_SLOT_ABSENT_FROM_REGISTRY")
    expected = canonical_email(selected.get("email"))
    print("PASS_ENCRYPTED_ACCOUNT_REGISTRY_DECRYPTED", flush=True)
    print("SELECTED_ACCOUNT_SLOT=" + str(slot), flush=True)
    print("SAVED_ACCOUNT_COUNT=" + str(len(accounts)), flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(
            "http://127.0.0.1:9222", timeout=20000)
        if not browser.contexts:
            raise SystemExit("FAIL_RESTORED_ACCOUNT_BROWSER_CONTEXT_MISSING")
        ctx = browser.contexts[0]
        pages = [p for p in ctx.pages if not p.is_closed()
                 and p.url.startswith("https://chatgpt.com/")]
        page = pages[0] if pages else ctx.new_page()
        if not page.url.startswith("https://chatgpt.com/"):
            page.goto("https://chatgpt.com/",
                      wait_until="domcontentloaded", timeout=45000)
        observed = None
        for _ in range(10):
            try:
                observed = read_browser_email(page)
                if observed:
                    break
            except Exception:
                pass
            time.sleep(3)
    if not observed:
        raise SystemExit("FAIL_SAVED_CHATGPT_SESSION_REAUTH_REQUIRED")
    if canonical_email(observed) != expected:
        raise SystemExit("FAIL_RESTORED_CHATGPT_IDENTITY_MISMATCH")
    print("PASS_SAVED_ACCOUNT_LIVE_CHATGPT_IDENTITY_MATCHES_ENCRYPTED_REGISTRY",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
