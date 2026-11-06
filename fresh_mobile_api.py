"""Read-only mobile search over FRESH official-site G2B notices.

The only database is freshg2b; no old imported procurement requests,
third-party BidPicker, data.go.kr OpenAPI, or fabricated sample data.
Keyword search and agency-name locality are explicit, not bid eligibility.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
import re

from fastapi import APIRouter, Query, HTTPException
import fresh_g2b_store as store

router=APIRouter(prefix="/api/mobile",tags=["Mobile official G2B discovery"])

REGIONS=("전국","서울","경기","인천","부산","대구","대전","광주","울산","세종",
         "강원","충북","충남","전북","전남","경북","경남","제주")
CATEGORIES={
 "it":("시스템","소프트웨어","네트워크","전산","정보화","ICT","SW","서버","DNS","데이터","인공지능","AI"),
 "design":("디자인","인쇄","홍보물","시각디자인","편집","홍보영상"),
 "food":("급식","식자재","식품","식재료","도시락","식당"),
 "cleaning":("청소","위생","시설관리","소독","경비","미화"),
 "interior":("인테리어","리모델링","수선","신축","공사","건축"),
 "education":("교육","강의","연수","훈련","학습"),
 "office":("사무용품","사무기기","복사용지","물품","구매","납품"),
 "etc":("기타",)
}
TASK_CODES={"GOODS":("조070001","01"),"CONSTRUCTION":("조070002","02"),
            "SERVICE":("조070003","03")}
TASK_TITLE={"GOODS":("구매","납품","물품"),"SERVICE":("용역","유지보수","운영","관리"),
            "CONSTRUCTION":("공사","보수공사","설치공사")}
DATE_KEYS=("bidClseDt","bidCloseDt","bidClseDate","bidClseDttm","bidClseYmd")
BUDGET_KEYS=("asignBdgtAmt","bdgtAmt","presmptPrce","bssamt")
TYPE_KEYS=("prcmBsneSeCd","bidPbancBsneClsfCd")
STATUS_KEYS=("bidPbancPgstCdNm","bidNtceSttusNm","bidPbancSttsCdNm")
OFFICIAL_DETAIL="https://www.g2b.go.kr/link/PNPE027_01/single/"

def original_value(raw,keys):
    if not isinstance(raw,dict):return ""
    for key in keys:
        value=raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""

def date_text(raw):
    text=original_value(raw,DATE_KEYS)
    digits=re.sub(r"[^0-9]","",text)
    if len(digits)<8:return ""
    try:return date.fromisoformat(digits[:4]+"-"+digits[4:6]+"-"+digits[6:8]).isoformat()
    except ValueError:return ""

def agency_region(agency):
    """Label an agency NAME only; never interpret as tender eligibility."""
    for name in REGIONS[1:]:
        if name in (agency or ""):return name
    return ""

def task_from_notice(raw,title):
    official_label=original_value(raw,("prcmBsneSeCdNm","bidPbancBsneClsfCdNm"))
    for keyword,label in (("물품","GOODS"),("공사","CONSTRUCTION"),("용역","SERVICE")):
        if keyword in official_label:return label,"official_label"
    code=original_value(raw,TYPE_KEYS)
    for label,vals in TASK_CODES.items():
        if code in vals:return label,"official_code"
    t=title or ""
    for label in ("CONSTRUCTION","SERVICE","GOODS"):
        if any(term.lower() in t.lower() for term in TASK_TITLE[label]):
            return label,"title_keyword_unverified"
    return "","unverified"

def map_notice(row):
    no=row["bid_no"]
    ord_=row["bid_ord"]
    raw=row.get("original_json") or {}
    if not isinstance(raw,dict):raw={}
    title=row.get("title") or ""
    dt=date_text(raw)
    task,basis=task_from_notice(raw,title)
    today=datetime.now(ZoneInfo("Asia/Seoul")).date()
    status_original=original_value(raw,STATUS_KEYS)
    if dt and date.fromisoformat(dt)<today:
        status="CLOSED"
    elif status_original and any(x in status_original for x in ("마감","취소","종료")):
        status="CLOSED"
    elif status_original and any(x in status_original for x in ("진행","공고중","접수")):
        status="OPEN"
    else:status=""  # Never claim open when source is silent.
    budget=original_value(raw,BUDGET_KEYS)
    if budget and not re.fullmatch(r"\d+(\.\d+)?",budget.replace(",","")):budget=""
    source_url=OFFICIAL_DETAIL+"?"+urlencode({"bidPbancNo":no,"bidPbancOrd":ord_})
    return {
      "id":no+"-"+ord_,"bidNo":no,"bidSeq":ord_,
      "title":title,"agencyName":row.get("agency") or "",
      "demandAgencyName":"","taskType":task,"taskTypeBasis":basis,
      "region":agency_region(row.get("agency") or ""),
      "regionBasis":"agency_name_only" if agency_region(row.get("agency") or "") else "unverified",
      "postedAt":row["posted_on"].isoformat() if isinstance(row.get("posted_on"),date) else row.get("posted_on"),
      "capturedAt":row["first_seen"].isoformat() if isinstance(row.get("first_seen"),datetime) else row.get("first_seen"),
      "deadlineAt":dt or None,"deadlineSoon":bool(dt and 0<=(date.fromisoformat(dt)-today).days<=2),
      "budgetAmount":budget or None,"status":status,
      "originalUrl":source_url,"original_url_confirmed_format":False,
      "categoryVerified":bool(row.get("category_verified")),
      "detail10":row.get("detail10") or "",
      "source":"fresh_g2b_official_site","originalEvidence":bool(row.get("response_sha")),
      "noticeKindName":"","contractMethodName":"","bidMethodName":"","summaryText":""
    }

def _contains_clause(column,parts,conditions,values):
    terms=["position(lower(%s) in lower("+column+"))>0" for _ in parts]
    conditions.append("("+" OR ".join(terms)+")")
    values.extend(parts)

def _date_expression():
    # Safe textual comparison of an eight-digit YYYYMMDD value, not an
    # unsafe cast of arbitrary untrusted site JSON.
    raw="coalesce(n.original_json->>'bidClseDt',n.original_json->>'bidCloseDt',n.original_json->>'bidClseDate','')"
    return "substring(regexp_replace("+raw+",'[^0-9]','','g') from 1 for 8)"

def search_notices(*,keyword="",region="전국",category="",task_type="",sort="latest",
                   page=1,size=10,deadline_soon=False,include_closed=False):
    if region not in REGIONS:raise ValueError("지원하지 않는 지역")
    if category not in ("",*CATEGORIES):raise ValueError("지원하지 않는 업종")
    if task_type not in ("",*TASK_CODES,"FOREIGN","ETC"):raise ValueError("지원하지 않는 업무구분")
    if sort not in ("latest","deadline","recommended"):raise ValueError("지원하지 않는 정렬")
    if not (1<=int(page)<=200 and 1<=int(size)<=50):raise ValueError("페이지 범위 오류")
    conditions=["TRUE"]
    values=[]
    notes=["지역은 발주기관 이름 기준입니다. 실제 입찰 참가 가능 지역과 다를 수 있습니다."]
    if keyword.strip():
        term=keyword.strip()
        conditions.append("(position(lower(%s) in lower(n.title))>0 OR "
                          "position(lower(%s) in lower(n.agency))>0 OR "
                          "position(lower(%s) in lower(n.bid_no))>0)")
        values.extend([term]*3)
    if region!="전국":
        conditions.append("position(%s in n.agency)>0")
        values.append(region)
    if category:
        _contains_clause("n.title",CATEGORIES[category],conditions,values)
        notes.append("업종은 공고명 키워드에 따른 임시 필터입니다. 공식 세부품명 분류 검증이 아닙니다.")
    if task_type:
        if task_type not in TASK_CODES:
            conditions.append("FALSE")
        else:
            raw_code="coalesce(n.original_json->>'prcmBsneSeCd',n.original_json->>'bidPbancBsneClsfCd','')"
            parts=["("+raw_code+"=%s)" for _ in TASK_CODES[task_type]]
            values.extend(TASK_CODES[task_type])
            parts.extend(["position(lower(%s) in lower(n.title))>0" for _ in TASK_TITLE[task_type]])
            values.extend(TASK_TITLE[task_type])
            conditions.append("("+" OR ".join(parts)+")")
            notes.append("업무구분은 공식 분류값 또는 공고명 키워드로 조회합니다. 미검증 항목이 있을 수 있습니다.")
    deadline=_date_expression()
    day=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    limitday=(datetime.now(ZoneInfo("Asia/Seoul")).date()+timedelta(days=2)).strftime("%Y%m%d")
    if deadline_soon:
        conditions.append("("+deadline+" BETWEEN %s AND %s)")
        values.extend([day,limitday])
        notes.append("마감일이 원본 데이터에 없는 공고는 마감임박 필터에서 제외합니다.")
    if not include_closed:
        # Unknown dates must not be silently treated as closed.
        conditions.append("("+deadline+" !~ '^[0-9]{8}$' OR "+deadline+">=%s)")
        values.append(day)
    where=" AND ".join(conditions)
    if sort=="deadline":
        order="CASE WHEN "+deadline+" ~ '^[0-9]{8}$' THEN "+deadline+" ELSE '99999999' END ASC,n.first_seen DESC"
        notes.append("마감일 미확인 공고는 마감일 정렬에서 뒤로 표시됩니다.")
    else:
        order="n.first_seen DESC,n.posted_on DESC NULLS LAST,n.bid_no DESC"
        if sort=="recommended":
            notes.append("추천 점수가 없어 수집 최신순으로 표시합니다.")
    query=("SELECT n.bid_no,n.bid_ord,n.detail10,n.title,n.agency,n.posted_on,"
            "n.original_json,n.response_sha,n.category_verified,n.first_seen "
            "FROM freshg2b.notices n WHERE "+where+" ORDER BY "+order+" LIMIT %s OFFSET %s")
    with store.conn() as conn:
        count=conn.execute("SELECT count(*) AS n FROM freshg2b.notices n WHERE "+where,values).fetchone()["n"]
        rows=conn.execute(query,[*values,size,(page-1)*size]).fetchall()
    return {"source":"fresh_g2b_official_site","origin":"ONLY_FRESHG2B_OFFICIAL_SITE",
      "total":int(count),"page":page,"size":size,
      "hasMore":page*size<int(count),"items":[map_notice(row) for row in rows],
      "filterNotes":notes,"searchBasis":"fresh_database_after_real_official_site_collection",
      "no_external_third_party_api":True}

@router.get("/notices")
def list_mobile_notices(
    keyword:str=Query("",max_length=160),
    region:str=Query("전국",max_length=20),
    category:str=Query("",max_length=40),
    task_type:str=Query("",max_length=20),
    sort:str=Query("latest",max_length=24),
    page:int=Query(1,ge=1,le=200),
    size:int=Query(10,ge=1,le=50),
    deadline_soon:bool=False,
    include_closed:bool=False
):
    try:
        return search_notices(keyword=keyword,region=region,category=category,
          task_type=task_type,sort=sort,page=page,size=size,
          deadline_soon=deadline_soon,include_closed=include_closed)
    except ValueError as err:
        raise HTTPException(400,str(err)) from None

@router.get("/notices/{bid_no}/{bid_ord}")
def mobile_notice_detail(bid_no:str,bid_ord:str):
    if not re.fullmatch(r"(R\d{2}[A-Z]{2}\d{8}|\d{11})",bid_no) or not re.fullmatch(r"\d{3}",bid_ord):
        raise HTTPException(400,"INVALID_G2B_NOTICE_ID")
    data=store.notice_detail(bid_no,bid_ord)
    if not data:raise HTTPException(404,"NOT_IN_FRESH_DB")
    # Always return real stored evidence, never invent missing deadlines.
    item=map_notice(data["notice"])
    return {"source":"fresh_g2b_official_site","item":item,
      "executions":data["executions"],"offers":data["offers"],
      "final_awards":data["final_awards"],"attachments":data["attachments"]}

