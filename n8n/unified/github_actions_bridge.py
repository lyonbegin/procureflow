"""Lightweight Railway control plane for 9 independent GitHub Actions stages.

Railway DOES NOT crawl, parse, or build documents. It dispatches one node,
accepts authenticated GitHub OIDC results/files, and dispatches the next node.
Workflow UI reads only persistent JSON state. Never use previous DB bid records.
"""
from __future__ import annotations
import base64,copy
from datetime import datetime,timedelta
from hashlib import sha256
import json,os,re,threading,uuid
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

from github_oidc import verify,GitHubOIDCError
from n02_collect import STORAGE_ROOT,_safe_name,_kind

ROOT=Path(os.environ.get("PROCUREFLOW_ACTION_STATE_ROOT","/data/n01/github-actions"))
def _active_path():return ROOT/"active_run.json"
REPO="lyonbegin/procureflow"
BRANCH=os.environ.get("PROCUREFLOW_ACTIONS_REF","main")
WORKFLOW="procureflow-node.yml"
STAGES=tuple("N%02d"%n for n in range(1,10))
TITLES=("공고 직접 조회","첨부 원본 다운로드","자격·원문 조건",
        "개찰 원본 직접 조회","경쟁 정보 분석","수행·원가 근거",
        "가격전략 검증","Word 검토 초안","독립 최종 검증")
LOCK=threading.RLock()
MAX_STATE=2_000_000
MAX_UPLOAD_CHUNK=2*1024*1024+1024

def _now():return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
def _sid(sid):return sha256(str(sid).encode()).hexdigest()
def _run_path(run_id):
    if not re.fullmatch(r"[0-9a-f]{32}",str(run_id)):
        raise ValueError("INVALID_ACTION_RUN_ID")
    return ROOT/"runs"/(run_id+".json")
def _atomic(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name("."+uuid.uuid4().hex+".tmp")
    try:
        temp.write_text(json.dumps(obj,ensure_ascii=False,separators=(",",":"),default=str),encoding="utf-8")
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)
def _read(path,default=None):
    if not path.exists():return default
    return json.loads(path.read_text(encoding="utf-8"))
def _state(run_id):
    run=_read(_run_path(run_id))
    if not isinstance(run,dict):raise LookupError("GH_ACTION_RUN_NOT_FOUND")
    return run
def _public(run):
    return {**{k:v for k,v in run.items()
            if k not in ("session_hash","uploads","dispatch_token","_private")},
            "dispatch_ready":bool(os.environ.get("PROCUREFLOW_GITHUB_DISPATCH_TOKEN","").strip())}
def _session_path(sid):return ROOT/"sessions"/(_sid(sid)+".json")
def _find_session(sid):
    session=_read(_session_path(sid),{}) or {}
    rid=session.get("run_id")
    return _state(rid) if rid else None
def _dispatch(run,stage):
    token=os.environ.get("PROCUREFLOW_GITHUB_DISPATCH_TOKEN","").strip()
    if not token:raise RuntimeError("GITHUB_DISPATCH_TOKEN_NOT_CONFIGURED_NO_RAILWAY_FALLBACK")
    if stage not in STAGES:raise ValueError("INVALID_ACTIONS_STAGE")
    url=f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"
    payload=json.dumps({"ref":BRANCH,"inputs":{"run_id":run["run_id"],"stage":stage}},
                       separators=(",",":")).encode()
    request=Request(url,data=payload,method="POST",headers={
         "Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
         "X-GitHub-Api-Version":"2022-11-28",
         "Content-Type":"application/json","User-Agent":"ProcureFlow-Action-Controller"})
    try:
        with urlopen(request,timeout=18) as response:
            if response.status!=204:raise RuntimeError("GITHUB_DISPATCH_NOT_204")
    except HTTPError as exc:
        raise RuntimeError("GITHUB_DISPATCH_HTTP_"+str(exc.code)) from exc
    except URLError as exc:
        raise RuntimeError("GITHUB_DISPATCH_NETWORK_FAILED") from exc
    return {"stage":stage,"requested_at":_now(),"method":"workflow_dispatch"}

