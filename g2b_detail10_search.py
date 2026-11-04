"""Actual G2B search: server-side EXACT 10-digit detailed category, not 8-digit bulk crawl.

One request is ONE page of ONE calendar month inside the historical range.
The entire historical horizon is a *filter*, never an implicit 121-month job.
Returned bids without an explicit official 10-digit code remain unverified.
"""
from __future__ import annotations
from datetime import date, timedelta
from calendar import monthrange
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import re

from g2b_official_notices import api_key

API = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch02"
DETAIL_FIELD = "dtilPrdctClsfcNo"
EXACT_FIELDS = ("dtilPrdctClsfcNo", "dtilPrdlstClsfcNo", "dtilPrdctClsfcCd")
ID = re.compile(r"(?:R\d{2}BK\d{8}|\d{11})\Z")
TEN = re.compile(r"\d{10}\Z")
MONTH = re.compile(r"(20\d{2})-(0[1-9]|1[0-2])\Z")
CUTOFF = date(2026, 10, 22)
MIN_DATE = date(2016, 10, 24)


def _months_back(d: date) -> str:
    year,month=(d.year-1,12) if d.month==1 else (d.year,d.month-1)
    return f"{year:04d}-{month:02d}"


def _official_response(document):
    if not isinstance(document, dict) or not isinstance(document.get("response"), dict):
        raise ValueError("INVALID_OFFICIAL_SEARCH_ENVELOPE")
    envelope = document["response"]
    header = envelope.get("header") or {}
    if str(header.get("resultCode", "")) not in ("00", "0"):
        # Do not persist a raw message; it may contain request data.
        raise ValueError("OFFICIAL_SEARCH_REJECTED_CODE_" + str(header.get("resultCode", ""))[:8])
    body = envelope.get("body") or {}
    raw = body.get("items") or []
    if isinstance(raw, dict):
        raw = raw.get("item") or []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("OFFICIAL_SEARCH_ITEMS_INVALID")
    try:
        count = int(body.get("totalCount") or 0)
    except (ValueError, TypeError):
        raise ValueError("OFFICIAL_SEARCH_TOTAL_COUNT_INVALID") from None
    if count < 0 or len(raw) > count:
        raise ValueError("OFFICIAL_SEARCH_COUNT_INCONSISTENT")
    return raw, count


def _normalize(item, detail10, agency):
    if not isinstance(item, dict):
        raise ValueError("OFFICIAL_SEARCH_NONOBJECT_ROW")
    raw_codes = {str(item[k]).strip() for k in EXACT_FIELDS
                 if k in item and item[k] not in (None, "")}
    bid_no = str(item.get("bidNtceNo") or "").strip()
    bid_ord = str(item.get("bidNtceOrd") or "000").strip().zfill(3)
    if not ID.fullmatch(bid_no) or not re.fullmatch(r"\d{3}", bid_ord):
        return "rejected_invalid_bid_identifier", None
    name = str(item.get("ntceInsttNm") or item.get("dminsttNm") or "")
    if agency and agency.casefold() not in name.casefold():
        return "rejected_agency", None
    if raw_codes and detail10 not in raw_codes:
        return "rejected_wrong_detail10", None
    row = {
        "bid_no": bid_no, "bid_ord": bid_ord,
        "title": str(item.get("bidNtceNm") or "")[:400],
        "agency": name[:200],
        "notice_date": str(item.get("bidNtceDt") or "")[:25],
        "exact_detail10": detail10 if detail10 in raw_codes else None,
        "source": "official_bidpublicinfo_service_pps_search",
        "original_url": "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo="+bid_no+"&bidPbancOrd="+bid_ord,
    }
    return ("matched_explicit_detail10" if detail10 in raw_codes else
            "pending_official_detail10_confirmation"), row


