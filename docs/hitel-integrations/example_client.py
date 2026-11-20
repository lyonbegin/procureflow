#!/usr/bin/env python3
"""HITEL integration API example. Do not commit credentials or cookies.

Environment:
  HITEL_BASE_URL=https://<verified-server-domain>
  HITEL_API_KEY=htli_<one-time-secret>
  HITEL_ACCOUNT_ID=oai_<selected-account>
Runs one synthetic text question. Polls its job without resending.
"""
from __future__ import annotations
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request


def required(key):
    value=os.environ.get(key,"").strip()
    if not value:
        raise SystemExit("Missing required environment variable: "+key)
    return value


BASE=required("HITEL_BASE_URL").rstrip("/")
SECRET=required("HITEL_API_KEY")
ACCOUNT=required("HITEL_ACCOUNT_ID")


def call(method,path,body=None,key=None):
    raw=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
    headers={"Accept":"application/json","Authorization":"Bearer "+SECRET}
    if raw is not None:
        headers["Content-Type"]="application/json"
    if key:
        headers["Idempotency-Key"]=key
    req=urllib.request.Request(BASE+path,method=method,
                               headers=headers,data=raw)
    try:
        with urllib.request.urlopen(req,timeout=30) as res:
            return res.status,json.load(res)
    except urllib.error.HTTPError as exc:
        # Never print complete response headers or confidential request data.
        raise SystemExit(f"HTTP {exc.code} at {path}") from None


def main():
    _, room=call("POST","/integrations/v1/rooms",
                 {"title":"HITEL API 합성 시험방"})
    rid=room["room_id"]
    idempotency="example-"+secrets.token_hex(16)
    code,accepted=call("POST","/integrations/v1/chat",{
        "room_id":rid,"account_id":ACCOUNT,
        "text":"HITEL API 연결 시험입니다. 짧게 인사해 주십시오.",
        "attachment_ids":[],
    },idempotency)
    if code!=202:
        raise SystemExit("Job was not accepted")
    jid=accepted["job_id"]
    print("Accepted job:",jid,"worker:",accepted["worker_connected"])
    for _ in range(12):
        _,job=call("GET","/integrations/v1/jobs/"+jid)
        if job["status"]=="completed":
            print("Verified assistant response:",job.get("result_text"))
            return 0
        if job["status"]=="failed":
            print("Job failed:",job.get("error"))
            return 1
        time.sleep(3)
    print("Job has not completed; poll again later with the SAME job_id:",jid)
    return 2


if __name__=="__main__":
    sys.exit(main())