def begin(sid,payload):
    if not isinstance(payload,dict) or payload not in ({"mode":"auto"},{}):
        raise ValueError("AUTOMATIC_SELECTION_ONLY_NO_PINNED_CASE")
    if not os.environ.get("PROCUREFLOW_GITHUB_DISPATCH_TOKEN","").strip():
        raise RuntimeError("GITHUB_DISPATCH_TOKEN_NOT_CONFIGURED_NO_RAILWAY_FALLBACK")
    with LOCK:
        last=_find_session(sid)
        if last and last.get("status")=="running":
            raise ValueError("LIVE_RUN_ALREADY_ACTIVE")
        occupied=_read(_active_path(),{}) or {}
        previous_id=occupied.get("run_id")
        if previous_id:
            previous=_read(_run_path(previous_id),{}) or {}
            if previous.get("status")=="running":
                started=datetime.fromisoformat(previous["started_at"])
                if datetime.now(ZoneInfo("Asia/Seoul"))-started<timedelta(hours=8):
                    raise ValueError("LIVE_RUN_ALREADY_ACTIVE")
        rid=uuid.uuid4().hex
        run={"run_id":rid,"status":"running","mode":"github_actions_nine_nodes",
             "selection_mode":"newest_incomplete_auto",
             "session_hash":_sid(sid),"case_bid_no":None,"case_bid_ord":None,
             "started_at":_now(),"last_activity":_now(),
             "completed_steps":0,"partial_steps":0,"steps":[],
             "active_node":"N01","active_title":TITLES[0],"active_since":_now(),
             "pending_stage":"N01","uploads":{},"github_action_runs":[],
             "db_reads":0,"worker_calls":0,"bid_submitted":False}
        _atomic(_run_path(rid),run)
        _atomic(_active_path(),{"run_id":rid})
        _atomic(_session_path(sid),{"run_id":rid})
        try:
            run["dispatch"]=_dispatch(run,"N01")
            _atomic(_run_path(rid),run)
        except Exception as exc:
            run["status"]="dispatch_failed"
            run["error"]=str(exc)
            run["active_node"]=None
            _atomic(_run_path(rid),run)
            _atomic(ACTIVE_FILE,{"run_id":None})
            raise RuntimeError("GITHUB_ACTIONS_DISPATCH_FAILED:"+str(exc)) from exc
        return _public(run)

def current(sid):
    with LOCK:
        r=_find_session(sid)
        if r and r.get("status")=="running" and r.get("active_since"):
            # Fail closed after an abandoned GitHub runner; do not let UI hang.
            since=datetime.fromisoformat(r["active_since"])
            if datetime.now(ZoneInfo("Asia/Seoul"))-since>timedelta(minutes=55):
                stage=r.get("pending_stage")
                if stage in STAGES and len(r["steps"])==int(stage[-2:])-1:
                    r["steps"].append({"node":stage,"title":TITLES[int(stage[-2:])-1],
                        "status":"source_error","input":{"source":"github_actions"},
                        "output":{"error":"GITHUB_ACTIONS_CALLBACK_TIMEOUT_55_MINUTES"},
                        "at":_now()})
                    r["completed_steps"]=len(r["steps"])
                    r["partial_steps"]+=1
                r["status"]="failed"
                r["error"]="GITHUB_ACTIONS_CALLBACK_TIMEOUT_55_MINUTES"
                r["active_node"]=None
                r["active_title"]=""
                r["active_since"]=None
                r["finished_at"]=_now()
                _atomic(_run_path(r["run_id"]),r)
                _atomic(ACTIVE_FILE,{"run_id":None})
        return _public(r) if r else {"status":"not_run","mode":"github_actions_nine_nodes",
                                      "dispatch_ready":bool(os.environ.get("PROCUREFLOW_GITHUB_DISPATCH_TOKEN","").strip()),
                                      "completed_steps":0,"steps":[]}

def document(sid,rid):
    with LOCK:
        r=_find_session(sid)
        if not r or r["run_id"]!=rid:raise LookupError("DOCUMENT_NOT_AVAILABLE")
        path=ROOT/"documents"/(rid+".docx")
        if not path.is_file():raise LookupError("DOCUMENT_NOT_AVAILABLE")
        return path.read_bytes()

def _verify_request(auth):
    return verify(auth)

def context(auth,run_id,stage):
    claims=_verify_request(auth)
    if stage not in STAGES:raise ValueError("INVALID_ACTION_STAGE")
    with LOCK:
        run=_state(run_id)
        if run["pending_stage"]!=stage or run["status"]!="running":
            raise ValueError("ACTION_STAGE_NOT_PENDING")
        results={s["node"]:s["output"] for s in run["steps"]}
        statuses={s["node"]:s["status"] for s in run["steps"]}
        journal={"version":1,"records":{}}
        if stage=="N01":
            from n01_auto import _load
            journal=_load()
        return {"run_id":run_id,"stage":stage,"outputs":results,"statuses":statuses,
                "selected_notice":results.get("N01"),
                "completion_journal":journal if stage=="N01" else None}

def _check_stage(run_id,stage,auth):
    claims=_verify_request(auth)
    if stage not in STAGES:raise ValueError("INVALID_ACTION_STAGE")
    run=_state(run_id)
    if run.get("pending_stage")!=stage or run.get("status")!="running":
        raise ValueError("ACTION_NOT_PENDING_FOR_RUN")
    return run,claims

