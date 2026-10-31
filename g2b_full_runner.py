"""Worker for the user's one selected G2B tender and 104 evidence-gated stages.

All steps operate on R26BK01787028. Each returns 'verified', 'partial' or
'blocked' backed by database evidence; never treat a placeholder as success.
"""
from __future__ import annotations
from datetime import date,timedelta
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

def historical_month_batch(candidate_limit=4, opening_limit=2, month_pages_max=2):
    """Bounded official ten-year discovery -> exact-code original -> actual results.

    Every invocation checks at most ONE registered month (and at most
    month_pages_max pages), then verifies a bounded number of candidate
    originals and official opening/final-award records. This is an ORIGINAL
    G2B Worker action, not a new DAG runner.

    Even 121 completed months only proves category-8 notice discovery:
    the category-10 opening/bidder/final-award completeness gate is separate.
    """
    from g2b_case_10y import ensure_schema as ensure_history_schema, SUB10
    from g2b_feature_api import notice_context
    from g2b_exact_outcome_history import run_batch
    ctx=notice_context(CASE_BID)
    if (not ctx.get("original_notice_verified") or
            SUB10 not in (ctx.get("official_detail10") or [])):
        return {"status":"blocked",
                "reason":"selected_notice_official_detail10_not_verified",
                "official_discovery_started":False,
                "ten_year_outcome_coverage_complete":False,
                "bid_submitted":False}
    ensure_history_schema()
    with session() as db:
        # Resume partial pages first. After successful pages advance to the
        # next oldest incomplete month; skip no windows silently.
        next_window=db.execute("""SELECT first_day,last_day,status,page_cursor
           FROM procureflow.g2b_case_10yr_windows
           WHERE case_bid_no=%s AND status<>'completed'
           ORDER BY CASE WHEN status='partial' THEN 0 ELSE 1 END,
                    first_day ASC LIMIT 1""",(CASE_BID,)).fetchone()
        window_count=db.execute("""SELECT COUNT(*) AS total,
              COUNT(*) FILTER (WHERE status='completed') AS completed
           FROM procureflow.g2b_case_10yr_windows
           WHERE case_bid_no=%s""",(CASE_BID,)).fetchone()
    total=int(window_count["total"] or 0)
    completed=int(window_count["completed"] or 0)
    if total!=121:
        return {"status":"blocked","reason":"official_month_registry_incomplete",
                "registered_months":total,"required_months":121,
                "ten_year_outcome_coverage_complete":False,"bid_submitted":False}
    limit_pages=max(1,min(2,int(month_pages_max)))
    month=(scan_month(next_window["first_day"],pages_max=limit_pages)
           if next_window else
           {"status":"no_pending_windows","scope":"8digit_notice_discovery_only"})
    if month.get("status") not in ("completed","partial","already_completed","no_pending_windows"):
        return {"status":"blocked","reason":"official_month_scan_not_verified",
                "official_month":month,"registered_months":total,
                "discovery_months_completed_before_run":completed,
                "ten_year_outcome_coverage_complete":False,"bid_submitted":False}
    # The exact 10-digit check occurs ONLY against original official notice
    # files and winner evidence, never a shared 8-digit notice title.
    result=run_batch(limit=max(1,min(4,int(candidate_limit))),
                     opening_limit=max(1,min(2,int(opening_limit))))
    return {"status":"partial_exact_results",
            "detail_product_code":SUB10,
            "registered_months":total,
            "discovery_months_completed_before_run":completed,
            "official_month":month,
            "discovery_scope":"eight_digit_candidate_notices_only",
            "verified_detail_bids":result["verified_exact_code"],
            "bidder_rows_saved":result["opening_bidder_rows_saved"],
            "confirmed_final_awards":result["final_awards_verified"],
            "verified_candidates_checked":result["candidate_checked"],
            "outcome":result,"official_full_ten_year_complete":False,
            "ten_year_outcome_coverage_complete":False,
            "bid_submitted":False}


def discover_new_bids():
    """New G2B tender notices for goods+services, independent of old R..DD orders."""
    from g2b_official_notices import refresh_window
    today=date.today()
    return {"status":"partial","windows":[
        refresh_window(kind,(today-timedelta(days=1)).isoformat(),
                       today.isoformat(),limit_pages=5)
        for kind in ("service","goods")]}


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
    from g2b_original_reparse import run as reparse_original_documents
    parse_results=reparse_original_documents()
    updated=list_documents(CASE_BID)
    return {"status":"verified" if updated["all_documents_text_extracted"]
             else "partial","attempted":len(visited),
             "files_listed":updated["files_listed"],
             "downloaded":updated["files_downloaded"],
             "all_parsed":updated["all_documents_text_extracted"],
             "parse_results":parse_results,"results":visited}

def one_phase(phase):
    if phase=="discover":return discover_new_bids()
    if phase=="notice":
        official=official_selected_notice()
        if official.get("status")=="verified":return official
        from g2b_selected_public import ingest_selected_public
        secondary=ingest_selected_public()
        return {"status":"partial" if secondary.get("status")=="collected_secondary_public"
                else "blocked","official":official,"secondary":secondary,
                "source_qualification":"secondary_public_not_official_verified"}
    if phase in ("ten_year","exact_outcomes","opening_details"):
        return historical_month_batch()
    if phase=="documents":return documents_batch()
    if phase=="evidence":
        from g2b_original_facts import run as parse_original_facts
        original=parse_original_facts()
        from g2b_scope_analysis import analyze as extract_actual_scope
        scope=extract_actual_scope()
        linked=refresh_existing_evidence()
        return {"status":"partial","original_rules":original,
                "scope_analysis":scope,"facts":linked}
    if phase=="readiness":
        r=readiness_check()
        return {"status":"verified" if r["status"]=="ready" else "blocked",
                "ready":r["status"]=="ready","phases":r["phases"]}
    raise ValueError("unsupported phase "+phase)

def execute(phase="all"):
    if phase not in ("all","discover","notice","ten_year","opening_details","exact_outcomes","documents","evidence","readiness"):
        raise ValueError("unknown phase")
    phases=("notice","documents","exact_outcomes","evidence","readiness") if phase=="all" else (phase,)
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
