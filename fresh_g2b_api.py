"""One-screen clean-source G2B ingestion. ZERO old DB imports/queries.

All jobs have explicit live request attempts. No stale 229 records are read.
HTTP POST queues one real site operation; GET endpoints only read newly acquired
records from the new independent PostgreSQL instance.
"""
from __future__ import annotations
import logging,re,os
from threading import Thread
from datetime import date
from pathlib import Path
from fastapi import FastAPI,BackgroundTasks,HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field
import fresh_g2b_store as store
from fresh_g2b_site import (
    search_one,opening_for_one,discover_attachments,download_attachment,SourceBlocked
)

ROOT=Path(__file__).parent
app=FastAPI(title="나라장터 실제 사이트 · 새 DB 독립 수집",version="1.0",
            docs_url=None,redoc_url=None)
BID=re.compile(r"^(?:R\d{2}[A-Z]{2}\d{8}|\d{11})$")
ORD=re.compile(r"^\d{3}$")

class SearchBody(BaseModel):
    detail10:str=Field(pattern=r"^\d{10}$")
    first:str=Field(min_length=10,max_length=10)
    last:str=Field(min_length=10,max_length=10)
    month:str|None=None
    page:int=Field(default=1,ge=1,le=10)

class BidBody(BaseModel):
    bid_no:str=Field(pattern=r"^(?:R\d{2}[A-Z]{2}\d{8}|\d{11})$")
    bid_ord:str=Field(default="000",pattern=r"^\d{3}$")

def _create_job_or_409(kind,args):
    try:
        return store.create_job(kind,args)
    except RuntimeError as exc:
        if str(exc) in ("FRESH_CRAWLER_ALREADY_RUNNING","FRESH_CRAWLER_ALREADY_QUEUING"):
            raise HTTPException(409,str(exc)) from None
        raise

def _run(job_id,kind,args):
    try:
        store.change_job(job_id,"running")
        store.attempt(job_id,kind,"started",
            args.get("bid_no",""),args.get("bid_ord",""))
        if kind=="search":
            w,result,records=search_one(args["detail10"],args["first"],
                args["last"],args.get("month"),args["page"])
            # ONLY records whose live search response itself carries exact
            # 10-digit original field qualify. No DB or title fallback.
            saved=store.page_saved(job_id,w,result.get("live_search_endpoint",""),
                {"response_sha":result.get("response_sha"),
                 "status":result.get("status"),"matched":records},
                records,result.get("official_total"))
            store.attempt(job_id,kind,"site_response_verified",
                source_url=result.get("live_search_endpoint",""))
            store.change_job(job_id,"completed",
                seen=result.get("returned_bid_ids",0),saved=saved)
        elif kind=="opening":
            bid,ord_=args["bid_no"],args["bid_ord"]
            case=store.notice_detail(bid,ord_)
            if not case:
                raise SourceBlocked("NOTICE_MUST_FIRST_BE_FOUND_ON_LIVE_SITE")
            if not case["notice"]["posted_on"]:
                raise SourceBlocked("ORIGINAL_PUBLISHED_DATE_MISSING")
            discovered=opening_for_one(bid,ord_,case["notice"]["posted_on"])
            if not discovered:
                raise SourceBlocked("OPENING_LISTING_NOT_FOUND_NOT_ZERO_BIDDERS")
            saved=0
            for item in discovered:
                listing,entry=item["listing"],item["opening"]
                saved+=store.save_opening(bid,ord_,listing,entry)
                winner=item.get("confirmed_winner_name")
                if winner:
                    store.save_final(bid,ord_,listing,entry,winner)
                store.attempt(job_id,"opening","websquare_verified",
                    bid,ord_,source_url=listing.get("listing_url",""))
            store.change_job(job_id,"completed",seen=len(discovered),saved=saved)
        elif kind=="files":
            bid,ord_=args["bid_no"],args["bid_ord"]
            case=store.notice_detail(bid,ord_)
            if not case:
                raise SourceBlocked("NOTICE_MUST_FIRST_BE_FOUND_ON_LIVE_SITE")
            found=discover_attachments(bid,ord_)
            if not found["files"]:
                raise SourceBlocked("OFFICIAL_ATTACHMENT_LINKS_NOT_FOUND")
            saved=0
            for item in found["files"][:10]:
                try:
                    data=download_attachment(item)
                    store.save_attachment(bid,ord_,data)
                    saved+=1
                    store.attempt(job_id,"attachment","saved",bid,ord_,
                                  source_url=data["url"])
                except Exception as err:
                    store.attempt(job_id,"attachment","error",bid,ord_,
                       source_url=item["url"],error_kind=type(err).__name__)
            store.change_job(job_id,"completed" if saved else "blocked",
                              seen=len(found["files"]),saved=saved,
                              error="" if saved else "OFFICIAL_ATTACHMENTS_UNAVAILABLE")
        else:
            raise ValueError("UNSUPPORTED_JOB_KIND")
    except Exception as err:
        # No false zero records and no raw response/cookie leakage.
        cause=type(err).__name__
        reason=str(err)[:160] if isinstance(err,(SourceBlocked,ValueError)) else cause
        logging.error("FRESH_SITE_JOB_FAILED id=%s kind=%s type=%s",
                      job_id,kind,cause)
        store.change_job(job_id,"blocked" if isinstance(err,SourceBlocked) else "error",
                         error=reason)
        store.attempt(job_id,kind,"failed",args.get("bid_no",""),
            args.get("bid_ord",""),error_kind=cause)