def upload(auth,headers,data):
    """Store binary chunks; CPU work is small streaming IO only."""
    if not isinstance(data,bytes) or not 0<len(data)<=MAX_UPLOAD_CHUNK:
        raise ValueError("N02_UPLOAD_CHUNK_INVALID")
    rid=headers.get("X-Procureflow-Run","")
    stage=headers.get("X-Procureflow-Stage","")
    seq=int(headers.get("X-Procureflow-File-Seq","0"))
    chunk=int(headers.get("X-Procureflow-Chunk","-1"))
    total=int(headers.get("X-Procureflow-File-Size","0"))
    checksum=headers.get("X-Procureflow-File-Sha256","")
    encoded=headers.get("X-Procureflow-File-Name","")
    if stage!="N02" or not 1<=seq<=64 or not 0<=chunk<=100 or not 0<total<=150*1024*1024:
        raise ValueError("N02_UPLOAD_METADATA_INVALID")
    if not re.fullmatch("[0-9a-f]{64}",checksum):
        raise ValueError("N02_UPLOAD_SHA256_INVALID")
    if len(encoded)>600:raise ValueError("N02_FILENAME_TOO_LONG")
    filename=_safe_name(base64.urlsafe_b64decode(encoded+"="*(-len(encoded)%4)).decode("utf-8"))
    with LOCK:
        run,claims=_check_stage(rid,"N02",auth)
        notice=next((s["output"] for s in run["steps"] if s["node"]=="N01"),None)
        if not notice:raise ValueError("N02_SELECTED_NOTICE_NOT_FOUND")
        folder=STORAGE_ROOT/(notice["bid_no"]+"-"+notice["bid_ord"])/"attachments"
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(f"{seq:03d}__"+filename)
        temp=folder/("."+rid+"-"+str(seq)+".part")
        receipts=run.setdefault("uploads",{})
        last=receipts.get(str(seq))
        if last and last.get("saved"):
            if last["sha256"]==checksum and last["original_filename"]==filename:
                return {"accepted":True,"saved":True,"bytes":last["size_bytes"]}
            raise ValueError("N02_DUPLICATE_FILE_METADATA_CONFLICT")
        if chunk==0:
            if temp.exists():temp.unlink()
        elif not temp.exists():raise ValueError("N02_UPLOAD_CHUNK_NOT_SEQUENTIAL")
        actual=temp.stat().st_size if temp.exists() else 0
        if actual!=chunk*2*1024*1024:
            raise ValueError("N02_UPLOAD_CHUNK_OFFSET_INVALID")
        if actual+len(data)>total:raise ValueError("N02_UPLOAD_EXCEEDS_EXPECTED_SIZE")
        with temp.open("ab") as target:target.write(data)
        count=actual+len(data)
        if count==total:
            digest=sha256()
            with temp.open("rb") as stream:
                while (buf:=stream.read(1024*1024)):digest.update(buf)
            if digest.hexdigest()!=checksum:
                temp.unlink(missing_ok=True)
                raise ValueError("N02_UPLOAD_FINAL_SHA_MISMATCH")
            os.replace(temp,path)
            receipts[str(seq)]={"file_seq":seq,"original_filename":filename,
               "saved_path":str(path),"size_bytes":total,"sha256":checksum,
               "saved":True,"file_type":_kind(filename,b"","")}
        _atomic(_run_path(rid),run)
    return {"accepted":True,"saved":count==total,"bytes":count}

def original(auth,run_id,seq):
    with LOCK:
        run,claims=_check_stage(run_id,"N09",auth)
        collection=next((s["output"] for s in run["steps"] if s["node"]=="N02"),None)
        if not collection:raise LookupError("ORIGINAL_COLLECTION_NOT_FOUND")
        file=next((f for f in collection.get("files",[]) if f.get("file_seq")==seq),None)
        if not file:raise LookupError("ORIGINAL_FILE_NOT_FOUND")
        path=Path(file["saved_path"]).resolve()
        folder=Path(collection["storage_folder"]).resolve()
        if path.parent!=folder or not path.is_file():
            raise LookupError("ORIGINAL_FILE_OUTSIDE_COLLECTION")
        if path.stat().st_size!=file["size_bytes"]:
            raise ValueError("ORIGINAL_FILE_SIZE_CHANGED")
        return path

