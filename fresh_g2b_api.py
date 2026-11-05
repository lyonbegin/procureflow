"""One-screen clean-source G2B ingestion. ZERO old DB imports/queries.

All jobs have explicit live request attempts. No stale 229 records are read.
HTTP POST queues one real site operation; GET endpoints only read newly acquired
records from the new independent PostgreSQL instance.
"""
from __future__ import annotations
import logging,re,os
from threading import Thread
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from calendar import monthrange
from pathlib import Path
from html import escape
from urllib.parse import urlencode
from fastapi import FastAPI,BackgroundTasks,HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
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

def latest_default_period():
    today=datetime.now(ZoneInfo("Asia/Seoul")).date()
    y,m=today.year,today.month-1
    if m==0:y,m=y-1,12
    start=date(y,m,min(today.day,monthrange(y,m)[1]))
    return start.isoformat(),today.isoformat()


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
        if kind=="latest_one":
            first,last=args["first"],args["last"]
            month=last[:7]
            total_seen=0
            page_count=0
            while month>=first[:7]:
                for page in range(1,11):
                    for retry in range(3):
                        try:
                            w,result,records=search_one("",first,last,month,page)
                            break
                        except SourceBlocked as exc:
                            # Retry transient G2B modal/search-render failures only.
                            reason=str(exc)
                            if retry>=2 or not any(x in reason for x in (
                                    "BID_NOTICE_10DIGIT_NOT_IN_ACTUAL_POST_REQUEST",
                                    "BID_NOTICE_SEARCH_BUTTON_NOT_FOUND",
                                    "G2B_OFFICIAL_SITE_RENDERED_EMPTY_AFTER_WAIT",
                                    "G2B_UI_RUNTIME")):
                                raise
                            store.attempt(job_id,"latest_one","transient_site_retry",
                                error_kind=reason[:120])

                    count=int(result.get("returned_bid_ids") or 0)
                    total_seen+=count
                    page_count+=1
                    found=store.save_first_unseen(
                        job_id,w,result.get("live_search_endpoint",""),
                        result.get("response_sha",""),records,
                        result.get("official_total"))
                    if found["saved"]==1:
                        store.attempt(job_id,"latest_one","new_notice_saved",
                            *(found["notice"].rsplit("-",1)),
                            source_url=result.get("live_search_endpoint",""))
                        store.change_job(job_id,"completed",
                            seen=total_seen,saved=1)
                        return
                    store.attempt(job_id,"latest_one","all_on_page_already_stored",
                        source_url=result.get("live_search_endpoint",""))
                    if count<10:
                        break
                y,m=map(int,month.split("-"))
                month=(f"{y-1:04d}-12" if m==1 else f"{y:04d}-{m-1:02d}")
            store.change_job(job_id,"completed",seen=total_seen,saved=0,
                             error="NO_NEW_NOTICE_IN_LAST_MONTH")
        elif kind=="search":
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
    # Never start a background smoke crawl automatically on app boot:
    # user-operated searches are the only source of latest_one jobs.
    store.initialize()


@app.get("/",response_class=HTMLResponse)
def home():
    markup=(ROOT/"fresh_g2b.html").read_text(encoding="utf-8")
    total=store.notice_count()
    markup=markup.replace('id="noticeCount">0</strong>',
                          'id="noticeCount">'+str(total)+'</strong>')
    latest=store.recent_notices(1)
    if latest:
        item=latest[0]
        no=escape(str(item["bid_no"]),quote=True)
        ord_=escape(str(item["bid_ord"]),quote=True)
        title=escape(str(item.get("title") or "공고명 확인 대기"))
        agency=escape(str(item.get("agency") or "기관 미확인"))
        verified="세부품명 원본 확인" if item.get("category_verified") else "세부품명 확인 대기"
        snippet=("<button class='item' data-no='"+no+"' data-ord='"+ord_+"'>"
                 "<div class='name'>"+title+"</div><div class='meta'>"+
                 no+"-"+ord_+" · "+agency+" · "+verified+
                 "</div></button>")
        markup=markup.replace(
            '<div class="list" id="noticeList"><div class="alert">최초 DB는 비어 있습니다.</div></div>',
            '<div class="list" id="noticeList">'+snippet+'</div>')

    return HTMLResponse(markup,headers={"Cache-Control":"no-store"})

