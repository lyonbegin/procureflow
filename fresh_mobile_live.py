"""Every mobile query executes a FRESH browser-authenticated public G2B WebSquare POST.

No database reads, no external paid API, no recycled tender rows. Jobs are
bounded in-memory only while the official Playwright browser search runs.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,date,timedelta
from threading import Lock
from uuid import uuid4
from zoneinfo import ZoneInfo
import logging,time,re

from fastapi import APIRouter,Query,HTTPException,Response
from g2b_bid_notice_site_search import run_search
from fresh_mobile_api import REGIONS,CATEGORIES,task_from_notice,original_value,date_text,agency_region

router=APIRouter(prefix="/api/mobile",tags=["Mobile live official G2B"])
JOBS={}
LOCK=Lock()
EXECUTOR=ThreadPoolExecutor(max_workers=1,thread_name_prefix="g2b_live_mobile")
MAX_WAITING=3
TTL_SECONDS=600
REGION_LABELS={
 "서울":"서울특별시","경기":"경기도","인천":"인천광역시",
 "부산":"부산광역시","대구":"대구광역시","대전":"대전광역시",
 "광주":"광주광역시","울산":"울산광역시","세종":"세종특별자치시",
 "강원":"강원특별자치도","충북":"충청북도","충남":"충청남도",
 "전북":"전북특별자치도","전남":"전라남도","경북":"경상북도",
 "경남":"경상남도","제주":"제주특별자치도"
}
CATEGORY_LABELS={"it":"시스템","design":"디자인","food":"급식",
 "cleaning":"청소","interior":"공사","education":"교육",
 "office":"납품","etc":"기타"}

def _public(row,filters):
    raw=row.get("raw") or {}
    if not isinstance(raw,dict):raw={}
    no=row["bid_no"];ord_=row["bid_ord"]
    posted=row.get("posted_on")
    if posted and re.fullmatch(r"\d{8}",posted):
        posted=posted[:4]+"-"+posted[4:6]+"-"+posted[6:8]
    deadline=date_text(raw)
    status_name=original_value(raw,("pbancSttsNm","bidPbancSttsNm"))
    status=""
    if "취소" in status_name or "마감" in status_name:status="CLOSED"
    elif "공고중" in status_name or "진행" in status_name:status="OPEN"
    task,basis=task_from_notice(raw,row.get("title",""))
    now=datetime.now(ZoneInfo("Asia/Seoul")).date()
    budget=original_value(raw,("asignBdgtAmt","bdgtAmt","presmptPrce","bssamt"))
    if not re.fullmatch(r"\d+(\.\d+)?",budget.replace(",","")):budget=""
    source_url=("https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo="
        +no+"&bidPbancOrd="+ord_)
    return {
        "id":no+"-"+ord_,"bidNo":no,"bidSeq":ord_,
        "title":row.get("title") or "","agencyName":row.get("agency") or "",
        "postedAt":posted or None,"deadlineAt":deadline or None,
        "deadlineSoon":bool(deadline and 0<=(date.fromisoformat(deadline)-now).days<=2),
        "status":status,"taskType":task,"taskTypeBasis":basis,
        "region":agency_region(row.get("agency") or ""),"regionBasis":"agency_name_only",
        "budgetAmount":budget or None,"originalUrl":source_url,
        "original_url_confirmed_format":False,
        "detail10":next(iter(row.get("direct_category_codes") or []),""),
        "categoryVerified":False,
        "source":"g2b_live_official_site","originalEvidence":True
    }

def clean_filters(keyword="",region="전국",category="",task_type="",sort="latest",
                  page=1,size=10,deadline_soon=False,include_closed=False):
    if region not in REGIONS:raise ValueError("UNSUPPORTED_REGION")
    if category not in ("",*CATEGORIES):raise ValueError("UNSUPPORTED_CATEGORY")
    if task_type not in ("","GOODS","SERVICE","CONSTRUCTION","FOREIGN","ETC"):
        raise ValueError("UNSUPPORTED_TASK")
    if sort not in ("latest","deadline","recommended"):raise ValueError("UNSUPPORTED_SORT")
    if not (1<=page<=10 and 1<=size<=10):raise ValueError("PAGE_OUT_OF_BOUNDS")
    return {"keyword":keyword.strip(),"region":region,"category":category,
        "task_type":task_type,"sort":sort,"page":page,"size":size,
        "deadline_soon":deadline_soon,"include_closed":include_closed}

def _work(job_id,params):
    with LOCK:
        JOBS[job_id]["status"]="running"
        JOBS[job_id]["started_at"]=time.time()
    today=datetime.now(ZoneInfo("Asia/Seoul")).date()
    # One official current-month date window per request; no historical DB fallback.
    first=today.replace(day=1).isoformat()
    last=today.isoformat()
    try:
        # UI "지역으로 찾기" means geographically relevant notices, NOT the
        # much narrower WebSquare "참가제한지역" eligibility dropdown.
        # Live evidence: G2B bidPbancNm='서울' returns matching fresh
        # public notices; dmstNm='서울' was ignored by the server.
        # Do not silently send the unrelated eligibility restriction.
        area=params["region"] if params["region"]!="전국" else ""
        keyword=params["keyword"]
        query_term=keyword or area or CATEGORY_LABELS.get(params["category"],"")
        result=run_search("",first,last,
           keyword=query_term,region="",
           category="",
           task_type=params["task_type"],page=params["page"],size=params["size"])
        if not result.get("search_request_verified") or not result.get("live_filter_verified"):
            raise RuntimeError("G2B_LIVE_UNVERIFIED_"+str(result.get("reason") or result.get("status")))
        raw=(result.get("matched_explicit_detail10") or [])+(result.get("pending_original_detail10_verification") or [])
        if area:
            raw=[row for row in raw if area in (row.get("title") or "") or
                 area in (row.get("agency") or "")]
        if params["category"]:
            category_terms=CATEGORIES[params["category"]]
            raw=[row for row in raw if any(term.lower() in
                  ((row.get("title") or "")+" "+(row.get("agency") or "")).lower()
                  for term in category_terms)]
        if area and keyword:
            # Two independent G2B live searches find keyword matches in
            # locality-labelled notices and locality matches under keyword.
            other=run_search("",first,last,keyword=area,region="",
                category="",
                task_type=params["task_type"],page=params["page"],size=params["size"])
            if not other.get("search_request_verified") or not other.get("live_filter_verified"):
                raise RuntimeError("G2B_LIVE_UNVERIFIED_SECOND_REGION_QUERY_"+
                    str(other.get("reason") or other.get("status")))
            raw.extend(row for row in
                (other.get("matched_explicit_detail10") or [])+
                (other.get("pending_original_detail10_verification") or [])
                if keyword.lower() in ((row.get("title") or "")+" "+
                      (row.get("agency") or "")).lower() and
                   (not params["category"] or any(term.lower() in
                      ((row.get("title") or "")+" "+(row.get("agency") or "")).lower()
                      for term in CATEGORIES[params["category"]])))
            dedup={}
            for row in raw:
                dedup[(row["bid_no"],row["bid_ord"])]=row
            raw=list(dedup.values())[:params["size"]]
        items=[_public(x,params) for x in raw]
        if area:
            for item in items:
                if not item["region"] and area in item["title"]:
                    item["region"]=area
                    item["regionBasis"]="notice_title_match"
        # Optional display constraints that are not verified as direct official
        # query fields (e.g. deadline) must be applied ONLY to this fresh response.
        if params["deadline_soon"]:
            items=[x for x in items if x["deadlineSoon"]]
        if not params["include_closed"]:
            items=[x for x in items if x["status"]!="CLOSED"]
        if params["sort"]=="deadline":
            items.sort(key=lambda x:x["deadlineAt"] or "9999-12-31")
        out={"status":"completed","items":items,"total":len(items),
           "officialTotal":result.get("official_total"),
           "page":params["page"],"size":params["size"],
           "hasMore":bool(result.get("next_page")),
           "source":"g2b_live_official_site","db_reads":0,
           "live_search_verified":True,"requestWindow":result.get("request_window"),
           "officialEndpoint":result.get("live_search_endpoint"),
           "responseSha":result.get("response_sha"),
           "regionMatchBasis":"notice_title_or_agency_name" if area else "none",
           "searchScope":"official_current_month_limited_pages",
           "appliedOfficialFilters":{"bidPbancNm":query_term,
               "source_region_eligibility_code":None,
               "area_match":area or None,"category_search_term":CATEGORY_LABELS.get(params["category"],""),
               "task_type":params["task_type"],"page":params["page"],"size":params["size"]},
           "filterNotes":[
              "선택 조건으로 나라장터 공식 사이트에 매번 새로 검색합니다. DB 결과를 사용하지 않습니다.",
              ("지역 "+area+"은 공고명·발주기관명에 지역명이 포함된 공고만 표시합니다. "
               "참가제한지역과 다르며 검색 범위에 따라 누락될 수 있습니다.") if area else
               "전국 공고를 검색합니다.",
              "현재 검색은 이번 달 공고의 지정 페이지 기준이며 전체 공고 전수검색은 아닙니다.",
              "게시일·마감일·예산 등 원문에서 확인되지 않은 값은 임의로 채우지 않습니다."]}
        with LOCK:
            JOBS[job_id]["result"]=out
            JOBS[job_id]["status"]="completed"
            JOBS[job_id]["finished_at"]=time.time()
        logging.info("G2B_LIVE_MOBILE_VERIFIED %s",{"job":job_id,"rows":len(items),
                "source":out["source"],"db_reads":0})
    except Exception as exc:
        error=str(exc)[:180]
        with LOCK:
            JOBS[job_id]["status"]="blocked"
            JOBS[job_id]["error"]=error
            JOBS[job_id]["finished_at"]=time.time()
        logging.warning("G2B_LIVE_MOBILE_BLOCKED job=%s reason=%s",job_id,error)

@router.get("/live",status_code=202)
def start_live_search(response:Response,
    keyword:str=Query("",max_length=160),
    region:str=Query("전국",max_length=20),
    category:str=Query("",max_length=24),
    task_type:str=Query("",max_length=24),
    sort:str=Query("latest",max_length=20),
    page:int=Query(1,ge=1,le=10),
    size:int=Query(10,ge=1,le=10),
    deadline_soon:bool=False,
    include_closed:bool=False):
    try:params=clean_filters(keyword,region,category,task_type,sort,page,size,
                            deadline_soon,include_closed)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    with LOCK:
        now=time.time()
        for key,job in list(JOBS.items()):
            if now-job["created_at"]>TTL_SECONDS and job["status"] in ("completed","blocked"):
                JOBS.pop(key,None)
        pending=sum(j["status"] in ("queued","running") for j in JOBS.values())
        if pending>=MAX_WAITING:
            raise HTTPException(429,"G2B_LIVE_SEARCH_BUSY_TRY_AGAIN")
        job_id=uuid4().hex
        JOBS[job_id]={"status":"queued","created_at":now,"params":params,
                      "result":None,"error":None}
        EXECUTOR.submit(_work,job_id,params)
    response.headers["Cache-Control"]="no-store"
    return {"status":"queued","jobId":job_id,"source":"g2b_live_official_site",
            "db_reads":0,"poll":"/api/mobile/live/jobs/"+job_id}

@router.get("/live/jobs/{job_id}")
def live_search_job(job_id:str):
    if not re.fullmatch("[a-f0-9]{32}",job_id):raise HTTPException(400,"INVALID_JOB_ID")
    with LOCK:
        job=JOBS.get(job_id)
        if not job:raise HTTPException(404,"UNKNOWN_OR_EXPIRED_G2B_JOB")
        state=job["status"]
        if state=="completed":return job["result"]
        if state=="blocked":
            return {"status":"blocked","reason":job["error"],"source":"g2b_live_official_site",
                    "db_reads":0,"live_search_verified":False,"items":[]}
        return {"status":state,"source":"g2b_live_official_site","db_reads":0,
                "live_search_verified":False,"items":[]}