def _reconcile_n02(run,out):
    files=out.get("files")
    if not isinstance(files,list):raise ValueError("N02_ORIGINAL_MANIFEST_NOT_LIST")
    uploads=run.get("uploads") or {}
    if len(files)!=len(uploads) or len(files)!=out.get("file_count"):
        raise ValueError("N02_ORIGINAL_FILE_COUNT_MISMATCH")
    for file in files:
        receipt=uploads.get(str(file.get("file_seq")))
        if not receipt or not receipt.get("saved") or receipt["sha256"]!=file.get("sha256"):
            raise ValueError("N02_ORIGINAL_TRANSFER_NOT_VERIFIED")
        if receipt["original_filename"]!=file.get("original_filename"):
            raise ValueError("N02_ORIGINAL_FILENAME_CHANGED")
        file.update(receipt)
    notice=next(s["output"] for s in run["steps"] if s["node"]=="N01")
    folder=STORAGE_ROOT/(notice["bid_no"]+"-"+notice["bid_ord"])
    out["storage_folder"]=str(folder/"attachments")
    manifest=folder/"attachment_manifest.json"
    out["manifest_path"]=str(manifest)
    out["persisted_on_railway"]=True
    out["analysis_performed"]=False
    _atomic(manifest,out)

def receive(auth,payload):
    """Results are single-use, ordered and bound to a verified GitHub workflow."""
    if not isinstance(payload,dict):raise ValueError("GITHUB_NODE_JSON_REQUIRED")
    rid=payload.get("run_id","")
    stage=payload.get("stage","")
    status=payload.get("status","")
    if status not in ("verified","partial","blocked","source_error","not_executed"):
        raise ValueError("GITHUB_STAGE_STATUS_INVALID")
    with LOCK:
        run,claims=_check_stage(rid,stage,auth)
        if len(run["steps"])!=int(stage[-2:])-1:
            raise ValueError("GITHUB_STAGE_OUT_OF_ORDER")
        result=copy.deepcopy(payload.get("output"))
        inp=payload.get("input")
        if not isinstance(inp,dict) or not isinstance(result,dict):
            raise ValueError("GITHUB_STAGE_INPUT_OUTPUT_REQUIRED")
        if stage=="N01" and status=="verified":
            if not (result.get("official_fields_verified") is True
                    and result.get("search_request_verified") is True
                    and result.get("bid_no") and result.get("bid_ord")):
                raise ValueError("N01_OFFICIAL_RESULT_REQUIRED")
            run["case_bid_no"]=result["bid_no"]
            run["case_bid_ord"]=result["bid_ord"]
            run["selection_reason"]=result.get("selection_reason")
        if stage=="N02" and result.get("files"):
            _reconcile_n02(run,result)
        if stage=="N08" and "_document_base64" in result:
            raw=base64.b64decode(result.pop("_document_base64"),validate=True)
            if not raw.startswith(b"PK") or len(raw)>2*1024*1024:
                raise ValueError("N08_DOCX_INVALID_OR_TOO_LARGE")
            if sha256(raw).hexdigest()!=result.get("sha256"):
                raise ValueError("N08_DOCX_HASH_MISMATCH")
            dest=ROOT/"documents"/(rid+".docx")
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(raw)
        step={"node":stage,"title":TITLES[int(stage[-2:])-1],
              "status":status,"input":inp,"output":result,
              "at":_now(),"github_run_id":claims.get("run_id")}
        run["steps"].append(step)
        run["completed_steps"]=len(run["steps"])
        if status!="verified":run["partial_steps"]+=1
        run["last_activity"]=_now()
        if run.get("case_bid_no"):
            from n01_auto import record_stage
            note={"run_id":rid,"selected_notice":{
                "bid_no":run["case_bid_no"],"bid_ord":run["case_bid_ord"],
                "title":next((s["output"].get("title") for s in run["steps"] if s["node"]=="N01"),""),
                "agency":next((s["output"].get("agency") for s in run["steps"] if s["node"]=="N01"),"")}}
            record_stage(note,int(stage[-2:]),status)
        if stage=="N09":
            run["pending_stage"]=None
            run["active_node"]=None
            run["active_title"]=""
            run["active_since"]=None
            run["status"]="completed" if all(s["status"]=="verified" for s in run["steps"]) else "completed_with_missing_evidence"
            run["finished_at"]=_now()
            _atomic(_run_path(rid),run)
            _atomic(ACTIVE_FILE,{"run_id":None})
            return {"accepted":True,"finished":True,"run_id":rid}
        next_stage=STAGES[int(stage[-2:])]
        run["pending_stage"]=next_stage
        run["active_node"]=next_stage
        run["active_title"]=TITLES[int(next_stage[-2:])-1]
        run["active_since"]=_now()
        _atomic(_run_path(rid),run)
        try:
            run["dispatch"]=_dispatch(run,next_stage)
            _atomic(_run_path(rid),run)
        except Exception as exc:
            run["status"]="dispatch_failed"
            run["error"]="NEXT_NODE_DISPATCH_FAILED:"+str(exc)
            run["active_node"]=None
            run["finished_at"]=_now()
            _atomic(_run_path(rid),run)
            _atomic(ACTIVE_FILE,{"run_id":None})
            return {"accepted":True,"next_stage":next_stage,"dispatch_failed":True}
        return {"accepted":True,"run_id":rid,"next_stage":next_stage}