@app.on_event("startup")
def boot():
    store.initialize()
    if os.getenv("FRESH_SMOKE_ON_START")!="1":
        return
    # One and ONLY one bounded real search request in the independent DB.
    # The same startup probe is never repeated across redeploys.
    with store.conn() as con:
        exists=con.execute("""SELECT id FROM freshg2b.jobs
          WHERE args->>'origin'='startup_probe_v33' LIMIT 1""").fetchone()
    if exists:return
    today=date.today()
    try:begin=today.replace(year=today.year-10)
    except ValueError:begin=today.replace(year=today.year-10,day=28)
    args={"detail10":"8111159901","first":begin.isoformat(),
      "last":today.isoformat(),"month":"2026-10",
      "page":1,"origin":"startup_probe_v33"}
    id_=store.create_job("search",args)
    Thread(target=_run,args=(id_,"search",args),daemon=True).start()


@app.get("/",response_class=HTMLResponse)
def home():
    return HTMLResponse((ROOT/"fresh_g2b.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control":"no-store"})

@app.get("/health")
def health():
    with store.conn() as c:
        old=c.execute("SELECT to_regclass('procureflow.tenders') IS NOT NULL AS old").fetchone()["old"]
        count=c.execute("SELECT count(*) AS n FROM freshg2b.notices").fetchone()["n"]
        confirmed=c.execute("SELECT count(*) AS n FROM freshg2b.search_pages WHERE request_verified=true").fetchone()["n"]
    if old:raise HTTPException(503,"LEGACY_DB_PRESENT_BLOCKED")
    return {"status":"ok","isolated_new_db":True,"old_db_access":False,
            "new_db_notices":count,"official_site_search_live_proven":bool(confirmed)}

@app.get("/api/fresh/notices")
def notices(limit:int=40):
    return {"origin":"ONLY_FRESHG2B_OFFICIAL_SITE","items":store.recent_notices(limit)}

@app.get("/api/fresh/notices/{bid_no}/{bid_ord}")
def notice(bid_no:str,bid_ord:str):
    if not BID.fullmatch(bid_no) or not ORD.fullmatch(bid_ord):
        raise HTTPException(400,"BAD_G2B_NOTICE_ID")
    row=store.notice_detail(bid_no,bid_ord)
    if not row:raise HTTPException(404,"NOT_IN_FRESH_DB")
    return row

@app.get("/api/fresh/jobs/{job_id}")
def job(job_id:int):
    if job_id<1:raise HTTPException(400,"BAD_JOB_ID")
    data=store.job_detail(job_id)
    if not data:raise HTTPException(404,"UNKNOWN_JOB")
    return data

@app.post("/api/fresh/search")
def search(body:SearchBody,background:BackgroundTasks):
    try:
        from g2b_bid_notice_site_search import search_window
        w=search_window(body.detail10,body.first,body.last,body.month,body.page)
    except Exception as exc:
        raise HTTPException(400,str(exc)) from None
    args=body.model_dump()
    id_=_create_job_or_409("search",args)
    background.add_task(_run,id_,"search",args)
    return {"job_id":id_,"status":"queued","request_window":w,
            "source":"actual_g2b_site_not_existing_database"}

@app.post("/api/fresh/opening")
def opening(body:BidBody,background:BackgroundTasks):
    args=body.model_dump()
    if not store.notice_detail(body.bid_no,body.bid_ord):
        raise HTTPException(404,"FIRST_COLLECT_NOTICE_FROM_LIVE_SITE")
    id_=_create_job_or_409("opening",args)
    background.add_task(_run,id_,"opening",args)
    return {"job_id":id_,"status":"queued",
            "uses":"real_websquare_listing_and_bidder_detail"}

@app.post("/api/fresh/files")
def files(body:BidBody,background:BackgroundTasks):
    args=body.model_dump()
    if not store.notice_detail(body.bid_no,body.bid_ord):
        raise HTTPException(404,"FIRST_COLLECT_NOTICE_FROM_LIVE_SITE")
    id_=_create_job_or_409("files",args)
    background.add_task(_run,id_,"files",args)
    return {"job_id":id_,"status":"queued",
            "uses":"real_official_notice_detail_attachment_download"}

@app.get("/api/fresh/recent-jobs")
def recent_jobs():
    with store.conn() as c:
        rows=c.execute("""SELECT id,kind,status,rows_seen,rows_saved,
           error,created_at,finished_at FROM freshg2b.jobs
           ORDER BY id DESC LIMIT 25""").fetchall()
    return {"items":[store.public(x) for x in rows]}
