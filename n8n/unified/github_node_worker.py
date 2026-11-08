"""GitHub-hosted executor for PF00 N01..N09. NEVER run this on Railway.

Data exchange: authenticated GitHub Actions OIDC -> Railway control-plane.
No fake competitiveness, qualification, cost, or pricing decisions.
"""
from __future__ import annotations
import base64
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json,os,sys,time
from pathlib import Path
from urllib.parse import quote,urlencode
from urllib.request import Request,urlopen

STAGES=tuple("N%02d"%i for i in range(1,10))
ROOT="https://procureflow-unified-studio-candidate-production.up.railway.app"
MAX_JSON=4_000_000
CHUNK=2*1024*1024

def _get_oidc(base):
    url=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
    auth=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not auth:raise RuntimeError("GITHUB_ACTIONS_OIDC_REQUIRED")
    separator="&" if "?" in url else "?"
    token_url=url+separator+"audience="+quote("procureflow-action-worker",safe="")
    request=Request(token_url,headers={"Authorization":"Bearer "+auth})
    with urlopen(request,timeout=15) as response:
        data=json.loads(response.read(16000))
    return data["value"]

def _api(base,path,body=None,raw=False,extra=None):
    headers={"Authorization":"Bearer "+_get_oidc(base),"Accept":"application/json",
             "User-Agent":"ProcureFlow-GitHub-Actions-Node/1"}
    if raw:
        payload=body
        headers["Content-Type"]="application/octet-stream"
    elif body is not None:
        payload=json.dumps(body,ensure_ascii=False,separators=(",",":")).encode("utf-8")
        if len(payload)>MAX_JSON:raise ValueError("NODE_RESULT_TOO_LARGE")
        headers["Content-Type"]="application/json"
    else:payload=None
    headers.update(extra or {})
    request=Request(base+path,data=payload,headers=headers,method="POST" if payload is not None else "GET")
    with urlopen(request,timeout=50) as response:
        data=response.read(MAX_JSON+1)
    if len(data)>MAX_JSON:raise ValueError("RELAY_JSON_TOO_LARGE")
    return json.loads(data) if data else {}

def _upload(base,run_id,file):
    path=Path(file["saved_path"])
    size=path.stat().st_size
    if size!=file["size_bytes"]:raise ValueError("N02_UPLOAD_SIZE_MISMATCH")
    digest=sha256()
    chunk_no=0
    with path.open("rb") as stream:
        while (part:=stream.read(CHUNK)):
            digest.update(part)
            headers={"X-Procureflow-Run":run_id,"X-Procureflow-Stage":"N02",
                "X-Procureflow-File-Seq":str(file["file_seq"]),
                "X-Procureflow-Chunk":str(chunk_no),
                "X-Procureflow-File-Name":base64.urlsafe_b64encode(file["original_filename"].encode()).decode(),
                "X-Procureflow-File-Size":str(size),
                "X-Procureflow-File-Sha256":file["sha256"]}
            answer=_api(base,"/api/procurement/public9/action-file",part,raw=True,extra=headers)
            if answer.get("accepted") is not True:raise ValueError("N02_UPLOAD_NOT_ACCEPTED")
            chunk_no+=1
    if digest.hexdigest()!=file["sha256"]:raise ValueError("N02_UPLOAD_SOURCE_HASH_MISMATCH")
    return chunk_no

def _download_saved(base,run_id,file):
    query=urlencode({"run_id":run_id,"file_seq":file["file_seq"]})
    headers={"Authorization":"Bearer "+_get_oidc(base),"User-Agent":"ProcureFlow-GitHub-Actions-N09"}
    req=Request(base+"/api/procurement/public9/action-original?"+query,headers=headers)
    digest=sha256();size=0
    with urlopen(req,timeout=45) as response:
        while (block:=response.read(1024*1024)):
            size+=len(block);digest.update(block)
            if size>150*1024*1024:raise ValueError("N09_ORIGINAL_EXCEEDS_LIMIT")
    return size==file["size_bytes"] and digest.hexdigest()==file["sha256"]

