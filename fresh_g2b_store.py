"""Isolated clean-room PostgreSQL repository: NEVER accesses procureflow schema.
Only same fresh database data acquired by fresh site's live HTTP requests.
"""
import hashlib,json,os
from contextlib import contextmanager
from datetime import datetime,date
import psycopg
from psycopg.rows import dict_row

SCHEMA=r"""
CREATE SCHEMA IF NOT EXISTS freshg2b;
CREATE TABLE IF NOT EXISTS freshg2b.jobs(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 kind text NOT NULL, args jsonb NOT NULL DEFAULT '{}'::jsonb,
 status text NOT NULL DEFAULT 'queued', rows_seen integer NOT NULL DEFAULT 0,
 rows_saved integer NOT NULL DEFAULT 0, error text NOT NULL DEFAULT '',
 started_at timestamptz, finished_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS freshg2b.search_pages(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 job_id bigint REFERENCES freshg2b.jobs(id),
 detail10 text NOT NULL, date_from date NOT NULL, date_to date NOT NULL,
 page integer NOT NULL, endpoint text NOT NULL, request_verified boolean NOT NULL,
 response_sha text NOT NULL, total_reported integer,
 row_count integer NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(detail10,date_from,date_to,page,response_sha)
);
CREATE TABLE IF NOT EXISTS freshg2b.notices(
 bid_no text NOT NULL,bid_ord text NOT NULL,detail10 text NOT NULL,
 title text NOT NULL DEFAULT '',agency text NOT NULL DEFAULT '',
 posted_on date,source_url text NOT NULL DEFAULT '',
 category_verified boolean NOT NULL DEFAULT false,
 original_json jsonb NOT NULL DEFAULT '{}'::jsonb,
 response_sha text NOT NULL,first_seen timestamptz NOT NULL DEFAULT now(),
 last_seen timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord)
);
CREATE TABLE IF NOT EXISTS freshg2b.notice_versions(
 bid_no text NOT NULL,bid_ord text NOT NULL,response_sha text NOT NULL,
 original_json jsonb NOT NULL, source_url text NOT NULL,
 downloaded_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,response_sha)
);
CREATE TABLE IF NOT EXISTS freshg2b.attachments(
 bid_no text NOT NULL,bid_ord text NOT NULL,file_key text NOT NULL,
 filename text NOT NULL DEFAULT '',source_url text NOT NULL,
 sha256 text NOT NULL, mime text NOT NULL DEFAULT '',
 data bytea NOT NULL, extracted_text text NOT NULL DEFAULT '',
 extract_state text NOT NULL DEFAULT 'unparsed',
 fetched_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,file_key,sha256)
);
CREATE TABLE IF NOT EXISTS freshg2b.executions(
 bid_no text NOT NULL,bid_ord text NOT NULL,
 bid_clsfc_no text NOT NULL DEFAULT '0',
 progress_ord text NOT NULL DEFAULT '000',
 observed_status text NOT NULL DEFAULT 'unverified',
 original_listing jsonb NOT NULL DEFAULT '{}'::jsonb,
 listing_sha text NOT NULL DEFAULT '',
 total_offers_claimed integer,
 detail_complete boolean NOT NULL DEFAULT false,
 last_checked timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,bid_clsfc_no,progress_ord)
);
CREATE TABLE IF NOT EXISTS freshg2b.offers(
 bid_no text NOT NULL,bid_ord text NOT NULL,
 bid_clsfc_no text NOT NULL,progress_ord text NOT NULL,
 offer_id text NOT NULL,company text NOT NULL DEFAULT '',
 business_no text NOT NULL DEFAULT '',amount text NOT NULL DEFAULT '',
 bid_rate text NOT NULL DEFAULT '',rank text NOT NULL DEFAULT '',
 invalid_reason text NOT NULL DEFAULT '',
 raw jsonb NOT NULL,raw_sha text NOT NULL,
 observed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,bid_clsfc_no,progress_ord,offer_id)
);
CREATE TABLE IF NOT EXISTS freshg2b.final_awards(
 bid_no text NOT NULL,bid_ord text NOT NULL,
 bid_clsfc_no text NOT NULL,progress_ord text NOT NULL,
 winner_company text NOT NULL,winner_amount text NOT NULL,
 evidence text NOT NULL,original_json jsonb NOT NULL,
 response_sha text NOT NULL,
 verified_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(bid_no,bid_ord,bid_clsfc_no,progress_ord)
);
CREATE TABLE IF NOT EXISTS freshg2b.fetch_attempts(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 bid_no text NOT NULL DEFAULT '',bid_ord text NOT NULL DEFAULT '',
 job_id bigint,stage text NOT NULL,status text NOT NULL,
 error_kind text NOT NULL DEFAULT '',source_url text NOT NULL DEFAULT '',
 checked_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fresh_notice_detail ON freshg2b.notices(detail10,posted_on DESC);
CREATE INDEX IF NOT EXISTS fresh_attempts_job ON freshg2b.fetch_attempts(job_id,checked_at DESC);
"""
def dsn():
    return os.environ.get("FRESH_DATABASE_URL","")

