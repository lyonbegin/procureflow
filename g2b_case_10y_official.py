"""Official G2B full ten-year monthly history retrieval for ONE category.

Run only after an official public-data service key is available in Railway.
Never scan unrelated cases. A month is 'completed' only after *all* API pages
were read, response category codes explicitly matched and no errors occurred.
"""
import json
import os
import re
from datetime import date
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
    total=int(body.get("totalCount") or 0)
    return items,total

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
            _write_month(row["first_day"],row["last_day"],"error",matched,inspected,page,
                         type(exc).__name__+":"+str(exc)[:180])
            return {"status":"error","first_day":str(first),
                    "reason":type(exc).__name__+":"+str(exc)[:180]}
        unknown=0
        confirmed=[]
        for item in entries:
            cls=_category_from(item)
            if cls is None:
                unknown+=1
                continue
            if cls is not True:continue
            no=str(item.get("bidNtceNo") or "").strip()
            ord_=str(item.get("bidNtceOrd") or "000").zfill(3)
            if not re.fullmatch(r"R\d{2}BK\d{8}|\d{11}",no):continue
            pub=str(item.get("bidNtceDt") or "").strip()
            stamp=re.match(r"(20\d{2})[-./]?(\d{2})[-./]?(\d{2})",pub)
            if not stamp:continue
            day=date(int(stamp[1]),int(stamp[2]),int(stamp[3]))
            if not BEGIN<=day<=END:continue
            confirmed.append((CASE_BID,no,ord_,CAT8,day,
                str(item.get("bidNtceNm") or "")[:350],
                str(item.get("dminsttNm") or item.get("ntceInsttNm") or "")[:250],
                int(item.get("asignBdgtAmt") or 0) or None,
                "https://www.g2b.go.kr/","official_openapi_explicit_code"))
        if unknown:
            _write_month(row["first_day"],row["last_day"],"blocked_unverified_response_category",
                         matched,inspected,page,"response_has_"+str(unknown)+"_rows_without_classification")
            return {"status":"blocked_unverified_response_category",
                    "undetermined_rows":unknown,"page":page,
                    "note":"Do not count matching without official classification value"}
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
        complete=(page-1)*500>=total or not entries
        _write_month(row["first_day"],row["last_day"],
                     "completed" if complete else "partial",
                     matched,inspected,page)
        if complete:
            return {"status":"completed","first_day":str(first),"checked":inspected,
                    "matched":matched,"total_records":total}
    return {"status":"partial","first_day":str(first),"next_page":page,
            "checked":inspected,"matched":matched}
