"""Single-purpose actual G2B selected-notice exact-10 historic analysis UI.

No code/worker side effects, no API key, no parent-8 mass collection, no
mock figures. DB transactions are READ ONLY. Site search is one filtered
31-day window/page, responses without proof are never counted as matches.
"""
import os
import re
import logging
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from g2b_bid_notice_site_search import run_search, search_window

CASE = re.compile(r"^(?:R\d{2}BK\d{8}|\d{11})$")
TEN = re.compile(r"^\d{10}$")
HERE = Path(__file__).parent
app = FastAPI(title="조달청 단일 공고·동일 세부종목 검색", docs_url=None, redoc_url=None)


@contextmanager
def readonly():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise HTTPException(503, "POSTGRESQL_READONLY_CONNECTION_NOT_CONFIGURED")
    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=6) as con:
            con.execute("SET TRANSACTION READ ONLY")
            yield con
    except psycopg.Error as err:
        # Log only exception CLASS and SQLSTATE, never connection URLs,
        # credentials, SQL parameters or raw database error text.
        logging.error("FOCUSED_G2B_DB_READ_FAILED type=%s sqlstate=%s",
                      type(err).__name__,getattr(err,"sqlstate",None))
        raise HTTPException(503, "EXISTING_G2B_DATABASE_UNAVAILABLE") from None


def clean(row):
    def plain(v):
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if isinstance(v, (int,float,str,bool)) or v is None:
            return v
        return str(v)
    return {k:plain(v) for k,v in dict(row).items()}


def ensure_bid(bid_no):
    if not CASE.fullmatch(bid_no):
        raise HTTPException(400, "INVALID_SELECTED_BID_NUMBER")
    return bid_no


def table_flags(con):
    row=con.execute("""SELECT
        to_regclass('procureflow.tenders') IS NOT NULL AS tenders,
        to_regclass('procureflow.g2b_notice_categories') IS NOT NULL AS categories,
        to_regclass('procureflow.g2b_case_10yr_history') IS NOT NULL AS history,
        to_regclass('procureflow.bid_results') IS NOT NULL AS results""").fetchone()
    return {k:bool(v) for k,v in row.items()}


def select_case(con,bid):
    row=con.execute("""SELECT external_id AS bid_no,title,agency,category,
      notice_date,deadline,status,source_url,last_seen
      FROM procureflow.tenders
      WHERE source='g2b' AND external_id=%s""",(bid,)).fetchone()
    if not row:
        raise HTTPException(404,"SELECTED_NOTICE_NOT_IN_ACTUAL_G2B_DB")
    codes=(con.execute("""SELECT code,source_uri,source_field,evidence_level,bid_ord
      FROM procureflow.g2b_notice_categories
      WHERE bid_no=%s AND code_type='detail10'
        AND evidence_level='official_direct' AND code ~ '^[0-9]{10}$'
      ORDER BY created_at DESC LIMIT 20""",(bid,)).fetchall()
           if table_flags(con)["categories"] else [])
    distinct=list(dict.fromkeys(x["code"] for x in codes))
    return {**clean(row),"original_detail10":distinct[0] if len(distinct)==1 else None,
        "source_verified":len(distinct)==1,
        "verification_status":("official_original_exact10" if len(distinct)==1
                 else "multiple_original_codes_needs_user_selection" if distinct
                 else "missing_exact10_original_evidence"),
        "original_sources":[clean(x) for x in codes]}


@app.get("/",response_class=HTMLResponse)
def home():
    return HTMLResponse((HERE/"focused_g2b.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control":"no-store"})


@app.get("/health")
def health():
    with readonly() as con:
        flags=table_flags(con)
        if not flags["tenders"]:
            raise HTTPException(503,"ACTUAL_G2B_TENDERS_TABLE_UNAVAILABLE")
        row=con.execute("""SELECT EXISTS(SELECT 1 FROM procureflow.tenders
                          WHERE source='g2b') AS has_g2b""").fetchone()
    logging.warning("FOCUSED_G2B_TABLES tenders=%s categories=%s history=%s results=%s",
        flags["tenders"],flags["categories"],flags["history"],flags["results"])
    return {"status":"ok" if flags["categories"] else "degraded_original_evidence_unavailable",
       "scope":"single_g2b_original_exact10_readonly",
       "database_connected":True,"table_flags":flags,
       "has_g2b_notice_rows":bool(row["has_g2b"]),
       "site_search_verified":False,"bid_submitted":False}


