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
    # An absent/null item list is normal for a zero-result month. Explicit
    # scalar values (including falsey 0/False/"") are malformed responses;
    # the old 'or []' coercion could falsely certify a zero-result month.
    items=body.get("items",[])
    if items is None:items=[]
    if isinstance(items,dict):
        items=items.get("item",[])
        if items is None:items=[]
    if isinstance(items,dict):items=[items]
    if not isinstance(items,list):raise ValueError("g2b_api_items_not_list")
    if any(not isinstance(item,dict) for item in items):
        raise ValueError("g2b_api_items_not_objects")
    if "totalCount" not in body:
        raise ValueError("g2b_api_total_count_missing")
    # The official page total is a *count*, not a monetary amount or a
    # floating-point estimate. int(1.5) and int(True) silently fabricate
    # coverage and can turn a truncated page into a false completed month.
    raw_total=body["totalCount"]
    if type(raw_total) is int:
        total=raw_total
    elif isinstance(raw_total,str) and re.fullmatch(r"[0-9]+",raw_total.strip()):
        total=int(raw_total.strip())
    else:
        raise ValueError("g2b_api_total_count_not_nonnegative_integer")
    if total<0:
        raise ValueError("g2b_api_negative_total_count")
    return items,total


def _page_verdict(inspected:int,total:int,entries:int,page_size:int=500)->str:
    """Fail closed on early/empty/truncated pages; no false 'completed' months.

    This validates an official 8-digit discovery window ONLY. It does not
    certify 10-digit eligibility or opening/final-award evidence.
    """
    if (type(inspected) is not int or type(total) is not int or
            type(entries) is not int or type(page_size) is not int or
            inspected<0 or total<0 or entries<0 or page_size<=0 or
            entries>page_size or inspected+entries>total):
        return "inconsistent"
    if inspected+entries==total:
        return "completed"
    if entries<page_size:
        return "incomplete_page"
    return "partial"

def _category_from(item):
    """Validate *all* supplied official classification fields, not just the first.

    A valid parent8 followed by a conflicting detail/parent field must not
    silently certify the page. Conflicting official fields require review;
    this is still only 8-digit notice discovery, not exact-10 evidence.
    """
    codes=[]
    for k in ("prdctClsfcNo","prdlstClsfcNo",
              "dtilPrdctClsfcNo","dtilPrdlstClsfcNo","prdctClsfcCd"):
        raw=item.get(k)
        if raw is None or raw=="":
            continue
        value=str(raw).strip()
        if not re.fullmatch(r"\d{8}(\d{2})?",value):
            return None
        codes.append(value)
    if not codes:
        return None
    parents={code[:8] for code in codes}
    details={code for code in codes if len(code)==10}
    if len(parents)!=1 or len(details)>1:
        return None
    return next(iter(parents))==CAT8

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
    # Validate persisted cursor types BEFORE coercion, network access or a
    # completed-month shortcut. int(True), int(1.5), and int("2") can mask
    # corrupted coverage evidence; a completed row is not automatically proof.
    inspected=_audit_nonnegative_integer(row["checked"])
    matched=_audit_nonnegative_integer(row["matched"])
    page=_audit_nonnegative_integer(row["page_cursor"])
    if (inspected is None or matched is None or page is None or page<1):
        return {"status":"blocked_invalid_page_cursor","first_day":str(first),
                "read_only":True,"reason":"invalid_persisted_cursor_values"}
    if row["status"]=="completed":
        # A zero-result month is page 1; a nonempty final page advances
        # exactly once. Corrupted completed rows must not be certified.
        if matched>inspected or page!=(inspected+499)//500+1:
            return {"status":"blocked_invalid_page_cursor","first_day":str(first),
                    "read_only":True,"reason":"completed_cursor_mismatch"}
        return {"status":"already_completed","first_day":str(first)}
    key=_service_key()
    if not key:
        _write_month(row["first_day"],row["last_day"],"blocked_missing_official_api_key",
                     matched,inspected,page)
        return {"status":"blocked_missing_official_api_key","first_day":str(first),
                "operation":"getBidPblancListInfoServcPPSSrch",
                "instructions":"Set existing Railway worker's G2B_API_KEY or DATA_GO_KR_SERVICE_KEY"}
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
            # A missing official notice round defaults to 000. Explicit
            # boolean, float, object or list values must never be coerced
            # into a valid notice identity (False previously became "000").
            raw_ord=item.get("bidNtceOrd")
            if raw_ord is None or raw_ord=="":
                ord_="000"
            elif type(raw_ord) is int or isinstance(raw_ord,str):
                ord_=str(raw_ord).strip().zfill(3)
            else:
                invalid+=1
                continue
            if not re.fullmatch(r"R\d{2}BK\d{8}|\d{11}",no) or not re.fullmatch(r"\d{3}",ord_):
                invalid+=1
                continue
            raw_pub=item.get("bidNtceDt")
            if not isinstance(raw_pub,str):
                invalid+=1
                continue
            pub=raw_pub.strip()
            # Match the ENTIRE official date/timestamp, not just a valid
            # YYYYMMDD prefix. A forged suffix or invalid clock previously
            # certified an otherwise unverified month's notice coverage.
            # Support compact and consistently delimited official dates,
            # optionally followed by HHMM[SS] or HH:MM[:SS].
            stamp=re.fullmatch(
                r"(20\d{2})([-./]?)(\d{2})\2(\d{2})(?:[ T]?(\d{2}):?(\d{2})(?::?(\d{2}))?)?",
                pub)
            if not stamp:
                invalid+=1
                continue
            try:
                day=date(int(stamp[1]),int(stamp[3]),int(stamp[4]))
                if stamp[5] is not None and (
                    int(stamp[5])>23 or int(stamp[6])>59 or
                    (stamp[7] is not None and int(stamp[7])>59)):
                    invalid+=1
                    continue
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
            # int(1.5) silently truncates official monetary evidence. Accept
            # only non-negative integer JSON numbers or decimal digit strings;
            # missing/empty amounts remain unknown (NULL), not fabricated 0.
            if raw_amount is None or raw_amount=="":
                amount=0
            elif type(raw_amount) is int:
                amount=raw_amount
            elif isinstance(raw_amount,str) and re.fullmatch(r"[0-9]+",raw_amount.strip()):
                amount=int(raw_amount.strip())
            else:
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
        inspected+=len(entries);matched+=len(confirmed)
        # A genuine zero-result month completes on page 1. Advancing its
        # cursor to 2 would contradict summarize_month_cursor()'s persisted
        # zero-count invariant and falsely mark the month corrupt on reload.
        # Nonempty pages advance to the next page, including a final short page.
        if entries:
            page+=1
        complete=verdict=="completed"
        _write_month(row["first_day"],row["last_day"],
                     "completed" if complete else "partial",
                     matched,inspected,page)
        if complete:
            return {"status":"completed","first_day":str(first),"checked":inspected,
                    "matched":matched,"total_records":total}
    return {"status":"partial","first_day":str(first),"next_page":page,
            "checked":inspected,"matched":matched}


