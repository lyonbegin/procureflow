"""Official KONEPS G2B notice ingestion: public-data service, not order requests.

Uses authorized data.go.kr credentials only when present. Dates are bounded,
pagination is verified, original JSON preserved, corrected notices versioned,
and no 'completed' result is returned when access/data are incomplete.
No automatic bid submission, sign-in, or LLM title similarity.
"""
from __future__ import annotations
from datetime import date,datetime,timedelta
from hashlib import sha256
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import json,logging,os,re
from db import session
from g2b_categories import extract_codes,upsert_verified_codes,ensure_schema

ROOT="https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
OPERATIONS={"service":"getBidPblancListInfoServc",
            "goods":"getBidPblancListInfoThng"}
ID=re.compile(r"^(?:R\d{2}BK\d{8}|\d{11})$")
CODE8=re.compile(r"^\d{8}$")
CODE10=re.compile(r"^\d{10}$")
BUDGET_KEYS=("asignBdgtAmt","bdgtAmt","presmptPrce","bssamt","prearngPrce")
ALLOWED_FILE_KEYS=("stdNtceDocUrl","bidNtceDtlUrl","specDocUrl","ntceSpecDocUrl",
                   "bidNtceDocUrl","ntceDocUrl")

def api_key():
    return os.getenv("G2B_API_KEY") or os.getenv("DATA_GO_KR_SERVICE_KEY") or ""

