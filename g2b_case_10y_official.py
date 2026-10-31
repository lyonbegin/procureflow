"""Official G2B full ten-year monthly history retrieval for ONE category.

Run only after an official public-data service key is available in Railway.
Never scan unrelated cases. A month is 'completed' only after *all* API pages
were read, response category codes explicitly matched and no errors occurred.
"""
import json
import os
import re
from datetime import date
import calendar
from urllib.parse import urlencode
from urllib.request import urlopen,Request
from g2b_case_10y import CASE_BID,CAT8,BEGIN,END,ensure_schema
from db import session

API="https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"
def _service_key():
    return os.getenv("G2B_API_KEY") or os.getenv("DATA_GO_KR_SERVICE_KEY") or ""

def _parse(response):
    if not isinstance(response,dict):raise ValueError("g2b_api_not_json_object")
    envelope=response.get("response") or {}
    head=envelope.get("header") or {}
    if str(head.get("resultCode","")) not in ("00","0"):
        raise ValueError("g2b_api_result_"+str(head.get("resultCode"))+":"+str(head.get("resultMsg",""))[:75])
    body=envelope.get("body") or {}
    items=body.get("items") or []
    if isinstance(items,dict):items=items.get("item") or []
    if isinstance(items,dict):items=[items]
    if not isinstance(items,list):raise ValueError("g2b_api_items_not_list")
    if any(not isinstance(item,dict) for item in items):
        raise ValueError("g2b_api_items_not_objects")
    if "totalCount" not in body:
        raise ValueError("g2b_api_total_count_missing")
    total=int(body["totalCount"])
    if total<0:
        raise ValueError("g2b_api_negative_total_count")
    return items,total


def _page_verdict(inspected:int,total:int,entries:int,page_size:int=500)->str:
    """Fail closed on early/empty/truncated pages; no false 'completed' months.

    This validates an official 8-digit discovery window ONLY. It does not
    certify 10-digit eligibility or opening/final-award evidence.
    """
    if (not isinstance(inspected,int) or not isinstance(total,int) or
            not isinstance(entries,int) or inspected<0 or total<0 or
            entries<0 or entries>page_size or inspected+entries>total):
        return "inconsistent"
    if inspected+entries==total:
        return "completed"
    if entries<page_size:
        return "incomplete_page"
    return "partial"

def _category_from(item):
    """Accept only a *dedicated official field*, not digits in bid title."""
    for k in ("prdctClsfcNo","prdlstClsfcNo","prdlstClsfcNo",
              "dtilPrdctClsfcNo","dtilPrdlstClsfcNo","prdctClsfcCd"):
        value=str(item.get(k) or "").strip()
        if re.fullmatch(r"\d{8}(\d{2})?",value):
            if value[:8]==CAT8:return True
            return False
    return None

def _write_month(first,last,status,matched=0,checked=0,page=1,err=""):
    with session() as con:
        con.execute("""UPDATE procureflow.g2b_case_10yr_windows
             SET status=%s,source=%s,matched=%s,checked=%s,page_cursor=%s,
               last_error=%s,updated_at=now()
             WHERE case_bid_no=%s AND first_day=%s AND last_day=%s
        """,(status,"official_bidpublicinfo",matched,checked,page,err[:300],CASE_BID,first,last))

