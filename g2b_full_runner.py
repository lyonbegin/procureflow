"""Worker for the user's one selected G2B tender and 104 evidence-gated stages.

All steps operate on R26BK01787028. Each returns 'verified', 'partial' or
'blocked' backed by database evidence; never treat a placeholder as success.
"""
from __future__ import annotations
from datetime import date
import json,logging,re
from db import session
from g2b_case_10y import CASE_BID
from g2b_official_notices import _get,_items,save_notice,api_key
from g2b_case_10y_official import scan_month
from g2b_documents import list_documents,acquire_one
from g2b_case_engine import dashboard,refresh_existing_evidence,readiness_check
from g2b_bid_package import proposal_contents

def official_selected_notice():
    if not api_key():
        return {"status":"blocked_missing_official_api_key",
                "operation":"getBidPblancListInfoServc",
                "bid_no":CASE_BID}
    try:
        response=_get("service",{"inqryDiv":"2","bidNtceNo":CASE_BID,
                                 "pageNo":1,"numOfRows":100})
        if "blocked" in response:return {"status":"blocked_missing_official_api_key"}
        rows,total=_items(response)
        saved=[]
        for entry in rows:
            if (isinstance(entry,dict) and
                    str(entry.get("bidNtceNo") or "")==CASE_BID):
                saved.append(save_notice(entry,"service"))
        return {"status":"verified" if any(x.get("accepted") for x in saved) else "blocked",
                "found":len(saved),"items_returned":len(rows),"total":total,
                "validated":saved,"bid_no":CASE_BID}
    except Exception as exc:
        return {"status":"error","reason":type(exc).__name__+":"+str(exc)[:180]}

def historical_month_batch():
    """Exactly one incomplete monthly window per run, with resumable pagination."""
    with session() as db:
        row=db.execute("""SELECT first_day,state,page_cursor
          FROM procureflow.g2b_case_10yr_windows
          WHERE case_bid_no=%s AND status NOT IN ('completed')
          ORDER BY first_day LIMIT 1""",(CASE_BID,)).fetchone()
    if not row:return {"status":"verified","window_coverage":"121/121"}
    return scan_month(row["first_day"],pages_max=8)

def documents_batch():
    index=list_documents(CASE_BID)
    if not index["files_listed"]:
        return {"status":"blocked_missing_official_file_index",
                "files_listed":0,"downloaded":0}
    visited=[]
    for item in index["original_index"][:12]:
        if item["state"] not in ("listed","extract_error","partial"):
            continue
        try:
            visited.append(acquire_one(CASE_BID,"000",item["file_id"]))
        except Exception as exc:
            visited.append({"file_id":item["file_id"],"status":"error",
                  "reason":type(exc).__name__+":"+str(exc)[:100]})
    updated=list_documents(CASE_BID)
    return {"status":"verified" if updated["all_documents_text_extracted"]
             else "partial","attempted":len(visited),
             "files_listed":updated["files_listed"],
             "downloaded":updated["files_downloaded"],
             "all_parsed":updated["all_documents_text_extracted"],
             "results":visited}

def one_phase(phase):
    if phase=="notice":return official_selected_notice()
    if phase=="ten_year":return historical_month_batch()
    if phase=="documents":return documents_batch()
    if phase=="evidence":
        return {"status":"partial","facts":refresh_existing_evidence()}
    if phase=="readiness":
        r=readiness_check()
        return {"status":"verified" if r["status"]=="ready" else "blocked",
                "ready":r["status"]=="ready","phases":r["phases"]}
    raise ValueError("unsupported phase "+phase)

def execute(phase="all"):
    if phase not in ("all","notice","ten_year","documents","evidence","readiness"):
        raise ValueError("unknown phase")
    phases=("notice","ten_year","documents","evidence","readiness") if phase=="all" else (phase,)
    results={}
    for key in phases:
        with session() as c:
            run_id=c.execute("""INSERT INTO procureflow.g2b_case_runs(
                bid_no,phase,state,started_at)
                VALUES (%s,%s,'running',now()) RETURNING id""",(CASE_BID,key)).fetchone()["id"]
        try:
            result=one_phase(key)
            state=result.get("status","partial")
            if state not in ("verified","partial","blocked","error"):
                state="blocked" if state.startswith("blocked") else "partial"
        except Exception as exc:
            result={"status":"error","reason":type(exc).__name__+":"+str(exc)[:150]}
            state="error"
        with session() as c:
            c.execute("""UPDATE procureflow.g2b_case_runs
                SET state=%s,result=%s::jsonb,
                    error=%s,finished_at=now() WHERE id=%s
            """,(state,json.dumps(result,ensure_ascii=False,default=str),
                 result.get("reason","") if state=="error" else "",run_id))
            c.execute("""INSERT INTO procureflow.g2b_case_events
                (bid_no,action,details) VALUES (%s,%s,%s::jsonb)
            """,(CASE_BID,"phase_finished",
                 json.dumps({"phase":key,"state":state,"run_id":run_id})))
        results[key]={"state":state,"result":result}
    # 'all completed' means every actual acceptance criterion met, not every
    # backend function happened to return a Python dict without exceptions.
    accepted=readiness_check()
    return {"bid_no":CASE_BID,"phase":phase,"results":results,
            "status":"verified" if accepted["status"]=="ready" else "incomplete",
            "ready_for_manual_bid_participation":accepted["status"]=="ready",
            "submitted":False,"bid_participation_clicked":False}
