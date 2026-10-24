"""G2B official classification-code index and exact-category historical bid lookup.

There is intentionally no headline similarity, LLM, embedding, or invented
product code. Business registration numbers are NEVER classification codes.
"""
from __future__ import annotations
import json
import re
from db import session, connect

NOTICE_RE=re.compile(r"^R\d{2}BK\d{8}$")
DETAIL10_KEYS={"dtilprdctclsfcno","dtilprdlstclsfcno","dtilprdlstclsfno",
    "dtilprdctclsfno","detailprdctclsfcno","dtilprdctclsfcd"}
PARENT8_KEYS={"prdctclsfcno","prdlstclsfcno","prdlstclsfno",
    "prdctclsfno","itemclsfcno","prdlstclsno"}
INDUSTRY_KEYS={"indstrytycd","indstycd","industrycode",
    "licnscd","lcsccd","rstrctindstrytycd"}
CODE_PATTERNS={"detail10":re.compile(r"^\d{10}$"),
               "parent8":re.compile(r"^\d{8}$"),
               "industry":re.compile(r"^\d{3,6}$")}
TABLE="procureflow.g2b_notice_categories"

def ensure_schema():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_notice_categories(
          bid_no text NOT NULL,bid_ord text NOT NULL DEFAULT '000',
          business_type text NOT NULL DEFAULT '',code_type text NOT NULL,
          code text NOT NULL,source_field text NOT NULL,
          source_uri text NOT NULL,
          evidence_level text NOT NULL DEFAULT 'official_direct',
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(bid_no,bid_ord,code_type,code)
        )""")
        con.execute("""ALTER TABLE procureflow.g2b_notice_categories
                  ADD COLUMN IF NOT EXISTS evidence_level text NOT NULL DEFAULT 'official_direct'""")
        con.execute("""CREATE INDEX IF NOT EXISTS ix_pf_g2b_category_lookup
                  ON procureflow.g2b_notice_categories(code_type,code,business_type)""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_category_audit(
          bid_no text NOT NULL,bid_ord text NOT NULL,
          source_uri text NOT NULL DEFAULT '',
          result text NOT NULL,reason text NOT NULL DEFAULT '',
          matched_codes int NOT NULL DEFAULT 0,
          checked_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(bid_no,bid_ord)
        )""")

def normalize_code(kind,value):
    # Official category *field name* must be whitelisted. The field content
    # cannot be a business number just because it has ten digits.
    name=re.sub(r"[^a-z0-9]","",str(kind or "").lower())
    if name in DETAIL10_KEYS:code_type="detail10"
    elif name in PARENT8_KEYS:code_type="parent8"
    elif name in INDUSTRY_KEYS:code_type="industry"
    else:return None
    text=str(value or "").strip()
    if not CODE_PATTERNS[code_type].fullmatch(text):return None
    return code_type,text

def extract_codes(public_response):
    """Extract classification from official structured fields ONLY."""
    found={}
    def rec(obj,path="",depth=0):
        if depth>7 or len(found)>60:return
        if isinstance(obj,dict):
            for k,v in obj.items():
                next_path=(path+"."+k) if path else k
                normalized=normalize_code(k,v) if isinstance(v,(str,int)) else None
                if normalized:
                    tp,code=normalized
                    found[(tp,code)]={"code_type":tp,"code":code,
                                      "source_field":next_path}
                elif isinstance(v,(dict,list)):
                    rec(v,next_path,depth+1)
        elif isinstance(obj,list):
            for v in obj[:150]:rec(v,path+"[]",depth+1)
    rec(public_response)
    return list(found.values())

def upsert_verified_codes(bid_no,bid_ord,business_type,parsed,source_uri,evidence_level="official_direct"):
    if not NOTICE_RE.fullmatch(bid_no or ""):raise ValueError("invalid G2B bid number")
    if not re.fullmatch(r"\d{3}",bid_ord or ""):raise ValueError("invalid G2B order")
    direct=(source_uri.startswith("https://www.g2b.go.kr/") or
            source_uri.startswith("https://apis.data.go.kr/"))
    secondary=source_uri.startswith("https://bid24.kr/b/")
    if not ((direct and evidence_level=="official_direct") or
            (secondary and evidence_level=="secondary_public")):
        raise ValueError("unrecognized classification evidence source")
    allowed_type={"goods","service",""}.intersection({business_type})
    if not allowed_type:raise ValueError("unsupported business type")
    matches=extract_codes(parsed)
    with session() as con:
        for item in matches:
            con.execute("""INSERT INTO procureflow.g2b_notice_categories
                (bid_no,bid_ord,business_type,code_type,code,source_field,source_uri,evidence_level)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (bid_no,bid_ord,code_type,code) DO UPDATE SET
                  business_type=excluded.business_type,
                  source_field=excluded.source_field,
                  source_uri=excluded.source_uri,
                  evidence_level=excluded.evidence_level
            """,(bid_no,bid_ord,business_type,item["code_type"],item["code"],
                 item["source_field"],source_uri,evidence_level))
        con.execute("""INSERT INTO procureflow.g2b_category_audit
            (bid_no,bid_ord,source_uri,result,reason,matched_codes)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (bid_no,bid_ord) DO UPDATE SET
              source_uri=excluded.source_uri,result=excluded.result,
              reason=excluded.reason,matched_codes=excluded.matched_codes,
              checked_at=now()
            """,(bid_no,bid_ord,source_uri,"matched" if matches else "no_category_fields",
                 "" if matches else "official response contained no explicit item/industry code",
                 len(matches)))
    return matches

def recover_from_existing_raw(limit=15000):
    """Re-use already stored official raw JSON, without web traffic or fabrication.

    Current old 'opening' rows contain bidder business numbers only; those
    must not be misidentified as classification.
    """
    with session() as con:
        rows=con.execute("""SELECT bid_ntce_no,bid_ntce_ord,category,operation,raw
                FROM procureflow.bid_results
                WHERE source='g2b' AND result_kind IN ('opening_status','award')
                ORDER BY first_seen DESC LIMIT %s""",(int(limit),)).fetchall()
    recovered=0
    bids=set()
    for row in rows:
        data=row.get("raw") or {}
        if not isinstance(data,dict):continue
        codes=extract_codes(data)
        if not codes:continue
        # Only imported official public web JSON fields are eligible; do not
        # write classification codes from a manually supplied record.
        if row.get("operation") not in (
            "g2b_web_opening_grid","nuri_final_winner_web","g2b_web_confirmed_award"):
            continue
        business=row.get("category")
        if business not in ("goods","service"):business=""
        found=upsert_verified_codes(row["bid_ntce_no"],row["bid_ntce_ord"],
              business,data,"https://www.g2b.go.kr/")
        if found:
            bids.add((row["bid_ntce_no"],row["bid_ntce_ord"]))
            recovered+=len(found)
    return {"examined_rows":len(rows),"codes_found":recovered,"notices_enriched":len(bids),
            "reason":"Only explicit 8/10-digit official classification fields are accepted"}

def coverage():
    with session() as con:
        total=con.execute("""SELECT count(DISTINCT (bid_ntce_no,bid_ntce_ord)) AS n
                FROM procureflow.bid_results
                WHERE source='g2b'""").fetchone()["n"]
        grouped=con.execute("""SELECT code_type,count(*) AS mapping_rows,
                    count(DISTINCT (bid_no,bid_ord)) AS bid_notices
                    FROM procureflow.g2b_notice_categories
                    GROUP BY code_type ORDER BY code_type""").fetchall()
        audit=con.execute("""SELECT result,count(*) AS count
                     FROM procureflow.g2b_category_audit GROUP BY result""").fetchall()
        examples=con.execute("""SELECT bid_no,bid_ord,code_type,code,business_type,
                              source_field,source_uri,evidence_level
                     FROM procureflow.g2b_notice_categories
                     ORDER BY created_at DESC LIMIT 12""").fetchall()
    return {"source":"g2b","known_execution_groups":total,
            "category_codes":grouped,"audit":audit,"examples":examples,
            "strict_code_match":True,"headline_similarity":False,"llm_used":False}

def exact_matches(bid_no=None,bid_ord="000",detail_code=None,limit=50):
    if bid_no is not None and not NOTICE_RE.fullmatch(bid_no):
        raise ValueError("invalid G2B bid number")
    if detail_code is not None and not re.fullmatch(r"\d{10}",detail_code):
        raise ValueError("detail category code must be exactly 10 digits")
    if bid_no is None and detail_code is None:
        raise ValueError("bid_no or detail_code required")
    if not re.fullmatch(r"\d{3}",bid_ord):
        raise ValueError("bid_ord must have 3 digits")
    limit=max(1,min(int(limit),200))
    with session() as con:
        if detail_code:
            targets=[{"code_type":"detail10","code":detail_code}]
        else:
            targets=con.execute("""SELECT code_type,code
                       FROM procureflow.g2b_notice_categories
                       WHERE bid_no=%s AND bid_ord=%s
                         AND code_type='detail10'
                       ORDER BY code""",(bid_no,bid_ord)).fetchall()
        if not targets:
            return {"target_bid_no":bid_no,"target_codes":[],
                    "results":[],"total":0,
                    "status":"missing_official_detail_code",
                    "reason":"No official 10-digit detail code stored; title guessing disabled."}
        codes=[x["code"] for x in targets]
        rows=con.execute("""WITH candidates AS (
                 SELECT DISTINCT c.bid_no,c.bid_ord,c.code,c.business_type
                 FROM procureflow.g2b_notice_categories c
                 WHERE c.code_type='detail10' AND c.code=ANY(%s)
                   AND (%s::text IS NULL OR c.bid_no<>%s OR c.bid_ord<>%s)
               )
               SELECT b.bid_no,b.bid_ord,
                      array_agg(DISTINCT b.code ORDER BY b.code) AS matched_codes,
                      max(r.title) FILTER (WHERE r.title<>'') AS title,
                      max(r.agency) FILTER (WHERE r.agency<>'') AS agency,
                      COUNT(DISTINCT r.record_key) FILTER (
                        WHERE r.result_kind='opening' AND r.company<>'') AS recorded_bidder_rows,
                      max(r.company) FILTER (WHERE r.result_kind='award') AS winner,
                      max(r.amount) FILTER (WHERE r.result_kind='award') AS award_amount,
                      max(r.raw#>>'{listing,onbsPrnmntDt}') FILTER (
                        WHERE r.result_kind='opening_status') AS opening_at_raw
               FROM candidates b
               LEFT JOIN procureflow.bid_results r
                 ON r.source='g2b' AND r.bid_ntce_no=b.bid_no
                 AND r.bid_ntce_ord=b.bid_ord
               GROUP BY b.bid_no,b.bid_ord
               ORDER BY b.bid_no DESC,b.bid_ord DESC
               LIMIT %s""",(codes,bid_no,bid_no,bid_ord,limit)).fetchall()
    return {"target_bid_no":bid_no,"target_codes":codes,
           "total":len(rows),"results":rows,"status":"ok",
           "search":"exact official detail10 code only",
           "llm_used":False,"headline_similarity":False}
