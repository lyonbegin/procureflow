import os,json
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
def connect():
    dsn=os.environ.get("DATABASE_URL")
    if not dsn: raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(dsn,row_factory=dict_row,connect_timeout=10)
@contextmanager
def session():
    with connect() as con:
        con.execute("SET search_path TO procureflow, public")
        yield con
def initialize():
    with connect() as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS procureflow")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.tenders
         (source text NOT NULL,external_id text NOT NULL,title text NOT NULL DEFAULT '',
         agency text NOT NULL DEFAULT '',category text NOT NULL DEFAULT '',
         notice_date text NOT NULL DEFAULT '',deadline text NOT NULL DEFAULT '',
         status text NOT NULL DEFAULT '',method text NOT NULL DEFAULT '',
         source_url text NOT NULL DEFAULT '',raw jsonb NOT NULL DEFAULT '{}'::jsonb,
         first_seen timestamptz NOT NULL DEFAULT now(),last_seen timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY(source,external_id))""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.jobs
         (id bigserial PRIMARY KEY,source text NOT NULL,
         state text NOT NULL DEFAULT 'queued', config jsonb NOT NULL DEFAULT '{}'::jsonb,
         checked int NOT NULL DEFAULT 0,added int NOT NULL DEFAULT 0,
         duplicates int NOT NULL DEFAULT 0,current_page int NOT NULL DEFAULT 0,
         message text NOT NULL DEFAULT '',last_error text NOT NULL DEFAULT '',
         created_at timestamptz NOT NULL DEFAULT now(),started_at timestamptz,finished_at timestamptz)""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.settings
         (key text PRIMARY KEY,value jsonb NOT NULL DEFAULT '{}'::jsonb,
         updated_at timestamptz NOT NULL DEFAULT now())""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.suppliers
         (id bigserial PRIMARY KEY,business_key text UNIQUE,name text NOT NULL,
         address text NOT NULL DEFAULT '',phone text NOT NULL DEFAULT '',
         raw jsonb NOT NULL DEFAULT '{}'::jsonb)""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.certifications
         (id bigserial PRIMARY KEY,supplier_id bigint REFERENCES procureflow.suppliers(id),
         cert_type text NOT NULL,product text NOT NULL DEFAULT '',cert_no text NOT NULL DEFAULT '',
         valid_to text NOT NULL DEFAULT '',raw jsonb NOT NULL DEFAULT '{}'::jsonb)""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.wishket_records
          (kind text NOT NULL,source_id text NOT NULL,title text NOT NULL DEFAULT '',
           url text NOT NULL DEFAULT '',body text NOT NULL DEFAULT '',
           customers jsonb NOT NULL DEFAULT '[]'::jsonb,
           raw jsonb NOT NULL DEFAULT '{}'::jsonb,
           updated_at timestamptz NOT NULL DEFAULT now(),
           PRIMARY KEY(kind,source_id))""")
        con.execute("CREATE INDEX IF NOT EXISTS ix_pf_wishket_kind ON procureflow.wishket_records(kind)")
        con.execute("CREATE INDEX IF NOT EXISTS ix_pf_tenders_date ON procureflow.tenders(notice_date DESC)")
def store(con, row):
    record=dict(row)
    record['raw']=json.dumps(record.get('raw',{}),ensure_ascii=False)
    r=con.execute("""INSERT INTO procureflow.tenders
    (source,external_id,title,agency,category,notice_date,deadline,status,method,source_url,raw)
    VALUES (%(source)s,%(external_id)s,%(title)s,%(agency)s,%(category)s,%(notice_date)s,
    %(deadline)s,%(status)s,%(method)s,%(source_url)s,%(raw)s::jsonb)
    ON CONFLICT(source,external_id) DO UPDATE SET last_seen=now(),title=excluded.title,
    agency=excluded.agency,category=excluded.category,notice_date=excluded.notice_date,
    deadline=excluded.deadline,status=excluded.status,method=excluded.method,
    source_url=excluded.source_url,raw=excluded.raw
    RETURNING (xmax=0) AS inserted""",record)
    return bool(r.fetchone()['inserted'])
