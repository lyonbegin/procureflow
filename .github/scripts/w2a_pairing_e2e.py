#!/usr/bin/env python3
"""Signed registered-account pairing + real external Bearer ChatGPT QA.

workflow_dispatch input is read from the runner event JSON without echo.
For the initial on-push smoke, a fresh synthetic HITEL browser cookie is used
and the challenge is linked by real GitHub OIDC + actual ChatGPT session email.
This does not require approved OpenAI OAuth or leak Chrome credentials.
"""
from __future__ import annotations
import http.cookiejar
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
from w2a_account_runtime import read_browser_email,canonical_email
from w2a_relay_worker import get_oidc_token

BASE="https://hitel-integration-api-production.up.railway.app"


def request(opener,method,path,body=None,headers=None):
    data=json.dumps(body,ensure_ascii=False,separators=(",",":")).encode() if body is not None else None
    head={"Accept":"application/json","Cache-Control":"no-store"}
    if data is not None:head["Content-Type"]="application/json"
    head.update(headers or {})
    req=urllib.request.Request(BASE+path,data=data,method=method,headers=head)
    try:
        with opener.open(req,timeout=25) as result:
            return result.status,json.load(result)
    except urllib.error.HTTPError as exc:
        # Never print response contents (could include a session identifier).
        raise RuntimeError("INTEGRATION_API_HTTP_"+str(exc.code)+"_"+path.split("/")[-1]) from None


def actual_session_email():
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp("http://127.0.0.1:9222",timeout=20000)
        ctx=browser.contexts[0]
        page=ctx.new_page()
        try:
            page.goto("https://chatgpt.com/",wait_until="domcontentloaded",timeout=45000)
            for _ in range(15):
                email=read_browser_email(page)
                if email:
                    return canonical_email(email)
                time.sleep(1)
        finally:
            page.close()
    raise RuntimeError("NO_VERIFIED_CHATGPT_SESSION_EMAIL")


def workflow_input():
    path=os.environ.get("GITHUB_EVENT_PATH","")
    if not path or not Path(path).is_file():
        return None
    event=json.loads(Path(path).read_text(encoding="utf-8"))
    value=(event.get("inputs") or {}).get("pairing_code")
    return value.strip() if isinstance(value,str) and value.strip() else None


def main():
    # This check is rerun before using a session email. The workflow itself
    # already checked the live session against the encrypted account registry.
    email=actual_session_email()
    event_code=workflow_input()
    opener=urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    if event_code:
        code=event_code
        csrf=None
        print("PASS_MANUAL_BROWSER_PAIRING_CODE_RECEIVED",flush=True)
    else:
        _,bootstrap=request(opener,"GET","/web/api/bootstrap")
        csrf=bootstrap["csrf"]
        _,challenge=request(opener,"POST","/web/api/integrations/pairing/request",
             {},{"X-Web-Csrf":csrf,"Origin":BASE})
        code=challenge["pairing_code"]
        print("PASS_SYNTHETIC_BROWSER_PAIRING_CHALLENGE_CREATED",flush=True)

    _,attested=request(opener,"POST","/integrations/v1/registration/pair",
        {"pairing_code":code,"verified_session_email":email},
        {"Authorization":"Bearer "+get_oidc_token()})
    if not attested.get("paired") or not attested.get("account_id","").startswith("oai_"):
        raise RuntimeError("ACCOUNT_PAIRING_NOT_ATTESTED")
    account_id=attested["account_id"]
    print("PASS_VERIFIED_CHROME_ACCOUNT_PAIRED_TO_ORIGINAL_BROWSER_OWNER",flush=True)
    if event_code:
        print("PASS_MANUAL_PAIRING_COMPLETE_ISSUE_KEY_IN_BROWSER",flush=True)
        return

    _,key=request(opener,"POST","/web/api/integrations/keys",
          {"name":"Synthetic signed pairing API contract run"},
          {"X-Web-Csrf":csrf,"Origin":BASE})
    if key["account_id"]!=account_id or not key["api_key"].startswith("htli_"):
        raise RuntimeError("BEARER_KEY_NOT_BOUND_TO_PAIRED_ACCOUNT")
    secret=key["api_key"]  # only in RAM, never prints or stores this
    print("PASS_REAL_OWNER_SCOPED_HITEL_BEARER_KEY_ISSUED",flush=True)
    common={"Authorization":"Bearer "+secret}
    _,room=request(opener,"POST","/integrations/v1/rooms",
           {"title":"Signed QA one-shot API session"},common)
    if room["account_id"]!=account_id:
        raise RuntimeError("ROOM_NOT_PINNED_TO_BROWSER_ACCOUNT")
    nonce="HITEL_BEARER_E2E_"+secrets.token_hex(8).upper()
    _,enqueued=request(opener,"POST","/integrations/v1/chat",{
         "room_id":room["room_id"],"account_id":account_id,
         "text":"For this isolated connection check, reply with exactly "+nonce+
                " and nothing else.","attachment_ids":[]},dict(
                common,**{"Idempotency-Key":"pairing-e2e-"+secrets.token_hex(16)}))
    if not enqueued.get("accepted") or enqueued.get("sent_to_chatgpt") is not False:
        raise RuntimeError("API_MESSAGE_NOT_SAFELY_ACCEPTED")
    print("PASS_REAL_EXTERNAL_BEARER_CHAT_JOB_ACCEPTED",flush=True)
    jid=enqueued["job_id"]
    for attempt in range(90):
        time.sleep(2)
        _,job=request(opener,"GET","/integrations/v1/jobs/"+jid,headers=common)
        if job["status"]=="failed":
            print("FAIL_BEARER_CHAT_JOB_STAGE_"+str(job.get("stage","unknown"))[:50],flush=True)
            raise RuntimeError("REAL_BEARER_CHAT_JOB_FAILED")
        if job["status"]=="completed":
            if (job.get("result_text") or "").strip()!=nonce:
                raise RuntimeError("REAL_BEARER_CHAT_WRONG_ASSISTANT_ANSWER")
            _,rooms=request(opener,"GET","/integrations/v1/rooms",headers=common)
            matched=next((r for r in rooms["rooms"] if r["id"]==room["room_id"]),None)
            if not matched or not (matched.get("chatgpt_url") or "").startswith("https://chatgpt.com/c/"):
                raise RuntimeError("REAL_BEARER_CHAT_CONVERSATION_URL_NOT_VERIFIED")
            print("PASS_REAL_EXTERNAL_BEARER_CHATGPT_RESPONSE_AND_ROOM_URL",flush=True)
            try:
                request(opener,"DELETE","/web/api/integrations/keys/"+key["id"],
                        headers={"X-Web-Csrf":csrf,"Origin":BASE})
                print("PASS_QA_API_KEY_REVOKED_AFTER_TEST",flush=True)
            except Exception:
                print("WARN_QA_KEY_REVOCATION_NOT_CONFIRMED",flush=True)
            return
    raise RuntimeError("REAL_BEARER_CHAT_JOB_TIMEOUT")


if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("FAIL_EXTERNAL_BEARER_API_PROOF_"+type(exc).__name__+"_"+str(exc)[:80],flush=True)
        sys.exit(1)