@app.get("/live-notices",response_class=HTMLResponse)
def live_notices():
    """Server-render actual isolated-DB notices, even without browser JS."""
    items=store.recent_notices(100)
    rows=[]
    for item in items:
        no=str(item.get("bid_no") or "")
        ord_=str(item.get("bid_ord") or "")
        flag=("원본 10자리 확인" if item.get("category_verified")
              else "공식 필터 조회 / 상세 분류 확인 대기")
        detail="https://www.g2b.go.kr/link/PNPE027_01/single/?"+urlencode({
            "bidPbancNo":no,"bidPbancOrd":ord_})
        rows.append("<tr><td><a href='"+escape(detail,quote=True)+
            "' target='_blank' rel='noopener'>"+escape(no+"-"+ord_)+
            "</a></td><td>"+escape(str(item.get("title") or ""))+
            "</td><td>"+escape(str(item.get("agency") or ""))+
            "</td><td>"+escape(str(item.get("posted_on") or "미확인"))+
            "</td><td>"+escape(flag)+"</td></tr>")
    data_rows="".join(rows) if rows else "<tr><td colspan='5'>실제 수집 공고 0건</td></tr>"
    markup=("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
       "<meta name='viewport' content='width=device-width,initial-scale=1'>"
       "<title>나라장터 실제 수집 공고</title>"
       "<style>body{font:15px/1.7 system-ui,sans-serif;max-width:1300px;"
       "padding:20px;margin:auto;color:#142b44}table{border-collapse:collapse;"
       "width:100%}td,th{border-bottom:1px solid #dfe7f1;padding:10px;"
       "text-align:left}th{background:#f3f6fa}a{color:#1463b7}"
       ".scroll{overflow-x:auto}.muted{color:#56677e}"
       "</style></head><body><h1>나라장터 실제 신규 수집 결과</h1>"
       "<p>기존 DB 미사용 · 공식 나라장터 검색 응답 원본 기반 · 신규 DB "
       +str(len(items))+"건</p>"
       "<p class='muted'>상세 분류 확인 대기는 공식 10자리 검색 결과이지만 공고 상세의 "
       "10자리 코드 확인이 아직 끝나지 않은 상태입니다. "
       "개찰·낙찰 결과를 확인한 것으로 보지 않습니다.</p>"
       "<p><a href='/'>수집 관리화면으로 돌아가기</a></p>"
       "<div class='scroll'><table><thead><tr><th>공고번호</th><th>공고명</th>"
       "<th>공고기관</th><th>공고일</th><th>분류검증</th></tr></thead>"
       "<tbody>"+data_rows+"</tbody></table></div></body></html>")
    return HTMLResponse(markup,headers={"Cache-Control":"no-store"})


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