def search_one_page(detail10: str, start: str, end: str, cursor: str | None = None,
                    page: int = 1, page_size: int = 100, agency: str = "",
                    *, request_fn=None, key: str | None = None):
    """One bounded remote SEARCH request, never download every bid announcement.

    Official service search applies dtilPrdctClsfcNo before pagination. Each
    returned record is separately checked; if the API omits its code, the
    record remains a *candidate*, not a verified matching bid.
    """
    if not isinstance(detail10, str) or not TEN.fullmatch(detail10):
        raise ValueError("EXACT_TEN_DIGIT_FILTER_REQUIRED")
    first,last = date.fromisoformat(start),date.fromisoformat(end)
    if first < MIN_DATE or last > CUTOFF or first > last:
        raise ValueError("INVALID_SELECTED_NOTICE_HISTORICAL_RANGE")
    if not isinstance(page,int) or not 1 <= page <= 10000:
        raise ValueError("INVALID_PAGE")
    if not isinstance(page_size,int) or not 1 <= page_size <= 100:
        raise ValueError("INVALID_PAGE_SIZE")
    if not isinstance(agency,str) or len(agency)>100 or any(ord(c)<32 for c in agency):
        raise ValueError("INVALID_AGENCY")
    c = cursor or last.strftime("%Y-%m")
    if not MONTH.fullmatch(c):
        raise ValueError("INVALID_MONTH_CURSOR")
    yy,mm=map(int,c.split("-"))
    month_start=date(yy,mm,1)
    month_end=date(yy,mm,monthrange(yy,mm)[1])
    if month_end < first or month_start > last:
        raise ValueError("MONTH_CURSOR_OUTSIDE_SEARCH_RANGE")
    period_start=max(first,month_start)
    period_end=min(last,month_end)
    params={
        "type":"json","inqryDiv":"1",
        "inqryBgnDt":period_start.strftime("%Y%m%d")+"0000",
        "inqryEndDt":period_end.strftime("%Y%m%d")+"2359",
        DETAIL_FIELD:detail10,"pageNo":page,"numOfRows":page_size
    }
    metadata={"source":"official_g2b_server_filtered_search",
      "operation":"getBidPblancListInfoServcPPSSrch02",
      "filter_field":DETAIL_FIELD, "exact_detail10":detail10,
      "selected_range":{"start":start,"end":end},
      "request_window":{"start":period_start.isoformat(),"end":period_end.isoformat()},
      "page":page,"page_size":page_size,"agency":agency,
      "new_crawler_run":False,"bulk_8digit_discovery":False,
      "outcome_collection_executed":False,"bid_submitted":False}
    service_key=api_key() if key is None else key
    if not service_key:
        return {**metadata,"status":"blocked_missing_official_api_credential",
            "api_requests":0,"matched":[],"unverified_candidates":[],
            "official_total":None, "next":None,
            "reason":"SERVER_SIDE_OFFICIAL_SEARCH_REQUIRES_EXISTING_SERVICE_KEY"}
    params["serviceKey"]=service_key
    if request_fn is None:
        def request_fn(url):
            req=Request(url,headers={"Accept":"application/json",
                    "User-Agent":"ProcureFlow-ExactDetailSearch/1.0"})
            with urlopen(req,timeout=25) as rsp:
                return json.loads(rsp.read(12000000))
    try:
        # Do not log this URL: it contains the official service key.
        document=request_fn(API+"?"+urlencode(params))
        items,total=_official_response(document)
    except Exception as exc:
        return {**metadata,"status":"source_error","api_requests":1,
            "matched":[],"unverified_candidates":[],"official_total":None,
            "next":None, "reason":"OFFICIAL_SEARCH_FAILED_"+type(exc).__name__}
    matched=[]
    pending=[]
    rejected={}
    seen=set()
    for item in items:
        reason,row=_normalize(item,detail10,agency)
        if row:
            identifier=(row["bid_no"],row["bid_ord"])
            if identifier in seen:
                continue
            seen.add(identifier)
            if reason=="matched_explicit_detail10":
                matched.append(row)
            else:
                pending.append(row)
        else:
            rejected[reason]=rejected.get(reason,0)+1
    if len(items)>page_size or (page-1)*page_size+len(items)>total:
        return {**metadata,"status":"blocked_inconsistent_official_pagination",
            "api_requests":1,"matched":[],"unverified_candidates":[],
            "official_total":total,"next":None}
    next_cursor=None
    next_page=None
    if page*page_size<total:
        if len(items)<page_size:
            return {**metadata,"status":"blocked_truncated_official_page",
                "api_requests":1,"matched":[],"unverified_candidates":[],
                "official_total":total,"next":None}
        next_cursor=c
        next_page=page+1
    else:
        prev=_months_back(month_start)
        if date.fromisoformat(prev+"-01").replace(day=monthrange(*map(int,prev.split("-")))[1])>=first:
            next_cursor=prev
            next_page=1
    return {**metadata,
        "status":"partial_more_filtered_windows" if next_cursor else "window_range_exhausted",
        "api_requests":1,"official_total":total,
        "official_rows_returned":len(items),
        "matched":matched,"unverified_candidates":pending,
        "rejected":rejected,
        "matched_count":len(matched),"unverified_count":len(pending),
        "next":{"cursor":next_cursor,"page":next_page} if next_cursor else None,
        "full_history_verified":False,
        "message":"공식 10자리 서버 필터 검색 결과. 일치코드 미제공 공고는 미검증, 개찰·낙찰결과는 별도 실제 조회 필요."
    }
