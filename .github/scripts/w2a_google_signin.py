#!/usr/bin/env python3
"""Ephemeral, user-authorized Google sign-in in GitHub's real Chrome.

A HITEL browser encrypts email/password via P-256 ECDH + AES-256-GCM to
the unique GitHub runner public key. Railway only forwards ciphertext.
No credential is written to files, environment variables, console, URL,
GitHub Secrets, or persisted in browser storage by this module.

Only Google's REAL accounts.google.com password field is ever filled.
No CAPTCHA, MFA, anti-bot check, or account recovery is bypassed.
"""
from __future__ import annotations

import base64
import json
import re
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class RemoteGoogleLoginError(Exception):
    def __init__(self,code:str):
        if code not in {
            "GOOGLE_ADDITIONAL_VERIFICATION_REQUIRED",
            "GOOGLE_LOGIN_PAGE_UNAVAILABLE",
            "GOOGLE_LOGIN_NOT_AUTHENTICATED",
            "GOOGLE_LOGIN_WRONG_ACCOUNT",
            "GOOGLE_CREDENTIALS_REJECTED",
            "CHROME_LOGIN_UNEXPECTED",
        }:
            code="CHROME_LOGIN_UNEXPECTED"
        super().__init__(code)


def new_runner_key():
    private=ec.generate_private_key(ec.SECP256R1())
    public=private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return private,base64.b64encode(public).decode("ascii")


def _decode(s:str,max_bytes:int) -> bytes:
    if not isinstance(s,str) or len(s)>max_bytes*2:
        raise ValueError("ENCRYPTED_REQUEST_INVALID")
    raw=base64.b64decode(s,validate=True)
    if not 0<len(raw)<=max_bytes:
        raise ValueError("ENCRYPTED_REQUEST_INVALID")
    return raw


def decrypt_login_envelope(private,packet:dict):
    """Authenticated AEAD binds to one server-generated request ID."""
    if not isinstance(packet,dict):
        raise ValueError("ENCRYPTED_REQUEST_INVALID")
    rid=packet.get("request_id")
    if not isinstance(rid,str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}",rid):
        raise ValueError("ENCRYPTED_REQUEST_INVALID")
    pub=_decode(packet.get("client_public_key"),100)
    nonce=_decode(packet.get("nonce"),12)
    data=_decode(packet.get("ciphertext"),8192)
    if len(nonce)!=12:
        raise ValueError("ENCRYPTED_REQUEST_INVALID")
    client=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),pub)
    key=private.exchange(ec.ECDH(),client)
    raw=AESGCM(key).decrypt(nonce,data,rid.encode("ascii"))
    try:
        obj=json.loads(raw)
    finally:
        del raw
        del key
    if not isinstance(obj,dict) or set(obj)!={"email","password"}:
        raise ValueError("ENCRYPTED_REQUEST_INVALID")
    email,password=obj["email"],obj["password"]
    if (not isinstance(email,str) or len(email)>254 or
        not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or
        not isinstance(password,str) or not 0<len(password)<=1024):
        raise ValueError("ENCRYPTED_REQUEST_INVALID")
    return email.strip().casefold(),password


def _check_google_host(page):
    """Never fill an arbitrary redirected password form."""
    url=page.url
    parsed=urlsplit(url)
    if parsed.scheme!="https" or parsed.hostname!="accounts.google.com":
        raise RemoteGoogleLoginError("GOOGLE_LOGIN_PAGE_UNAVAILABLE")


def _find_visible(candidates,timeout_ms=2200):
    for target in candidates:
        try:
            if target.count() and target.first.is_visible():
                return target.first
            target.first.wait_for(state="visible",timeout=timeout_ms)
            return target.first
        except Exception:
            pass
    return None


def _google_page(context,original):
    for page in reversed(context.pages):
        if page.url.startswith("https://accounts.google.com/"):
            return page
    if original.url.startswith("https://accounts.google.com/"):
        return original
    return None