def scan_month(first, pages_max=30):
    """Progress a single pre-registered month; next call resumes last page."""
    ensure_schema()
    if isinstance(first,str):first=date.fromisoformat(first)
    with session() as con:
        row=con.execute("""SELECT first_day,last_day,status,page_cursor,
                 checked,matched FROM procureflow.g2b_case_10yr_windows
                 WHERE case_bid_no=%s AND first_day=%s""",(CASE_BID,first)).fetchone()
    if not row:raise ValueError("month not in chosen ten-year horizon")
    if row["status"]=="completed":return {"status":"already_completed","first_day":str(first)}
    key=_service_key()
    if not key:
        _write_month(row["first_day"],row["last_day"],"blocked_missing_official_api_key",
                     row["matched"],row["checked"],row["page_cursor"])
        return {"status":"blocked_missing_official_api_key","first_day":str(first),
                "operation":"getBidPblancListInfoServcPPSSrch",
                "instructions":"Set existing Railway worker's G2B_API_KEY or DATA_GO_KR_SERVICE_KEY"}
    inspected=int(row["checked"])
    matched=int(row["matched"])
    page=int(row["page_cursor"])
    # A partial month advances only after a FULL 500-row page has been
    # persisted. A mismatched page_cursor/checked pair can silently skip
    # official pages and falsely certify a ten-year discovery window.
    # Fail closed before issuing any API request; never guess a new cursor.
    if (inspected<0 or matched<0 or matched>inspected or
            inspected%500!=0 or page!=inspected//500+1):
        _write_month(row["first_day"],row["last_day"],
                     "blocked_invalid_page_cursor",matched,inspected,page,
                     "checked_page_cursor_or_matched_inconsistent")
        return {"status":"blocked_invalid_page_cursor","first_day":str(first),
                "checked":inspected,"matched":matched,"next_page":page,
                "read_only":True}
    pages_max=max(1,min(30,int(pages_max)))
    params={"serviceKey":key,"type":"json","inqryDiv":"1",
        "inqryBgnDt":row["first_day"].strftime("%Y%m%d")+"0000",
        "inqryEndDt":row["last_day"].strftime("%Y%m%d")+"2359",
        "prdctClsfcNo":CAT8,"numOfRows":500}
    for _ in range(pages_max):
        params["pageNo"]=page
        url=API+"?"+urlencode(params)
        try:
            req=Request(url,headers={"Accept":"application/json",
                              "User-Agent":"ProcureFlow-G2B-Category/1.0"})
            with urlopen(req,timeout=22) as rsp:
                data=json.loads(rsp.read(15000000))
            entries,total=_parse(data)
        except Exception as exc:
            # urllib exceptions may include the serviceKey URL. Neither DB
            # audit nor REST output may persist an exception's raw message.
            reason="official_api_request_or_parse_failed:"+type(exc).__name__
            _write_month(row["first_day"],row["last_day"],"error",matched,inspected,page,reason)
            return {"status":"error","first_day":str(first),"reason":reason}
        verdict=_page_verdict(inspected,total,len(entries))
        if verdict in ("inconsistent","incomplete_page"):
            _write_month(row["first_day"],row["last_day"],"blocked_incomplete_api_page",
                         matched,inspected,page,"page_count_inconsistent_or_truncated")
            return {"status":"blocked_incomplete_api_page","first_day":str(first),
                    "page":page,"checked":inspected,"returned":len(entries),
                    "official_total_count":total,"reason":verdict}
        unknown=0
        invalid=0
        confirmed=[]
        for item in entries:
            cls=_category_from(item)
            if cls is None:
                unknown+=1
                continue
            if cls is not True:continue
            no=str(item.get("bidNtceNo") or "").strip()
            ord_=str(item.get("bidNtceOrd") or "000").zfill(3)
            if not re.fullmatch(r"R\d{2}BK\d{8}|\d{11}",no) or not re.fullmatch(r"\d{3}",ord_):
                invalid+=1
                continue
            pub=str(item.get("bidNtceDt") or "").strip()
            stamp=re.match(r"(20\d{2})[-./]?(\d{2})[-./]?(\d{2})",pub)
            if not stamp:
                invalid+=1
                continue
            try:
                day=date(int(stamp[1]),int(stamp[2]),int(stamp[3]))
            except ValueError:
                invalid+=1
                continue
            # A response for April must NEVER make March's month appear fully
            # checked even if its date lies somewhere in the ten-year range.
            if not row["first_day"]<=day<=row["last_day"]:
                invalid+=1
                continue
            # A malformed official amount must be treated as an unverified
            # page, not raise outside the HTTP/parse exception handler and
            # leave a misleading cursor state. Never silently coerce a
            # negative amount into a valid historical notice.
            raw_amount=item.get("asignBdgtAmt")
            if isinstance(raw_amount,(list,dict,bool)):
                invalid+=1
                continue
            try:
                amount=int(raw_amount) if raw_amount is not None and raw_amount!="" else 0
            except (ValueError,TypeError,OverflowError):
                invalid+=1
                continue
            if amount<0:
                invalid+=1
                continue
            confirmed.append((CASE_BID,no,ord_,CAT8,day,
                str(item.get("bidNtceNm") or "")[:350],
                str(item.get("dminsttNm") or item.get("ntceInsttNm") or "")[:250],
                amount or None,
                "https://www.g2b.go.kr/","official_openapi_explicit_code"))
        if unknown or invalid:
            reason=("undetermined_category_rows="+str(unknown)+
                    ";invalid_notice_or_month_rows="+str(invalid))
            _write_month(row["first_day"],row["last_day"],"blocked_unverified_response_scope",
                         matched,inspected,page,reason)
            return {"status":"blocked_unverified_response_scope",
                    "undetermined_rows":unknown,"invalid_scope_rows":invalid,
                    "page":page,"note":"No full month coverage without valid official category, notice and date"}
        with session() as con:
            for bid in confirmed:
                con.execute("""INSERT INTO procureflow.g2b_case_10yr_history(
                   case_bid_no,hist_notice_no,hist_notice_ord,classification8,
                   published_on,title,agency,amount,source_url,evidence)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(case_bid_no,hist_notice_no,hist_notice_ord)
                   DO UPDATE SET published_on=excluded.published_on,title=excluded.title,
                     agency=excluded.agency,amount=excluded.amount,
                     source_url=excluded.source_url,evidence=excluded.evidence,
                     collected_at=now()
                """,bid)
        inspected+=len(entries);matched+=len(confirmed);page+=1
        complete=verdict=="completed"
        _write_month(row["first_day"],row["last_day"],
                     "completed" if complete else "partial",
                     matched,inspected,page)
        if complete:
            return {"status":"completed","first_day":str(first),"checked":inspected,
                    "matched":matched,"total_records":total}
    return {"status":"partial","first_day":str(first),"next_page":page,
            "checked":inspected,"matched":matched}


def summarize_month_cursor(rows):
    """Pure, read-only and credential-free audit of the 121 discovery windows.

    A completed MONTH is a parent8 notice search only; neither official
    10-digit detail matching nor bidder-by-bidder opening/award completeness
    can be inferred from these cursors.
    """
    expected={}
    for year in range(BEGIN.year,END.year+1):
        for month in range(1,13):
            start=max(BEGIN,date(year,month,1))
            stop=min(END,date(year,month,calendar.monthrange(year,month)[1]))
            if start<=stop:expected[start]=stop
    seen=set()
    months=[]
    invalid=0
    for row in rows:
        start=row.get("first_day")
        stop=row.get("last_day")
        if (start not in expected or start in seen or stop!=expected.get(start)):
            invalid+=1
            continue
        seen.add(start)
        stat=str(row.get("status") or "unsearched")
        checked=max(0,int(row.get("checked") or 0))
        matched=max(0,int(row.get("matched") or 0))
        page=max(1,int(row.get("page_cursor") or 1))
        months.append({"first_day":start.isoformat(),
                       "last_day":stop.isoformat(),
                       "status":stat,"checked":checked,"matched":matched,
                       "next_page":page})
    months.sort(key=lambda r:r["first_day"])
    complete=sum(r["status"]=="completed" for r in months)
    candidates=[x for x in months if x["status"]!="completed"]
    candidates.sort(key=lambda r:(r["status"]!="partial",r["first_day"]))
    registry_ok=len(seen)==len(expected)==121 and invalid==0
    return {"bid_no":CASE_BID,"configured_parent8":CAT8,
            "requested_10digit_from_selected_notice":"8111159901",
            "period_start":BEGIN.isoformat(),"period_end":END.isoformat(),
            "registry_complete":registry_ok,
            "required_months":len(expected),
            "registered_months":len(seen),
            "invalid_or_duplicate_rows":invalid,
            "discovery_months_completed":complete,
            "discovery_months_remaining":len(expected)-complete,
            "next_month":candidates[0] if candidates else None,
            "eight_digit_notice_discovery_complete":registry_ok and complete==len(expected),
            "ten_year_exact_opening_and_award_complete":False,
            "read_only":True,"job_enqueued":False,"bid_submitted":False,
            "months":months,
            "caution":"A completed 8-digit discovery window is not verified 10-digit bidding, bidder amounts, rankings or final awards."}


def official_month_progress():
    """Read only saved monthly cursors; NEVER call the G2B API or mutate jobs."""
    with session() as con:
        rows=con.execute("""SELECT first_day,last_day,status,checked,matched,page_cursor
          FROM procureflow.g2b_case_10yr_windows
          WHERE case_bid_no=%s ORDER BY first_day""",(CASE_BID,)).fetchall()
    return summarize_month_cursor([dict(row) for row in rows])
