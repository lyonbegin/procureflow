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
# Persisted state is evidence. An unknown state must never be silently
# treated as a resumable page, even when its numeric cursor looks plausible.
MONTH_STATES=frozenset({
    "unsearched", "partial", "completed", "error",
    "blocked_missing_official_api_key", "blocked_unverified_response_scope",
    "blocked_incomplete_api_page",
})
def _service_key():
    return os.getenv("G2B_API_KEY") or os.getenv("DATA_GO_KR_SERVICE_KEY") or ""

def _reject_duplicate_json_keys(pairs):
    """Fail closed when an official JSON object repeats a key.

    json.loads normally keeps the LAST occurrence. A duplicated totalCount,
    items, resultCode or notice ID can hide a conflicting upstream value and
    falsely certify a zero-result month or a specific notice. Check every
    object level before parsing page counts or writing any official history.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("g2b_api_duplicate_json_key")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value):
    """Official G2B JSON must not contain NaN/Infinity at ANY object depth.

    Python's json.loads accepts these non-standard literals by default.
    Even if they occur in unused metadata, a malformed upstream response
    must never become a certified completed discovery month.
    """
    raise ValueError("g2b_api_nonfinite_json_constant")


def _parse(response, *, expected_page=None, expected_rows=None):
    if not isinstance(response,dict):raise ValueError("g2b_api_not_json_object")
    # A successful nested header is insufficient when the provider or an
    # intermediary also sends an explicit error at the response root,
    # envelope, or header level. A zero-result page with such a marker must
    # never become an auditable completed month.
    failure_markers=frozenset((
        "error","errors","fault","errorCode","errorMessage",
        "errorMsg","error_message","resultCode",
    ))
    if any(marker in response for marker in failure_markers):
        raise ValueError("g2b_api_root_error_marker")
    envelope=response.get("response")
    if not isinstance(envelope,dict):
        raise ValueError("g2b_api_envelope_not_object")
    if any(marker in envelope for marker in failure_markers):
        raise ValueError("g2b_api_envelope_error_marker")
    head=envelope.get("header")
    if not isinstance(head,dict):
        raise ValueError("g2b_api_header_not_object")
    # resultCode belongs in the documented header and is validated below.
    if any(marker in head for marker in failure_markers-{"resultCode"}):
        raise ValueError("g2b_api_header_error_marker")
    if str(head.get("resultCode","")) not in ("00","0"):
        raise ValueError("g2b_api_result_"+str(head.get("resultCode"))+":"+str(head.get("resultMsg",""))[:75])
    body=envelope.get("body")
    # A nominally successful header cannot override an explicit error/fault
    # in the body. In particular, totalCount=0 with an empty item list plus
    # a provider error must never certify an entire month as searched.
    # Only the documented pagination/item fields are used for coverage;
    # unknown harmless metadata is tolerated, but known failure markers are
    # always fail-closed even when their value is an empty string or null.
    if not isinstance(body,dict):
        raise ValueError("g2b_api_body_not_object")
    if any(key in body for key in (
            "error","errors","fault","errorCode","errorMessage",
            "errorMsg","error_message","resultCode")):
        raise ValueError("g2b_api_body_error_marker")
    # An absent/null item list is normal for a zero-result month. Explicit
    # scalar values (including falsey 0/False/"") are malformed responses;
    # the old 'or []' coercion could falsely certify a zero-result month.
    items=body.get("items",[])
    if items is None:items=[]
    if isinstance(items,dict):
        # A nonempty unknown items wrapper is not an empty official page.
        # Otherwise {"error": "..."} + totalCount=0 could falsely
        # certify a month without inspecting any actual notice rows.
        if items and "item" not in items:
            raise ValueError("g2b_api_items_wrapper_missing_item")
        # A wrapper that contains 'item' PLUS an upstream error or an
        # unrecognized field is not the documented official item envelope.
        # In particular, {"item":[],"error":"upstream unavailable"} with
        # totalCount=0 must never certify a zero-result month.
        if any(key!="item" for key in items):
            raise ValueError("g2b_api_items_wrapper_extra_fields")
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
    # Some official endpoints echo the pagination request in the response.
    # A stale proxy response for page 1 or a silently reduced page size
    # must not certify the requested page as fully inspected. Missing echo
    # fields remain supported for older official API variants.
    for field,expected in (("pageNo",expected_page),("numOfRows",expected_rows)):
        if field not in body:
            continue
        raw=body[field]
        if type(raw) is int:
            actual=raw
        elif isinstance(raw,str) and re.fullmatch(r"[0-9]+",raw.strip()):
            actual=int(raw.strip())
        else:
            raise ValueError("g2b_api_"+field+"_not_positive_integer")
        if actual<1:
            raise ValueError("g2b_api_"+field+"_not_positive_integer")
        if expected is not None and actual!=expected:
            raise ValueError("g2b_api_"+field+"_request_mismatch")
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
        # G2B classification identifiers are ASCII decimal strings. Python's
        # \\d also matches full-width/Arabic-Indic digits, which could make a
        # non-official 10-digit suffix look like a valid selected category.
        if not re.fullmatch(r"[0-9]{8}([0-9]{2})?",value):
            return None
        codes.append(value)
    if not codes:
        return None
    parents={code[:8] for code in codes}
    details={code for code in codes if len(code)==10}
    if len(parents)!=1 or len(details)>1:
        return None
    return next(iter(parents))==CAT8

def _official_notice_text_is_valid(value):
    """Reject malformed Unicode/control characters in official text evidence.

    Python's JSON parser accepts escaped lone UTF-16 surrogates (\\uD800),
    which are not valid Unicode scalar values and can fail at PostgreSQL UTF-8
    insertion. Embedded NUL, non-whitespace C0 controls, DEL and C1 controls
    can carry invisible/terminal control data into evidence records. Keep
    missing/null and normal Korean, spaces, CR/LF and tabs compatible.
    """
    if value is None:
        return True
    if not isinstance(value,str):
        return False
    return not any(
        0xD800<=ord(ch)<=0xDFFF or
        ord(ch)==0 or
        (ord(ch)<32 and ch not in "\t\r\n") or
        (0x7F<=ord(ch)<=0x9F)
        for ch in value
    )


def _write_month(first,last,status,matched=0,checked=0,page=1,err="",expected_total=None):
    with session() as con:
        con.execute("""UPDATE procureflow.g2b_case_10yr_windows
             SET status=%s,source=%s,matched=%s,checked=%s,page_cursor=%s,
               last_error=%s,expected_total=COALESCE(%s,expected_total),
               updated_at=now()
             WHERE case_bid_no=%s AND first_day=%s AND last_day=%s
        """,(status,"official_bidpublicinfo",matched,checked,page,err[:300],
             expected_total,CASE_BID,first,last))


def _persisted_official_notice_keys(row, matched):
    """Read-only resume guard for already stored target-category notice IDs.

    A stable totalCount alone cannot detect page-1 records repeated on page 2
    when scan_month is called separately for each page. Require the persisted
    official target rows to agree with the matched cursor before resuming.
    Non-target IDs are not stored, so this is a *partial* dedupe guard, not
    a proof of the complete official result set.
    """
    try:
        with session() as con:
            records=con.execute("""SELECT hist_notice_no,hist_notice_ord
                FROM procureflow.g2b_case_10yr_history
                WHERE case_bid_no=%s AND published_on BETWEEN %s AND %s
                  AND classification8=%s AND evidence=%s""",
                (CASE_BID,row["first_day"],row["last_day"],CAT8,
                 "official_openapi_explicit_code")).fetchall()
        keys={(r["hist_notice_no"],r["hist_notice_ord"]) for r in records}
        if len(records)!=matched or len(keys)!=matched:
            return None
        return keys
    except Exception:
        # No raw SQL/connection exception (possibly containing credentials)
        # may escape to the public month-progress or execution log.
        return None


def scan_month(first, pages_max=30):
    """Progress a single pre-registered month; next call resumes last page."""
    ensure_schema()
    if isinstance(first,str):first=date.fromisoformat(first)
    with session() as con:
        row=con.execute("""SELECT first_day,last_day,status,page_cursor,
                 checked,matched,expected_total FROM procureflow.g2b_case_10yr_windows
                 WHERE case_bid_no=%s AND first_day=%s""",(CASE_BID,first)).fetchone()
    if not row:raise ValueError("month not in chosen ten-year horizon")
    # The persisted window boundaries are themselves part of the official
    # ten-year evidence contract. A tampered last_day could silently scan an
    # adjacent month (or a wider interval) and mark the WRONG month complete,
    # even when every page count and notice date matches the forged window.
    # The first/last months are partial (BEGIN/END), all others are calendar
    # months. Reject any changed boundary BEFORE credentials, HTTP or writes.
    expected_first=max(BEGIN,date(first.year,first.month,1))
    expected_last=min(END,date(first.year,first.month,
                               calendar.monthrange(first.year,first.month)[1]))
    if (expected_first>expected_last or first!=expected_first or
            row["first_day"]!=expected_first or row["last_day"]!=expected_last):
        return {"status":"blocked_invalid_month_window","first_day":str(first),
                "read_only":True,"reason":"persisted_month_boundary_mismatch"}
    # Refuse unknown/tampered states before credential lookup, HTTP or
    # cursor mutation. An untouched month must start at page 1 with zero
    # inspected/matched rows, otherwise there is no trustworthy resume point.
    if row["status"] not in MONTH_STATES:
        return {"status":"blocked_invalid_month_state","first_day":str(first),
                "read_only":True,"reason":"unknown_persisted_month_status"}
    # Validate persisted cursor types BEFORE coercion, network access or a
    # completed-month shortcut. int(True), int(1.5), and int("2") can mask
    # corrupted coverage evidence; a completed row is not automatically proof.
    inspected=_audit_nonnegative_integer(row["checked"])
    matched=_audit_nonnegative_integer(row["matched"])
    page=_audit_nonnegative_integer(row["page_cursor"])
    if (inspected is None or matched is None or page is None or page<1):
        return {"status":"blocked_invalid_page_cursor","first_day":str(first),
                "read_only":True,"reason":"invalid_persisted_cursor_values"}
    if row["status"]=="unsearched" and (
            inspected!=0 or matched!=0 or page!=1 or
            row.get("expected_total") is not None):
        return {"status":"blocked_invalid_page_cursor","first_day":str(first),
                "read_only":True,"reason":"unsearched_month_has_progress"}
    # A page cursor alone cannot prove that totalCount stayed stable across
    # separate scan_month invocations. The first verified page persists the
    # official snapshot; later calls must compare against the same count.
    # Legacy partial/completed rows with missing snapshots are not certified.
    raw_snapshot=row.get("expected_total")
    snapshot=_audit_nonnegative_integer(raw_snapshot)
    if row["status"]=="completed":
        # A zero-result month is page 1; a nonempty final page advances
        # exactly once. Corrupted completed rows must not be certified.
        if matched>inspected or page!=(inspected+499)//500+1:
            return {"status":"blocked_invalid_page_cursor","first_day":str(first),
                    "read_only":True,"reason":"completed_cursor_mismatch"}
        if snapshot is None or snapshot!=inspected:
            return {"status":"blocked_unverified_snapshot","first_day":str(first),
                    "read_only":True,"reason":"completed_snapshot_mismatch"}
        # Even a completed zero-result month must have ZERO persisted
        # target-category official history rows. Otherwise a stale/orphaned
        # history INSERT can contradict a 0/0 cursor and be silently certified
        # by the completed-month shortcut. A failed read is not evidence.
        if _persisted_official_notice_keys(row,matched) is None:
            return {"status":"blocked_unverified_persisted_history",
                    "first_day":str(first),"read_only":True,
                    "reason":"completed_history_count_or_identity_mismatch"}
        return {"status":"already_completed","first_day":str(first)}
    # Validate the persisted partial cursor BEFORE credential lookup or any
    # DB mutation. A malformed row must remain untouched for independent
    # forensic review, including when the API key is absent.
    if (matched>inspected or inspected%500!=0 or page!=inspected//500+1):
        return {"status":"blocked_invalid_page_cursor","first_day":str(first),
                "checked":inspected,"matched":matched,"next_page":page,
                "reason":"partial_cursor_mismatch","read_only":True}
    if inspected>0 and (snapshot is None or snapshot<=inspected):
        return {"status":"blocked_unverified_snapshot","first_day":str(first),
                "read_only":True,"reason":"partial_snapshot_missing_or_not_ahead_of_cursor"}
    prior_notice_keys=set()
    if inspected>0:
        prior_notice_keys=_persisted_official_notice_keys(row,matched)
        if prior_notice_keys is None:
            return {"status":"blocked_unverified_persisted_history",
                    "first_day":str(first),"read_only":True,
                    "reason":"partial_history_count_or_identity_mismatch"}
    # Boolean/fractional/string page limits must not silently become a
    # positive request count (int(True)==1, int(1.5)==1).
    if type(pages_max) is not int or pages_max<1:
        return {"status":"blocked_invalid_page_limit","first_day":str(first),
                "reason":"pages_max_must_be_positive_integer","read_only":True}
    pages_max=min(30,pages_max)
    key=_service_key()
    if not key:
        _write_month(row["first_day"],row["last_day"],"blocked_missing_official_api_key",
                     matched,inspected,page)
        return {"status":"blocked_missing_official_api_key","first_day":str(first),
                "operation":"getBidPblancListInfoServcPPSSrch",
                "instructions":"Set existing Railway worker's G2B_API_KEY or DATA_GO_KR_SERVICE_KEY"}
    params={"serviceKey":key,"type":"json","inqryDiv":"1",
        "inqryBgnDt":row["first_day"].strftime("%Y%m%d")+"0000",
        "inqryEndDt":row["last_day"].strftime("%Y%m%d")+"2359",
        "prdctClsfcNo":CAT8,"numOfRows":500}
    # A live official API can change while a month is being paginated.
    # Never certify coverage if its totalCount drifts or a notice identity
    # reappears on a later page within the same scan invocation.
    expected_total=snapshot
    # Includes already persisted target IDs from earlier scan_month calls.
    seen_notice_keys=set(prior_notice_keys)
    for _ in range(pages_max):
        params["pageNo"]=page
        url=API+"?"+urlencode(params)
        try:
            req=Request(url,headers={"Accept":"application/json",
                              "User-Agent":"ProcureFlow-G2B-Category/1.0"})
            with urlopen(req,timeout=22) as rsp:
                data=json.loads(rsp.read(15000000), object_pairs_hook=_reject_duplicate_json_keys,
                                parse_constant=_reject_nonfinite_json_constant)
            entries,total=_parse(data,expected_page=page,expected_rows=500)
        except Exception as exc:
            # urllib exceptions may include the serviceKey URL. Neither DB
            # audit nor REST output may persist an exception's raw message.
            reason="official_api_request_or_parse_failed:"+type(exc).__name__
            _write_month(row["first_day"],row["last_day"],"error",matched,inspected,page,reason)
            return {"status":"error","first_day":str(first),"reason":reason}
        if expected_total is not None and total!=expected_total:
            # Previous pages remain auditable as partial; the changed page
            # is neither inserted nor counted toward a completed month,
            # including when the earlier page came from a previous call.
            _write_month(row["first_day"],row["last_day"],
                         "blocked_unverified_response_scope",
                         matched,inspected,page,
                         "official_total_count_changed_between_pages",expected_total)
            return {"status":"blocked_unverified_response_scope",
                    "first_day":str(first),"page":page,
                    "reason":"official_total_count_changed_between_pages"}
        expected_total=total
        verdict=_page_verdict(inspected,total,len(entries))
        if verdict in ("inconsistent","incomplete_page"):
            _write_month(row["first_day"],row["last_day"],"blocked_incomplete_api_page",
                         matched,inspected,page,"page_count_inconsistent_or_truncated")
            return {"status":"blocked_incomplete_api_page","first_day":str(first),
                    "page":page,"checked":inspected,"returned":len(entries),
                    "official_total_count":total,"reason":verdict}
        # A zero-result official page cannot certify a month if an older
        # official target-category history row still exists in the database.
        # The normal completed-month shortcut checks this on subsequent
        # calls; check BEFORE the first completion write as well. A failed
        # read is not evidence of zero rows and must not mutate the cursor.
        if verdict=="completed" and total==0 and \
                _persisted_official_notice_keys(row,0) is None:
            return {"status":"blocked_unverified_persisted_history",
                    "first_day":str(first),"read_only":True,
                    "reason":"zero_result_month_has_unverified_history"}
        unknown=0
        invalid=0
        confirmed=[]
        # Duplicate identities on this page OR earlier pages in the same
        # scan make totalCount ambiguous. Never write the duplicate page.
        for item in entries:
            cls=_category_from(item)
            if cls is None:
                unknown+=1
                continue
            # Every official page row contributes to totalCount, even when
            # its category is not our selected parent8. Check its notice
            # identity BEFORE skipping it: otherwise a duplicate or a row
            # with no identity in an out-of-scope category could silently
            # replace another result while the month is marked completed.
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
            # Official notice IDs/rounds must be ASCII. Unicode decimal
            # digits match Python \\d but are not canonical G2B identifiers.
            if not re.fullmatch(r"R[0-9]{2}BK[0-9]{8}|[0-9]{11}",no) or not re.fullmatch(r"[0-9]{3}",ord_):
                invalid+=1
                continue
            notice_key=(no,ord_)
            if notice_key in seen_notice_keys:
                invalid+=1
                continue
            seen_notice_keys.add(notice_key)
            # Every official row contributes to the month totalCount, even
            # when it is outside the selected parent8. A stale/out-of-month
            # non-target notice must not certify this month's completeness.
            # Validate its publication date before filtering by category.
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
                r"(20[0-9]{2})([-./]?)([0-9]{2})\2([0-9]{2})(?:[ T]?([0-9]{2}):?([0-9]{2})(?::?([0-9]{2}))?)?",
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
            if cls is not True:
                # Valid other-category rows count as inspected, not matched.
                # Their identity AND month timestamp were still verified.
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
            # Official notice title/agency are text fields, not arbitrary
            # JSON values. str(dict/list/bool) previously fabricated printable
            # "evidence" and could mark a malformed notice page completed.
            # Missing/null fields remain unknown/empty for API compatibility.
            raw_title=item.get("bidNtceNm")
            raw_agency=item.get("dminsttNm")
            raw_alt_agency=item.get("ntceInsttNm")
            if any(not _official_notice_text_is_valid(v) for v in
                   (raw_title,raw_agency,raw_alt_agency)):
                invalid+=1
                continue
            confirmed.append((CASE_BID,no,ord_,CAT8,day,
                (raw_title or "")[:350],
                (raw_agency or raw_alt_agency or "")[:250],
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
                     matched,inspected,page,"",expected_total)
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
        # Preserve invalid/NULL states as invalid: never coerce them into
        # an apparently clean unsearched month in the read-only audit.
        raw_stat=row.get("status")
        stat=raw_stat if isinstance(raw_stat,str) else ""
        valid_state=stat in MONTH_STATES
        raw_checked=_audit_nonnegative_integer(row.get("checked"))
        raw_matched=_audit_nonnegative_integer(row.get("matched"))
        raw_page=_audit_nonnegative_integer(row.get("page_cursor"))
        raw_snapshot=_audit_nonnegative_integer(row.get("expected_total"))
        # Keep the read-only diagnostic available even for corrupted DB rows.
        # Never treat a coerced/negative/bool/fractional count as completed.
        cursor_valid=(valid_state and raw_checked is not None and raw_matched is not None and
                      raw_page is not None and raw_page>=1 and
                      raw_matched<=raw_checked)
        checked=raw_checked if raw_checked is not None else 0
        matched=raw_matched if raw_matched is not None else 0
        page=raw_page if raw_page is not None and raw_page>=1 else 1
        if stat=="completed":
            # Every completed row MUST carry the exact official totalCount
            # snapshot. An absent key is not proof of a zero-result month.
            # scan_month already blocks missing snapshots on resume; the
            # read-only summary must enforce the same invariant.
            cursor_valid=(cursor_valid and raw_snapshot==checked and
                          page==(checked+499)//500+1)
        elif stat=="partial":
            # A resumed nonempty partial row requires a persisted official
            # totalCount snapshot strictly ahead of its inspected cursor.
            # Missing keys must not be treated as valid merely because the
            # API/DB row predates the snapshot migration.
            cursor_valid=(cursor_valid and checked%500==0 and
                          page==checked//500+1)
            if checked>0:
                cursor_valid=(cursor_valid and raw_snapshot is not None
                              and raw_snapshot>checked)
        if stat=="unsearched":
            # A new month has no trustworthy page snapshot or scanned rows.
            cursor_valid=(cursor_valid and checked==0 and matched==0 and
                          page==1 and raw_snapshot is None)
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
        rows=con.execute("""SELECT first_day,last_day,status,checked,matched,page_cursor,expected_total
          FROM procureflow.g2b_case_10yr_windows
          WHERE case_bid_no=%s ORDER BY first_day""",(CASE_BID,)).fetchall()
    return summarize_month_cursor([dict(row) for row in rows])
