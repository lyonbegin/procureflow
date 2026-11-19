"""Isolated real HITEL ChatGPT contracts: synthetic Scribd / A.
Exactly one send per test, never touching original rooms, data or checkpoints.
"""
import argparse,json,os,time,urllib.request,hashlib
from pathlib import Path
BASE="https://hitel-integration-api-production.up.railway.app"
OPEN=urllib.request.build_opener(urllib.request.ProxyHandler({}))
OUT=Path("recovery-contract-evidence")
def call(path,data=None):
    raw=json.dumps(data,ensure_ascii=False).encode() if data is not None else None
    req=urllib.request.Request(BASE+path,data=raw,method="POST" if data is not None else "GET",headers={"Content-Type":"application/json"})
    with OPEN.open(req,timeout=40) as r:
        return r.status,json.load(r)
def save(kind,state):
    OUT.mkdir(exist_ok=True)
    (OUT/(kind+".json")).write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
def prompt(kind):
    if kind=="scribd":
        return ('가상 교재 두 개를 분류하는 전송 계약 시험입니다. 제목 "중학교 2학년 1학기 수학 교재"와 '
                '"2022 개정 고등학교 공통수학1 교재"에 대하여 JSON 객체 하나만 반환하십시오. '
                '반드시 {"rows":[{"no":1,"id":"SYNTHETIC-S1","school":"중등",'
                '"grade":"2","semester":"1","subject":"수학","edition":"해당없음",'
                '"download":"대상","reason":"중학교 수학 교재"},'
                '{"no":2,"id":"SYNTHETIC-S2","school":"고등","grade":"해당없음",'
                '"semester":"해당없음","subject":"공통수학1","edition":"판본검토",'
                '"download":"판본검토","reason":"판본 정보 미확인"}]}처럼 두 행과 모든 필드가 있어야 합니다.')
    return ('A 연구 교통망 JSON 스키마 독립 시험입니다. 기존 A그룹 방의 실제 연구를 반복하거나 '
            '변경하지 마십시오. 반드시 {"source_id":"0LJUxO7T","cases":[],'
            '"transport_test":"PASS","source_access_status":"PREVIEW_ONLY"}만 응답하십시오.')
def parse(value):
    s=str(value or "").strip()
    fence=chr(96)*3
    if s.startswith(fence):
        s=s.split("\n",1)[-1].rsplit(fence,1)[0].strip()
    obj,_=json.JSONDecoder().raw_decode(s)
    if not isinstance(obj,dict):raise RuntimeError("NOT_OBJECT")
    return obj
def main(kind):
    run=os.environ["GITHUB_RUN_ID"]
    name=("HITEL-SCRIBD-SYNTHETIC-CONTRACT-" if kind=="scribd" else "STOCK-A-SYNTHETIC-CONTRACT-")+run
    state={"kind":kind,"synthetic":True,"original_job_touched":False,"room_name":name,"request_id":"hitel-contract-"+kind+"-"+run}
    save(kind,state)
    _,status=call("/integrations/v1/public/status")
    if not status.get("worker_heartbeat_recent") or status.get("worker_busy"):
        state["result"]="WORKER_NOT_AVAILABLE_NO_SEND"
        save(kind,state)
        raise RuntimeError(state["result"])
    code,room=call("/integrations/v1/public/rooms",{"name":name})
    rid=room.get("room_id")
    if code not in (200,201) or not rid:raise RuntimeError("ROOM_CREATE_FAILED")
    state["room_id"]=rid;save(kind,state)
    try:
        code,result=call("/integrations/v1/public/chat",{"room_id":rid,"text":prompt(kind),"request_id":state["request_id"]})
    except Exception as exc:
        state["result"]="POST_DELIVERY_UNKNOWN_NO_RESEND"
        state["error_class"]=type(exc).__name__
        save(kind,state)
        raise
    jid=result.get("job_id")
    if code!=202 or not jid or result.get("room_id") not in (None,rid):
        raise RuntimeError("WRONG_ROOM_OR_ACCEPTANCE")
    state["job_id"]=jid;save(kind,state)
    for attempt in range(90):
        _,job=call("/integrations/v1/public/jobs/"+jid)
        if job.get("job_id")!=jid or job.get("room_id")!=rid:
            raise RuntimeError("JOB_IDENTITY_CHANGED")
        if job.get("status")=="failed":
            state["result"]="FAILED"
            state["server_error"]=job.get("error")
            state["stage"]=job.get("stage")
            save(kind,state)
            raise RuntimeError("REAL_JOB_FAILED_"+str(job.get("error")))
        if job.get("status")=="completed":
            data=parse(job.get("result_text"))
            if kind=="scribd":
                rows=data.get("rows",[])
                if not isinstance(rows,list) or len(rows)!=2 or {(int(x["no"]),str(x["id"])) for x in rows}!={(1,"SYNTHETIC-S1"),(2,"SYNTHETIC-S2")}:
                    raise RuntimeError("SCRIBD_JSON_ID_COUNT_MISMATCH")
                required=["school","grade","semester","subject","edition","download","reason"]
                if any(any(f not in row for f in required) for row in rows):
                    raise RuntimeError("SCRIBD_REQUIRED_FIELD_MISSING")
            elif data.get("source_id")!="0LJUxO7T" or not isinstance(data.get("cases"),list) or data.get("transport_test")!="PASS":
                raise RuntimeError("A_JSON_SOURCE_SCHEMA_MISMATCH")
            state["result"]="PASS_REAL_CHATGPT_PROGRAM_JSON_CONTRACT"
            state["stage"]=job.get("stage")
            state["result_sha256"]=hashlib.sha256(job["result_text"].encode()).hexdigest()
            save(kind,state)
            print("PASS_REAL_"+kind.upper()+"_JSON_CONTRACT "+jid,flush=True)
            return
        time.sleep(4)
    state["result"]="PENDING_NO_RESEND";save(kind,state)
    raise RuntimeError("PENDING_PRESERVED")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--case",choices=["scribd","a"],required=True)
    main(p.parse_args().case)
