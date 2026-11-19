#!/usr/bin/env python3
"""Self-continue signed Chrome worker only while an existing 18,109-row
classification workflow is actively running. Never sends a ChatGPT prompt.

GitHub-hosted workers are finite sessions. This is a push/workflow self-handoff,
not a cron, Railway service, or always-on paid worker. It stops when the corpus
workflow has completed or failed and does not restart unknown requests.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request

CORPUS_RUNS=("https://api.github.com/repos/lyonbegin/hitel-scribd-runner/"
             "actions/workflows/hitel-public-ai-corpus.yml/runs?per_page=5")
WORKER_RUNS=("https://api.github.com/repos/lyonbegin/procureflow/"
             "actions/workflows/hitel-integration-bridge-live-qa.yml/runs?per_page=12")
DISPATCH=("https://api.github.com/repos/lyonbegin/procureflow/"
          "actions/workflows/hitel-integration-bridge-live-qa.yml/dispatches")
ACTIVE=frozenset(("queued","in_progress","pending","waiting","requested"))
HEADERS={"Accept":"application/vnd.github+json",
         "User-Agent":"HITEL-Corpus-Active-Worker-Self-Continuation",
         "X-GitHub-Api-Version":"2022-11-28"}

def get_json(url):
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=20) as response:
        return json.load(response)

def main():
    if os.environ.get("GITHUB_REPOSITORY")!="lyonbegin/procureflow":
        raise RuntimeError("REFUSE_UNEXPECTED_WORKER_REPOSITORY")
    try:
        corpus=get_json(CORPUS_RUNS)
        runs=corpus.get("workflow_runs") or []
        if not runs or runs[0].get("status") not in ACTIVE:
            print("PASS_CORPUS_WORKER_CONTINUATION_NOT_RUNNING",flush=True)
            return
        worker=get_json(WORKER_RUNS)
    except (urllib.error.URLError,TimeoutError,ValueError):
        print("CORPUS_WORKER_CONTINUATION_STATUS_UNAVAILABLE_NO_DISPATCH",flush=True)
        return
    own=str(os.environ.get("GITHUB_RUN_ID",""))
    active_others=[r for r in worker.get("workflow_runs",[])
                   if str(r.get("id"))!=own and r.get("status") in ACTIVE]
    if active_others:
        print("PASS_CORPUS_WORKER_CONTINUATION_ALREADY_QUEUED",flush=True)
        return
    token=os.environ.get("GH_TOKEN","")
    if not token:
        print("FAIL_CORPUS_WORKER_CONTINUATION_ACTIONS_TOKEN_MISSING",flush=True)
        return
    body=json.dumps({"ref":"main","inputs":{
        "operation":"worker_only","run_minutes":"240","pairing_code":""
    }}).encode("utf-8")
    req=urllib.request.Request(DISPATCH,data=body,method="POST",headers={
        **HEADERS,"Authorization":"Bearer "+token,
        "Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=20) as resp:
            if resp.status not in (200,201,204):
                raise RuntimeError("UNCONFIRMED_DISPATCH_HTTP_STATUS")
            print("PASS_CORPUS_ACTIVE_SIGNED_WORKER_CONTINUATION_DISPATCHED",flush=True)
    except urllib.error.HTTPError as exc:
        print("FAIL_CORPUS_WORKER_CONTINUATION_HTTP_"+str(exc.code),flush=True)
    except (urllib.error.URLError,TimeoutError,OSError):
        print("FAIL_CORPUS_WORKER_CONTINUATION_TRANSPORT",flush=True)

if __name__=="__main__":
    main()
