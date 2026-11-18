#!/usr/bin/env python3
"""Run signed, synthetic ChatGPT relay QA through the actual Railway API.

Only the fixed synthetic prompt from the authenticated server is ever sent.
Never logs cookies, OAuth/OIDC tokens, profile emails, or ChatGPT answer text.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

from w2a_relay_worker import get_oidc_token

HOST="https://hitel-integration-api-production.up.railway.app"
PREFIX="/integrations/v1/qa/bridge"


def call(method,path):
    token=get_oidc_token()
    req=urllib.request.Request(HOST+PREFIX+path,
        data=b"" if method=="POST" else None,method=method,
        headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=20) as resp:
            return resp.status,json.load(resp)
    except urllib.error.HTTPError as exc:
        print("BRIDGE_QA_HTTP_ERROR="+str(exc.code),flush=True)
        return exc.code,{}


def main():
    for retry in range(30):
        try:
            code,j=call("POST","/once")
        except Exception as exc:
            print("BRIDGE_QA_RELAY_WAIT_"+type(exc).__name__,flush=True)
            time.sleep(2);continue
        if code==503:
            time.sleep(2);continue
        if code!=201:raise SystemExit("FAIL_BRIDGE_QA_CREATION_"+str(code))
        break
    else:raise SystemExit("FAIL_BRIDGE_QA_WORKER_NOT_CONNECTED")
    job_id=j["job_id"]
    print("PASS_SIGNED_RAILWAY_QA_JOB_ACCEPTED",flush=True)
    for _ in range(75):
        time.sleep(2)
        code,j=call("GET","/jobs/"+job_id)
        if code!=200:raise SystemExit("FAIL_BRIDGE_QA_POLL_"+str(code))
        if j.get("status") in ("completed","failed"):
            print("RELAY_QA_JOB_STATUS="+j["status"],flush=True)
            print("RELAY_QA_REPLY_MARKER_MATCH="+str(int(j["reply_matches_expected_marker"])),flush=True)
            print("RELAY_QA_CONVERSATION_URL_VERIFIED="+str(int(j["conversation_url_verified"])),flush=True)
            if j.get("error_type"):print("RELAY_QA_ERROR_CLASS="+j["error_type"],flush=True)
            if j.get("end_to_end_pass"):
                print("PASS_REAL_CHATGPT_SERVER_WORKER_RESPONSE_E2E",flush=True)
                return
            raise SystemExit("FAIL_REAL_CHATGPT_BRIDGE_PROBE")
    raise SystemExit("FAIL_REAL_CHATGPT_BRIDGE_TIMEOUT")


if __name__=="__main__":
    main()