def execute(stage,context,base=ROOT):
    """One independent GitHub Actions stage; result has only genuine evidence."""
    import live_nine_test as live
    previous=context.get("outputs") or {}
    notice=context.get("selected_notice") or previous.get("N01")
    collection=previous.get("N02") or {}
    docs=collection.get("files") or []
    inputs={"source":"official_g2b_live_site","stage":stage}
    if stage=="N01":
        import n01_auto
        ledger=context.get("completion_journal") or {"version":1,"records":{}}
        tmp=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"n01_gha_journal.json"
        n01_auto.LEDGER_PATH=tmp
        tmp.write_text(json.dumps(ledger,ensure_ascii=False),encoding="utf-8")
        opener=live._client();live._once(opener)
        value=live._official_g2b_search(opener)
        status="verified" if value.get("search_request_verified") and value.get("official_fields_verified") else "partial"
        return status,{"mode":"newest_incomplete_auto"},value
    if stage=="N02":
        if not notice or not notice.get("bid_no"):
            return "blocked",inputs,{"error":"N02_SELECTED_NOTICE_REQUIRED"}
        import n02_collect
        opener=live._client();live._once(opener)
        n02_collect.STORAGE_ROOT=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"procureflow-originals"
        value=n02_collect.collect(opener,notice)
        for file in value["files"]:_upload(base,context["run_id"],file)
        status="verified" if value.get("official_attachment_inventory_complete") else ("partial" if docs or value.get("files") else "source_error")
        inputs={"bid_no":notice["bid_no"],"bid_ord":notice.get("bid_ord","000"),"request":"collect_all_official_attachments"}
        # Raw runner paths MUST NOT be persisted. The Railway callback replaces
        # each runner path with its independently verified persistent path.
        for file in value["files"]:file.pop("saved_path",None)
        value["storage_folder"]=None
        value["manifest_path"]=None
        return status,inputs,value
    if stage=="N03":
        value={"status":"DEFERRED_TO_FINAL_ORIGINAL_FILE_EVALUATION",
          "source":"N02_official_attachment_manifest",
          "downloaded_files":len(docs),
          "original_file_names":[f.get("original_filename") for f in docs],
          "company_eligibility":"NOT_VERIFIED_NO_COMPANY_ORIGINAL",
          "company_eligibility_verified":False,"analysis_performed":False}
        return ("partial" if docs else "blocked"),{"N02_original_file_count":len(docs)},value
    if stage=="N04":
        if not notice or not notice.get("bid_no"):
            return "blocked",inputs,{"error":"N04_SELECTED_NOTICE_REQUIRED"}
        opener=live._client();live._once(opener)
        value=live._live_openings(opener,notice)
        return "partial",{"selected_bid_no":notice["bid_no"],"selected_bid_ord":notice["bid_ord"]},value
    if stage=="N05":
        h=previous.get("N04") or {}
        return "blocked",{"N04_status":h.get("query_result")},{
           "source":"N04_official_selected_notice_opening",
           "raw_opening_rows":h.get("official_rows"),
           "exact10_matched_competitors":None,"confirmed_awards":None,
           "status":"HOLD_ORIGINAL_10DIGIT_MATCH_UNVERIFIED"}
    if stage=="N06":
        return "blocked",{"N02_docs":len(docs)},{
          "status":"MISSING_COMPANY_COST_EVIDENCE",
          "source":"official_tender_attachment_only",
          "bid_budget":(notice or {}).get("budget"),
          "verified_company_cost":None}
    if stage=="N07":
        return "blocked",{"N03":previous.get("N03"),"N06":previous.get("N06")},{
          "status":"NO_PRICE_RECOMMENDATION",
          "bid_budget":(notice or {}).get("budget"),
          "eligibility_verified":False,"cost_verified":False,
          "recommended_bid":None}
    if stage=="N08":
        raw=live._document(notice,docs,previous.get("N03"),
                           previous.get("N04"),previous.get("N05"),
                           previous.get("N06"),previous.get("N07"))
        return "partial",{"source":"N01-N07_GITHUB_ACTIONS_RESULTS"},{
          "draft_generated":True,"bytes":len(raw),
          "sha256":sha256(raw).hexdigest(),"draft_only":True,
          "_document_base64":base64.b64encode(raw).decode("ascii")}
    if stage=="N09":
        results=[]
        for file in docs:
            verified=_download_saved(base,context["run_id"],file)
            results.append({"file_seq":file["file_seq"],"integrity_verified":verified})
        valid=bool(results) and all(x["integrity_verified"] for x in results)
        statuses=context.get("statuses") or {}
        return "partial",{"stage_count":8,"N02_original_file_count":len(docs)},{
          "verified_steps":sum(x=="verified" for x in statuses.values()),
          "blocked_steps":sum(x=="blocked" for x in statuses.values()),
          "source_errors":sum(x=="source_error" for x in statuses.values()),
          "N02_persistent_file_handoff":{
              "verified_saved_original_count":sum(x["integrity_verified"] for x in results),
              "original_files_integrity_verified":valid,
              "file_checks":results,
              "content_analysis_performed":False},
          "db_reads":0,"worker_calls":0,
          "bid_submitted":False,"final_bid_approval":False}
    raise ValueError("UNKNOWN_GITHUB_NODE_STAGE")

def main():
    run_id=os.environ.get("PROCUREFLOW_RUN_ID","")
    stage=os.environ.get("PROCUREFLOW_STAGE","")
    base=os.environ.get("PROCUREFLOW_RELAY_URL",ROOT).rstrip("/")
    if stage not in STAGES or len(run_id)!=32 or not all(c in "0123456789abcdef" for c in run_id):
        raise SystemExit("INVALID_GITHUB_STAGE_REQUEST")
    context=_api(base,"/api/procurement/public9/action-input?"+
                 urlencode({"run_id":run_id,"stage":stage}))
    if context.get("run_id")!=run_id or context.get("stage")!=stage:
        raise SystemExit("STAGE_CONTEXT_MISMATCH")
    try:
        status,inp,output=execute(stage,context,base)
    except Exception as error:
        status="source_error"
        inp={"source":"github_actions","stage":stage}
        output={"error":type(error).__name__+":"+str(error)[:180],
                "source":"GITHUB_ACTIONS_STAGE"}
    result={"run_id":run_id,"stage":stage,"status":status,
            "input":inp,"output":output,
            "github_run_id":os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt":os.environ.get("GITHUB_RUN_ATTEMPT")}
    _api(base,"/api/procurement/public9/action-result",result)
    print("GITHUB_ACTION_NODE_DONE",json.dumps({"stage":stage,"status":status,
          "run_id":run_id,"github_run_id":result["github_run_id"]},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