@contextmanager
def conn():
    if not dsn():raise RuntimeError("FRESH_DATABASE_URL_MISSING")
    with psycopg.connect(dsn(),connect_timeout=8,row_factory=dict_row) as c:
        yield c

def initialize():
    with conn() as c:
        if c.execute("SELECT to_regclass('procureflow.tenders') IS NOT NULL AS old").fetchone()["old"]:
            raise RuntimeError("LEGACY_DATABASE_FORBIDDEN_DO_NOT_CONNECT")
        c.execute(SCHEMA)

def dump(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,default=str)

def digest(x):
    if isinstance(x,bytes):return hashlib.sha256(x).hexdigest()
    if isinstance(x,str):return digest(x.encode())
    return digest(dump(x))

def public(row):
    return {k:(v.isoformat() if isinstance(v,(datetime,date)) else v)
            for k,v in dict(row).items()}

def create_job(kind,args):
    with conn() as c:
        if not c.execute("SELECT pg_try_advisory_xact_lock(66770119) AS ok").fetchone()["ok"]:
            raise RuntimeError("FRESH_CRAWLER_ALREADY_QUEUING")
        busy=c.execute("""SELECT EXISTS(SELECT 1 FROM freshg2b.jobs
          WHERE status IN ('queued','running')) AS busy""").fetchone()["busy"]
        if busy:raise RuntimeError("FRESH_CRAWLER_ALREADY_RUNNING")
        r=c.execute("INSERT INTO freshg2b.jobs(kind,args) VALUES (%s,%s::jsonb) RETURNING id",
                    (kind,dump(args))).fetchone()
        return r["id"]

def change_job(job_id,status,*,seen=0,saved=0,error=""):
    with conn() as c:
        c.execute("""UPDATE freshg2b.jobs SET status=%s,rows_seen=%s,
          rows_saved=%s,error=%s,
          started_at=CASE WHEN %s='running' THEN coalesce(started_at,now()) ELSE started_at END,
          finished_at=CASE WHEN %s IN ('completed','blocked','error') THEN now() ELSE finished_at END
          WHERE id=%s""",(status,seen,saved,error[:200],status,status,job_id))

def attempt(job_id,stage,status,bid_no="",bid_ord="",source_url="",error_kind=""):
    with conn() as c:
        c.execute("""INSERT INTO freshg2b.fetch_attempts(job_id,stage,status,bid_no,bid_ord,source_url,error_kind)
          VALUES(%s,%s,%s,%s,%s,%s,%s)""",
          (job_id,stage,status,bid_no,bid_ord,source_url,error_kind[:90]))

