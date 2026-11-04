"""Independent site-first G2B management API. No original procureflow DB.

POST actions require the existing private Railway API admin token via an
environment variable. GET operations show ONLY the new isolated database.
Each action makes an actual official G2B request before persisting results.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import hmac
import json
import logging
import os
import re

from fastapi import FastAPI, BackgroundTasks, HTTPException, Header, Body, Query
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

import fresh_g2b_store as store
import fresh_g2b_site as site

HERE=Path(__file__).parent

@asynccontextmanager
async def lifespan(app):
    store.initialize()  # hard fail when wired to legacy DB
    # One bounded, auditable official-site probe on an EMPTY new database.
    # This never imports old notices and does not perform a bid submission.
    if os.environ.get("FRESH_CANARY_ON_BOOT")=="1":
        with store.db() as cx:
            previous=cx.execute("SELECT count(*) AS n FROM fresh_g2b.site_search_runs").fetchone()["n"]
        if previous==0:
            from threading import Thread
            args={"detail10":"8111159901","start":"2016-11-04",
                  "end":"2026-11-04","month":"2026-11","page":1}
            job_id=store.create_job("search",args)
            Thread(target=_execute,args=(job_id,"search",args),daemon=True).start()
    yield

app=FastAPI(title="나라장터 실사이트 신규 수집센터",lifespan=lifespan,
            docs_url=None,redoc_url=None)

@app.get("/",response_class=HTMLResponse)
def home():
    return HTMLResponse((HERE/"fresh_g2b.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

@app.get("/health")
def health():
    with store.db() as cx:
        store.guard(cx)
        totals=store.stats(cx)
    return {"status":"ok","fresh_database_only":True,"old_229_imported":False,
            "source":"fresh_g2b","totals":totals,"website_full_decade_verified":False}

@app.get("/api/summary")
def summary():
    with store.db() as cx:
        return {"fresh_database_only":True,"totals":store.stats(cx),
                "existing_procureflow_data_used":False}

@app.get("/api/notices")
def notices(code10:str="",limit:int=Query(50,ge=1,le=100),
            offset:int=Query(0,ge=0,le=5000)):
    if code10 and not store.TEN.fullmatch(code10):
        raise HTTPException(400,"EXACT_10_DIGITS_REQUIRED")
    return {"source":"fresh_site_only","items":store.list_notices(code10,limit,offset),
            "no_legacy_db":True}

@app.get("/api/notices/{bid_no}/{bid_ord}")
def notice(bid_no:str,bid_ord:str):
    if not store.BID.fullmatch(bid_no) or not store.ORD.fullmatch(bid_ord):
        raise HTTPException(400,"INVALID_BID_IDENTIFIER")
    with store.db() as cx:
        try:r=store.get_notice(cx,bid_no,bid_ord)
        except LookupError:raise HTTPException(404,"NOT_YET_COLLECTED_FROM_SITE") from None
        files=cx.execute("""SELECT file_url,filename,sha256,mime,
                        extraction_state,last_checked_at
                        FROM fresh_g2b.site_attachments
                        WHERE bid_no=%s AND bid_ord=%s ORDER BY file_url""",
                        (bid_no,bid_ord)).fetchall()
        offers=cx.execute("""SELECT bid_clsfc_no,progress_ord,company,amount,rate,rank,
                       validity_code,last_checked_at FROM fresh_g2b.site_offers
                       WHERE bid_no=%s AND bid_ord=%s ORDER BY progress_ord,rank
                       LIMIT 300""",(bid_no,bid_ord)).fetchall()
        awards=cx.execute("""SELECT bid_clsfc_no,progress_ord,company,amount,
                  evidence_status,captured_at FROM fresh_g2b.site_awards
                  WHERE bid_no=%s AND bid_ord=%s""",(bid_no,bid_ord)).fetchall()
        executions=cx.execute("""SELECT bid_clsfc_no,progress_ord,status,total_reported,
                     full_bidders_verified,last_checked_at
                     FROM fresh_g2b.site_executions
                     WHERE bid_no=%s AND bid_ord=%s""",(bid_no,bid_ord)).fetchall()
    return {"notice":r,"files":files,"offers":offers,
            "awards":awards,"executions":executions,"source":"fresh_site_only"}

@app.get("/api/history/{bid_no}/{bid_ord}")
def history(bid_no:str,bid_ord:str):
    if not store.BID.fullmatch(bid_no) or not store.ORD.fullmatch(bid_ord):
        raise HTTPException(400,"INVALID_BID_IDENTIFIER")
    try:
        return store.history_for(bid_no,bid_ord)
    except LookupError:
        raise HTTPException(404,"NOT_YET_COLLECTED_FROM_SITE") from None

@app.get("/api/jobs")
def jobs(limit:int=Query(20,ge=1,le=80)):
    return {"jobs":store.read_jobs(limit),"source":"fresh_site_only"}

@app.get("/api/search-runs")
def search_runs(limit:int=Query(30,ge=1,le=100)):
    with store.db() as cx:
        rows=cx.execute("""SELECT id,code10,from_day,to_day,cursor,page,status,
                        official_endpoint,request_verified,confirmed_count,
                        pending_count,official_total,reason,created_at
                 FROM fresh_g2b.site_search_runs ORDER BY id DESC LIMIT %s""",
                        (limit,)).fetchall()
    return {"items":rows,"source":"actual_site_request_audit"}

def _verify_admin(token):
    expected=os.environ.get("FRESH_ADMIN_TOKEN","")
    if not expected or not token or not hmac.compare_digest(token,expected):
        raise HTTPException(403,"ADMIN_TOKEN_REQUIRED")

def _parse_date(value):
    if not isinstance(value,str):raise ValueError("YYYY_MM_DD_REQUIRED")
    return date.fromisoformat(value)

def _validate_action(kind,params):
    if kind not in ("search","detail","opening","file"):
        raise ValueError("UNSUPPORTED_SITE_ACTION")
    if not isinstance(params,dict):
        raise ValueError("ACTION_PARAMS_MUST_BE_OBJECT")
    if kind=="search":
        code=str(params.get("detail10") or "")
        if not store.TEN.fullmatch(code):
            raise ValueError("EXACT_10_REQUIRED")
        start=_parse_date(params.get("start"))
        end=_parse_date(params.get("end"))
        if start>end or (end-start).days>3660:
            raise ValueError("DATE_RANGE_OUT_OF_BOUND")
        page=params.get("page",1)
        if type(page)!=int or page<1 or page>10:
            raise ValueError("INVALID_PAGE")
        month=params.get("month")
        if month is not None and not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])",str(month)):
            raise ValueError("INVALID_MONTH_CURSOR")
        return {"detail10":code,"start":start.isoformat(),"end":end.isoformat(),
                "month":month,"page":page}
    no=str(params.get("bid_no") or "")
    ord_=str(params.get("bid_ord") or "000")
    if not store.BID.fullmatch(no) or not store.ORD.fullmatch(ord_):
        raise ValueError("INVALID_BID_ID")
    result={"bid_no":no,"bid_ord":ord_}
    if kind=="detail":
        detail10=str(params.get("detail10") or "")
        if not store.TEN.fullmatch(detail10):
            raise ValueError("EXPECTED_DETAIL10_REQUIRED")
        result["detail10"]=detail10
    elif kind=="file":
        url=str(params.get("url") or "")
        if not site.official_url(url) or len(url)>1600:
            raise ValueError("ONLY_G2B_OFFICIAL_FILE_URL")
        result["url"]=url
    return result

def _execute(job_id,kind,params):
    store.job_update(job_id,"running")
    try:
        if kind=="search":
            w=site.search_original_site(params["detail10"],params["start"],
                       params["end"],params["month"],params["page"])
            result=store.store_search(w,params["detail10"],params["start"],
                       params["end"],params["month"],params["page"],job_id)
            result["website_status"]=w["status"]
            result["reason"]=w.get("reason")
            result["next_month"]=w.get("next_month")
            result["website_request_verified"]=bool(w.get("search_request_verified"))
            state="completed" if result["website_request_verified"] else "blocked"
        elif kind=="detail":
            no,ord_=params["bid_no"],params["bid_ord"]
            with store.db() as cx:
                store.get_notice(cx,no,ord_)
            data=site.fetch_original_detail(no,ord_,params["detail10"])
            result=store.store_detail(no,ord_,data,job_id)
            state="completed" if result["original_verified"] else "blocked"
        elif kind=="opening":
            no,ord_=params["bid_no"],params["bid_ord"]
            with store.db() as cx:
                n=store.get_notice(cx,no,ord_)
                if not n["original_verified"]:
                    raise ValueError("ORIGINAL_10DIGIT_MUST_BE_VERIFIED_FIRST")
            data=site.fetch_actual_opening(no,ord_)
            result=store.store_opening(no,ord_,data,job_id)
            final=site.explicitly_confirmed_winner(data)
            result["final_award"]=final["status"]
            if final["status"]=="explicit_final_confirmed":
                info=data.get("bid_info") or {}
                clsfc=str(info.get("bidClsfNo") or "0")
                progress=str(info.get("bidPrgrsOrd") or "000")
                with store.db() as cx:
                    cx.execute("""INSERT INTO fresh_g2b.site_awards(
                       bid_no,bid_ord,bid_clsfc_no,progress_ord,company,
                       amount,evidence_sha256)
                       VALUES(%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(bid_no,bid_ord,bid_clsfc_no,progress_ord)
                       DO UPDATE SET company=excluded.company,amount=excluded.amount,
                             evidence_sha256=excluded.evidence_sha256,captured_at=now()""",
                       (no,ord_,clsfc,progress,final["company"],final["amount"],
                        final["source_sha256"]))
                store.audit(job_id,"www.g2b.go.kr",no,"explicit_final_award",
                     {"sha256":final["source_sha256"]})
            state="completed"
        else:
            no,ord_=params["bid_no"],params["bid_ord"]
            with store.db() as cx:
                n=store.get_notice(cx,no,ord_)
                if not n["original_verified"]:
                    raise ValueError("OFFICIAL_ORIGINAL_MUST_BE_VERIFIED_BEFORE_FILE")
            file=site.download_original_file(params["url"])
            result=store.store_attachment(no,ord_,params["url"],file["content"],
                    file["filename"],file["mime"],file["text"],file["state"],job_id)
            state="completed"
        store.job_update(job_id,state,result)
    except Exception as exc:
        # No credentials, URLs with query tokens or response body dumped to logs.
        reason=type(exc).__name__
        logging.warning("FRESH_G2B_JOB_FAILURE kind=%s job=%s exception=%s",
                        kind,job_id,reason)
        store.job_update(job_id,"error",error=reason)

@app.post("/api/actions/{kind}")
def perform_action(kind:str,background:BackgroundTasks,
                   params:dict=Body(...),x_admin_token:str|None=Header(None,alias="X-Admin-Token")):
    _verify_admin(x_admin_token)
    try:
        normalized=_validate_action(kind,params)
    except (ValueError,TypeError) as exc:
        raise HTTPException(400,str(exc)) from None
    # Limit parallel active work in shared API container.
    with store.db() as cx:
        count=cx.execute("""SELECT count(*) AS n FROM fresh_g2b.site_jobs
                            WHERE status IN ('queued','running')""").fetchone()["n"]
        if count>=3:raise HTTPException(429,"TOO_MANY_ACTIVE_SITE_JOBS")
    job_id=store.create_job(kind,normalized)
    background.add_task(_execute,job_id,kind,normalized)
    return {"job_id":job_id,"status":"queued",
            "source":"official_g2b_site_only","no_old_database":True}