@app.get("/api/notices")
def notices(q:str=Query("",max_length=100),
            limit:int=Query(40,ge=1,le=100),
            offset:int=Query(0,ge=0,le=5000)):
    pat="%"+q.strip().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
    with readonly() as con:
        flags=table_flags(con)
        if not flags["tenders"]:
            raise HTTPException(503,"ACTUAL_G2B_TENDERS_TABLE_UNAVAILABLE")
        join = ("          LEFT JOIN LATERAL (\n             SELECT code,source_uri\n               FROM procureflow.g2b_notice_categories c\n              WHERE c.bid_no=t.external_id AND c.code_type='detail10'\n                AND c.evidence_level='official_direct'\n                AND c.code ~ '^[0-9]{10}$'\n              ORDER BY created_at DESC LIMIT 1\n          ) c ON true\n" if flags["categories"] else
            " LEFT JOIN LATERAL (SELECT NULL::text AS code,NULL::text AS source_uri) c ON true ")
        rows=con.execute(f"""SELECT t.external_id AS bid_no,t.title,t.agency,
            t.category,t.notice_date,t.deadline,t.status,t.source_url,
            c.code AS exact_detail10,c.source_uri AS exact_code_source
          FROM procureflow.tenders t
          {join}
          WHERE t.source='g2b'
            AND (t.title ILIKE %s OR t.agency ILIKE %s OR t.external_id ILIKE %s)
          ORDER BY t.notice_date DESC,t.last_seen DESC,t.external_id DESC
          LIMIT %s OFFSET %s""",(pat,pat,pat,limit,offset)).fetchall()
    return {"source":"existing_live_procureflow_g2b_tenders",
            "items":[clean(x) for x in rows],"offset":offset,
            "no_fixture":True,"actual_site_search_executed":False}


@app.get("/api/case")
def case(bid_no:str):
    with readonly() as con:
        return select_case(con,ensure_bid(bid_no))


def _history(con, bid_no, detail10, start,end, offset,limit):
    # Category is from the official original document, NOT an 8-digit
    # ancestor, text similarity, or category guessed from result title.
    rows=con.execute("""WITH eligible AS (
        SELECT DISTINCT c.bid_no,c.bid_ord,c.source_uri
        FROM procureflow.g2b_notice_categories c
        WHERE c.code_type='detail10' AND c.evidence_level='official_direct'
          AND c.code=%s AND c.bid_no<>%s
      ), matches AS (
        SELECT e.bid_no,e.bid_ord,
               COALESCE(NULLIF(t.title,''),h.title,'') AS title,
               COALESCE(NULLIF(t.agency,''),h.agency,'') AS agency,
               COALESCE(NULLIF(left(t.notice_date,10),''),h.published_on::text,'') AS published,
               e.source_uri
        FROM eligible e
        LEFT JOIN procureflow.tenders t
           ON t.source='g2b' AND t.external_id=e.bid_no
        LEFT JOIN LATERAL (
           SELECT title,agency,published_on
           FROM procureflow.g2b_case_10yr_history h
           WHERE h.hist_notice_no=e.bid_no AND h.hist_notice_ord=e.bid_ord
           ORDER BY h.published_on DESC LIMIT 1
        ) h ON true
      )
      SELECT DISTINCT ON (bid_no,bid_ord)
       bid_no,bid_ord,title,agency,published,source_uri
      FROM matches
      WHERE published ~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}$'
        AND left(published,10) BETWEEN %s AND %s
      ORDER BY bid_no,bid_ord,published DESC
     """,(detail10,bid_no,start,end)).fetchall()
    # Small capped per-notice page; counts are only rows already proven in DB.
    distinct=sorted([clean(x) for x in rows],
                    key=lambda x:x["published"],reverse=True)
    total=len(distinct)
    selected=distinct[offset:offset+limit]
    result=[]
    for row in selected:
        records=con.execute("""SELECT result_kind,company,amount,rate,rank,
               participation_count,result_status,last_seen
           FROM procureflow.bid_results
           WHERE source='g2b' AND bid_ntce_no=%s
             AND lpad(bid_ntce_ord,3,'0')=%s
             AND result_kind IN ('opening','award')
           ORDER BY result_kind,rank,last_seen DESC LIMIT 150""",
           (row["bid_no"],row["bid_ord"])).fetchall()
        opening=[clean(x) for x in records if x["result_kind"]=="opening"]
        award=[clean(x) for x in records if x["result_kind"]=="award"]
        result.append({**row,"detail10":detail10,
            "opening_records":opening,"award_records":award,
            "opening_count":len(opening),"award_count":len(award),
            "opening_state":"found" if opening else "not_collected_or_not_published",
            "final_award_state":"record_present_needs_explicit_final_provenance" if award
                       else "not_collected_or_not_published",
            "official_original_match":True})
    return {"matching_notice_count_in_verified_db":total,
        "items":result,"offset":offset,"limit":limit,
        "complete_10yr_website_search":False,"external_site_search_performed":False,
        "source":"verified_original_detail10_in_existing_database",
        "note":"Only original-proven exact-10 DB notices. Not the entire G2B website."}