def page_saved(job_id,w,endpoint,source_json,records,total):
    """Save live filtered search candidates, never conflate with detail-verified codes."""
    raw_sha=digest(source_json)
    saved=0
    with conn() as c:
        c.execute("""INSERT INTO freshg2b.search_pages
          (job_id,detail10,date_from,date_to,page,endpoint,request_verified,response_sha,total_reported,row_count)
          VALUES(%s,%s,%s,%s,%s,%s,true,%s,%s,%s)
          ON CONFLICT DO NOTHING""",(job_id,w["detail10"],w["start"],w["end"],
          w["page"],endpoint,raw_sha,total,len(records)))
        for x in records:
            if x["detail10"]!=w["detail10"] or not x.get("official_filter_verified"):
                continue
            bid,ord_=x["bid_no"],x["bid_ord"]
            row=x["raw"]
            sha=digest(row)
            result=c.execute("""INSERT INTO freshg2b.notices
              (bid_no,bid_ord,detail10,title,agency,posted_on,source_url,
               category_verified,original_json,response_sha)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
              ON CONFLICT (bid_no,bid_ord) DO UPDATE SET
               detail10=excluded.detail10,title=excluded.title,
               agency=excluded.agency,posted_on=excluded.posted_on,
               source_url=excluded.source_url,
               category_verified=(freshg2b.notices.category_verified OR excluded.category_verified),
               original_json=excluded.original_json,response_sha=excluded.response_sha,
               last_seen=now() RETURNING bid_no""",(bid,ord_,x["detail10"],
              x.get("title",""),x.get("agency",""),x.get("posted_on"),
              endpoint,bool(x["original_category_evidence"]),dump(row),sha)).fetchone()
            c.execute("""INSERT INTO freshg2b.notice_versions
               (bid_no,bid_ord,response_sha,original_json,source_url)
               VALUES(%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING""",
               (bid,ord_,sha,dump(row),endpoint))
            saved+=int(bool(result))
    return saved

def save_first_unseen(job_id,w,endpoint,response_sha,records,total):
    """Inspect newest first; commit at most ONE new public notice atomically.

    A previously stored notice is never rewritten or counted as new.
    The original official JSON is preserved, while detail10 remains empty
    until its exact classification has been established from the source.
    """
    if not endpoint.startswith("/pn/pnp/pnpe/BidPbac/"):
        raise RuntimeError("UNVERIFIED_BID_LIST_SOURCE")
    seen=0
    with conn() as c:
        c.execute("""INSERT INTO freshg2b.search_pages
          (job_id,detail10,date_from,date_to,page,endpoint,request_verified,response_sha,total_reported,row_count)
          VALUES(%s,%s,%s,%s,%s,%s,true,%s,%s,%s)
          ON CONFLICT DO NOTHING""",
          (job_id,w["detail10"],w["start"],w["end"],w["page"],
           endpoint,response_sha,total,len(records)))
        for x in records:
            seen+=1
            bid,ord_=x["bid_no"],x["bid_ord"]
            raw=x["raw"]
            sha=digest(raw)
            posted=x.get("posted_on")
            if posted and isinstance(posted,str):
                digits="".join(ch for ch in posted if ch.isdigit())
                if len(digits)>=8:
                    posted=digits[:4]+"-"+digits[4:6]+"-"+digits[6:8]
            if not isinstance(posted,str) or len(posted)!=10:
                posted=None
            row=c.execute("""INSERT INTO freshg2b.notices
              (bid_no,bid_ord,detail10,title,agency,posted_on,source_url,
               category_verified,original_json,response_sha)
              VALUES(%s,%s,'',%s,%s,%s,%s,false,%s::jsonb,%s)
              ON CONFLICT (bid_no,bid_ord) DO NOTHING RETURNING bid_no""",
              (bid,ord_,x.get("title",""),x.get("agency",""),
               posted,endpoint,dump(raw),sha)).fetchone()
            if row:
                c.execute("""INSERT INTO freshg2b.notice_versions
                  (bid_no,bid_ord,response_sha,original_json,source_url)
                  VALUES(%s,%s,%s,%s::jsonb,%s)
                  ON CONFLICT DO NOTHING""",(bid,ord_,sha,dump(raw),endpoint))
                return {"saved":1,"checked":seen,"notice":bid+"-"+ord_}
    return {"saved":0,"checked":seen,"notice":None}


