"""Fresh site-only G2B database. NEVER read procureflow.* or existing historical DB.

A brand new Railway Postgres service must be supplied as FRESH_DATABASE_URL.
The startup guard fails if the database contains procureflow.tenders, making
accidental reuse of the previous production DB impossible.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re

import psycopg
from psycopg.rows import dict_row

TEN=re.compile(r"^\d{10}$")
BID=re.compile(r"^(?:R\d{2}[A-Z]{2}\d{8}|\d{11})$")
ORD=re.compile(r"^\d{3}$")
DDLS=[
"""CREATE SCHEMA IF NOT EXISTS fresh_g2b""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_search_runs(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 code10 text NOT NULL, from_day date NOT NULL, to_day date NOT NULL,
 cursor text NOT NULL DEFAULT '', page int NOT NULL DEFAULT 1,
 status text NOT NULL DEFAULT 'started', official_endpoint text NOT NULL DEFAULT '',
 request_verified boolean NOT NULL DEFAULT false,
 confirmed_count int NOT NULL DEFAULT 0, pending_count int NOT NULL DEFAULT 0,
 official_total int, reason text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz)""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_notices(
 bid_no text NOT NULL, bid_ord text NOT NULL DEFAULT '000',
 detail10 text NOT NULL DEFAULT '',title text NOT NULL DEFAULT '',
 agency text NOT NULL DEFAULT '',published text NOT NULL DEFAULT '',
 original_url text NOT NULL DEFAULT '', original_verified boolean NOT NULL DEFAULT false,
 verification_reason text NOT NULL DEFAULT 'unverified_search_candidate',
 original_sha256 text NOT NULL DEFAULT '',
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord))""",
"""CREATE INDEX IF NOT EXISTS ix_fresh_notice_code
  ON fresh_g2b.site_notices(detail10,original_verified,published DESC)""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_notice_versions(
 bid_no text NOT NULL,bid_ord text NOT NULL,sha256 text NOT NULL,
 content text NOT NULL DEFAULT '',source_url text NOT NULL,
 collected_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,sha256))""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_attachments(
 bid_no text NOT NULL,bid_ord text NOT NULL,file_url text NOT NULL,
 filename text NOT NULL DEFAULT '',sha256 text NOT NULL DEFAULT '',
 mime text NOT NULL DEFAULT '',data bytea,extracted_text text NOT NULL DEFAULT '',
 extraction_state text NOT NULL DEFAULT 'listed',
 last_checked_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,file_url))""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_executions(
 bid_no text NOT NULL,bid_ord text NOT NULL,
 bid_clsfc_no text NOT NULL DEFAULT '0',
 progress_ord text NOT NULL DEFAULT '000',
 status text NOT NULL DEFAULT 'unknown',
 total_reported int,
 full_bidders_verified boolean NOT NULL DEFAULT false,
 source_sha256 text NOT NULL DEFAULT '',
 last_checked_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,bid_clsfc_no,progress_ord))""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_offers(
 bid_no text NOT NULL,bid_ord text NOT NULL,
 bid_clsfc_no text NOT NULL,progress_ord text NOT NULL,
 offer_key text NOT NULL,
 company text NOT NULL DEFAULT '',business_no text NOT NULL DEFAULT '',
 amount text NOT NULL DEFAULT '',rate text NOT NULL DEFAULT '',rank text NOT NULL DEFAULT '',
 validity_code text NOT NULL DEFAULT '',
 source_sha256 text NOT NULL DEFAULT '',
 last_checked_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,bid_clsfc_no,progress_ord,offer_key))""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_awards(
 bid_no text NOT NULL,bid_ord text NOT NULL,
 bid_clsfc_no text NOT NULL,progress_ord text NOT NULL,
 company text NOT NULL,amount text NOT NULL,
 evidence_status text NOT NULL DEFAULT 'official_explicit_final',
 evidence_sha256 text NOT NULL,
 captured_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,bid_clsfc_no,progress_ord))""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_jobs(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 kind text NOT NULL,params jsonb NOT NULL DEFAULT '{}'::jsonb,
 status text NOT NULL DEFAULT 'queued',result jsonb NOT NULL DEFAULT '{}'::jsonb,
 error text NOT NULL DEFAULT '',created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,completed_at timestamptz)""",
"""CREATE TABLE IF NOT EXISTS fresh_g2b.site_fetch_audit(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 job_id bigint REFERENCES fresh_g2b.site_jobs(id),
 source text NOT NULL,resource_id text NOT NULL DEFAULT '',
 status text NOT NULL,summary jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now())"""
]

def connect():
    url=os.environ.get("FRESH_DATABASE_URL","").strip()
    if not url:
        raise RuntimeError("FRESH_DATABASE_URL_REQUIRED")
    return psycopg.connect(url,row_factory=dict_row,connect_timeout=8)

@contextmanager
def db():
    with connect() as cx:
        yield cx

def guard(cx):
    # Must be a different database, not just a different schema.
    existing=cx.execute("SELECT to_regclass('procureflow.tenders') AS legacy").fetchone()
    if existing["legacy"] is not None:
        raise RuntimeError("LEGACY_DATABASE_REJECTED_FRESH_DB_ONLY")

def initialize():
    with db() as cx:
        guard(cx)
        for stmt in DDLS:
            cx.execute(stmt)
        # In-process BackgroundTasks do not survive deploy/restarts.
        cx.execute("""UPDATE fresh_g2b.site_jobs SET status='interrupted',
                      error='process_restarted_before_completion',completed_at=now()
                      WHERE status IN ('running','queued')""")
        return stats(cx)

def stats(cx):
    return cx.execute("""SELECT
         (SELECT count(*) FROM fresh_g2b.site_notices) AS notices,
         (SELECT count(*) FROM fresh_g2b.site_notices WHERE original_verified) AS verified,
         (SELECT count(*) FROM fresh_g2b.site_offers) AS offers,
         (SELECT count(*) FROM fresh_g2b.site_awards) AS awards,
         (SELECT count(*) FROM fresh_g2b.site_attachments WHERE sha256<>'') AS files,
         (SELECT count(*) FROM fresh_g2b.site_search_runs
                   WHERE request_verified) AS real_site_search_runs""").fetchone()

def encode(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,default=str)

def signature(content):
    return sha256((content if isinstance(content,bytes) else str(content).encode("utf-8"))).hexdigest()

def create_job(kind,params):
    with db() as cx:
        return int(cx.execute("""INSERT INTO fresh_g2b.site_jobs(kind,params)
            VALUES(%s,%s::jsonb) RETURNING id""",(kind,encode(params))).fetchone()["id"])

def job_update(job_id,status,result=None,error=""):
    with db() as cx:
        cx.execute("""UPDATE fresh_g2b.site_jobs
            SET status=%s,result=%s::jsonb,error=%s,
                started_at=CASE WHEN %s='running' THEN now() ELSE started_at END,
                completed_at=CASE WHEN %s IN ('completed','blocked','error') THEN now()
                  ELSE completed_at END
            WHERE id=%s""",(status,encode(result or {}),error[:240],status,status,job_id))

def audit(job_id,source,resource_id,status,summary):
    with db() as cx:
        cx.execute("""INSERT INTO fresh_g2b.site_fetch_audit
              (job_id,source,resource_id,status,summary)
              VALUES(%s,%s,%s,%s,%s::jsonb)""",
              (job_id,source,resource_id,status,encode(summary)))

def store_search(result,code10,start,end,cursor,page,job_id):
    if not TEN.fullmatch(code10):
        raise ValueError("EXACT10_REQUIRED")
    verified=bool(result.get("search_request_verified"))
    confirmed=result.get("matched_explicit_detail10") or []
    pending=result.get("pending_original_detail10_verification") or []
    if not verified and (confirmed or pending):
        raise ValueError("UNVERIFIED_WEBSITE_RESULTS_MUST_NOT_BE_STORED")
    with db() as cx:
        cx.execute("""INSERT INTO fresh_g2b.site_search_runs
          (code10,from_day,to_day,cursor,page,status,official_endpoint,
           request_verified,confirmed_count,pending_count,official_total,reason)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (code10,result.get("request_window",{}).get("start") or start,
           result.get("request_window",{}).get("end") or end,cursor or "",page,
           result.get("status","blocked"),str(result.get("live_search_endpoint") or ""),
           verified,len(confirmed),len(pending),result.get("official_total"),
           str(result.get("reason") or "")[:180]))
        accepted=0
        for v in confirmed+pending:
            no=str(v.get("bid_no") or "")
            ord_=str(v.get("bid_ord") or "000")
            if not BID.fullmatch(no) or not ORD.fullmatch(ord_):
                continue
            is_proven=(v in confirmed and code10 in (v.get("direct_category_codes") or []))
            cx.execute("""INSERT INTO fresh_g2b.site_notices
              (bid_no,bid_ord,detail10,title,agency,original_verified,
               verification_reason,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,now())
              ON CONFLICT (bid_no,bid_ord) DO UPDATE SET
                 title=excluded.title,agency=excluded.agency,
                 detail10=CASE WHEN excluded.original_verified THEN excluded.detail10
                        ELSE fresh_g2b.site_notices.detail10 END,
                 original_verified=fresh_g2b.site_notices.original_verified OR
                        excluded.original_verified,
                 verification_reason=CASE WHEN fresh_g2b.site_notices.original_verified
                          THEN fresh_g2b.site_notices.verification_reason
                          ELSE excluded.verification_reason END,updated_at=now()""",
              (no,ord_,code10 if is_proven else "",
               str(v.get("title") or "")[:450],str(v.get("agency") or "")[:250],
               is_proven,"official_search_response_explicit_10_digit" if is_proven
                         else "candidate_needs_original_site_detail"))
            accepted+=1
    audit(job_id,"www.g2b.go.kr","detail10:"+code10,result.get("status","blocked"),
          {"confirmed":len(confirmed),"unverified_candidates":len(pending),
           "request_verified":verified})
    return {"saved_search_candidates":accepted,"verified":len(confirmed),
            "needs_original_confirmation":len(pending)}