def perform_google_login(email:str,password:str,timeout_seconds:float=55.0) -> str:
    """Return only email from actual ChatGPT /api/auth/session, never UI text.

    The same already authenticated email is accepted without logout.
    Different email requires real UI logout first. If Google requires MFA,
    returns a safe status to allow user approval on their own device.
    """
    from playwright.sync_api import sync_playwright
    from w2a_account_runtime import (
        read_browser_email, _real_logout, SESSION_JS, confirmed_signed_out,
    )

    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        if not browser.contexts:
            raise RemoteGoogleLoginError("GOOGLE_LOGIN_PAGE_UNAVAILABLE")
        context=browser.contexts[0]
        old_pages=[p for p in context.pages if not p.is_closed()
                   and p.url.startswith("https://chatgpt.com/")]
        page=old_pages[0] if old_pages else context.new_page()
        if not page.url.startswith("https://chatgpt.com/"):
            page.goto("https://chatgpt.com/",wait_until="domcontentloaded",timeout=30000)
        existing=read_browser_email(page)
        if existing==email:
            return existing
        if existing is not None:
            _real_logout(page)  # Actual UI sign-out, no direct cookie edits.
        page.goto("https://chatgpt.com/auth/login",
                  wait_until="domcontentloaded",timeout=30000)

        # ChatGPT may first show the Log in action rather than the provider list.
        signin=_find_visible([
            page.get_by_role("link",name=re.compile(r"^Log in$|^로그인$",re.I)),
            page.get_by_role("button",name=re.compile(r"^Log in$|^로그인$",re.I)),
        ],timeout_ms=1800)
        if signin:
            signin.click(timeout=5000)
        provider=_find_visible([
            page.get_by_role("button",name=re.compile(
                r"Continue with Google|Google로 계속|Google 계정으로 계속",re.I)),
            page.get_by_role("link",name=re.compile(
                r"Continue with Google|Google로 계속|Google 계정으로 계속",re.I)),
            page.locator('button:has-text("Google")'),
        ],timeout_ms=4500)
        if not provider:
            raise RemoteGoogleLoginError("GOOGLE_LOGIN_PAGE_UNAVAILABLE")
        provider.click(timeout=10000)

        deadline=time.monotonic()+min(max(timeout_seconds,5.0),100.0)
        google=None
        while time.monotonic()<deadline:
            google=_google_page(context,page)
            if google is not None:
                break
            time.sleep(0.5)
        if google is None:
            raise RemoteGoogleLoginError("GOOGLE_LOGIN_PAGE_UNAVAILABLE")
        _check_google_host(google)

        # An already remembered Google account can be shown first.
        chooser=_find_visible([
            google.get_by_text(re.compile(r"Use another account|다른 계정 사용",re.I)),
        ],timeout_ms=650)
        if chooser:
            chooser.click(timeout=3500)

        _check_google_host(google)
        identifier=_find_visible([
            google.locator('input#identifierId'),
            google.locator('input[name="identifier"]'),
            google.locator('input[type="email"]'),
        ],timeout_ms=4500)
        if not identifier:
            raise RemoteGoogleLoginError("GOOGLE_LOGIN_PAGE_UNAVAILABLE")
        identifier.fill(email,timeout=4000)
        nxt=_find_visible([google.locator("#identifierNext"),
                           google.get_by_role("button",name=re.compile(
                               r"^Next$|^다음$",re.I))],timeout_ms=3000)
        if not nxt:
            raise RemoteGoogleLoginError("GOOGLE_LOGIN_PAGE_UNAVAILABLE")
        nxt.click(timeout=6500)

        password_field=_find_visible([
            google.locator('input[name="Passwd"]'),
            google.locator('input[type="password"]'),
        ],timeout_ms=12000)
        if not password_field:
            raise RemoteGoogleLoginError("GOOGLE_ADDITIONAL_VERIFICATION_REQUIRED")
        _check_google_host(google)
        password_field.fill(password,timeout=6500)
        submit=_find_visible([
            google.locator("#passwordNext"),
            google.get_by_role("button",name=re.compile(r"^Next$|^다음$",re.I)),
        ],timeout_ms=4500)
        if not submit:
            raise RemoteGoogleLoginError("GOOGLE_LOGIN_PAGE_UNAVAILABLE")
        _check_google_host(google)
        submit.click(timeout=9000)

        while time.monotonic()<deadline:
            # Read only the ChatGPT session from the ChatGPT origin.
            for chat in reversed(context.pages):
                if chat.is_closed() or not chat.url.startswith("https://chatgpt.com/"):
                    continue
                try:
                    authenticated=read_browser_email(chat)
                    if authenticated:
                        if authenticated!=email:
                            raise RemoteGoogleLoginError("GOOGLE_LOGIN_WRONG_ACCOUNT")
                        return authenticated
                except RemoteGoogleLoginError:
                    raise
                except Exception:
                    pass
            time.sleep(1)
    # Extra verification cannot be automated or bypassed; preserve the
    # page so the user can approve Google's prompt on their own device.
    raise RemoteGoogleLoginError("GOOGLE_ADDITIONAL_VERIFICATION_REQUIRED")


def recheck_google_session(expected_email:str) -> str | None:
    """Re-read the original ChatGPT session after user-approved MFA."""
    from playwright.sync_api import sync_playwright
    from w2a_account_runtime import read_browser_email
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        if not browser.contexts:
            return None
        for page in browser.contexts[0].pages:
            if page.is_closed() or not page.url.startswith("https://chatgpt.com/"):
                continue
            try:
                email=read_browser_email(page)
                if email==expected_email:
                    return email
            except Exception:
                pass
    return None