def save_opening(bid_no,bid_ord,listing,entry):
    from hashlib import sha256
    cl=str(listing.get("bid_clsfc_no") or "0")
    pr=str(listing.get("bid_progress_ord") or "000")
    bidders=entry.get("bidders") or []
    total=entry.get("total")
    with conn() as c:
        c.execute("""INSERT INTO freshg2b.executions
            (bid_no,bid_ord,bid_clsfc_no,progress_ord,observed_status,
             original_listing,listing_sha,total_offers_claimed,detail_complete)
           VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,true)
           ON CONFLICT(bid_no,bid_ord,bid_clsfc_no,progress_ord) DO UPDATE SET
           observed_status=excluded.observed_status,original_listing=excluded.original_listing,
           listing_sha=excluded.listing_sha,total_offers_claimed=excluded.total_offers_claimed,
           detail_complete=true,last_checked=now()""",
           (bid_no,bid_ord,cl,pr,str(listing.get("status") or ""),
            dump(listing),digest(listing),total))
        count=0
        for i,row in enumerate(bidders):
            raw_sha=digest(row)
            business_no=str(row.get("bzmnRegNo") or "").strip()
            name=str(row.get("grpNm") or "").strip()
            rank=str(row.get("onbsRnkg") or "").strip()
            identity=business_no or name or f"row-{i}"
            offer_id=digest([bid_no,bid_ord,cl,pr,identity,rank])[:40]
            c.execute("""INSERT INTO freshg2b.offers
             (bid_no,bid_ord,bid_clsfc_no,progress_ord,offer_id,company,business_no,
              amount,bid_rate,rank,invalid_reason,raw,raw_sha)
             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
             ON CONFLICT(bid_no,bid_ord,bid_clsfc_no,progress_ord,offer_id)
             DO UPDATE SET company=excluded.company,business_no=excluded.business_no,
              amount=excluded.amount,bid_rate=excluded.bid_rate,
              rank=excluded.rank,invalid_reason=excluded.invalid_reason,
              raw=excluded.raw,raw_sha=excluded.raw_sha,observed_at=now()""",
             (bid_no,bid_ord,cl,pr,offer_id,name,business_no,
              str(row.get("bdngAmt") or ""),str(row.get("bdrt") or ""),rank,
              str(row.get("bidUfnsRsnCd") or ""),dump(row),raw_sha))
            count+=1
    return count

def save_final(bid_no,bid_ord,listing,entry,winner_name):
    matches=[x for x in entry.get("bidders",[]) if str(x.get("grpNm") or "").strip()==winner_name]
    if len(matches)!=1:return False
    r=matches[0];amount=str(r.get("bdngAmt") or "")
    if not amount:return False
    with conn() as c:
        c.execute("""INSERT INTO freshg2b.final_awards
          (bid_no,bid_ord,bid_clsfc_no,progress_ord,winner_company,winner_amount,
            evidence,original_json,response_sha)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
          ON CONFLICT(bid_no,bid_ord,bid_clsfc_no,progress_ord)
          DO UPDATE SET winner_company=excluded.winner_company,
          winner_amount=excluded.winner_amount,
          evidence=excluded.evidence,original_json=excluded.original_json,
          response_sha=excluded.response_sha,verified_at=now()""",
          (bid_no,bid_ord,str(listing.get("bid_clsfc_no") or "0"),
           str(listing.get("bid_progress_ord") or "000"),winner_name,amount,
           "official_explicit_final_winner_with_completion",
           dump({"bid_info":entry.get("bid_info"),"etc_data":entry.get("etc_data"),
                 "winner_row":r}),digest(entry)))
    return True