def ensure_notice_schema():
    with session() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_notice_revisions(
          bid_no text NOT NULL,bid_ord text NOT NULL,content_sha text NOT NULL,
          category text NOT NULL,published_at text NOT NULL DEFAULT '',
          captured_at timestamptz NOT NULL DEFAULT now(),
          source_uri text NOT NULL,raw jsonb NOT NULL DEFAULT '{}'::jsonb,
          PRIMARY KEY(bid_no,bid_ord,content_sha))""")
        db.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_notice_sync(
          source text NOT NULL,from_day date NOT NULL,to_day date NOT NULL,
          page_no int NOT NULL DEFAULT 1,
          state text NOT NULL DEFAULT 'pending',seen int NOT NULL DEFAULT 0,
          accepted int NOT NULL DEFAULT 0,total_reported int,
          last_error text NOT NULL DEFAULT '',
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(source,from_day,to_day))""")
        db.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_notice_source_files(
          bid_no text NOT NULL,bid_ord text NOT NULL,
          file_id text NOT NULL,source_url text NOT NULL,
          file_label text NOT NULL DEFAULT '',
          content_sha text NOT NULL DEFAULT '',
          bytes_size bigint,
          state text NOT NULL DEFAULT 'listed',
          last_seen timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(bid_no,bid_ord,file_id))""")
        db.execute("""CREATE INDEX IF NOT EXISTS ix_pf_notice_revisions_date
                     ON procureflow.g2b_notice_revisions(captured_at DESC)""")

def _items(body):
    envelope=body.get("response") if isinstance(body,dict) else None
    if not isinstance(envelope,dict):raise ValueError("official_api_bad_envelope")
    header=envelope.get("header") or {}
    if str(header.get("resultCode") or "") not in ("00","0"):
        raise ValueError("official_api_"+str(header.get("resultCode"))+":"+
                         str(header.get("resultMsg"))[:70])
    result=envelope.get("body") or {}
    values=result.get("items") or []
    if isinstance(values,dict):values=values.get("item") or []
    if isinstance(values,dict):values=[values]
    if not isinstance(values,list):raise ValueError("official_api_bad_items")
    return values,int(result.get("totalCount") or 0)

def _get(kind,params):
    if kind not in OPERATIONS:raise ValueError("unsupported_g2b_notice_kind")
    key=api_key()
    if not key:return {"blocked":"missing_official_api_key"}
    query={"serviceKey":key,"type":"json","numOfRows":100,"pageNo":1}
    query.update(params)
    url=ROOT+OPERATIONS[kind]+"?"+urlencode(query)
    with urlopen(Request(url,headers={"Accept":"application/json",
                  "User-Agent":"ProcureFlow-notices/1.0"}),timeout=25) as response:
        value=response.read(14000000)
    return json.loads(value)

def _as_text(item,*keys):
    for k in keys:
        value=item.get(k)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""

def _category_codes(item):
    details=extract_codes(item)
    for k in ("prdctClsfcNo","prdlstClsfcNo","prdctClsfcCd"):
        v=_as_text(item,k)
        if CODE8.fullmatch(v) and not any(
            x["code"]==v and x["code_type"]=="parent8" for x in details):
            details.append({"code_type":"parent8","code":v,"source_field":k})
        if CODE10.fullmatch(v) and not any(
            x["code"]==v and x["code_type"]=="detail10" for x in details):
            details.append({"code_type":"detail10","code":v,"source_field":k})
    return details

def save_notice(item,kind):
    ensure_notice_schema()
    no=_as_text(item,"bidNtceNo")
    ord_=_as_text(item,"bidNtceOrd") or "000"
    if not ID.fullmatch(no):return {"accepted":False,"reason":"not_real_bid_notice"}
    if not re.fullmatch(r"\d{3}",ord_):return {"accepted":False,"reason":"bad_bid_ord"}
    title=_as_text(item,"bidNtceNm")
    if not title:return {"accepted":False,"reason":"missing_bid_name"}
    published=_as_text(item,"bidNtceDt")
    deadline=_as_text(item,"bidClseDt")
    agency=_as_text(item,"ntceInsttNm","dminsttNm")
    method=_as_text(item,"cntrctCnclsMthdNm","bidMethdNm")
    raw=json.dumps(item,ensure_ascii=False,sort_keys=True,default=str)
    digest=sha256(raw.encode()).hexdigest()
    official_url=_as_text(item,"bidNtceDtlUrl","bidNtceUrl")
    if not official_url.startswith("https://www.g2b.go.kr/"):
        official_url=("https://www.g2b.go.kr/link/PNPE027_01/single/"
                      "?bidPbancNo="+no+"&bidPbancOrd="+ord_)
    revision=_as_text(item,"ntceKindNm","rgstTyNm")
    with session() as db:
        db.execute("""INSERT INTO procureflow.tenders
          (source,external_id,title,agency,category,notice_date,deadline,
           status,method,source_url,raw)
          VALUES ('g2b',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
          ON CONFLICT(source,external_id) DO UPDATE SET
            title=excluded.title,agency=excluded.agency,category=excluded.category,
            notice_date=excluded.notice_date,deadline=excluded.deadline,
            status=excluded.status,method=excluded.method,
            source_url=excluded.source_url,raw=excluded.raw,
            last_seen=now()
        """,(no,title[:500],agency[:300],"일반용역" if kind=="service" else "물품",
             published,deadline,revision,method,official_url,raw))
        db.execute("""INSERT INTO procureflow.g2b_notice_revisions
          (bid_no,bid_ord,content_sha,category,published_at,source_uri,raw)
          VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
          ON CONFLICT DO NOTHING
        """,(no,ord_,digest,kind,published,ROOT+OPERATIONS[kind],raw))
        for k in ALLOWED_FILE_KEYS:
            link=_as_text(item,k)
            if not link.startswith("https://"):continue
            # Listing a link is not evidence of downloading or parsing it.
            db.execute("""INSERT INTO procureflow.g2b_notice_source_files
              (bid_no,bid_ord,file_id,source_url,file_label)
              VALUES (%s,%s,%s,%s,%s)
              ON CONFLICT(bid_no,bid_ord,file_id) DO UPDATE SET
                source_url=excluded.source_url,last_seen=now()
            """,(no,ord_,k,link,k))
    evidence=[]
    for c in _category_codes(item):
        if c["code_type"] not in ("detail10","parent8","industry"):continue
        # Only original agency JSON with explicit fields may add codes.
        normalized={c["source_field"]:c["code"]}
        # Nested path name from extract_codes is not a field; fallback direct.
        if "." in c["source_field"]:normalized={c["source_field"].split(".")[-1]:c["code"]}
        try:
            evidence+=upsert_verified_codes(no,ord_,kind,normalized,
                    "https://apis.data.go.kr/",evidence_level="official_direct")
        except ValueError as exc:
            logging.warning("G2B_NOTICE_CODE_REJECTED bid=%s reason=%s",no,str(exc)[:100])
    return {"accepted":True,"bid_no":no,"revision":digest[:12],
            "category_codes":[x["code"] for x in evidence]}

def refresh_window(kind,first_day,last_day,limit_pages=8):
    """One bounded actual official query window, with resumable page cursor."""
    ensure_notice_schema()
    if kind not in OPERATIONS:raise ValueError("unsupported notice type")
    start=date.fromisoformat(str(first_day));end=date.fromisoformat(str(last_day))
    if end<start or (end-start).days>30:raise ValueError("maximum 31 days per window")
    with session() as db:
        db.execute("""INSERT INTO procureflow.g2b_notice_sync
           (source,from_day,to_day)
           VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",(kind,start,end))
        state=db.execute("""SELECT * FROM procureflow.g2b_notice_sync
            WHERE source=%s AND from_day=%s AND to_day=%s""",(kind,start,end)).fetchone()
    if state["state"]=="completed":
        return {"status":"already_completed","kind":kind,"window":[str(start),str(end)]}
    if not api_key():
        with session() as db:
            db.execute("""UPDATE procureflow.g2b_notice_sync
               SET state='blocked_missing_key',updated_at=now()
               WHERE source=%s AND from_day=%s AND to_day=%s""",(kind,start,end))
        return {"status":"blocked_missing_official_api_key","kind":kind}
    page=int(state["page_no"]);seen=int(state["seen"]);accepted=int(state["accepted"])
    for _ in range(max(1,min(20,int(limit_pages)))):
        try:
            response=_get(kind,{"inqryDiv":"1",
                   "inqryBgnDt":start.strftime("%Y%m%d")+"0000",
                   "inqryEndDt":end.strftime("%Y%m%d")+"2359",
                   "pageNo":page})
            items,total=_items(response)
            complete=(page*100>=total or not items)
            for item in items:
                if not isinstance(item,dict):continue
                saved=save_notice(item,kind)
                accepted+=int(saved["accepted"])
                seen+=1
            page+=1
            with session() as db:
                db.execute("""UPDATE procureflow.g2b_notice_sync
                  SET page_no=%s,seen=%s,accepted=%s,total_reported=%s,
                      state=%s,last_error='',updated_at=now()
                  WHERE source=%s AND from_day=%s AND to_day=%s
                """,(page,seen,accepted,total,"completed" if complete else "partial",
                     kind,start,end))
            if complete:
                return {"status":"completed","kind":kind,"seen":seen,"saved":accepted,
                        "total":total,"window":[str(start),str(end)]}
        except Exception as exc:
            with session() as db:
                db.execute("""UPDATE procureflow.g2b_notice_sync SET state='error',
                     last_error=%s,updated_at=now()
                     WHERE source=%s AND from_day=%s AND to_day=%s
                """,(type(exc).__name__+":"+str(exc)[:180],kind,start,end))
            return {"status":"error","kind":kind,"error":type(exc).__name__+":"+str(exc)[:180]}
    return {"status":"partial","kind":kind,"seen":seen,
            "saved":accepted,"next_page":page}

def sync_status():
    ensure_notice_schema()
    with session() as db:
        grouped=db.execute("""SELECT source,state,count(*) AS windows,
          sum(seen) AS checked,sum(accepted) AS saved
          FROM procureflow.g2b_notice_sync GROUP BY source,state
          ORDER BY source,state""").fetchall()
        recent=db.execute("""SELECT source,from_day,to_day,page_no,state,seen,
          accepted,total_reported,last_error,updated_at
          FROM procureflow.g2b_notice_sync
          ORDER BY updated_at DESC LIMIT 12""").fetchall()
        actual=db.execute("""SELECT count(*) AS n FROM procureflow.tenders
          WHERE source='g2b' AND external_id ~ '^R[0-9]{2}BK[0-9]{8}$'""").fetchone()["n"]
    return {"actual_new_style_notice_rows":actual,"sync_by_state":grouped,
            "recent_windows":recent,"configured_key":bool(api_key()),
            "source":"official_public_data_API","submitted":False}
