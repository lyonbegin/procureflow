#!/usr/bin/env python3
"""Real HTTPS file-scenario API client for pinned GitHub Actions workflow.

init: obtain signed GitHub OIDC -> POST /runs -> multipart upload two fixed
synthetic files -> GET exact stored bytes -> verify sha256 -> local staging.
submit: POST actual Playwright test statuses, no credentials or response text.

The private ChatGPT profile, auth cookies and real chat text are never sent.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE="https://hitel-integration-api-production.up.railway.app"
AUD="urn:lyonbegin:procureflow:hitel-file-scenario-api"
ROOT=Path(os.environ["RUNNER_TEMP"])
STATE=ROOT/"hitel_file_api_state.json"
INPUTS=ROOT/"w2a-file-api-inputs"
INPUTS.mkdir(mode=0o700,parents=True,exist_ok=True)


def oidc_token():
    url=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL","")
    bearer=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN","")
    if not url.startswith("https://") or not bearer:
        raise RuntimeError("ACTIONS_OIDC_NOT_AVAILABLE")
    address=url+("&" if "?" in url else "?")+urllib.parse.urlencode({"audience":AUD})
    req=urllib.request.Request(address,
        headers={"Authorization":"Bearer "+bearer,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=15) as r:
        token=json.load(r).get("value")
    if not isinstance(token,str) or len(token)<50:
        raise RuntimeError("ACTIONS_OIDC_EMPTY")
    return token


def call(method,path,token,payload=None,content_type=None):
    address=BASE+path
    if not address.startswith(BASE+"/integrations/v1/scenarios/files/"):
        raise RuntimeError("FILE_SCENARIO_UNTRUSTED_DESTINATION")
    headers={"Authorization":"Bearer "+token,"Accept":"application/json"}
    if content_type: headers["Content-Type"]=content_type
    req=urllib.request.Request(address,data=payload,method=method,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=30) as res:
            return res.status,res.read(),dict(res.headers)
    except urllib.error.HTTPError as e:
        raise RuntimeError("FILE_API_HTTP_"+str(e.code)) from None


def parse(data):
    return json.loads(data.decode("utf-8"))


def multipart(name,body):
    boundary="hitel-synth-"+secrets.token_hex(16)
    header=(f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n").encode()
    payload=header+body+f"\r\n--{boundary}--\r\n".encode()
    return payload,"multipart/form-data; boundary="+boundary


def init():
    token=oidc_token()
    code,raw,_=call("POST","/integrations/v1/scenarios/files/runs",token,payload=b"",
                    content_type="application/json")
    if code!=201:raise RuntimeError("SYNTHETIC_RUN_NOT_CREATED")
    run=parse(raw)
    rid=run["run_id"]
    if not rid.startswith("frun_"):raise RuntimeError("INVALID_SCENARIO_RUN_ID")
    proof={}
    for role in ("txt","csv"):
        manifest=run["manifest"][role]
        data=manifest["body"].encode("utf-8")
        packet,ctype=multipart(manifest["name"],data)
        status,answer,_=call(
            "POST",f"/integrations/v1/scenarios/files/runs/{rid}/files/{role}",
            token,payload=packet,content_type=ctype)
        receipt=parse(answer)
        expected_hash=hashlib.sha256(data).hexdigest()
        if status!=200 or receipt["sha256"]!=expected_hash:
            raise RuntimeError("FILE_API_UPLOAD_HASH_NOT_VERIFIED_"+role.upper())
        code,down,headers=call(
            "GET",f"/integrations/v1/scenarios/files/runs/{rid}/files/{role}/content",
            token)
        if code!=200 or down!=data or hashlib.sha256(down).hexdigest()!=expected_hash:
            raise RuntimeError("FILE_API_DOWNLOAD_BYTES_MISMATCH_"+role.upper())
        if {str(k).lower():v for k,v in headers.items()}.get("x-synthetic-sha256")!=expected_hash:
            raise RuntimeError("FILE_API_DOWNLOAD_HASH_HEADER_MISMATCH_"+role.upper())
        saved=INPUTS/manifest["name"]
        saved.write_bytes(down)
        proof[role]={"sha256":expected_hash,"size":len(down)}
        print("PASS_FILE_API_"+role.upper()+"_UPLOAD_DOWNLOAD_SHA256",flush=True)
    state={"run_id":rid,"marker":run["manifest"]["txt"]["body"].split("=",1)[1].split("\n")[0],
           "files":proof,"transport":{
             "uploaded_via_api":True,
             "downloaded_via_api":True,
             "sha256_match":True,
             "saved_chatgpt_account_verified":False}}
    STATE.write_text(json.dumps(state),encoding="utf-8")
    print("PASS_REAL_HTTPS_FILE_API_ROUNDTRIP",flush=True)


def submit():
    if not STATE.is_file():
        raise RuntimeError("FILE_API_SCENARIO_RUN_NOT_CREATED")
    state=json.loads(STATE.read_text())
    source=ROOT/"hitel_file_scenario_results.json"
    if source.is_file():
        report=json.loads(source.read_text())
        cases=report.get("results",[])
    else:
        names={
          "S08":"Upload synthetic TXT","S09":"Remove unsent TXT attachment",
          "S10":"Ask about TXT content","S15":"Analyze CSV","S11":"Download CSV"
        }
        cases=[{"id":k,"name":v,"status":"BLOCKED",
                "detail":"UPSTREAM_BROWSER_TEST_INTERRUPTED"} for k,v in names.items()]
    verified=(ROOT/"hitel_file_api_chrome_verified").is_file()
    state["transport"]["saved_chatgpt_account_verified"]=verified
    status,raw,_=call(
        "POST",f"/integrations/v1/scenarios/files/runs/{state['run_id']}/results",
        oidc_token(),
        payload=json.dumps({
          "github_run_id":os.environ["GITHUB_RUN_ID"],
          "transport":state["transport"],
          "results":cases
        }).encode("utf-8"),
        content_type="application/json")
    if status!=200:raise RuntimeError("FILE_API_RESULT_REPORT_NOT_SAVED")
    resp=parse(raw)
    print("PASS_FILE_API_RESULT_REPORT_SAVED",flush=True)
    for c in resp["cases"]:
        print("FILE_API_SCENARIO_"+c["id"]+"_"+c["status"]+"="+c["detail"],flush=True)
    print("FILE_API_REPORT_ALL_PASS="+str(int(resp["all_pass"])),flush=True)
    # Persist sanitized result for artifact + step summary, no private content.
    (ROOT/"hitel_file_api_results.json").write_text(
        json.dumps(resp,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return 0 if resp["all_pass"] else 2


def main():
    command=sys.argv[1] if len(sys.argv)>1 else ""
    if command=="init":init();return 0
    if command=="submit":return submit()
    raise SystemExit("Usage: w2a_file_api_client.py init|submit")


if __name__=="__main__":
    try:sys.exit(main())
    except Exception as exc:
        print("FAIL_FILE_API_"+type(exc).__name__+"_"+str(exc)[:80],flush=True)
        sys.exit(1)