def save_attachment(no,ord_,file):
    with conn() as c:
        c.execute("""INSERT INTO freshg2b.attachments
          (bid_no,bid_ord,file_key,filename,source_url,sha256,mime,
           data,extracted_text,extract_state)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT (bid_no,bid_ord,file_key,sha256)
          DO NOTHING""",(no,ord_,file["file_key"],file["filename"],file["url"],
           file["sha256"],file["mime"],file["data"],file["extracted_text"],
           file["extract_state"]))

def recent_notices(limit=40):
    with conn() as c:
        rows=c.execute("""SELECT n.bid_no,n.bid_ord,n.detail10,n.title,
            n.agency,n.posted_on,n.source_url,n.category_verified,n.first_seen,
            COUNT(DISTINCT e.bid_clsfc_no||'/'||e.progress_ord) AS opening_executions,
            COUNT(DISTINCT a.file_key) AS files
          FROM freshg2b.notices n
          LEFT JOIN freshg2b.executions e ON e.bid_no=n.bid_no AND e.bid_ord=n.bid_ord
          LEFT JOIN freshg2b.attachments a ON a.bid_no=n.bid_no AND a.bid_ord=n.bid_ord
          GROUP BY n.bid_no,n.bid_ord
          ORDER BY n.first_seen DESC,n.posted_on DESC NULLS LAST LIMIT %s""",
          (min(max(1,limit),100),)).fetchall()
    return [public(r) for r in rows]

def notice_detail(no,ord_):
    with conn() as c:
        row=c.execute("""SELECT bid_no,bid_ord,detail10,title,agency,posted_on,
           source_url,category_verified,response_sha,first_seen,last_seen
           FROM freshg2b.notices WHERE bid_no=%s AND bid_ord=%s""",(no,ord_)).fetchone()
        if not row:return None
        execs=c.execute("""SELECT bid_clsfc_no,progress_ord,observed_status,
            total_offers_claimed,detail_complete,last_checked
          FROM freshg2b.executions
          WHERE bid_no=%s AND bid_ord=%s ORDER BY progress_ord,bid_clsfc_no""",
          (no,ord_)).fetchall()
        offers=c.execute("""SELECT bid_clsfc_no,progress_ord,company,
             amount,bid_rate,rank,invalid_reason,business_no
          FROM freshg2b.offers WHERE bid_no=%s AND bid_ord=%s
          ORDER BY progress_ord,bid_clsfc_no,rank LIMIT 2000""",(no,ord_)).fetchall()
        awards=c.execute("""SELECT bid_clsfc_no,progress_ord,winner_company,
            winner_amount,evidence,verified_at
          FROM freshg2b.final_awards WHERE bid_no=%s AND bid_ord=%s""",
          (no,ord_)).fetchall()
        files=c.execute("""SELECT file_key,filename,sha256,extract_state,
           length(extracted_text) AS text_len,fetched_at
          FROM freshg2b.attachments WHERE bid_no=%s AND bid_ord=%s
          ORDER BY fetched_at DESC LIMIT 100""",(no,ord_)).fetchall()
    return {"notice":public(row),"executions":[public(r) for r in execs],
      "offers":[public(r) for r in offers],"final_awards":[public(r) for r in awards],
      "attachments":[public(r) for r in files]}

def job_detail(job_id):
    with conn() as c:
        row=c.execute("""SELECT id,kind,args,status,rows_seen,rows_saved,error,
            created_at,started_at,finished_at FROM freshg2b.jobs WHERE id=%s""",
            (job_id,)).fetchone()
        if not row:return None
        events=c.execute("""SELECT stage,status,bid_no,bid_ord,error_kind,checked_at
          FROM freshg2b.fetch_attempts WHERE job_id=%s
          ORDER BY id DESC LIMIT 70""",(job_id,)).fetchall()
    return {**public(row),"events":[public(x) for x in events]}