def _status_page(job, *, already_running=False):
    state=job["status"]
    done=state in ("completed","blocked","error")
    meta="" if done else '<meta http-equiv="refresh" content="3">'
    notice_html=("<p style='color:#175da5;font-weight:700'>"
                 "이미 실행 중인 작업이 있어 해당 작업 화면을 표시합니다. "
                 "중복 수집을 시작하지 않았습니다.</p>" if already_running else "")
    if state=="completed" and int(job.get("rows_saved") or 0)==1:
        event=next((e for e in job.get("events",[])
                    if e.get("status")=="new_notice_saved"),None)
        if event:
            no,ord_=event["bid_no"],event["bid_ord"]
            current=store.notice_detail(no,ord_)
            title=escape(str((current or {}).get("notice",{}).get("title") or "공고명 미확인"))
            notice_html=("<h2>신규 공고 1건 저장 완료</h2><p><strong>"+
                         title+"</strong></p><p>"+escape(no+"-"+ord_)+"</p>")
    elif state=="completed":
        notice_html="<h2>최근 1개월에 추가할 새 공고가 없습니다.</h2><p>이미 저장된 공고는 건너뛰었습니다.</p>"
    elif state in ("blocked","error"):
        notice_html="<h2>검색 실패 · 새 공고 저장 없음</h2><p>"+escape(str(job.get("error") or state))+"</p>"
    else:
        notice_html+="<h2>나라장터 최신 공고 확인 중</h2><p>작업 완료 여부를 자동으로 갱신합니다.</p>"
    return HTMLResponse(
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"+
        meta+"<title>공고 1건 수집 상태</title>"
        "<style>body{font:16px/1.65 system-ui,sans-serif;margin:35px auto;padding:0 20px;"
        "max-width:760px;color:#142b44}button{padding:14px 22px;background:#1463b7;color:#fff;"
        "border:0;border-radius:8px;cursor:pointer;font-size:16px}"
        "a{color:#1463b7}p{margin:12px 0}</style></head><body>"
        "<h1>나라장터 최신 공고 · 1건씩 수집</h1><p>작업 번호 #"+
        str(job["id"])+" · 상태 "+escape(state)+" · 확인 "+
        str(job.get("rows_seen") or 0)+"건 · 신규 저장 "+
        str(job.get("rows_saved") or 0)+"건</p>"+
        notice_html+
        ("<form method='post' action='/run-next'><button type='submit'>다음 신규 공고 1건 가져오기</button></form>"
         if done else "<p>현재 수집이 끝나면 다음 공고 1건을 시작할 수 있습니다.</p>")+
        "<p><a href='/'>메인 화면으로</a> · <a href='/live-notices'>저장된 공고 전체 보기</a></p>"
        "</body></html>",headers={"Cache-Control":"no-store"})


def _latest_job_args():
    first,last=latest_default_period()
    return {"first":first,"last":last,"detail10":"",
            "scope":"all_official_notices","limit_new":1}


def _latest_start_or_watch(background,args):
    """Create one task or reuse the current one without a raw JSON 409."""
    try:
        job_id=_create_job_or_409("latest_one",args)
    except HTTPException as exc:
        if exc.status_code!=409:
            raise
        active=store.active_job_id()
        if active is None:
            raise HTTPException(503,"작업 상태가 변경됐습니다. 화면을 갱신해 다시 실행하세요.") from None
        return active,False
    background.add_task(_run,job_id,"latest_one",args)
    return job_id,True


@app.post("/run-next")
def run_next_from_browser(background:BackgroundTasks):
    """Native browser POST redirects to the new or existing active job."""
    args=_latest_job_args()
    job_id,created=_latest_start_or_watch(background,args)
    suffix="" if created else "?already_running=1"
    return RedirectResponse("/run-status/"+str(job_id)+suffix,status_code=303)


@app.get("/run-status/{job_id}",response_class=HTMLResponse)
def run_status(job_id:int,already_running:bool=False):
    if job_id<1:raise HTTPException(400,"BAD_JOB_ID")
    job=store.job_detail(job_id)
    if not job:raise HTTPException(404,"UNKNOWN_JOB")
    return _status_page(job,already_running=already_running)


@app.post("/api/fresh/next")
def collect_one_new_notice(background:BackgroundTasks):
    args=_latest_job_args()
    job_id,created=_latest_start_or_watch(background,args)
    return {"job_id":job_id,"status":"queued" if created else "already_running",
            "already_running":not created,"limit_new":1,
            "first":args["first"],"last":args["last"],"order":"latest_first",
            "skip_existing":True}


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
