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

def _read_original_for_n03(base,run_id,file):
    """Fetch a saved N02 original only for N09 AI final evaluation."""
    from n03_documents import MAX_ORIGINAL_SIZE,N03SourceError
    size=file.get("size_bytes")
    if not isinstance(size,int) or not 0<size<=MAX_ORIGINAL_SIZE:
        raise N03SourceError("N03_ORIGINAL_SIZE_INVALID")
    source=base+"/api/procurement/public9/action-original?"+urlencode({
        "run_id":run_id,"file_seq":file["file_seq"]})
    req=Request(source,headers={
        "Authorization":"Bearer "+_get_oidc(base),
        "User-Agent":"ProcureFlow-GitHub-Actions-N09"})
    digest=sha256()
    parts=[]
    received=0
    with urlopen(req,timeout=60) as response:
        if response.status!=200:
            raise N03SourceError("N03_SAVED_ORIGINAL_READ_HTTP_"+str(response.status))
        while (chunk:=response.read(1024*1024)):
            received+=len(chunk)
            if received>size or received>MAX_ORIGINAL_SIZE:
                raise N03SourceError("N03_SAVED_ORIGINAL_OVERFLOW")
            parts.append(chunk)
            digest.update(chunk)
    if received!=size or digest.hexdigest()!=file.get("sha256"):
        raise N03SourceError("N03_SAVED_ORIGINAL_SHA256_MISMATCH")
    return b"".join(parts)

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
    # N03–N08 are collection-only. No HWP/PDF interpretation, company
    # eligibility judgments, competitive predictions, pricing or Word drafts.
    if stage=="N03":
        from collect_only_stages import n03_metadata
        opener=live._client();live._once(opener)
        status,value=n03_metadata(opener,notice,live._json_post,live,live._now().date())
        return status,{"selected_bid_no":(notice or {}).get("bid_no"),
            "selected_bid_ord":(notice or {}).get("bid_ord"),
            "request":"official_exact_number_metadata_only"},value
    if stage=="N04":
        from collect_only_stages import n04_history
        opener=live._client();live._once(opener)
        status,value=n04_history(opener,notice,previous.get("N03"),
                                  live._json_post,live,live._now().date())
        return status,{"selected_bid_no":(notice or {}).get("bid_no"),
            "detail10":(previous.get("N03") or {}).get("detail10"),
            "initial_years":3,"target_records":50,
            "max_years":10,"requested_period":"three_years_extend_one_year_until_50"},value
    if stage=="N05":
        from collect_only_stages import n05_openings
        opener=live._client();live._once(opener)
        status,value=n05_openings(opener,previous.get("N04"),
                                  live._json_post,live._now().date())
        return status,{"N04_verified_historical_records":
            (previous.get("N04") or {}).get("verified_record_count",0)},value
    if stage=="N06":
        from collect_only_stages import n06_supply_catalog
        status,value=n06_supply_catalog(notice,collection,
                          previous.get("N04"),previous.get("N05"))
        return status,{"N02_original_file_count":len(docs),
            "request":"collect_supplier_workforce_source_catalog_only"},value
    if stage=="N07":
        from collect_only_stages import n07_price_sources
        status,value=n07_price_sources(notice,previous.get("N03"),
                     previous.get("N04"),previous.get("N05"),previous.get("N06"))
        return status,{"source":"N01_N03_N04_N05_N06_official_source_records"},value
    if stage=="N08":
        from collect_only_stages import n08_handoff
        status,value=n08_handoff(notice,previous)
        return status,{"source":"N01_N07_collected_unassessed_evidence"},value
    if stage=="N09":
        from n09_final_ai import evaluate
        def read_original(file):
            return _read_original_for_n03(base,context["run_id"],file)
        status,value=evaluate(previous,read_original,live._extract)
        return status,{"source":"N08_bundle_and_N02_originals",
             "request":"first_and_only_AI_business_evaluation",
             "original_count":len(docs)},value
    raise ValueError("UNKNOWN_GITHUB_NODE_STAGE")

def _safe_collected_counts(stage,status,output):
    """Non-sensitive audit only: actual source counts and missing connectors.

    Do not print source documents, model prompts, tokens, company identifiers,
    personal data, original filenames or bidder identities into Actions logs.
    """
    result={"stage":stage,"status":status}
    if not isinstance(output,dict):return result
    if stage=="N01":
        result["selected_bid_no"]=str(output.get("bid_no") or "")[:30]
        result["official_fields_verified"]=bool(output.get("official_fields_verified"))
    elif stage=="N02":
        result["file_count"]=output.get("file_count")
        result["official_inventory_complete"]=bool(output.get("official_attachment_inventory_complete"))
    elif stage=="N03":
        result["official_record_found"]=bool(output.get("official_selected_record_found"))
        result["detail10_verified"]=bool(output.get("detail10_verified"))
        result["official_field_count"]=len(output.get("official_fields") or {})
    elif stage=="N04":
        result["periods_checked"]=len(output.get("periods_checked") or [])
        result["periods_requested"]=output.get("periods_requested")
        result["target_records"]=output.get("target_records",50)
        result["target_reached"]=bool(output.get("target_reached"))
        result["years_expanded"]=output.get("years_expanded")
        result["candidate_records"]=output.get("candidate_record_count",0)
        result["verified_history_records"]=output.get("verified_record_count",0)
    elif stage=="N05":
        result["history_candidates"]=output.get("candidates",0)
        result["opening_queries_checked"]=output.get("checked",0)
        result["opening_records"]=len(output.get("opening_records") or [])
    elif stage=="N06":
        result["supplier_quotations"]=output.get("supplier_quotation_original_count",0)
        result["company_workforce_originals"]=output.get("company_workforce_original_count",0)
    elif stage=="N07":
        result["collected_amount_fields"]=len(output.get("source_amounts") or [])
        result["recommended_bid_generated"]=output.get("recommended_bid") is not None
    elif stage=="N08":
        result["handoff_assembled"]=bool(output.get("handoff_assembled") or output.get("handoff_bundle"))
        result["bundled_originals"]=output.get("source_originals",0)
        result["upstream_gaps_preserved"]=len(output.get("collection_gaps") or [])
    elif stage=="N09":
        result["ai_evaluation_performed"]=bool(output.get("ai_evaluation_performed"))
        result["ai_not_run_reason"]=str(output.get("reason") or "")[:70]
    gaps=output.get("gaps") or output.get("collection_gaps") or []
    result["missing_source_count"]=len(gaps)
    return result

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
    print("GITHUB_ACTION_NODE_EVIDENCE_COUNTS",json.dumps(_safe_collected_counts(stage,status,output),ensure_ascii=False),flush=True)
    print("GITHUB_ACTION_NODE_DONE",json.dumps({"stage":stage,"status":status,
          "run_id":run_id,"github_run_id":result["github_run_id"]},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