@app.get("/api/history")
def history(bid_no:str,
            offset:int=Query(0,ge=0,le=10000),
            limit:int=Query(20,ge=1,le=50)):
    bid_no=ensure_bid(bid_no)
    with readonly() as con:
        selected=select_case(con,bid_no)
        if not selected["source_verified"]:
            return {"status":"HOLD","reason":selected["verification_status"],
                "selected":selected,"items":[],
                "complete_10yr_website_search":False}
        date_text=str(selected.get("notice_date") or "")[:10]
        try:
            end=date.fromisoformat(date_text)
        except ValueError:
            return {"status":"HOLD","reason":"SELECTED_NOTICE_POST_DATE_UNVERIFIED",
                "selected":selected,"items":[]}
        today=date.today()
        if end>today:end=today
        try:
            start=end.replace(year=end.year-10)
        except ValueError:
            start=end.replace(year=end.year-10,day=28)
        data=_history(con,bid_no,selected["original_detail10"],
                      start.isoformat(),end.isoformat(),offset,limit)
    return {"status":"partial_original_verified_database_only",
        "selected":selected,"filter":{"detail10":selected["original_detail10"],
          "start":start.isoformat(),"end":end.isoformat(),
          "agency":"ALL_AGENCIES","exact10":True},**data}


@app.post("/api/official-search")
def official_search(bid_no:str,month:Optional[str]=None,
                    page:int=Query(1,ge=1,le=10)):
    """One read-only real G2B screen XHR, never claim no matches on blocker."""
    bid_no=ensure_bid(bid_no)
    with readonly() as con:
        selected=select_case(con,bid_no)
    if not selected["source_verified"]:
        return {"status":"HOLD","reason":selected["verification_status"],
                "website_search_verified":False,"items":[]}
    try:
        last=date.fromisoformat(str(selected["notice_date"])[:10])
        if last>date.today():last=date.today()
        try: first=last.replace(year=last.year-10)
        except ValueError:first=last.replace(year=last.year-10,day=28)
        window=search_window(selected["original_detail10"],first.isoformat(),
                             last.isoformat(),month,page)
    except (ValueError,TypeError):
        raise HTTPException(400,"INVALID_OR_UNVERIFIED_SELECTED_NOTICE_DATE") from None
    result=run_search(window["detail10"],first.isoformat(),last.isoformat(),
                      month,page)
    result["selected_bid_no"]=bid_no
    result["window"]=window
    result["official_verified_rows_only"]=result.pop("matched_explicit_detail10",[])
    result["unverified_candidates"]=result.pop("pending_original_detail10_verification",[])
    result["website_search_verified"]=bool(result.get("search_request_verified"))
    result["never_count_unverified_candidates_as_matches"]=True
    result["bid_submitted"]=False
    return result