def _audit_nonnegative_integer(value):
    """Reject bool/float/None instead of silently fabricating cursor coverage."""
    if type(value) is int and value>=0:
        return value
    if isinstance(value,str) and re.fullmatch(r"[0-9]+",value.strip()):
        return int(value.strip())
    return None


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
    invalid_cursors=0
    for row in rows:
        start=row.get("first_day")
        stop=row.get("last_day")
        if (start not in expected or start in seen or stop!=expected.get(start)):
            invalid+=1
            continue
        seen.add(start)
        stat=str(row.get("status") or "unsearched")
        raw_checked=_audit_nonnegative_integer(row.get("checked"))
        raw_matched=_audit_nonnegative_integer(row.get("matched"))
        raw_page=_audit_nonnegative_integer(row.get("page_cursor"))
        # Keep the read-only diagnostic available even for corrupted DB rows.
        # Never treat a coerced/negative/bool/fractional count as completed.
        cursor_valid=(raw_checked is not None and raw_matched is not None and
                      raw_page is not None and raw_page>=1 and
                      raw_matched<=raw_checked)
        checked=raw_checked if raw_checked is not None else 0
        matched=raw_matched if raw_matched is not None else 0
        page=raw_page if raw_page is not None and raw_page>=1 else 1
        if stat=="completed":
            # scan_month advances the page cursor after saving its last page.
            # A 0-row month ends on page 1; 1..500 on page 2, etc.
            cursor_valid=cursor_valid and page==(checked+499)//500+1
        elif stat=="partial":
            # A partial month can resume ONLY after a full persisted page.
            cursor_valid=(cursor_valid and checked%500==0 and
                          page==checked//500+1)
        if not cursor_valid:
            invalid_cursors+=1
        months.append({"first_day":start.isoformat(),
                       "last_day":stop.isoformat(),
                       "status":stat,"checked":checked,"matched":matched,
                       "next_page":page,"cursor_valid":cursor_valid})
    months.sort(key=lambda r:r["first_day"])
    complete=sum(r["status"]=="completed" and r["cursor_valid"] for r in months)
    candidates=[x for x in months if x["status"]!="completed" or not x["cursor_valid"]]
    candidates.sort(key=lambda r:(r["status"]!="partial",r["first_day"]))
    registry_ok=len(seen)==len(expected)==121 and invalid==0
    return {"bid_no":CASE_BID,"configured_parent8":CAT8,
            "requested_10digit_from_selected_notice":"8111159901",
            "period_start":BEGIN.isoformat(),"period_end":END.isoformat(),
            "registry_complete":registry_ok,
            "required_months":len(expected),
            "registered_months":len(seen),
            "invalid_or_duplicate_rows":invalid,
            "invalid_cursor_rows":invalid_cursors,
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