def get_notice(cx,no,ord_):
    r=cx.execute("""SELECT * FROM fresh_g2b.site_notices
                     WHERE bid_no=%s AND bid_ord=%s""",(no,ord_)).fetchone()
    if r is None:raise LookupError("NOTICE_NOT_IN_FRESH_SITE_DB")
    return r

def store_detail(no,ord_,detail,job_id):
    if not BID.fullmatch(no) or not ORD.fullmatch(ord_):raise ValueError("BAD_NOTICE_ID")
    if detail.get("bid_no")!=no or detail.get("bid_ord")!=ord_:
        raise ValueError("DETAIL_IDENTITY_MISMATCH")
    body=detail.get("content") or ""
    digest=signature(body)
    code=detail.get("detail10") or ""
    verified=bool(TEN.fullmatch(code) and detail.get("explicit_detail10"))
    with db() as cx:
        old=get_notice(cx,no,ord_)
        cx.execute("""INSERT INTO fresh_g2b.site_notice_versions
            (bid_no,bid_ord,sha256,content,source_url)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (no,ord_,digest,body[:2000000],str(detail.get("url") or "")[:1000]))
        cx.execute("""UPDATE fresh_g2b.site_notices
          SET detail10=CASE WHEN %s THEN %s ELSE detail10 END,
              title=CASE WHEN title='' THEN %s ELSE title END,
              agency=CASE WHEN agency='' THEN %s ELSE agency END,
              original_url=%s,original_verified=original_verified OR %s,
              original_sha256=%s,
              verification_reason=CASE WHEN %s THEN 'official_site_detail_explicit10'
                 ELSE verification_reason END,updated_at=now()
          WHERE bid_no=%s AND bid_ord=%s""",
          (verified,code,str(detail.get("title") or "")[:450],
           str(detail.get("agency") or "")[:250],detail["url"],
           verified,digest,verified,no,ord_))
        for f in detail.get("attachments") or []:
            cx.execute("""INSERT INTO fresh_g2b.site_attachments(
               bid_no,bid_ord,file_url,filename)
               VALUES(%s,%s,%s,%s)
               ON CONFLICT DO NOTHING""",
               (no,ord_,f["url"],f["filename"][:250]))
    audit(job_id,"www.g2b.go.kr",no+"-"+ord_,
          "verified_original" if verified else "unverified_original",
          {"sha256":digest,"attachments":len(detail.get("attachments") or []),
           "explicit_detail10":verified})
    return {"original_sha256":digest,"original_verified":verified,
            "detail10":code if verified else None,
            "attachment_links":len(detail.get("attachments") or []),
            "already_same_original":old["original_sha256"]==digest}

def store_attachment(no,ord_,url,content,filename,mime,text_value,state,job_id):
    digest=signature(content)
    with db() as cx:
        old=cx.execute("""SELECT sha256 FROM fresh_g2b.site_attachments
                          WHERE bid_no=%s AND bid_ord=%s AND file_url=%s""",
                          (no,ord_,url)).fetchone()
        if old is None:raise LookupError("FILE_NOT_IN_CURRENT_SITE_DETAIL")
        same=old["sha256"]==digest
        if not same:
            cx.execute("""UPDATE fresh_g2b.site_attachments SET
              filename=%s,sha256=%s,mime=%s,data=%s,extracted_text=%s,
              extraction_state=%s,last_checked_at=now()
              WHERE bid_no=%s AND bid_ord=%s AND file_url=%s""",
              (filename[:250],digest,mime[:120],content,text_value[:800000],state,no,ord_,url))
        else:
            cx.execute("""UPDATE fresh_g2b.site_attachments SET
               last_checked_at=now() WHERE bid_no=%s AND bid_ord=%s AND file_url=%s""",
               (no,ord_,url))
    audit(job_id,"www.g2b.go.kr",no+"/"+filename,state,{"sha256":digest,"unchanged":same})
    return {"sha256":digest,"unchanged":same,"bytes":len(content),"state":state}

def store_opening(no,ord_,data,job_id):
    if data.get("bid_no")!=no or data.get("bid_ord")!=ord_:
        raise ValueError("OPENING_IDENTITY_MISMATCH")
    raw_offers=data.get("bidders")
    if not isinstance(raw_offers,list):
        raise ValueError("OPENING_BIDDER_LIST_NOT_VERIFIED")
    # At most one current selected execution. Unknown classification/progress
    # stays UNKNOWN. Never confuse one opening-ranked firm with a winner.
    info=data.get("bid_info") or {}
    clsfc=str(info.get("bidClsfNo") or data.get("bid_clsfc_no") or "0")
    progress=str(info.get("bidPrgrsOrd") or data.get("progress_ord") or "000")
    if len(raw_offers)>2000:
        raise ValueError("UNBOUNDED_OPENING_ROWS")
    dig=signature(encode({"info":info,"bidders":raw_offers}))
    with db() as cx:
        notice=get_notice(cx,no,ord_)
        if not notice["original_verified"]:
            raise ValueError("OPENING_NOT_ALLOWED_BEFORE_OFFICIAL_ORIGINAL_DETAIL10")
        cx.execute("""INSERT INTO fresh_g2b.site_executions(
             bid_no,bid_ord,bid_clsfc_no,progress_ord,status,total_reported,
             full_bidders_verified,source_sha256)
             VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT (bid_no,bid_ord,bid_clsfc_no,progress_ord)
             DO UPDATE SET status=excluded.status,total_reported=excluded.total_reported,
               full_bidders_verified=excluded.full_bidders_verified,
               source_sha256=excluded.source_sha256,last_checked_at=now()""",
             (no,ord_,clsfc,progress,str(info.get("bidPgstCd") or "opening_observed")[:70],
              int(data.get("total") or len(raw_offers)),
              len(raw_offers)>=int(data.get("total") or len(raw_offers)),dig))
        count=0
        from g2b_bid_collector import normalize_item
        for i,raw in enumerate(raw_offers):
            x=normalize_item({**raw,"bid_no":no,"bid_ord":ord_,
              "bidClsfNo":clsfc,"bidPrgrsOrd":progress},"service",
              "opening","fresh_g2b_websquare",i)
            if not x:continue
            m=x["raw"]
            key=x["record_key"]
            cx.execute("""INSERT INTO fresh_g2b.site_offers(
              bid_no,bid_ord,bid_clsfc_no,progress_ord,offer_key,company,
              business_no,amount,rate,rank,validity_code,source_sha256)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(bid_no,bid_ord,bid_clsfc_no,progress_ord,offer_key)
              DO UPDATE SET company=excluded.company,business_no=excluded.business_no,
                amount=excluded.amount,rate=excluded.rate,rank=excluded.rank,
                validity_code=excluded.validity_code,
                source_sha256=excluded.source_sha256,last_checked_at=now()""",
              (no,ord_,clsfc,progress,key,x["company"],m["bidder_business_no"],
               x["amount"],x["rate"],x["rank"],m["bid_qualification_code"],dig))
            count+=1
    audit(job_id,"www.g2b.go.kr",no+"-"+ord_,"opening_saved",
           {"bidders":count,"reported_total":data.get("total"),"source_sha256":dig})
    return {"opening_rows":count,"reported_total":data.get("total"),"sha256":dig,
            "complete":len(raw_offers)>=int(data.get("total") or len(raw_offers))}

def list_notices(code10="",limit=50,offset=0):
    with db() as cx:
        q="""SELECT bid_no,bid_ord,detail10,title,agency,published,original_url,
               original_verified,verification_reason,updated_at
               FROM fresh_g2b.site_notices"""
        params=[]
        if code10:
            q+=" WHERE detail10=%s";params.append(code10)
        q+=" ORDER BY updated_at DESC LIMIT %s OFFSET %s"
        params.extend([limit,offset])
        return cx.execute(q,tuple(params)).fetchall()

def history_for(no,ord_):
    with db() as cx:
        notice=get_notice(cx,no,ord_)
        code=notice["detail10"]
        if not notice["original_verified"] or not TEN.fullmatch(code):
            return {"status":"HOLD","reason":"SELECTED_NOTICE_ORIGINAL_10DIGIT_NOT_VERIFIED",
                    "items":[]}
        notices=cx.execute("""SELECT n.bid_no,n.bid_ord,n.title,n.agency,n.published,
            n.detail10,n.original_verified,
            (SELECT count(*) FROM fresh_g2b.site_offers o
                 WHERE o.bid_no=n.bid_no AND o.bid_ord=n.bid_ord) AS offer_rows,
            (SELECT count(*) FROM fresh_g2b.site_awards a
                 WHERE a.bid_no=n.bid_no AND a.bid_ord=n.bid_ord) AS final_award_rows
            FROM fresh_g2b.site_notices n
            WHERE n.detail10=%s AND n.original_verified=true AND
              (n.bid_no,n.bid_ord)<>(%s,%s)
            ORDER BY n.published DESC,n.updated_at DESC LIMIT 250""",
            (code,no,ord_)).fetchall()
    return {"status":"fresh_website_evidence_only","detail10":code,"items":notices,
            "ten_year_complete":False}

def read_jobs(limit=25):
    with db() as cx:
        return cx.execute("""SELECT id,kind,params,status,result,error,created_at,
                  started_at,completed_at FROM fresh_g2b.site_jobs
                  ORDER BY id DESC LIMIT %s""",(limit,)).fetchall()


def store_official_notice_file(no,ord_,url,expected10,file,job_id):
    """Commit fresh original G2B PDF ONLY when its actual text proves detail10.

    The official download was obtained in THIS job. No existing row is
    consulted as source evidence; existing fresh rows are used only for
    version equality and conflict detection.
    """
    if not BID.fullmatch(no) or not ORD.fullmatch(ord_):
        raise ValueError("INVALID_OFFICIAL_FILE_NOTICE")
    if not TEN.fullmatch(expected10):
        raise ValueError("INVALID_EXPECTED_DETAIL10")
    from fresh_g2b_site import explicit_detail10
    content=file["content"]
    text_value=str(file.get("text") or "")
    digest=signature(content)
    if not text_value or not explicit_detail10(text_value,expected10):
        audit(job_id,"www.g2b.go.kr",no+"-"+ord_,"blocked_no_explicit_code",
              {"file_sha256":digest,"extraction_state":file.get("state")})
        return {"status":"blocked","reason":"OFFICIAL_FILE_DOES_NOT_PROVE_EXACT_DETAIL10",
                "file_sha256":digest,"stored":False}
    # Titles and institutions must be visible in the newly downloaded PDF.
    title=""
    agency=""
    for pattern,target in (
      (r"(?:용\s*역\s*명|입찰\s*건명|사\s*업\s*명)\s*[:：]\s*([^\r\n]{5,150})","title"),
      (r"(?:수요기관|발주기관)\s*[:：]\s*([^\r\n]{2,130})","agency")):
        m=re.search(pattern,text_value,re.I)
        if m:
            candidate=" ".join(m.group(1).split())
            if target=="title":title=candidate[:300]
            else:agency=candidate[:220]
    with db() as cx:
        prev=cx.execute("""SELECT detail10,original_verified,original_sha256
            FROM fresh_g2b.site_notices WHERE bid_no=%s AND bid_ord=%s""",
            (no,ord_)).fetchone()
        if prev and prev["original_verified"] and prev["detail10"]!=expected10:
            raise ValueError("CONFLICTING_OFFICIAL_ORIGINAL_DETAIL10")
        unchanged=bool(prev and prev["original_sha256"]==digest)
        cx.execute("""INSERT INTO fresh_g2b.site_notices(
          bid_no,bid_ord,detail10,title,agency,original_url,original_verified,
          original_sha256,verification_reason)
          VALUES(%s,%s,%s,%s,%s,%s,true,%s,
                  'official_g2b_downloaded_pdf_explicit10')
          ON CONFLICT(bid_no,bid_ord) DO UPDATE SET
             detail10=excluded.detail10,
             title=CASE WHEN fresh_g2b.site_notices.title='' THEN excluded.title
                        ELSE fresh_g2b.site_notices.title END,
             agency=CASE WHEN fresh_g2b.site_notices.agency='' THEN excluded.agency
                        ELSE fresh_g2b.site_notices.agency END,
             original_url=excluded.original_url,
             original_verified=true,
             original_sha256=excluded.original_sha256,
             verification_reason=excluded.verification_reason,updated_at=now()""",
            (no,ord_,expected10,title,agency,url,digest))
        cx.execute("""INSERT INTO fresh_g2b.site_notice_versions(
             bid_no,bid_ord,sha256,content,source_url)
             VALUES(%s,%s,%s,%s,%s)
             ON CONFLICT DO NOTHING""",
             (no,ord_,digest,text_value[:800000],url))
        cx.execute("""INSERT INTO fresh_g2b.site_attachments(
             bid_no,bid_ord,file_url,filename,sha256,mime,
             data,extracted_text,extraction_state)
             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT(bid_no,bid_ord,file_url) DO UPDATE SET
                filename=excluded.filename,sha256=excluded.sha256,
                mime=excluded.mime,data=excluded.data,
                extracted_text=excluded.extracted_text,
                extraction_state=excluded.extraction_state,last_checked_at=now()""",
             (no,ord_,url,file["filename"][:250],digest,file["mime"][:120],
              content,text_value[:800000],file["state"]))
    audit(job_id,"www.g2b.go.kr",no+"-"+ord_,"official_file_exact10_verified",
         {"file_sha256":digest,"detail10":expected10,"unchanged":unchanged,
          "discovery_method":"direct_official_file_url_not_g2b_search"})
    return {"status":"completed","stored":True,"original_verified":True,
            "detail10":expected10,"file_sha256":digest,
            "filename":file["filename"],"unchanged":unchanged,
            "discovery_method":"direct_official_file_url_not_g2b_search"}
