#!/usr/bin/env python3
"""Fallback only: signed GitHub runner restarts itself if verified work remains.

Requires job-specific GITHUB_TOKEN with Actions:write on same repository.
The Railway server first reserves a singleton lease via exact workflow OIDC.
No ChatGPT prompts, account data or GitHub secrets are logged.
"""
import json
import os
import urllib.error
import urllib.request

from w2a_relay_worker import get_oidc_token

ROOT="https://hitel-integration-api-production.up.railway.app"
GITHUB="https://api.github.com/repos/lyonbegin/procureflow/actions/workflows/hitel-integration-bridge-live-qa.yml/dispatches"


def main():
    grant_req=urllib.request.Request(
        ROOT+"/integrations/v1/qa/bridge/worker-fallback",
        data=b"{}",method="POST",
        headers={"Authorization":"Bearer "+get_oidc_token(),
                 "Accept":"application/json","Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(grant_req,timeout=18) as r:
            data=json.load(r)
    except (urllib.error.URLError,TimeoutError,OSError):
        print("WORKER_FALLBACK_RAILWAY_STATUS_UNAVAILABLE",flush=True)
        return
    if data.get("relaunch_authorized") is not True:
        print("PASS_WORKER_FALLBACK_NO_PENDING_RESTART",flush=True)
        return
    key=os.environ.get("GH_TOKEN","")
    if not key:
        print("FAIL_WORKER_FALLBACK_ACTIONS_TOKEN_NOT_AVAILABLE",flush=True)
        return
    body=json.dumps({
        "ref":"main","inputs":{
          "operation":"worker_only",
          "run_minutes":"240","pairing_code":""
        }},separators=(",",":")).encode()
    req=urllib.request.Request(GITHUB,data=body,method="POST",headers={
        "Authorization":"Bearer "+key,
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "Content-Type":"application/json",
        "User-Agent":"HITEL-Chrome-Runner-Self-Restart",
    })
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            if r.status not in (201,204):
                raise RuntimeError("WORKFLOW_DISPATCH_RESPONSE_UNCONFIRMED")
            print("PASS_SIGNED_GITHUB_WORKER_SELF_RESTART_DISPATCHED",flush=True)
    except urllib.error.HTTPError as e:
        print("FAIL_WORKER_FALLBACK_DISPATCH_HTTP_"+str(e.code),flush=True)
    except Exception as exc:
        print("FAIL_WORKER_FALLBACK_DISPATCH_"+type(exc).__name__,flush=True)


if __name__=="__main__":
    main()
